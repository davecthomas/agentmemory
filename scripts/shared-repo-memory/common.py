"""Shared helpers for the agentmemory scripts.

Every script in this directory imports from here. This module has no side
effects at import time so hook entry points stay fast.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
import sys
import traceback
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType
from typing import Any

VERSION: str = "0.5.0"

MEMORY_DIR: str = ".agents/memory"
ADR_DIR: str = f"{MEMORY_DIR}/adr"
NOTES_DIR: str = f"{MEMORY_DIR}/notes"
LOCAL_DIR: str = f"{MEMORY_DIR}/local"
CONFIG_FILE: str = f"{MEMORY_DIR}/config.json"
GITHOOKS_DIR: str = ".githooks"
CONFIGURED_FLAG: str = "shared_repo_memory_configured"
ASSETS_REPO_KEY: str = "shared_agent_assets_repo_path"

DEFAULT_CONFIG: dict[str, Any] = {
    "decision_surfaces": ["docs/**"],
    "context_budget_words": 2500,
    "notes_window_days": 14,
    "notes_full_days": 3,
}

# A commit body that contains one of these explains a why; the miner and the
# post-commit capture both use it so "decision-bearing commit" means one thing.
REASON_WORDS: re.Pattern[str] = re.compile(
    r"\bbecause\b|\bso that\b|\binstead of\b|\brather than\b|\btrade-?off\b|"
    r"^Decision:",
    re.IGNORECASE | re.MULTILINE,
)

ADR_SECTIONS: tuple[str, ...] = (
    "Context",
    "Decision",
    "Alternatives",
    "Consequences",
    "Sources",
)


# ---------------------------------------------------------------------------
# Logging and process helpers
# ---------------------------------------------------------------------------


def log(message: str) -> None:
    """Write one line to stderr with the agentmemory prefix.

    Hook stdout is reserved for the JSON response the agent reads, so every
    human-facing message goes to stderr.

    Args:
        message: Text to print.
    """
    print(f"[agentmemory v{VERSION}] {message}", file=sys.stderr)


def safe_main(main_fn: Callable[[], int], name: str) -> int:
    """Run a script's main() and turn any exception into a logged exit code 1.

    Args:
        main_fn: The script's main function.
        name: Script name used in the crash message.

    Returns:
        int: main_fn's return value, or 1 when it raised.
    """
    try:
        return main_fn()
    except Exception:  # noqa: BLE001 - hooks must never crash the agent
        log(f"{name} crashed:\n{traceback.format_exc()}")
        return 1


def install_root() -> Path:
    """Return the directory the installer copies scripts into.

    Returns:
        Path: ``~/.agent/shared-repo-memory``.
    """
    return Path.home() / ".agent" / "shared-repo-memory"


def load_module(path: Path) -> ModuleType:
    """Import a sibling script by path so hyphenated filenames stay importable.

    Args:
        path: Absolute path to a ``.py`` file.

    Returns:
        ModuleType: The loaded module.
    """
    name: str = path.stem.replace("-", "_")
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def read_stdin_json() -> dict[str, Any]:
    """Parse the hook payload from stdin, tolerating empty or invalid input.

    Returns:
        dict[str, Any]: The parsed object, or an empty dict.
    """
    if sys.stdin.isatty():
        return {}
    text: str = sys.stdin.read().strip()
    if not text:
        return {}
    try:
        parsed: Any = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


# ---------------------------------------------------------------------------
# Git
# ---------------------------------------------------------------------------


def git(args: list[str], cwd: Path, *, check: bool = False) -> str:
    """Run a git command and return its stripped stdout.

    Args:
        args: Arguments after ``git``.
        cwd: Directory to run in.
        check: Raise ``CalledProcessError`` on a non-zero exit when True.

    Returns:
        str: Stripped stdout; empty string on failure when ``check`` is False.
    """
    result = subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True, check=check
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def repo_root(explicit: str | Path | None = None) -> Path | None:
    """Resolve the git repository root for a directory.

    Args:
        explicit: Directory to start from; the process cwd when omitted.

    Returns:
        Path | None: The resolved root, or None outside a git repository.
    """
    start = Path(explicit) if explicit else Path.cwd()
    if not start.is_dir():
        return None
    top: str = git(["rev-parse", "--show-toplevel"], start)
    return Path(top).resolve() if top else None


def current_branch(root: Path) -> str:
    """Return the current branch name, or ``HEAD`` when detached.

    Args:
        root: Repository root.

    Returns:
        str: Branch name.
    """
    return git(["rev-parse", "--abbrev-ref", "HEAD"], root) or "HEAD"


def author_slug(root: Path) -> str:
    """Return a short author identifier from git config or the environment.

    Args:
        root: Repository root used for the git config lookup.

    Returns:
        str: Slug such as ``davidthomas``.
    """
    email: str = git(["config", "--get", "user.email"], root)
    if email:
        return slugify(email.split("@", 1)[0])
    name: str = git(["config", "--get", "user.name"], root)
    if name:
        return slugify(name)
    return slugify(os.environ.get("USER") or "unknown")


def stage(root: Path, paths: list[Path]) -> None:
    """``git add`` the given paths, ignoring failures.

    Args:
        root: Repository root.
        paths: Files to stage.
    """
    if paths:
        git(["add", "--", *[str(p) for p in paths]], root)


# ---------------------------------------------------------------------------
# Time and text
# ---------------------------------------------------------------------------


def utc_now() -> datetime:
    """Return the current UTC time.

    Returns:
        datetime: Timezone-aware now.
    """
    return datetime.now(UTC)


def stamp(value: datetime | None = None) -> str:
    """Format a datetime as ``YYYY-MM-DDTHH:MMZ``.

    Args:
        value: Time to format; now when omitted.

    Returns:
        str: Minute-precision UTC stamp.
    """
    return (value or utc_now()).strftime("%Y-%m-%dT%H:%MZ")


def today(value: datetime | None = None) -> str:
    """Format a datetime as ``YYYY-MM-DD``.

    Args:
        value: Time to format; now when omitted.

    Returns:
        str: ISO date.
    """
    return (value or utc_now()).strftime("%Y-%m-%d")


def slugify(value: str, *, limit: int = 80) -> str:
    """Lowercase a string and replace runs of non-alphanumerics with hyphens.

    Args:
        value: Text to slugify.
        limit: Maximum length of the result.

    Returns:
        str: Hyphenated slug.
    """
    slug: str = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug[:limit].rstrip("-") or "untitled"


def word_count(text: str) -> int:
    """Count whitespace-separated words.

    Args:
        text: Text to count.

    Returns:
        int: Word count.
    """
    return len(text.split())


# ---------------------------------------------------------------------------
# Files
# ---------------------------------------------------------------------------


def ensure_dir(path: Path) -> Path:
    """Create a directory and its parents.

    Args:
        path: Directory to create.

    Returns:
        Path: The same path.
    """
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_text(path: Path, text: str) -> None:
    """Write text to a file, creating parent directories.

    Args:
        path: Destination.
        text: Content.
    """
    ensure_dir(path.parent)
    path.write_text(text, encoding="utf-8")


def read_text(path: Path) -> str:
    """Read a file as UTF-8, returning an empty string when it is missing.

    Args:
        path: File to read.

    Returns:
        str: File content or ``""``.
    """
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def load_json(path: Path, default: Any) -> Any:
    """Parse a JSON file, returning ``default`` when missing or invalid.

    Args:
        path: File to read.
        default: Value to return on failure.

    Returns:
        Any: Parsed JSON or ``default``.
    """
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def dump_json(path: Path, payload: Any) -> None:
    """Write pretty-printed JSON with a trailing newline.

    Args:
        path: Destination.
        payload: JSON-serialisable value.
    """
    write_text(path, json.dumps(payload, indent=2, sort_keys=True) + "\n")


def is_opted_in(root: Path) -> bool:
    """Return True when the repo has opted in to agentmemory.

    The opt-in marker is a committed ``.agents/memory/config.json``. Without
    it every hook exits silently, so installing agentmemory on a machine never
    turns it on for a repository that did not ask for it.

    Args:
        root: Repository root.

    Returns:
        bool: True when the config file exists.
    """
    return (root / CONFIG_FILE).is_file()


def load_config(root: Path) -> dict[str, Any]:
    """Return the repo's memory config merged over ``DEFAULT_CONFIG``.

    Args:
        root: Repository root.

    Returns:
        dict[str, Any]: Effective configuration.
    """
    config: dict[str, Any] = dict(DEFAULT_CONFIG)
    loaded: Any = load_json(root / CONFIG_FILE, {})
    if isinstance(loaded, dict):
        config.update(loaded)
    return config


def matches_surface(path: str, patterns: list[str]) -> bool:
    """Return True when a repo-relative path matches any glob pattern.

    ``**`` matches any number of directories, ``*`` matches within one
    segment, so ``docs/**`` matches ``docs/a/b.md`` and ``src/*.py`` does
    not match ``src/pkg/mod.py``.

    Args:
        path: Repo-relative POSIX path.
        patterns: Glob patterns.

    Returns:
        bool: True on the first match.
    """
    for pattern in patterns:
        regex: str = (
            re.escape(pattern)
            .replace(r"\*\*/", "(?:.*/)?")
            .replace(r"\*\*", ".*")
            .replace(r"\*", "[^/]*")
        )
        if re.fullmatch(regex, path):
            return True
    return False


# ---------------------------------------------------------------------------
# Markdown: frontmatter and sections
# ---------------------------------------------------------------------------


def render_frontmatter(meta: dict[str, Any]) -> str:
    """Render a dict as a YAML frontmatter block with JSON-quoted scalars.

    Args:
        meta: Ordered field mapping. Values may be bool, list[str], or str.

    Returns:
        str: Block including both ``---`` delimiters.
    """
    lines: list[str] = ["---"]
    for key, value in meta.items():
        if isinstance(value, bool):
            lines.append(f"{key}: {'true' if value else 'false'}")
        elif isinstance(value, list):
            lines.append(f"{key}:")
            lines.extend(f"  - {json.dumps(str(item))}" for item in value)
        else:
            lines.append(f"{key}: {json.dumps(str(value))}")
    lines.append("---")
    return "\n".join(lines)


def _scalar(value: str) -> Any:
    if value in {"true", "false"}:
        return value == "true"
    if len(value) >= 2 and value[0] == value[-1] == '"':
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value.strip('"')
    return value


def parse_frontmatter(markdown: str) -> tuple[dict[str, Any], str]:
    """Split a Markdown document into its frontmatter dict and body.

    Args:
        markdown: Full file text.

    Returns:
        tuple[dict[str, Any], str]: Parsed fields (empty when there is no
            frontmatter) and the body after the closing delimiter.
    """
    if not markdown.startswith("---\n"):
        return {}, markdown
    head, sep, body = markdown[4:].partition("\n---\n")
    if not sep:
        return {}, markdown
    meta: dict[str, Any] = {}
    key: str | None = None
    for line in head.splitlines():
        if line.startswith("  - ") and key:
            meta.setdefault(key, []).append(_scalar(line[4:].strip()))
            continue
        if ":" not in line:
            continue
        key, _, raw = line.partition(":")
        key = key.strip()
        raw = raw.strip()
        meta[key] = _scalar(raw) if raw else []
    return meta, body.lstrip("\n")


def section(body: str, heading: str) -> str:
    """Return the text under a ``## heading`` up to the next ``## ``.

    Args:
        body: Markdown body.
        heading: Heading text without the ``## `` prefix.

    Returns:
        str: Stripped section text, or ``""`` when absent.
    """
    match = re.search(
        rf"^## {re.escape(heading)}\s*$\n(.*?)(?=^## |\Z)",
        body,
        re.MULTILINE | re.DOTALL,
    )
    return match.group(1).strip() if match else ""


# ---------------------------------------------------------------------------
# Memory inventory
# ---------------------------------------------------------------------------


def list_adrs(root: Path) -> list[dict[str, Any]]:
    """Load every ADR file with its parsed frontmatter and body.

    Args:
        root: Repository root.

    Returns:
        list[dict[str, Any]]: ``{"path", "meta", "body"}`` sorted by filename,
            which is id order. ``meta["id"]`` and ``meta["title"]`` are always
            present, derived from the filename when the frontmatter lacks them.
    """
    adrs: list[dict[str, Any]] = []
    for path in sorted((root / ADR_DIR).glob("ADR-*.md")):
        meta, body = parse_frontmatter(read_text(path))
        parts: list[str] = path.stem.split("-", 2)
        meta.setdefault("id", f"{parts[0]}-{parts[1]}")
        if "title" not in meta:
            h1 = re.search(r"^# (?:ADR-\d+:?\s*)?(.+)$", body, re.MULTILINE)
            meta["title"] = h1.group(1).strip() if h1 else path.stem
        adrs.append({"path": path, "meta": meta, "body": body})
    return adrs


def list_notes(root: Path, window_days: int | None = None) -> list[Path]:
    """Return decision-note files, newest first, optionally within a window.

    Args:
        root: Repository root.
        window_days: Keep only files dated within this many days of today.

    Returns:
        list[Path]: Note files sorted newest first.
    """
    notes: list[Path] = sorted((root / NOTES_DIR).glob("????-??-??.md"), reverse=True)
    if window_days is None:
        return notes
    cutoff: str = today(utc_now() - timedelta(days=window_days))
    return [note for note in notes if note.stem >= cutoff]


def note_index(
    root: Path, *, exclude: set[Path] | None = None, only: set[Path] | None = None
) -> list[str]:
    """One line per note entry: ``- YYYY-MM-DD: <decision>``, newest first.

    Args:
        root: Repository root.
        exclude: Note files to skip (those already injected in full).
        only: When given, index these files and no others.

    Returns:
        list[str]: Markdown bullet lines.
    """
    lines: list[str] = []
    for note in list_notes(root):
        if exclude and note in exclude:
            continue
        if only is not None and note not in only:
            continue
        for block in reversed(re.split(r"(?m)^## ", read_text(note))[1:]):
            match = re.search(r"^\*\*Decision:\*\*\s*(.+)$", block, re.MULTILINE)
            if match:
                flag = " (candidate)" if "**Candidate:** true" in block else ""
                lines.append(f"- {note.stem}: {match.group(1).strip()}{flag}")
    return lines


def memory_counts(root: Path) -> tuple[int, int]:
    """Count ADRs and note files.

    Args:
        root: Repository root.

    Returns:
        tuple[int, int]: ``(adr_count, note_file_count)``.
    """
    return len(list((root / ADR_DIR).glob("ADR-*.md"))), len(list_notes(root))


def build_memory_context(root: Path, config: dict[str, Any] | None = None) -> str:
    """Build the bounded Markdown block injected at session start.

    Order: ADR index (skipped when it has no rows), the Decision section of
    each must-read ADR (newest first), notes from the last ``notes_full_days``
    in full, decision lines only for the rest of ``notes_window_days``, a
    one-line index of everything older so nothing recorded is invisible,
    then the local catch-up. Later blocks are dropped once
    ``context_budget_words`` is reached and a trailing line names what was
    omitted.

    Args:
        root: Repository root.
        config: Effective config; loaded from the repo when omitted.

    Returns:
        str: Markdown, or ``""`` when the repo has no memory.
    """
    cfg: dict[str, Any] = config or load_config(root)
    budget: int = int(cfg["context_budget_words"])
    blocks: list[tuple[str, str]] = []

    index_text: str = read_text(root / ADR_DIR / "INDEX.md").strip()
    if index_text and "| ADR-" in index_text:
        blocks.append(("ADR index", index_text))
    for adr in reversed(list_adrs(root)):
        meta = adr["meta"]
        if meta.get("must_read") is True and meta.get("status") != "superseded":
            decision: str = section(adr["body"], "Decision")
            if decision:
                blocks.append((f"{meta['id']}: {meta['title']}", decision))
    full: list[Path] = list_notes(root, int(cfg.get("notes_full_days", 3)))
    for note in full:
        blocks.append((f"Decision notes {note.stem}", read_text(note).strip()))
    window: list[Path] = [
        n for n in list_notes(root, int(cfg["notes_window_days"])) if n not in full
    ]
    recent_lines: list[str] = note_index(root, only=set(window))
    if recent_lines:
        blocks.append(
            (
                "Recent decisions (one line each; ask the `memory` skill for the why)",
                "\n".join(recent_lines),
            )
        )
    older: list[str] = note_index(root, exclude=set(full) | set(window))
    if older:
        blocks.append(
            (
                "Older decision notes (one line each; ask the `memory` skill for detail)",
                "\n".join(older),
            )
        )
    catchup: str = read_text(root / LOCAL_DIR / "catchup.md").strip()
    if catchup:
        blocks.append(("Catch-up since last session", catchup))

    out: list[str] = []
    used: int = 0
    omitted: list[str] = []
    for title, text in blocks:
        words: int = word_count(text)
        if out and used + words > budget:
            omitted.append(title)
            continue
        out.append(f"### {title}\n\n{text}")
        used += words
    if omitted:
        out.append(
            f"_Omitted to stay under {budget} words: {', '.join(omitted)}. "
            "Use the `memory` skill to query them._"
        )
    return "\n\n".join(out)
