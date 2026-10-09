#!/usr/bin/env python3
"""Serve the runs and start briefs on demand, for the browser extension.

usage: serve.py [--port 8765]

Binds to 127.0.0.1 only. Serves $PR_BRIEF_HOME (default: the tool's folder) as static files, so the
extension finds runs/<key>/<variant>/..., and adds an API under /api/ that starts `run.py` for one PR:

    POST /api/run     {host, owner, repo, n}  ->  {key, state}   start a run (or report the one in progress)
    GET  /api/status  ?key=fj-7[&host=&owner=&repo=]  ->  {state, stage, elapsed, error?, allowed?}
    POST /api/cancel  {key}                   ->  {state}        kill the run's process group
    GET  /api/config                          ->  {default_variant}   the variant a brief shows
    GET  /api/head    ?host=&owner=&repo=&n=  ->  {sha}            the PR's current head commit, or null when the host cannot say

`/api/head` only reads: it asks the host for the pull request's head commit (`gh` for GitHub, the REST API for
Forgejo), for an allow-listed repository only, and remembers each answer for 30 seconds.

`state` is idle, running, done, failed or canceled; `status` reads runs/<key>/status.json, which run.py
writes at each stage (see run_status.py). `allowed` is only present when host, owner and repo are given.
Every /api/ request must carry the server token in `X-PR-Brief-Token`, and any `Origin` it carries must start
with chrome-extension://, or it gets 403. The token is created on first start in ~/.config/pr-brief/token
(mode 0600) and never logged. Static files need neither.

local.toml sets `default_variant` (the variant a run uses) and `serve_repos`, the repositories a run may be
started for, as a table of host to owner/name list; see local.example.toml. Standard library only.
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
from hosts import get_host, host_names, parse_run_key, run_key

ADDRESS = "127.0.0.1"
PORT = 8765
MAX_RUNNING = 2
TOKEN_FILE = Path("~/.config/pr-brief/token").expanduser()
TOKEN_HEADER = "X-PR-Brief-Token"
EXTENSION_ORIGIN = "chrome-extension://"
MAX_BODY_BYTES = 4096
KILL_GRACE_SECONDS = 5
HEAD_CACHE_SECONDS = 30
SHA = re.compile(r"^[0-9a-f]{40}$")
NAME = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9._-]{0,99}$")

ArgvFor = Callable[[str, str, str, int], list[str]]
HeadLookup = Callable[[str, str, str, int], str]


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


def pr_number(value: Any) -> int:
    """`value` as a pull request number; raises ApiError unless it is a positive integer."""
    if isinstance(value, bool) or not isinstance(value, int) or not 0 < value < 10**9:
        raise ApiError(HTTPStatus.BAD_REQUEST, "bad_request", "n must be a positive integer")
    return value


def default_head_lookup(settings: dict[str, Any]) -> HeadLookup:
    """Reads a head commit through the host modules, which only read; `settings` is local.toml's contents."""
    def lookup(host: str, owner: str, repo: str, n: int) -> str:
        return get_host(host, settings).head_sha(owner, repo, n)
    return lookup


class Heads:
    """Answers GET /api/head: a PR's current head commit, for allow-listed repositories only. `lookup(host,
    owner, repo, n)` reads it from the host (a test substitutes a fake); an answer is kept for `ttl` seconds
    per host, repository and number. A lookup that fails, or returns anything but a 40-character sha, answers
    null, is logged as one line, and is not kept, so the next request asks the host again."""

    def __init__(self, allowed: dict[str, frozenset[str]], lookup: HeadLookup, ttl: float = HEAD_CACHE_SECONDS,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.allowed: dict[str, frozenset[str]] = allowed
        self.lookup: HeadLookup = lookup
        self.ttl: float = ttl
        self.clock: Callable[[], float] = clock
        self.lock: threading.Lock = threading.Lock()
        self.kept: dict[tuple[str, str, str, int], tuple[float, str]] = {}

    def head(self, query: dict[str, list[str]]) -> dict[str, Any]:
        values: dict[str, Any] = {name: query.get(name, [None])[0] for name in ("host", "owner", "repo", "n")}
        host, owner, repo, permitted = repo_parts(values["host"], values["owner"], values["repo"], self.allowed)
        raw: Any = values["n"]
        number: int = pr_number(int(raw) if isinstance(raw, str) and raw.isascii() and raw.isdigit() else None)
        if not permitted:
            raise ApiError(HTTPStatus.FORBIDDEN, "repo_not_allowed", f"{owner}/{repo} is not in serve_repos for {host}")
        key: tuple[str, str, str, int] = (host, owner.lower(), repo.lower(), number)
        with self.lock:
            hit: tuple[float, str] | None = self.kept.get(key)
            if hit and self.clock() - hit[0] < self.ttl:
                return {"sha": hit[1]}
        try:
            sha: Any = self.lookup(host, owner, repo, number)
            if not isinstance(sha, str) or not SHA.match(sha):
                raise ValueError("no 40-character head sha in the answer")
        except (Exception, SystemExit) as error:
            reason: str = str(error).strip().splitlines()[0][:200] if str(error).strip() else type(error).__name__
            print(f"head lookup failed for {host} {owner}/{repo}#{number}: {reason}", file=sys.stderr, flush=True)
            return {"sha": None}
        with self.lock:
            self.kept[key] = (self.clock(), sha)
        return {"sha": sha}


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
        number: int = pr_number(body.get("n"))
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
                        env={**os.environ, "PR_BRIEF_HOME": str(self.home)},
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
            status: dict[str, Any] | None = run_status.read_status(self.home, key)
            if job and job.running() and status and status.get("state") == run_status.RUNNING:
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
    heads: Heads
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
            elif (method, url.path) == ("GET", "/api/head"):
                self._send_json(HTTPStatus.OK, self.heads.head(parse_qs(url.query)))
            elif (method, url.path) == ("GET", "/api/status"):
                query: dict[str, list[str]] = parse_qs(url.query)
                key: str = query.get("key", [""])[0]
                repo: tuple[Any, Any, Any] | None = None
                if "host" in query or "owner" in query or "repo" in query:
                    repo = tuple(query.get(name, [None])[0] for name in ("host", "owner", "repo"))  # type: ignore[assignment]
                self._send_json(HTTPStatus.OK, self.runner.status(key, repo))
            else:
                known: bool = url.path in ("/api/run", "/api/cancel", "/api/status", "/api/config", "/api/head")
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


def make_server(home: Path, runner: Runner, token: str, port: int = PORT, config: dict[str, Any] | None = None,
                heads: Heads | None = None) -> ThreadingHTTPServer:
    """`config` is what GET /api/config answers: {default_variant}. `heads` answers GET /api/head; by
    default it reads the real hosts for the runner's allow-list."""
    heads = heads or Heads(runner.allowed, default_head_lookup({}))
    handler = type("BoundHandler", (Handler,), {"runner": runner, "heads": heads, "token": token.encode(),
                                                "config": config or {"default_variant": None}})
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
    heads = Heads(allowed, default_head_lookup(local))
    server = make_server(HOME, runner, token, args.port, {"default_variant": variant}, heads)
    print(f"serving {HOME} on http://{ADDRESS}:{args.port} (token in {TOKEN_FILE}; variant {variant})", flush=True)
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
