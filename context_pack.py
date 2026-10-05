"""Builds the "Repository context" markdown for a PR: who calls the changed code, which apps it
reaches, contract changes, destructive migration statements and related wiki pages.

usage: from context_pack import ensure_commits, build
       ensure_commits([base, head]); pack = build(pr, diff, ["callers", "reach"]); pack.markdown()

Reads from a bare mirror of a local checkout kept in .cache/, topped up from GitHub by `git fetch`
for any commit it lacks. Reads the wiki checkout without writing to it. Every repository-specific
setting comes from local.toml (see local.example.toml and config.py); a section whose settings are
missing is skipped and the reason goes in the pack's `dropped` stats.
"""
import fcntl
import fnmatch
import json
import posixpath
import re
import subprocess
import tomllib
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

from config import HOME, config_file, load_local

LOCAL: dict[str, Any] = load_local()
CACHE = HOME / ".cache"
MIRROR = CACHE / LOCAL.get("mirror_name", "mirror.git")
LOCK = CACHE / "mirror.lock"
SOURCE_CHECKOUT: str | None = LOCAL.get("source_checkout")
GITHUB_URL: str | None = LOCAL.get("github_url")
WIKI_REPO: Path | None = Path(LOCAL["wiki_repo"]) if LOCAL.get("wiki_repo") else None
WIKI_FOLDER: str = LOCAL.get("wiki_dir", ".")
WIKI_DIR: Path | None = WIKI_REPO / WIKI_FOLDER if WIKI_REPO else None
REACH_CONFIG: Path | None = config_file("reach")

SECTIONS: tuple[str, ...] = ("callers", "reach", "contract", "migrations", "wiki")
TITLES: dict[str, str] = {
    "callers": "Callers",
    "reach": "App reach",
    "contract": "API contract changes",
    "migrations": "Migrations",
    "wiki": "Codebase wiki",
}
OWNER_CALLERS_INTRO = ("Files outside this PR that mention a changed symbol and also reference the class or module "
                       "that declares it, matched by name in the base commit.")
PRECISE_CALLERS_INTRO = ("Confirmed callers of changed code, from the base commit. The list is partial: every file listed "
                         "really calls the code, but many callers are missing (for example calls over HTTP, through "
                         "interfaces or by reflection).")
INTROS: dict[str, str] = {
    "callers": "Files outside this PR that mention a changed symbol, matched by name in the base commit.",
    "reach": "Apps that contain changed files or files that call the changed code.",
    "contract": f"Differences between the base and head `{LOCAL.get('openapi_path', 'OpenAPI document')}`.",
    "migrations": "Statements in the PR's new migration files that change or remove existing data or schema.",
    "wiki": "Related pages from the codebase wiki; may be out of date.",
}
# The order in which sections lose items when the pack is over budget.
TRIM_ORDER: tuple[str, ...] = ("wiki", "callers", "reach", "contract", "migrations")
OMITTED_UNITS: dict[str, str] = {
    "callers": "changed symbols", "reach": "apps", "contract": "contract lines",
    "migrations": "migration statements", "wiki": "wiki pages",
}

MAX_SYMBOLS = 15
MAX_CALLER_FILES_PER_SYMBOL = 50
MAX_CALLER_PATHS_SHOWN = 10
MAX_CONTRACT_LINES = 30
MAX_WIKI_PAGES = 4
CODE_PATHSPECS: tuple[str, ...] = ("*.java", "*.kt", "*.ts", "*.tsx", "*.js", "*.jsx", "*.sql")
CODE_ONLY_EXCLUDES: tuple[str, ...] = (
    ":!**/*.md", ":!**/*.mdc", ":!**/package-lock.json",
    *(f":!{glob}" for glob in LOCAL.get("callers_exclude_globs", [])),
)
WIKI_MATCH_MODES: frozenset[str] = frozenset({"folder", "exact"})
CALLERS_MODES: frozenset[str] = frozenset({"default", "precise"})
# Context options a variant may set in its `[context_options]` table. Each default reproduces the
# behavior of a variant that sets no options.
DEFAULT_OPTIONS: dict[str, Any] = {
    "callers_code_only": False, "list_uncalled": False, "wiki_match": "folder",
    "callers_skip_new_files": False, "callers_require_owner": False, "callers_skip_fields": False,
    "callers_mode": "default",
}
BOOLEAN_OPTIONS: frozenset[str] = frozenset(k for k, v in DEFAULT_OPTIONS.items() if isinstance(v, bool))
MAX_NEW_SYMBOLS_LISTED = 15
MIN_SYMBOL_LENGTH = 4
COMMON_WORDS: frozenset[str] = frozenset({
    "get", "set", "find", "create", "update", "delete", "build", "apply", "equals", "hashCode",
    "toString", "main", "render", "default",
})
OPENAPI_PATH: str | None = LOCAL.get("openapi_path")
HTTP_METHODS: frozenset[str] = frozenset({"get", "put", "post", "delete", "options", "head", "patch", "trace"})

JAVA_METHOD = re.compile(r"(public|protected)\s+[^=;(]*\b(\w+)\s*\(")
JAVA_TYPE = re.compile(r"^\s*(?:(?:public|protected|private|static|final|abstract|sealed|non-sealed)\s+)*(?:class|interface|record|enum)\s+(\w+)")
TS_EXPORT = re.compile(r"export\s+(default\s+)?(async\s+)?(function|const|class|type|interface|enum)\s+(\w+)")
HUNK_HEADER = re.compile(r"^@@ [^@]* @@\s*(.*)$")
HEADER_CALL = re.compile(r"\b(\w+)\s*\(")
HEADER_DECLARATION = re.compile(r"\b(?:function|const|class|type|interface|enum|record)\s+(\w+)")
NOT_CALLS: frozenset[str] = frozenset({"if", "for", "while", "switch", "catch", "return", "new", "synchronized"})
JAVA_ANNOTATION = re.compile(r"@\w+(?:\([^)]*\))?\s*")
JAVA_MODIFIERS = re.compile(r"\b(?:public|protected|private|static|final|abstract|default|synchronized|native)\b")
JAVA_TYPE_TOKEN = re.compile(r"^(?:<[^>]*>\s*)?[\w.]+(?:<.*>)?(?:\[\])*$")
NOT_RETURN_TYPES: frozenset[str] = frozenset({"return", "new", "throw", "else", "case", "yield", "await"})
TS_IMPORT_EXTENSIONS = r"(\.[jt]sx?)?"
IMPORT_QUOTE = "[\"']"

MIGRATION_DIRS: tuple[str, ...] = tuple(LOCAL.get("migration_dirs", []))
ALTER_TABLE = re.compile(r"\bALTER\s+TABLE\s+(?:ONLY\s+|IF\s+EXISTS\s+)*([\w.\"]+)", re.IGNORECASE)
MIGRATION_STATEMENTS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("DELETE FROM", re.compile(r"\bDELETE\s+FROM\s+([\w.\"]+)", re.IGNORECASE)),
    ("UPDATE", re.compile(r"(?<!\bON\s)\bUPDATE\s+(?!CASCADE\b|RESTRICT\b|SET\b|NO\b)([\w.\"]+)", re.IGNORECASE)),
    ("DROP TABLE", re.compile(r"\bDROP\s+TABLE\s+(?:IF\s+EXISTS\s+)?([\w.\"]+)", re.IGNORECASE)),
    ("DROP COLUMN", re.compile(r"\bDROP\s+COLUMN\s+(?:IF\s+EXISTS\s+)?([\w.\"]+)", re.IGNORECASE)),
    ("DROP CONSTRAINT", re.compile(r"\bDROP\s+CONSTRAINT\s+(?:IF\s+EXISTS\s+)?([\w.\"]+)", re.IGNORECASE)),
    ("DROP INDEX", re.compile(r"\bDROP\s+INDEX\s+(?:CONCURRENTLY\s+)?(?:IF\s+EXISTS\s+)?([\w.\"]+)", re.IGNORECASE)),
    ("TRUNCATE", re.compile(r"\bTRUNCATE\s+(?:TABLE\s+)?(?:ONLY\s+)?([\w.\"]+)", re.IGNORECASE)),
    ("SET NOT NULL", re.compile(r"\bALTER\s+COLUMN\s+([\w.\"]+)\s+SET\s+NOT\s+NULL", re.IGNORECASE)),
)
# Statements whose captured name is a column or index of the table named by the enclosing ALTER TABLE.
MEMBER_STATEMENTS: frozenset[str] = frozenset({"DROP COLUMN", "DROP CONSTRAINT", "DROP INDEX", "SET NOT NULL"})


def git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", "-C", str(repo), *args], check=check, capture_output=True, text=True)


def has_commit(sha: str) -> bool:
    return MIRROR.exists() and git(MIRROR, "cat-file", "-e", f"{sha}^{{commit}}", check=False).returncode == 0


def ensure_commits(shas: list[str], host: str = "github") -> None:
    """Make every sha available in the mirror, cloning it first when absent. Serialized across
    processes by a file lock. Without `source_checkout` no mirror is cloned. For a GitHub PR a missing sha
    is fetched from `github_url` (nothing is fetched without it); for a Forgejo PR it is fetched from
    `source_checkout`, where the commits of a Forgejo branch normally already are, and never from GitHub.
    A sha that cannot be fetched stays missing; `build` drops the sections that need it."""
    if not (MIRROR.exists() or SOURCE_CHECKOUT):
        return
    CACHE.mkdir(exist_ok=True)
    with LOCK.open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if not MIRROR.exists():
            subprocess.run(["git", "clone", "--bare", SOURCE_CHECKOUT, str(MIRROR)], check=True, capture_output=True, text=True)
        for sha in shas:
            if has_commit(sha):
                continue
            if host == "github":
                if GITHUB_URL:
                    git(MIRROR, "-c", "credential.helper=", "-c", "credential.helper=!gh auth git-credential",
                        "fetch", GITHUB_URL, sha, check=False)
            elif SOURCE_CHECKOUT:
                git(MIRROR, "fetch", "--no-tags", SOURCE_CHECKOUT, sha, check=False)


TEST_DIRS: tuple[str, ...] = ("/src/test/", *LOCAL.get("test_dirs", []))


def is_test_file(path: str) -> bool:
    return any(d in path for d in TEST_DIRS) or ".test." in path or path.endswith("Test.java")


@dataclass
class DiffFile:
    path: str
    is_new: bool = False
    lines: list[str] = field(default_factory=list)


def parse_diff(diff: str) -> list[DiffFile]:
    files: list[DiffFile] = []
    for line in diff.splitlines():
        if line.startswith("diff --git "):
            match = re.match(r"diff --git a/(.*) b/(.*)$", line)
            files.append(DiffFile(path=match.group(2) if match else line))
        elif files:
            if line.startswith("new file mode"):
                files[-1].is_new = True
            files[-1].lines.append(line)
    return files


def usable_symbol(name: str) -> bool:
    return len(name) >= MIN_SYMBOL_LENGTH and name not in COMMON_WORDS and name not in NOT_CALLS


@dataclass
class Declaration:
    """A name found on a changed line or in a hunk header. `kind` is "type" (a class, interface,
    record or enum, which is its own owner), "method" (a Java method with a return type), "export"
    (an exported TS function, const or type alias) or "other" (anything else: an annotation, a call,
    a local name)."""
    name: str
    path: str
    kind: str


def is_java_method_declaration(text: str, name: str) -> bool:
    """Whether `text` declares a method `name`: modifiers and annotations, then a return type, then `name(`."""
    m = re.search(rf"\b{re.escape(name)}\s*\(", text)
    if not m:
        return False
    prefix: str = JAVA_MODIFIERS.sub(" ", JAVA_ANNOTATION.sub(" ", text[:m.start()])).strip()
    return bool(JAVA_TYPE_TOKEN.match(prefix)) and not NOT_RETURN_TYPES.intersection(re.findall(r"\w+", prefix))


def java_kind(name: str, path: str, text: str) -> str:
    if name == PurePosixPath(path).stem:
        return "type"
    return "method" if is_java_method_declaration(text, name) else "other"


def header_symbol(context: str, path: str, is_java: bool) -> Declaration | None:
    if is_java:
        m = JAVA_TYPE.match(context)
        if m:
            return Declaration(m.group(1), path, "type")
    m = HEADER_DECLARATION.search(context)
    if m:
        keyword: str = context[m.start():m.start(1)].split()[0]
        if keyword in {"class", "interface", "enum", "record"}:
            kind: str = "type"
        elif is_java:
            kind = java_kind(m.group(1), path, context)
        else:
            kind = "export" if re.search(r"\bexport\b", context[:m.start()]) else "other"
        return Declaration(m.group(1), path, kind)
    for m in HEADER_CALL.finditer(context):
        if m.group(1) not in NOT_CALLS:
            return Declaration(m.group(1), path, java_kind(m.group(1), path, context) if is_java else "other")
    return None


def declarations(files: list[DiffFile]) -> list[Declaration]:
    """Declarations on changed lines (in order of appearance), then those from hunk headers."""
    declared: list[Declaration] = []
    from_headers: list[Declaration] = []
    for f in files:
        if is_test_file(f.path):
            continue
        is_java: bool = f.path.endswith(".java")
        is_ts: bool = f.path.endswith((".ts", ".tsx"))
        if not (is_java or is_ts):
            continue
        for line in f.lines:
            if line.startswith("@@"):
                m = HUNK_HEADER.match(line)
                header: Declaration | None = header_symbol(m.group(1), f.path, is_java) if m and m.group(1).strip() else None
                if header:
                    from_headers.append(header)
            elif line[:1] in "+-" and not line.startswith(("+++", "---")):
                body: str = line[1:]
                if body.lstrip().startswith(("//", "*", "/*")):
                    continue
                if is_java:
                    method = JAVA_METHOD.search(body)
                    if method:
                        declared.append(Declaration(method.group(2), f.path, java_kind(method.group(2), f.path, body)))
                    declared_type = JAVA_TYPE.match(body)
                    if declared_type:
                        declared.append(Declaration(declared_type.group(1), f.path, "type"))
                else:
                    m = TS_EXPORT.search(body)
                    if m:
                        declared.append(Declaration(m.group(4), f.path, "type" if m.group(3) in {"class", "interface", "enum"} else "export"))
    return [*declared, *from_headers]


def declarations_by_name(files: list[DiffFile]) -> dict[str, list[Declaration]]:
    """Usable names in order of first appearance, each with all of its declarations."""
    by_name: dict[str, list[Declaration]] = {}
    for d in declarations(files):
        if usable_symbol(d.name):
            by_name.setdefault(d.name, []).append(d)
    return by_name


def changed_symbols(files: list[DiffFile]) -> list[str]:
    """Names declared on changed lines (in order of appearance), then names from hunk headers."""
    return list(declarations_by_name(files))[:MAX_SYMBOLS]


def grep_files(base: str, pattern_args: tuple[str, ...], changed: set[str], code_only: bool,
               includes: tuple[str, ...] | None = None) -> list[str]:
    """Non-test files outside the PR that match `pattern_args`, a `git grep` pattern with its flags,
    within the pathspecs `includes` (default: all files, or code files when `code_only`)."""
    includes = includes or (CODE_PATHSPECS if code_only else (".",))
    excludes: tuple[str, ...] = (*(f":!**{d.rstrip('/')}/**" for d in TEST_DIRS), ":!**/*.test.ts", ":!**/*.test.tsx",
                                 *(CODE_ONLY_EXCLUDES if code_only else ()))
    out: str = git(MIRROR, "grep", "-l", *pattern_args, base, "--", *includes, *excludes, check=False).stdout
    prefix: str = f"{base}:"
    paths: list[str] = [line.removeprefix(prefix) for line in out.splitlines() if line]
    return sorted(p for p in paths if p not in changed)


def grep_callers(base: str, name: str, changed: set[str], code_only: bool = False) -> list[str]:
    return grep_files(base, ("-w", name), changed, code_only)


def grep_importers(base: str, module: str, changed: set[str], code_only: bool) -> list[str]:
    """Files with an import line whose module specifier ends with `module`, a file name without its extension."""
    escaped: str = re.sub(r"([.$*+?()\[\]{}|^\\])", r"\\\1", module)
    pattern: str = rf"(from|import|require)[[:space:]]*\(?[[:space:]]*{IMPORT_QUOTE}([^\"']*/)?{escaped}{TS_IMPORT_EXTENSIONS}{IMPORT_QUOTE}"
    return grep_files(base, ("-E", "-e", pattern), changed, code_only)


def owner_files(base: str, declarations: list[Declaration], changed: set[str], code_only: bool,
                cache: dict[tuple[str, str], set[str]]) -> set[str] | None:
    """Files that reference a declaring class (Java) or import a defining module (TS) of a symbol.
    None when the symbol needs no owner (it is a type, so it is its own owner)."""
    if any(d.kind == "type" for d in declarations):
        return None
    found: set[str] = set()
    for d in declarations:
        stem: str = PurePosixPath(d.path).stem
        is_java: bool = d.path.endswith(".java")
        key: tuple[str, str] = ("class" if is_java else "module", stem)
        if key not in cache:
            cache[key] = set(grep_callers(base, stem, changed, code_only) if is_java
                             else grep_importers(base, stem, changed, code_only))
        found |= cache[key]
    return found


JAVA_IMPORT = re.compile(r"^[ \t]*import\s[^;]*;", re.MULTILINE)
JAVA_NOISE = re.compile(r"\"\"\"[\s\S]*?\"\"\"|\"(?:\\.|[^\"\\\n])*\"|'(?:\\.|[^'\\\n])*'|//[^\n]*|/\*[\s\S]*?\*/")
TS_NOISE = re.compile(r"(\"(?:\\.|[^\"\\\n])*\"|'(?:\\.|[^'\\\n])*'|`(?:\\.|[^`\\])*`)|//[^\n]*|/\*[\s\S]*?\*/")
TS_IMPORT = re.compile(r"\bimport\s+(?:type\s+)?(?P<clause>[^;\"']*?)\s*from\s*(?P<quote>[\"'])(?P<spec>[^\"'\n]+)(?P=quote)")
TS_SOURCE_EXTENSION = re.compile(r"\.(?:[cm]?[jt]sx?)$")
SDK_DIR: str | None = LOCAL.get("sdk_dir")
SDK_SPECIFIER: str | None = LOCAL.get("sdk_specifier")
WORKSPACE_ALIAS: re.Pattern[str] | None = re.compile(LOCAL["workspace_alias"]) if LOCAL.get("workspace_alias") else None
WORKSPACE_ROOT: str | None = LOCAL.get("workspace_root")
JAVA_SOURCE_ROOT = "/src/main/java/"
LANGUAGE_PATHSPECS: dict[str, tuple[str, ...]] = {"java": ("*.java",), "ts": ("*.ts", "*.tsx")}
DROP_AMBIGUOUS = "ambiguous name"
DROP_NO_MATCH = "no qualified match"
DROP_CROSS_LANGUAGE = "cross-language"


def language_of(path: str) -> str | None:
    if path.endswith(".java"):
        return "java"
    return "ts" if path.endswith((".ts", ".tsx")) else None


class BlobReader:
    """Reads files at one commit of the mirror, many per `git cat-file --batch`, and caches their text
    with comments (and, for Java, string literals) removed."""

    def __init__(self, commit: str) -> None:
        self.commit: str = commit
        self._raw: dict[str, str] = {}
        self._clean: dict[str, str] = {}

    def raw(self, path: str) -> str:
        self.load([path])
        return self._raw[path]

    def load(self, paths: list[str]) -> None:
        missing: list[str] = [p for p in dict.fromkeys(paths) if p not in self._raw]
        if not missing:
            return
        wanted: bytes = "".join(f"{self.commit}:{p}\n" for p in missing).encode()
        out: bytes = subprocess.run(["git", "-C", str(MIRROR), "cat-file", "--batch"], input=wanted,
                                    capture_output=True, check=True).stdout
        pos: int = 0
        for path in missing:
            end: int = out.index(b"\n", pos)
            header: list[bytes] = out[pos:end].split()
            pos = end + 1
            if header[-1] == b"missing":
                self._raw[path] = ""
                continue
            size: int = int(header[2])
            self._raw[path] = out[pos:pos + size].decode(errors="replace")
            pos += size + 1

    def java_body(self, path: str) -> str:
        """A Java file's cleaned text without its import statements, so that a name counts only when the code uses it."""
        return JAVA_IMPORT.sub("", self.clean(path))

    def clean(self, path: str) -> str:
        """The file without comments; Java string literals become empty strings."""
        if path not in self._clean:
            text: str = self.raw(path)
            if path.endswith(".java"):
                self._clean[path] = JAVA_NOISE.sub(lambda m: m.group()[0] * 2 if m.group()[0] in "\"'" else " ", text)
            else:
                self._clean[path] = TS_NOISE.sub(lambda m: m.group(1) or " ", text)
        return self._clean[path]


def declares_java_method(text: str, name: str) -> bool:
    """Whether the line declares a method `name`: a return type before the name and not a call."""
    m = re.search(rf"\b{re.escape(name)}\s*\(", text)
    return bool(m and m.start() > 0 and text[m.start() - 1].isspace()
                and not text.lstrip().startswith(("//", "*", "/*"))
                and is_java_method_declaration(text, name))


def java_method_declarations(base: str, name: str) -> dict[str, list[str]]:
    """Declaration lines of a method `name` in every Java file at `base`, by path."""
    out: str = git(MIRROR, "grep", "-n", "-w", "-F", name, base, "--", "*.java", check=False).stdout
    found: dict[str, list[str]] = {}
    for line in out.splitlines():
        path, _, rest = line.removeprefix(f"{base}:").partition(":")
        text: str = rest.partition(":")[2]
        if declares_java_method(text, name):
            found.setdefault(path, []).append(text)
    return found


def extends_class(reader: BlobReader, path: str, owner: str) -> bool:
    """Whether a type in the file at `path` names `owner` in its `implements` or `extends` clause."""
    return bool(re.search(rf"\b(?:class|interface|record|enum)\s+\w+[^{{;]*\b(?:implements|extends)\b[^{{;]*\b{re.escape(owner)}\b",
                          reader.clean(path)))


def java_package(path: str) -> str | None:
    return path.partition(JAVA_SOURCE_ROOT)[2].rpartition("/")[0].replace("/", ".") if JAVA_SOURCE_ROOT in path else None


def java_type_callers(reader: BlobReader, name: str, decl_path: str, candidates: list[str]) -> list[str]:
    """Java files that mention type `name` and either import it or sit in the declaring file's directory."""
    package: str | None = java_package(decl_path)
    stem: str = PurePosixPath(decl_path).stem
    imported: re.Pattern[str] | None = None
    if package:
        target: str = rf"(?:{re.escape(name)}\b|\*)" if stem == name else rf"{re.escape(stem)}(?:\.(?:{re.escape(name)}\b|\*)|\s*;)"
        imported = re.compile(rf"^\s*import\s+(?:static\s+)?{re.escape(package)}\.{target}", re.MULTILINE)
    word: re.Pattern[str] = re.compile(rf"\b{re.escape(name)}\b")
    return [p for p in candidates
            if word.search(reader.java_body(p))
            and (PurePosixPath(p).parent == PurePosixPath(decl_path).parent or (imported and imported.search(reader.clean(p))))]


def calls_on_owner_variable(body: str, call: re.Pattern[str], owner: str) -> bool:
    """Whether `body` calls the method on a variable, field or parameter declared with type `owner`."""
    return any(re.search(rf"\b{re.escape(owner)}\b(?:<[^;(){{}}]*>)?\s+{re.escape(m.group(1))}\b", body)
               for m in call.finditer(body))


def java_method_callers(base: str, reader: BlobReader, name: str, decl_path: str, candidates: list[str]) -> tuple[list[str], str]:
    """Callers of a Java method declared in `decl_path`, with the reason when none qualifies.
    A static method is called as `Owner.name(`. An instance method needs a unique name across the
    base commit's Java classes, except for implementations of the declaring type, and then a file that
    calls `.name(` on a variable declared with the owner's type."""
    owner: str = PurePosixPath(decl_path).stem
    declared: dict[str, list[str]] = java_method_declarations(base, name)
    own_lines: list[str] = declared.get(decl_path, [])
    if not own_lines:
        return [], DROP_NO_MATCH
    statics: list[bool] = [bool(re.search(r"\bstatic\b", line[:re.search(rf"\b{re.escape(name)}\s*\(", line).start()])) for line in own_lines]
    if all(statics):
        call: re.Pattern[str] = re.compile(rf"\b{re.escape(owner)}\s*\.\s*{re.escape(name)}\s*\(")
        return [p for p in candidates if call.search(reader.java_body(p))], DROP_NO_MATCH
    if any(statics):
        return [], DROP_AMBIGUOUS
    reader.load([p for p in declared if p != decl_path])
    if not all(extends_class(reader, p, owner) for p in declared if p != decl_path):
        return [], DROP_AMBIGUOUS
    call = re.compile(rf"\b(\w+)\s*\.\s*{re.escape(name)}\s*\(")
    return [p for p in candidates if calls_on_owner_variable(reader.java_body(p), call, owner)], DROP_NO_MATCH


def import_target(spec: str, caller: str) -> list[str] | None:
    """The module paths (without extension) that an import specifier can name, or None for a package
    outside the workspace. A directory import also names its `index` module."""
    spec = TS_SOURCE_EXTENSION.sub("", spec.split("?")[0])
    if spec.startswith("."):
        target: str = posixpath.normpath(posixpath.join(posixpath.dirname(caller), spec))
    else:
        alias = WORKSPACE_ALIAS.match(spec) if WORKSPACE_ALIAS and WORKSPACE_ROOT else None
        if not alias:
            return None
        target = posixpath.join(WORKSPACE_ROOT, alias.group(1), alias.group(2) or "index")
    return [target, f"{target}/index"]


def ts_imports(text: str, name: str) -> list[str]:
    """Module specifiers of the import statements in `text` that bring in `name` (a named import, with
    or without `type`, or a default import)."""
    specs: list[str] = []
    for m in TS_IMPORT.finditer(text):
        clause: str = m.group("clause").strip()
        if clause.startswith("*"):
            continue
        braces = re.search(r"\{([^}]*)\}", clause)
        named: list[str] = [re.sub(r"^type\s+", "", item.strip()).split(" as ")[0].strip()
                            for item in (braces.group(1).split(",") if braces else [])]
        default = re.match(r"(\w+)\s*(?:,|$)", clause)
        if name in named or (default and default.group(1) == name):
            specs.append(m.group("spec"))
    return specs


def ts_export_callers(reader: BlobReader, name: str, decl_path: str, candidates: list[str]) -> list[str]:
    """TS/TSX files with an import statement that names `name` from the module that defines it. Every
    TS declaration is checked this way, classes, interfaces and enums included, since only an import
    ties a mention to the declaring module."""
    module: str = TS_SOURCE_EXTENSION.sub("", decl_path)
    in_sdk: bool = bool(SDK_DIR and SDK_SPECIFIER and decl_path.startswith(SDK_DIR))
    callers: list[str] = []
    for path in candidates:
        for spec in ts_imports(reader.clean(path), name):
            target: list[str] | None = import_target(spec, path)
            if (in_sdk and (spec == SDK_SPECIFIER or spec.startswith(f"{SDK_SPECIFIER}/"))) or (target and module in target):
                callers.append(path)
                break
    return callers


def precise_callers(base: str, reader: BlobReader, name: str, declared: list[Declaration], changed: set[str],
                    code_only: bool) -> tuple[list[str], str | None]:
    """Callers of `name` that the declaration's own rules confirm, and when there are none, why the
    symbol was dropped."""
    confirmed: set[str] = set()
    reasons: list[str] = []
    everywhere: list[str] = grep_callers(base, name, changed, code_only)
    for d in declared:
        language: str | None = language_of(d.path)
        if d.kind == "other" or language is None:
            reasons.append(DROP_NO_MATCH)
            continue
        candidates: list[str] = [p for p in grep_files(base, ("-w", name), changed, code_only, LANGUAGE_PATHSPECS[language])
                                 if p in everywhere]
        reader.load(candidates)
        reason: str = DROP_NO_MATCH
        if language == "ts":
            found: list[str] = ts_export_callers(reader, name, d.path, candidates)
        elif d.kind == "type":
            found = java_type_callers(reader, name, d.path, candidates)
        else:
            found, reason = java_method_callers(base, reader, name, d.path, candidates)
        confirmed.update(found)
        reasons.append(reason)
    if confirmed:
        return sorted(confirmed), None
    if DROP_AMBIGUOUS in reasons:
        return [], DROP_AMBIGUOUS
    languages: set[str | None] = {language_of(d.path) for d in declared}
    if everywhere and not any(language_of(p) in languages for p in everywhere):
        return [], DROP_CROSS_LANGUAGE
    return [], DROP_NO_MATCH


def app_names_for(path: str, apps: list[dict[str, Any]]) -> list[str]:
    return [a["name"] for a in apps if any(fnmatch.fnmatchcase(path, g) for g in a["globs"])]


def read_json_at(sha: str, path: str) -> dict[str, Any] | None:
    shown = git(MIRROR, "show", f"{sha}:{path}", check=False)
    return json.loads(shown.stdout) if shown.returncode == 0 else None


def enum_values(node: Any) -> list[Any]:
    """Enum values of a schema or property, including those of an array's items."""
    if not isinstance(node, dict):
        return []
    return [*node.get("enum", []), *enum_values(node.get("items"))]


def contract_lines(base: dict[str, Any], head: dict[str, Any]) -> list[str]:
    operations: list[str] = []
    removed_props: list[str] = []
    required: list[str] = []
    enums: list[str] = []

    for path, item in base.get("paths", {}).items():
        head_item: dict[str, Any] = head.get("paths", {}).get(path, {})
        for method in item:
            if method in HTTP_METHODS and method not in head_item:
                operations.append(f"removed operation {method.upper()} {path}")

    base_schemas: dict[str, Any] = base.get("components", {}).get("schemas", {})
    head_schemas: dict[str, Any] = head.get("components", {}).get("schemas", {})
    for name, schema in base_schemas.items():
        new_schema: dict[str, Any] | None = head_schemas.get(name)
        if new_schema is None:
            removed_props.append(f"{name} (schema removed)")
            continue
        old_props: dict[str, Any] = schema.get("properties", {})
        new_props: dict[str, Any] = new_schema.get("properties", {})
        removed_props.extend(f"{name}.{p} (property removed)" for p in old_props if p not in new_props)
        required.extend(f"{name}.{p} (now required)"
                        for p in new_schema.get("required", []) if p not in schema.get("required", []))
        for value in enum_values(schema):
            if value not in enum_values(new_schema):
                enums.append(f"{name} (enum value {value} removed)")
        for p, prop in old_props.items():
            if p in new_props:
                gone: list[Any] = [v for v in enum_values(prop) if v not in enum_values(new_props[p])]
                enums.extend(f"{name}.{p} (enum value {v} removed)" for v in gone)
    return [*operations, *removed_props, *required, *enums]


def migration_items(files: list[DiffFile]) -> list[str]:
    items: list[str] = []
    for f in files:
        if not (f.is_new and any(d in f.path for d in MIGRATION_DIRS)):
            continue
        table: str = ""
        for line in f.lines:
            if not line.startswith("+") or line.startswith("+++"):
                continue
            sql: str = line[1:].split("--", 1)[0]
            alter = ALTER_TABLE.search(sql)
            if alter:
                table = alter.group(1)
            for keyword, pattern in MIGRATION_STATEMENTS:
                m = pattern.search(sql)
                if not m:
                    continue
                target: str = m.group(1)
                if keyword in MEMBER_STATEMENTS and table:
                    target = f"{table}.{target}" if keyword in {"DROP COLUMN", "SET NOT NULL"} else f"{table} ({target})"
                items.append(f"{PurePosixPath(f.path).name}: {keyword} {target}")
    return list(dict.fromkeys(items))


@dataclass
class WikiPage:
    path: str
    title: str
    description: str
    resources: set[str]


def load_wiki_pages() -> list[WikiPage]:
    pages: list[WikiPage] = []
    if WIKI_DIR is None or not WIKI_DIR.exists():
        return pages
    for md in sorted(WIKI_DIR.rglob("*.md")):
        rel: Path = md.relative_to(WIKI_DIR)
        if any(part.startswith(".") for part in rel.parts):
            continue
        text: str = md.read_text()
        match = re.match(r"---\n(.*?)\n---\n(.*)", text, re.DOTALL)
        if not match:
            continue
        front: dict[str, Any] = yaml.safe_load(match.group(1)) or {}
        heading = re.search(r"^# (.+)$", match.group(2), re.MULTILINE)
        title: str = str(front.get("title") or (heading.group(1) if heading else rel.stem))
        resources: set[str] = set(re.findall(r"resource:\s*repo://(\S+)", match.group(1)))
        pages.append(WikiPage(rel.as_posix() if WIKI_FOLDER == "." else f"{WIKI_FOLDER}/{rel.as_posix()}", title, " ".join(str(front.get("description", "")).split()), resources))
    return pages


def wiki_items(changed: list[str], match: str = "folder") -> list[str]:
    """Pages ranked by score. "folder" gives an exact `repo://` path 2 points and a path in the same
    folder 1. "exact" counts only exact paths, one point each, and skips pages without a description."""
    scored: list[tuple[int, WikiPage]] = []
    for page in load_wiki_pages():
        if match == "exact":
            score: int = sum(1 for p in changed if p in page.resources) if page.description else 0
        else:
            folders: set[str] = {str(PurePosixPath(r).parent) for r in page.resources}
            score = sum(2 if p in page.resources else 1 if str(PurePosixPath(p).parent) in folders else 0 for p in changed)
        if score:
            scored.append((score, page))
    scored.sort(key=lambda s: (-s[0], s[1].path))
    return [f"**{p.title}** (`{p.path}`)" + (f": {p.description}" if p.description else "") for _, p in scored[:MAX_WIKI_PAGES]]


def wiki_sha() -> str | None:
    if WIKI_REPO is None:
        return None
    result = git(WIKI_REPO, "rev-parse", "HEAD", check=False)
    return result.stdout.strip() if result.returncode == 0 else None


@dataclass
class Pack:
    items: dict[str, list[str]]
    skipped_common: dict[str, int]
    dropped: dict[str, str]
    wiki_sha: str | None
    trimmed: dict[str, int] = field(default_factory=dict)
    footers: dict[str, list[str]] = field(default_factory=dict)
    uncalled: list[str] | None = None
    new_in_pr: list[str] | None = None
    fields_dropped: int | None = None
    intros: dict[str, str] = field(default_factory=dict)
    caller_files: dict[str, list[str]] = field(default_factory=dict)
    precise: dict[str, str | None] | None = None
    _text: str | None = None
    _tokens: int = 0

    def markdown(self, budget_tokens: int = 6000) -> str:
        """One `### <Section>` per section with items, trimmed by whole items to the token budget
        (chars / 4). Trimmed sections say how many items were left out."""
        kept: dict[str, list[str]] = {name: list(items) for name, items in self.items.items() if items or self.footers.get(name)}
        omitted: dict[str, int] = {}
        text: str = self._render(kept, omitted)
        for name in TRIM_ORDER:
            while len(text) / 4 > budget_tokens and kept.get(name):
                kept[name].pop()
                omitted[name] = omitted.get(name, 0) + 1
                text = self._render(kept, omitted)
        self.trimmed = omitted
        self._text = text
        self._tokens = round(len(text) / 4)
        return text

    def _render(self, kept: dict[str, list[str]], omitted: dict[str, int]) -> str:
        blocks: list[str] = []
        for name in SECTIONS:
            if name not in kept:
                continue
            lines: list[str] = [f"### {TITLES[name]}", self.intros.get(name, INTROS[name]), *kept[name], *self.footers.get(name, [])]
            if omitted.get(name):
                lines.append(f"({omitted[name]} more {OMITTED_UNITS[name]} omitted)")
            blocks.append("\n".join(lines))
        return "\n\n".join(blocks)

    def _precise_stats(self, reasons: dict[str, str | None]) -> dict[str, Any]:
        """Per symbol, `dropped_reason` (None for a symbol with confirmed callers), and the totals."""
        by_reason: dict[str, int] = {}
        for reason in reasons.values():
            if reason:
                by_reason[reason] = by_reason.get(reason, 0) + 1
        return {
            "symbols": {name: {"dropped_reason": reason, "caller_files": len(self.caller_files.get(name, []))}
                        for name, reason in reasons.items()},
            "confirmed": sum(1 for reason in reasons.values() if reason is None),
            "dropped": sum(by_reason.values()),
            "dropped_by_reason": by_reason,
        }

    def stats(self) -> dict[str, Any]:
        if self._text is None:
            self.markdown()
        dropped: dict[str, str] = {**self.dropped}
        for name, count in self.trimmed.items():
            dropped[name] = f"{count} items trimmed to fit the token budget"
        return {
            "sections": {name: len(items) - self.trimmed.get(name, 0) for name, items in self.items.items()},
            **({"uncalled": len(self.uncalled)} if self.uncalled is not None else {}),
            **({"new_in_pr": len(self.new_in_pr)} if self.new_in_pr is not None else {}),
            **({"fields_dropped": self.fields_dropped} if self.fields_dropped is not None else {}),
            **({"callers_precise": self._precise_stats(self.precise)} if self.precise is not None else {}),
            "skipped_common": self.skipped_common,
            "dropped": dropped,
            "estimated_tokens": self._tokens,
            "wiki_sha": self.wiki_sha,
        }


def build(pr: dict[str, Any], diff: str, sections: list[str], options: dict[str, Any] | None = None) -> Pack:
    """`options` overrides DEFAULT_OPTIONS: `callers_code_only` restricts the callers search to code
    files, `list_uncalled` lists changed symbols without callers outside the PR in the callers
    section, and `wiki_match` ("folder" or "exact") sets how wiki pages qualify. `callers_skip_new_files`
    skips the caller search for symbols declared only in files the PR adds and lists them instead,
    `callers_require_owner` keeps a caller only when it also references the symbol's declaring class
    (Java) or imports its defining module (TS), and `callers_skip_fields` drops names that are not
    methods, types or TS exports. `callers_mode` "precise" lists only callers that pass the
    declaration-specific rules (qualified static calls, unique instance-method names, resolved TS
    imports, same-language type mentions), says the list is partial and records why each other symbol
    was dropped."""
    settings: dict[str, Any] = {**DEFAULT_OPTIONS, **(options or {})}
    unknown_options: list[str] = [k for k in settings if k not in DEFAULT_OPTIONS]
    if unknown_options:
        raise ValueError(f"unknown context options: {', '.join(unknown_options)}")
    not_boolean: list[str] = [k for k in BOOLEAN_OPTIONS if not isinstance(settings[k], bool)]
    if not_boolean:
        raise ValueError(f"context options must be true or false: {', '.join(not_boolean)}")
    if settings["wiki_match"] not in WIKI_MATCH_MODES:
        raise ValueError(f"unknown wiki_match: {settings['wiki_match']}")
    if settings["callers_mode"] not in CALLERS_MODES:
        raise ValueError(f"unknown callers_mode: {settings['callers_mode']}")
    if settings["callers_mode"] == "precise" and settings["list_uncalled"]:
        raise ValueError("list_uncalled cannot be used with callers_mode precise")
    unknown: list[str] = [s for s in sections if s not in SECTIONS]
    if unknown:
        raise ValueError(f"unknown context sections: {', '.join(unknown)}")
    base: str = pr["baseRefOid"]
    head: str = pr["headRefOid"]
    files: list[DiffFile] = parse_diff(diff)
    changed: list[str] = sorted({*(f.path for f in files), *(f["path"] for f in pr.get("files", []))})
    changed_code: list[str] = [p for p in changed if not is_test_file(p)]
    wanted: list[str] = [s for s in SECTIONS if s in sections]
    items: dict[str, list[str]] = {name: [] for name in wanted}
    dropped: dict[str, str] = {}
    skipped_common: dict[str, int] = {}

    base_present: bool = has_commit(base)
    head_present: bool = has_commit(head)
    no_mirror: str = "local.toml sets no source_checkout and .cache has no mirror to search"
    if "callers" in wanted and not base_present:
        dropped["callers"] = no_mirror if not MIRROR.exists() else f"base commit {base[:10]} is not in the mirror"
    if "contract" in wanted:
        if not OPENAPI_PATH:
            dropped["contract"] = "local.toml sets no openapi_path"
        elif not (base_present and head_present):
            dropped["contract"] = no_mirror if not MIRROR.exists() else f"base or head commit is not in the mirror ({base[:10]}, {head[:10]})"
    if "reach" in wanted and REACH_CONFIG is None:
        dropped["reach"] = "no reach.toml (copy reach.example.toml and edit it)"
    if "migrations" in wanted and not MIGRATION_DIRS:
        dropped["migrations"] = "local.toml sets no migration_dirs"
    if "wiki" in wanted and (WIKI_DIR is None or not WIKI_DIR.exists()):
        dropped["wiki"] = "local.toml sets no wiki_repo, or its wiki_dir does not exist"

    caller_files: dict[str, list[str]] = {}
    footers: dict[str, list[str]] = {}
    intros: dict[str, str] = {}
    uncalled: list[str] | None = None
    new_in_pr: list[str] | None = None
    fields_dropped: int | None = None
    precise: bool = settings["callers_mode"] == "precise"
    reasons: dict[str, str | None] | None = None
    if "callers" in wanted and "callers" not in dropped:
        changed_set: set[str] = set(changed)
        code_only: bool = settings["callers_code_only"]
        added: set[str] = {f.path for f in files if f.is_new} | {
            f["path"] for f in pr.get("files", []) if f.get("changeType") == "ADDED" or f.get("status") == "added"}
        by_name: dict[str, list[Declaration]] = declarations_by_name(files)
        names: list[str] = list(by_name)
        if settings["callers_skip_fields"]:
            kept_names: list[str] = [n for n in names if any(d.kind != "other" for d in by_name[n])]
            fields_dropped = len(names) - len(kept_names)
            names = kept_names
        if settings["callers_skip_new_files"]:
            new_in_pr = [n for n in names if all(d.path in added for d in by_name[n])]
            names = [n for n in names if n not in new_in_pr]
        if settings["callers_require_owner"]:
            intros["callers"] = OWNER_CALLERS_INTRO
        if precise:
            intros["callers"] = PRECISE_CALLERS_INTRO
            reasons = {}
            reader: BlobReader = BlobReader(base)
        owner_cache: dict[tuple[str, str], set[str]] = {}
        uncalled = []
        for name in names[:MAX_SYMBOLS]:
            paths: list[str]
            if precise:
                paths, reasons[name] = precise_callers(base, reader, name, by_name[name], changed_set, code_only)
            else:
                paths = grep_callers(base, name, changed_set, code_only)
            if settings["callers_require_owner"] and not precise:
                owners: set[str] | None = owner_files(base, by_name[name], changed_set, code_only, owner_cache)
                if owners is not None:
                    paths = [p for p in paths if p in owners]
            if len(paths) > MAX_CALLER_FILES_PER_SYMBOL:
                skipped_common[name] = len(paths)
                if reasons is not None:
                    del reasons[name]
            elif paths:
                caller_files[name] = paths
                shown: str = ", ".join(paths[:MAX_CALLER_PATHS_SHOWN])
                more: str = f", +{len(paths) - MAX_CALLER_PATHS_SHOWN} more" if len(paths) > MAX_CALLER_PATHS_SHOWN else ""
                items["callers"].append(f"- `{name}`: {len(paths)} caller files: {shown}{more}")
            elif not precise:
                uncalled.append(name)
        if not settings["list_uncalled"]:
            uncalled = None
        elif uncalled:
            footers["callers"] = [f"No callers outside this PR: {', '.join(uncalled)}"]
        if new_in_pr:
            listed: str = ", ".join(new_in_pr[:MAX_NEW_SYMBOLS_LISTED])
            more: str = f", +{len(new_in_pr) - MAX_NEW_SYMBOLS_LISTED} more" if len(new_in_pr) > MAX_NEW_SYMBOLS_LISTED else ""
            footers.setdefault("callers", []).append(f"New in this PR (no outside callers possible): {listed}{more}")

    if "reach" in wanted and "reach" not in dropped:
        apps: list[dict[str, Any]] = tomllib.loads(REACH_CONFIG.read_text())["app"]
        changed_by_app: dict[str, int] = {a["name"]: 0 for a in apps}
        callers_by_app: dict[str, int] = {a["name"]: 0 for a in apps}
        for p in changed_code:
            for app in app_names_for(p, apps):
                changed_by_app[app] += 1
        for p in sorted({p for paths in caller_files.values() for p in paths}):
            for app in app_names_for(p, apps):
                callers_by_app[app] += 1
        items["reach"] = [f"- {a['name']}: {changed_by_app[a['name']]} changed files, {callers_by_app[a['name']]} caller files"
                          for a in apps if changed_by_app[a["name"]] or callers_by_app[a["name"]]]

    if "contract" in wanted and "contract" not in dropped and OPENAPI_PATH in changed:
        old: dict[str, Any] | None = read_json_at(base, OPENAPI_PATH)
        new: dict[str, Any] | None = read_json_at(head, OPENAPI_PATH)
        if old is not None and new is not None:
            lines: list[str] = contract_lines(old, new)
            items["contract"] = [f"- {line}" for line in lines[:MAX_CONTRACT_LINES]]
            if len(lines) > MAX_CONTRACT_LINES:
                items["contract"].append(f"- ({len(lines) - MAX_CONTRACT_LINES} more contract lines not listed)")

    if "migrations" in wanted and "migrations" not in dropped:
        items["migrations"] = [f"- {line}" for line in migration_items(files)]

    if "wiki" in wanted and "wiki" not in dropped:
        items["wiki"] = [f"- {line}" for line in wiki_items(changed_code, settings["wiki_match"])]

    return Pack(items=items, skipped_common=skipped_common, dropped=dropped, wiki_sha=wiki_sha() if "wiki" in wanted and "wiki" not in dropped else None,
                footers=footers, uncalled=uncalled, new_in_pr=new_in_pr, fields_dropped=fields_dropped, intros=intros,
                caller_files=caller_files, precise=reasons)
