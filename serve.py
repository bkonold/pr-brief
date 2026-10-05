#!/usr/bin/env python3
"""Serve the runs and start briefs on demand, for the browser extension.

usage: serve.py [--port 8765]

Binds to 127.0.0.1 only. Serves $PR_DESCRIBE_HOME (default: the tool's folder) as static files, so the
extension finds runs/<key>/<variant>/..., and adds an API under /api/ that starts `run.py` for one PR:

    POST /api/run     {host, owner, repo, n}  ->  {key, state}   start a run (or report the one in progress)
    GET  /api/status  ?key=fj-7[&host=&owner=&repo=]  ->  {state, stage, elapsed, error?, allowed?}
    POST /api/cancel  {key}                   ->  {state}        kill the run's process group
    GET  /api/config                          ->  {default_variant, variants}   the variant a brief shows, and the active ones

`state` is idle, running, done, failed or canceled; `status` reads runs/<key>/status.json, which run.py
writes at each stage (see run_status.py). `allowed` is only present when host, owner and repo are given.
Every /api/ request must carry the server token in `X-PR-Describe-Token`, and any `Origin` it carries must start
with chrome-extension://, or it gets 403. The token is created on first start in ~/.config/pr-describe/token
(mode 0600) and never logged. Static files need neither.

local.toml sets `default_variant` (the variant a run uses) and `serve_repos`, the repositories a run may be
started for, as a table of host to owner/name list; see local.example.toml. `variants` in /api/config is the active
list: compare.toml's `variants`, read at startup, or [default_variant] when compare.toml is missing or has none.
Standard library only.
"""
import argparse
import hmac
import json
import os
import re
import secrets
import signal
import subprocess
import sys
import threading
import time
import tomllib
from collections.abc import Callable
from dataclasses import dataclass
from functools import partial
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import run_status
from config import HOME, ROOT, load_local, variant_file
from hosts import host_names, parse_run_key, run_key

ADDRESS = "127.0.0.1"
PORT = 8765
MAX_RUNNING = 2
TOKEN_FILE = Path("~/.config/pr-describe/token").expanduser()
TOKEN_HEADER = "X-PR-Describe-Token"
EXTENSION_ORIGIN = "chrome-extension://"
MAX_BODY_BYTES = 4096
KILL_GRACE_SECONDS = 5
NAME = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9._-]{0,99}$")

ArgvFor = Callable[[str, str, str, int], list[str]]


class ApiError(Exception):
    def __init__(self, status: HTTPStatus, code: str, message: str) -> None:
        super().__init__(message)
        self.status: HTTPStatus = status
        self.code: str = code
        self.message: str = message


def load_token(path: Path) -> str:
    """The token in `path`, created with a random value (file 0600, folder 0700) when there is none."""
    if not path.exists():
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        descriptor: int = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w") as handle:
            handle.write(secrets.token_urlsafe(32) + "\n")
    if path.stat().st_mode & 0o077:
        path.chmod(0o600)
    token: str = path.read_text().strip()
    if not token:
        raise SystemExit(f"{path} is empty; delete it and start again to get a new token")
    return token


def parse_serve_repos(raw: Any) -> dict[str, frozenset[str]]:
    """local.toml's `serve_repos`: {host: ["owner/name", ...]}, compared case-insensitively."""
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise SystemExit("local.toml: serve_repos must be a table of host to a list of owner/name")
    allowed: dict[str, frozenset[str]] = {}
    for host, repos in raw.items():
        if host not in host_names():
            raise SystemExit(f"local.toml: serve_repos names unknown host {host!r}; expected one of {', '.join(host_names())}")
        if not isinstance(repos, list) or not all(isinstance(r, str) and r.count("/") == 1 for r in repos):
            raise SystemExit(f"local.toml: serve_repos.{host} must be a list of owner/name strings")
        allowed[host] = frozenset(r.lower() for r in repos)
    return allowed


def load_active_variants(home: Path, default_variant: str) -> list[str]:
    """The active variants: `variants` of `home`/compare.toml, or [default_variant] without that file or key."""
    path: Path = home / "compare.toml"
    if not path.exists():
        return [default_variant]
    listed: Any = tomllib.loads(path.read_text()).get("variants")
    if listed is None:
        return [default_variant]
    if not isinstance(listed, list) or not all(isinstance(name, str) for name in listed):
        raise SystemExit("compare.toml: variants must be a list of variant names")
    return list(listed)


def default_argv_for(variant: str) -> ArgvFor:
    def argv(host: str, owner: str, repo: str, n: int) -> list[str]:
        return [sys.executable, str(ROOT / "run.py"), str(n), "--variant", variant, "--host", host, "--repo", f"{owner}/{repo}"]
    return argv


@dataclass
class Job:
    process: subprocess.Popen[bytes]

    def running(self) -> bool:
        return self.process.poll() is None


def repo_parts(host: Any, owner: Any, repo: Any, allowed: dict[str, frozenset[str]]) -> tuple[str, str, str, bool]:
    """(host, owner, repo, on the allow-list) for values from a request; raises ApiError when they are malformed."""
    if host not in host_names():
        raise ApiError(HTTPStatus.BAD_REQUEST, "bad_request", f"host must be one of {', '.join(host_names())}")
    for value in (owner, repo):
        if not isinstance(value, str) or not NAME.match(value):
            raise ApiError(HTTPStatus.BAD_REQUEST, "bad_request", "owner and repo must be plain repository names")
    return host, owner, repo, f"{owner}/{repo}".lower() in allowed.get(host, frozenset())


class Runner:
    """Starts, watches and cancels runs. `argv_for(host, owner, repo, n)` builds the command of one run, so
    a test can substitute a fake. All of a run's state is in runs/<key>/status.json; the job table only
    holds the processes this server started, under `lock`."""

    def __init__(self, home: Path, allowed: dict[str, frozenset[str]], argv_for: ArgvFor, max_running: int = MAX_RUNNING) -> None:
        self.home: Path = home
        self.allowed: dict[str, frozenset[str]] = allowed
        self.argv_for: ArgvFor = argv_for
        self.max_running: int = max_running
        self.lock: threading.Lock = threading.Lock()
        self.jobs: dict[str, Job] = {}

    def recover(self) -> list[str]:
        """Marks every run still saying `running` as failed: a server that is starting has no run in progress,
        so such a status was left by one that died. Returns the keys."""
        recovered: list[str] = []
        for path in sorted((self.home / "runs").glob("*/status.json")):
            key: str = path.parent.name
            status: dict[str, Any] | None = run_status.read_status(self.home, key)
            if status and status.get("state") == run_status.RUNNING:
                run_status.write_status(self.home, key, state=run_status.FAILED, finished=time.time(), error="server restarted")
                recovered.append(key)
        return recovered

    def start(self, body: Any) -> dict[str, Any]:
        if not isinstance(body, dict):
            raise ApiError(HTTPStatus.BAD_REQUEST, "bad_request", "expected a JSON object")
        host, owner, repo, permitted = repo_parts(body.get("host"), body.get("owner"), body.get("repo"), self.allowed)
        number: Any = body.get("n")
        if isinstance(number, bool) or not isinstance(number, int) or not 0 < number < 10**9:
            raise ApiError(HTTPStatus.BAD_REQUEST, "bad_request", "n must be a positive integer")
        if not permitted:
            raise ApiError(HTTPStatus.FORBIDDEN, "repo_not_allowed", f"{owner}/{repo} is not in serve_repos for {host}")
        key: str = run_key(host, number)
        with self.lock:
            job: Job | None = self.jobs.get(key)
            if job and job.running():
                return {"key": key, "state": self.status(key)["state"]}
            if sum(1 for other in self.jobs.values() if other.running()) >= self.max_running:
                raise ApiError(HTTPStatus.TOO_MANY_REQUESTS, "busy", f"{self.max_running} briefs already running")
            run_status.begin_status(self.home, key)
            log_path: Path = run_status.status_path(self.home, key).with_name("serve.log")
            try:
                with open(log_path, "ab") as log:
                    process: subprocess.Popen[bytes] = subprocess.Popen(
                        self.argv_for(host, owner, repo, number),
                        stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                        env={**os.environ, "PR_DESCRIBE_HOME": str(self.home)},
                        start_new_session=True,
                    )
            except OSError as error:
                run_status.write_status(self.home, key, state=run_status.FAILED, finished=time.time(), error=f"could not start the run: {error}")
                raise ApiError(HTTPStatus.INTERNAL_SERVER_ERROR, "start_failed", str(error)) from error
            self.jobs[key] = Job(process)
        threading.Thread(target=self._watch, args=(key, process, log_path), daemon=True).start()
        return {"key": key, "state": run_status.RUNNING}

    def _watch(self, key: str, process: subprocess.Popen[bytes], log_path: Path) -> None:
        """Settles a run whose process ended without run.py having said how it ended."""
        code: int = process.wait()
        with self.lock:
            status: dict[str, Any] | None = run_status.read_status(self.home, key)
            current: Job | None = self.jobs.get(key)
            if not status or status.get("state") != run_status.RUNNING or current is None or current.process is not process:
                return
            if code == 0:
                run_status.write_status(self.home, key, state=run_status.DONE, finished=time.time())
                return
            try:
                tail: str = run_status.last_line(log_path.read_text(errors="replace")[-4000:])
            except OSError:
                tail = ""
            run_status.write_status(self.home, key, state=run_status.FAILED, finished=time.time(),
                                    error=tail or f"run exited with status {code}")

    def status(self, key: str, repo: tuple[Any, Any, Any] | None = None) -> dict[str, Any]:
        if parse_run_key(key) is None:
            raise ApiError(HTTPStatus.BAD_REQUEST, "bad_request", "key must be a PR number or fj-<number>")
        status: dict[str, Any] | None = run_status.read_status(self.home, key)
        answer: dict[str, Any] = {"key": key, "state": run_status.IDLE}
        if status:
            answer = {"key": key, "state": status.get("state", run_status.IDLE), "stage": status.get("stage"),
                      "elapsed": run_status.elapsed(status)}
            if status.get("error"):
                answer["error"] = status["error"]
        if repo is not None:
            answer["allowed"] = repo_parts(*repo, self.allowed)[3]
        return answer

    def cancel(self, body: Any) -> dict[str, Any]:
        key: Any = body.get("key") if isinstance(body, dict) else None
        if not isinstance(key, str) or parse_run_key(key) is None:
            raise ApiError(HTTPStatus.BAD_REQUEST, "bad_request", "key must be a PR number or fj-<number>")
        with self.lock:
            job: Job | None = self.jobs.get(key)
            if job and job.running():
                self._kill_group(job.process, signal.SIGTERM)
                run_status.write_status(self.home, key, state=run_status.CANCELED, finished=time.time())
                killer: threading.Timer = threading.Timer(KILL_GRACE_SECONDS, self._kill_group, args=(job.process, signal.SIGKILL))
                killer.daemon = True
                killer.start()
        return {"key": key, "state": self.status(key)["state"]}

    @staticmethod
    def _kill_group(process: subprocess.Popen[bytes], sent: int) -> None:
        """Signals the run's whole process group (`claude -p` and render.py's Chrome are its descendants)."""
        if sent == signal.SIGKILL and process.poll() is not None:
            return
        try:
            os.killpg(process.pid, sent)
        except ProcessLookupError:
            pass

    def stop_all(self) -> None:
        with self.lock:
            for job in self.jobs.values():
                if job.running():
                    self._kill_group(job.process, signal.SIGTERM)


class Handler(SimpleHTTPRequestHandler):
    """Static files from the home folder, plus the authenticated /api/ routes."""

    runner: Runner
    token: bytes
    config: dict[str, Any]

    def log_message(self, format: str, *args: Any) -> None:
        if not self.path.startswith("/api/status"):
            super().log_message(format, *args)

    def _authorized(self) -> bool:
        # Chrome sends no Origin on an extension's GETs, so only a page's own Origin is refused; the token is the gate.
        origin: str | None = self.headers.get("Origin")
        origin_ok: bool = origin is None or origin.startswith(EXTENSION_ORIGIN)
        token_ok: bool = hmac.compare_digest(self.headers.get(TOKEN_HEADER, "").encode("utf-8", "replace"), self.token)
        return origin_ok and token_ok

    def _send_json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        data: bytes = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _body(self) -> Any:
        try:
            length: int = int(self.headers.get("Content-Length", ""))
        except ValueError:
            raise ApiError(HTTPStatus.BAD_REQUEST, "bad_request", "a JSON body is required") from None
        if not 0 < length <= MAX_BODY_BYTES:
            raise ApiError(HTTPStatus.BAD_REQUEST, "bad_request", "the JSON body must be 1 to 4096 bytes")
        try:
            return json.loads(self.rfile.read(length))
        except ValueError:
            raise ApiError(HTTPStatus.BAD_REQUEST, "bad_request", "the body is not valid JSON") from None

    def _api(self, method: str) -> None:
        if not self._authorized():
            self._send_json(HTTPStatus.FORBIDDEN, {"error": "auth", "message": "token or origin missing or wrong"})
            return
        url = urlparse(self.path)
        try:
            if (method, url.path) == ("POST", "/api/run"):
                self._send_json(HTTPStatus.OK, self.runner.start(self._body()))
            elif (method, url.path) == ("POST", "/api/cancel"):
                self._send_json(HTTPStatus.OK, self.runner.cancel(self._body()))
            elif (method, url.path) == ("GET", "/api/config"):
                self._send_json(HTTPStatus.OK, self.config)
            elif (method, url.path) == ("GET", "/api/status"):
                query: dict[str, list[str]] = parse_qs(url.query)
                key: str = query.get("key", [""])[0]
                repo: tuple[Any, Any, Any] | None = None
                if "host" in query or "owner" in query or "repo" in query:
                    repo = tuple(query.get(name, [None])[0] for name in ("host", "owner", "repo"))  # type: ignore[assignment]
                self._send_json(HTTPStatus.OK, self.runner.status(key, repo))
            else:
                known: bool = url.path in ("/api/run", "/api/cancel", "/api/status", "/api/config")
                self._send_json(HTTPStatus.METHOD_NOT_ALLOWED if known else HTTPStatus.NOT_FOUND, {"error": "not_found", "message": "no such endpoint"})
        except ApiError as error:
            self._send_json(error.status, {"error": error.code, "message": error.message})

    def do_GET(self) -> None:
        if self.path.startswith("/api/"):
            self._api("GET")
        else:
            super().do_GET()

    def do_HEAD(self) -> None:
        if self.path.startswith("/api/"):
            self._api("HEAD")
        else:
            super().do_HEAD()

    def do_POST(self) -> None:
        if self.path.startswith("/api/"):
            self._api("POST")
        else:
            self._send_json(HTTPStatus.METHOD_NOT_ALLOWED, {"error": "method_not_allowed", "message": "POST is only for /api/"})


def make_server(home: Path, runner: Runner, token: str, port: int = PORT, config: dict[str, Any] | None = None) -> ThreadingHTTPServer:
    """`config` is what GET /api/config answers: {default_variant, variants}."""
    handler = type("BoundHandler", (Handler,), {"runner": runner, "token": token.encode(),
                                                "config": config or {"default_variant": None, "variants": []}})
    server = ThreadingHTTPServer((ADDRESS, port), partial(handler, directory=str(home)))
    server.daemon_threads = True
    return server


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--port", type=int, default=PORT)
    args = parser.parse_args()
    local: dict[str, Any] = load_local()
    variant: str | None = local.get("default_variant")
    if not variant:
        raise SystemExit("local.toml needs `default_variant`, the variant a started run uses")
    if variant_file(variant) is None:
        raise SystemExit(f"local.toml: default_variant {variant!r} is not a variant in {HOME / 'variants'} or {ROOT / 'variants'}")
    allowed: dict[str, frozenset[str]] = parse_serve_repos(local.get("serve_repos"))
    if not any(allowed.values()):
        print("local.toml sets no serve_repos: every request to start a run will be refused", file=sys.stderr)
    token: str = load_token(TOKEN_FILE)
    runner = Runner(HOME, allowed, default_argv_for(variant))
    for key in runner.recover():
        print(f"run {key} was left running by a server that died; marked failed", file=sys.stderr)
    active: list[str] = load_active_variants(HOME, variant)
    server = make_server(HOME, runner, token, args.port, {"default_variant": variant, "variants": active})
    print(f"serving {HOME} on http://{ADDRESS}:{args.port} (token in {TOKEN_FILE}; variant {variant}; active {', '.join(active)})", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        runner.stop_all()
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
