#!/usr/bin/env python3
"""common.py -- Shared utilities for all shared-repo-memory scripts.

This module is imported by every other helper script in this package.
It covers six areas:

  1. Timestamps -- UTC datetime helpers used to name shards and tag metadata.
  2. Git operations -- thin wrappers around git subprocess calls.
  3. File I/O -- safe directory creation, text read/write, and JSON helpers.
  4. Shard serialisation -- frontmatter rendering and parsing for event shards.
  5. Payload extraction -- flatten and search the arbitrary JSON that agent
     hook payloads deliver, regardless of field naming conventions.
  6. Hook infrastructure -- append_hook_trace, warn/info.

All public symbols are re-exported; callers should import from common directly.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from collections import OrderedDict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Canonical section headings used inside event shard bodies.
# Rebuilders (rebuild-summary.py, build-catchup.py) key on these exact strings
# when parsing shard content, so they must stay in sync with the shard template.
# ---------------------------------------------------------------------------
SECTION_HEADINGS = [
    "Why",
    "What changed",
    "Evidence",
    "Next",
]

# Older shards wrote "Repo changes" instead of "What changed".
# This alias maps the old heading to the canonical one during parsing so that
# both summary rebuilds and catch-up digests treat them identically.
SECTION_ALIASES = {
    "Repo changes": "What changed",
}


# ---------------------------------------------------------------------------
# Timestamps
# ---------------------------------------------------------------------------


def utc_now() -> datetime:
    """Return the current moment as a timezone-aware UTC datetime.

    Returns:
        datetime: Current UTC time with timezone.utc attached.
    """
    return datetime.now(UTC)


def utc_timestamp(value: datetime | None = None) -> str:
    """Format a datetime as an ISO-8601 UTC string suitable for shard filenames and metadata.

    Args:
        value: Datetime to format.  Uses utc_now() when None.

    Returns:
        str: Timestamp in the form "YYYY-MM-DDTHH:MM:SSZ".
    """
    current = value or utc_now()
    return current.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def iso_date(value: datetime | None = None) -> str:
    """Format a datetime as a plain ISO date string, used for daily directory names.

    Args:
        value: Datetime to format.  Uses utc_now() when None.

    Returns:
        str: Date in the form "YYYY-MM-DD".
    """
    current = value or utc_now()
    return current.astimezone(UTC).strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# Subprocess / git helpers
# ---------------------------------------------------------------------------


def run(
    args: list[str],
    *,
    cwd: str | Path | None = None,
    check: bool = True,
    capture_output: bool = True,
) -> subprocess.CompletedProcess[str]:
    """Run a subprocess and return its CompletedProcess result.

    Args:
        args: Command and arguments to execute.
        cwd: Working directory for the subprocess.  None inherits the caller's cwd.
        check: When True, raise CalledProcessError on non-zero exit.
        capture_output: When True, capture stdout and stderr instead of forwarding
            them to the terminal.

    Returns:
        subprocess.CompletedProcess[str]: Result with decoded stdout/stderr strings.
    """
    return subprocess.run(
        args,
        cwd=str(cwd) if cwd else None,
        check=check,
        capture_output=capture_output,
        text=True,
    )


def git(args: list[str], repo_root: str | Path, check: bool = True) -> str:
    """Run a git command inside repo_root and return stripped stdout.

    Args:
        args: git sub-command and flags, e.g. ["rev-parse", "--abbrev-ref", "HEAD"].
        repo_root: Absolute path to the repository root used as the working directory.
        check: When True, raise CalledProcessError on non-zero exit.

    Returns:
        str: Stripped stdout from the git command; empty string if nothing was printed.
    """
    result = run(["git", *args], cwd=repo_root, check=check)
    return result.stdout.strip()


def try_repo_root(explicit: str | None = None) -> Path | None:
    """Walk up from explicit (or cwd) to find the nearest git repository root.

    Uses `git rev-parse --show-toplevel` rather than searching for .git manually,
    so it correctly handles worktrees and nested repos.

    Args:
        explicit: Path to start from.  Falls back to os.getcwd() when None.
            If the path points to a file its parent directory is used.

    Returns:
        Path | None: Absolute path to the repo root, or None if not inside a repo.
    """
    candidate = Path(explicit).resolve() if explicit else Path.cwd().resolve()
    cwd = candidate if candidate.is_dir() else candidate.parent
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=str(cwd),
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    return Path(result.stdout.strip()).resolve()


def repo_root(explicit: str | None = None) -> Path:
    """Return the git repository root, raising if not inside a repo.

    Prefer try_repo_root() when a graceful noop is acceptable.  This function
    is for callers that must abort when no repo is found.

    Args:
        explicit: Optional path hint passed through to try_repo_root().

    Returns:
        Path: Absolute path to the repository root.

    Raises:
        ValueError: If the path is not inside a git repository.
    """
    resolved = try_repo_root(explicit)
    if resolved is None:
        raise ValueError("current working directory is not inside a Git repository")
    return resolved


def head_sha(repo_root_path: str | Path) -> str:
    """Return the short HEAD commit SHA, used as a watermark in sync_state.json.

    Args:
        repo_root_path: Absolute path to the repository root.

    Returns:
        str: Full SHA of HEAD, or empty string on failure.
    """
    return git(["rev-parse", "HEAD"], repo_root_path, check=False)


def has_merge_conflicts(repo_root_path: str | Path) -> bool:
    """Return True if the working tree has unresolved merge conflicts.

    Staging memory files during a conflicted merge would corrupt the index,
    so stage_paths() uses this as a safety gate before calling git add.

    Args:
        repo_root_path: Absolute path to the repository root.

    Returns:
        bool: True if any unmerged (both-modified) paths exist.
    """
    output = git(
        ["diff", "--name-only", "--diff-filter=U"], repo_root_path, check=False
    )
    return bool(output.strip())


def current_branch(repo_root_path: str | Path) -> str:
    """Return the name of the currently checked-out branch.

    Falls back to "HEAD" when in detached-HEAD state (e.g., during a rebase or
    when checking out a tag), so shard metadata always has a valid branch field.

    Args:
        repo_root_path: Absolute path to the repository root.

    Returns:
        str: Branch name, or "HEAD" in detached-HEAD state.
    """
    branch = git(["rev-parse", "--abbrev-ref", "HEAD"], repo_root_path, check=False)
    return branch or "HEAD"


def tracked_changed_files(repo_root_path: str | Path) -> list[str]:
    """Return a deduplicated, sorted list of tracked files with uncommitted changes.

    Excludes:
      - Untracked files (they have not been added to the index yet).
      - Anything under .agents/memory/ (to avoid circular shard references).
      - Anything under .codex/local/ (ephemeral local state, never committed).

    Rename entries ("old -> new") are normalised to the destination path only.
    The null-delimiter format (-z) avoids problems with spaces or newlines in paths.

    Args:
        repo_root_path: Absolute path to the repository root.

    Returns:
        list[str]: Sorted, deduplicated POSIX paths relative to the repo root.
    """
    result = subprocess.run(
        ["git", "status", "--porcelain=v1", "-z", "--untracked-files=no"],
        cwd=str(repo_root_path),
        check=True,
        capture_output=True,
    )
    changed: list[str] = []
    for raw in result.stdout.decode("utf-8", errors="replace").split("\0"):
        if not raw:
            continue
        # Porcelain v1 format: XY path or XY original -> path (for renames).
        path_text = raw[3:]
        if " -> " in path_text:
            path_text = path_text.split(" -> ", 1)[1]
        normalized = path_text.strip()
        if not normalized:
            continue
        # Skip memory and local state paths -- they are managed by this system
        # and should not appear as "code changes" in shard metadata.
        if normalized.startswith(".agents/memory/") or normalized.startswith(
            ".codex/local/"
        ):
            continue
        changed.append(normalized)
    return sorted(dict.fromkeys(changed))


def stage_paths(repo_root_path: str | Path, paths: list[str | Path]) -> None:
    """Stage the given paths via git add, skipping when merge conflicts are present.

    Called by post-turn-notify.py after writing a shard and rebuilding the daily
    summary.  The agent still needs to commit explicitly -- this system never
    auto-commits.

    Args:
        repo_root_path: Absolute path to the repository root.
        paths: Relative paths (from repo root) to stage.  Accepts str or Path.
    """
    # Staging during a conflict would corrupt the index, so bail early.
    if not paths or has_merge_conflicts(repo_root_path):
        return
    normalized = [str(Path(path).as_posix()) for path in paths]
    run(["git", "add", "--", *normalized], cwd=repo_root_path, check=True)


# ---------------------------------------------------------------------------
# File I/O
# ---------------------------------------------------------------------------


def ensure_dir(path: str | Path) -> Path:
    """Create path and any missing parents, then return the Path object.

    Idempotent -- silently succeeds if the directory already exists.

    Args:
        path: Directory to create.

    Returns:
        Path: The resolved Path object for the created or existing directory.
    """
    target = Path(path)
    target.mkdir(parents=True, exist_ok=True)
    return target


def write_text(path: str | Path, text: str) -> None:
    """Write text to a file, creating parent directories as needed.

    Args:
        path: Destination file path.
        text: UTF-8 content to write.  Overwrites any existing file.
    """
    target = Path(path)
    ensure_dir(target.parent)
    target.write_text(text, encoding="utf-8")


def append_jsonl(path: str | Path, payload: dict[str, Any]) -> None:
    """Append a single JSON object as a newline-delimited record to a JSONL file.

    Used to append entries to the hook trace log at
    ~/.agent/state/shared-repo-memory-hook-trace.jsonl.

    Args:
        path: Target JSONL file path.  Parent directories are created if missing.
        payload: Mapping to serialize as a single JSON line.  Keys are sorted for
            stable output so the file is diff-friendly.
    """
    target = Path(path)
    ensure_dir(target.parent)
    with target.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")


def read_text(path: str | Path) -> str:
    """Read and return the full UTF-8 contents of a file.

    Args:
        path: File to read.

    Returns:
        str: Full file contents as a Unicode string.
    """
    return Path(path).read_text(encoding="utf-8")


def dump_json(path: str | Path, payload: Any) -> None:
    """Write a Python object as pretty-printed JSON (2-space indent, sorted keys).

    Used for sync_state.json and similar structured state files.

    Args:
        path: Destination file path.
        payload: JSON-serialisable object to write.
    """
    write_text(path, json.dumps(payload, indent=2, sort_keys=True) + "\n")


def load_json(path: str | Path, default: Any) -> Any:
    """Load a JSON file, returning default when the file does not exist.

    Args:
        path: JSON file to read.
        default: Value to return when path does not exist.

    Returns:
        Any: Parsed JSON value, or default if the file is absent.
    """
    target = Path(path)
    if not target.exists():
        return default
    return json.loads(target.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# String utilities
# ---------------------------------------------------------------------------


def slugify(value: str) -> str:
    """Convert a string into a lowercase, hyphen-separated slug for use in filenames.

    Non-alphanumeric characters are collapsed into single hyphens.  Leading and
    trailing hyphens are stripped.  Returns "untitled" for empty or all-special input.

    Args:
        value: Arbitrary string to convert.

    Returns:
        str: Lowercase slug, e.g. "My Feature!" -> "my-feature".
    """
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "untitled"


def author_slug(repo_root_path: str | Path) -> str:
    """Derive a short, filesystem-safe author identifier from git config or the environment.

    Used to populate the "author" field in event shard filenames and frontmatter.

    Resolution order:
      1. git config user.email -- local part before "@" is slugified.
      2. git config user.name  -- full name is slugified.
      3. USER / USERNAME env var.
      4. Fallback: "unknown-author".

    Args:
        repo_root_path: Absolute path to the repository root used for git config lookup.

    Returns:
        str: Lowercase hyphen-slug identifying the author, e.g. "alice-smith".
    """
    email = git(["config", "--get", "user.email"], repo_root_path, check=False)
    if email:
        return slugify(email.split("@", 1)[0])
    name = git(["config", "--get", "user.name"], repo_root_path, check=False)
    if name:
        return slugify(name)
    user = os.environ.get("USER") or os.environ.get("USERNAME")
    if user:
        return slugify(user)
    return "unknown-author"


def excerpt(lines: list[str], default: str) -> str:
    """Return the first non-empty, non-placeholder line from a section's bullet list.

    Used to extract a short human-readable summary from Why or What changed sections
    when building snapshot tables and ADR bodies.

    Args:
        lines: Bullet lines from a parsed shard section, e.g. ["- Updated foo.py"].
        default: Fallback string when lines is empty or every entry is "- None".

    Returns:
        str: First meaningful line with leading "- " stripped, or default.
    """
    for line in lines:
        text = line.strip()
        if text and text != "- None":
            return re.sub(r"^- ", "", text)
    return default


def relative_link(from_path: str | Path, to_path: str | Path, label: str) -> str:
    """Build a relative Markdown link from one file to another.

    Paths are resolved relative to their respective parent directories so the
    link works correctly when either file is opened in a Markdown viewer.

    Args:
        from_path: File that will contain the link (the link source).
        to_path: File the link should point at (the link target).
        label: Display text for the Markdown link.

    Returns:
        str: Markdown link, e.g. "[label](../events/shard.md)".
    """
    rel = os.path.relpath(str(to_path), start=str(Path(from_path).parent))
    return f"[{label}]({Path(rel).as_posix()})"


# ---------------------------------------------------------------------------
# Shard frontmatter serialisation
# ---------------------------------------------------------------------------


def scalar_yaml(value: str) -> str:
    """Serialize a scalar string as a JSON-quoted string for YAML frontmatter.

    We use JSON quoting (double-quoted, with escape sequences) rather than
    bare YAML scalars to avoid ambiguity with colons, boolean keywords, etc.

    Args:
        value: String to quote.

    Returns:
        str: JSON-encoded string, e.g. 'some value' -> '"some value"'.
    """
    return json.dumps(value)


def bool_yaml(value: bool) -> str:
    """Return the lowercase YAML boolean literal for a Python bool.

    Args:
        value: Python boolean.

    Returns:
        str: "true" or "false".
    """
    return "true" if value else "false"


def render_frontmatter(metadata: OrderedDict[str, Any]) -> str:
    """Render an OrderedDict of shard metadata as a YAML frontmatter block.

    Preserves key order from the input dict.  Uses JSON-quoted strings for
    scalar values to avoid YAML parsing ambiguity.  Lists are rendered as YAML
    sequences.  Booleans use lowercase YAML literals.

    Args:
        metadata: Ordered mapping of field name to value.  Supported value types:
            bool, list[str], and str (including numeric strings cast from other types).

    Returns:
        str: Complete frontmatter block enclosed in "---" delimiters, ready to
            prepend to a Markdown shard body.
    """
    lines = ["---"]
    for key, value in metadata.items():
        if isinstance(value, bool):
            lines.append(f"{key}: {bool_yaml(value)}")
        elif isinstance(value, list):
            lines.append(f"{key}:")
            for item in value:
                lines.append(f"  - {scalar_yaml(str(item))}")
        else:
            lines.append(f"{key}: {scalar_yaml(str(value))}")
    lines.append("---")
    return "\n".join(lines)


def parse_frontmatter(markdown: str) -> tuple[dict[str, Any], str]:
    """Parse YAML frontmatter from a Markdown string.

    Splits on the opening and closing "---" delimiters, then processes each
    key-value pair.  List items (lines beginning with two-space indent "  - ")
    are collected under the preceding key.

    Args:
        markdown: Full Markdown file contents beginning with "---\\n".

    Returns:
        tuple[dict[str, Any], str]: A (metadata, body) pair where metadata maps
            field names to parsed Python values and body is the Markdown text
            after the closing "---".

    Raises:
        ValueError: If markdown does not begin with the "---\\n" frontmatter opener.
    """
    if not markdown.startswith("---\n"):
        raise ValueError("missing frontmatter")
    _, rest = markdown.split("---\n", 1)
    frontmatter_text, body = rest.split("\n---\n", 1)
    metadata: dict[str, Any] = {}
    current_key: str | None = None
    for line in frontmatter_text.splitlines():
        if not line.strip():
            continue
        # Continuation list item: appended to the list started by the last key.
        if line.startswith("  - ") and current_key:
            metadata.setdefault(current_key, []).append(_parse_scalar(line[4:].strip()))
            continue
        key, value = line.split(":", 1)
        current_key = key.strip()
        stripped = value.strip()
        if stripped:
            metadata[current_key] = _parse_scalar(stripped)
        else:
            # Empty value means this key is the start of a list block.
            metadata[current_key] = []
    return metadata, body.lstrip("\n")


def _parse_scalar(value: str) -> Any:
    """Convert a raw YAML scalar string to its Python equivalent.

    Handles:
      - Lowercase YAML booleans ("true" / "false").
      - JSON-quoted strings (starting and ending with double-quote).
      - Bare strings (returned unchanged).

    Args:
        value: Single scalar token from frontmatter parsing.

    Returns:
        Any: bool, str, or whatever json.loads produces for quoted strings.
    """
    if value in {"true", "false"}:
        return value == "true"
    if value.startswith('"') and value.endswith('"'):
        return json.loads(value)
    return value


# ---------------------------------------------------------------------------
# Shard section parsing
# ---------------------------------------------------------------------------


def parse_sections(markdown_body: str) -> dict[str, list[str]]:
    """Parse the body of a shard Markdown file into its named sections.

    Recognizes H2 headings ("## Title") and collects subsequent non-heading lines
    under the corresponding section key.  Section names listed in SECTION_ALIASES
    are normalized to the canonical heading before storage.

    Only sections whose keys appear in SECTION_HEADINGS are collected; unrecognized
    headings are ignored.

    Args:
        markdown_body: Markdown text after the frontmatter closing delimiter.

    Returns:
        dict[str, list[str]]: Mapping from canonical heading name to the list of
            non-empty lines under that heading.  All keys from SECTION_HEADINGS
            are always present, even if the section was absent (empty list).
    """
    current: str | None = None
    sections = {heading: [] for heading in SECTION_HEADINGS}
    for raw_line in markdown_body.splitlines():
        line = raw_line.rstrip()
        if line.startswith("## "):
            # Resolve aliases so "Repo changes" and "What changed" are treated the same.
            current = SECTION_ALIASES.get(line[3:].strip(), line[3:].strip())
            continue
        if current in sections and line:
            sections[current].append(line)
    return sections


def render_sections(sections: OrderedDict[str, list[str]]) -> str:
    """Render an ordered section mapping back to Markdown body text.

    Each section is written as an H2 heading followed by its bullet lines, or a
    "- None" placeholder when the list is empty.

    Args:
        sections: Ordered mapping from section heading to bullet lines.

    Returns:
        str: Markdown body text ending with a single trailing newline.
    """
    lines: list[str] = []
    for title, entries in sections.items():
        lines.append(f"## {title}")
        lines.append("")
        if entries:
            lines.extend(entries)
        else:
            lines.append("- None")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


# ---------------------------------------------------------------------------
# Event file helpers
# ---------------------------------------------------------------------------


def load_event(path: str | Path) -> dict[str, Any]:
    """Load a single event shard file and return its metadata enriched with section data.

    Parses frontmatter into a flat metadata dict, then parses the body into sections.
    Adds three private keys prefixed with "__" so callers can access the path and
    pre-parsed sections without a second read:

      __path     -- absolute path string
      __basename -- filename stem (used as a short label in summary links)
      __sections -- dict from parse_sections()

    Args:
        path: Path to the .md shard file.

    Returns:
        dict[str, Any]: Merged metadata plus __path, __basename, and __sections.
    """
    markdown = read_text(path)
    metadata, body = parse_frontmatter(markdown)
    sections = parse_sections(body)
    metadata["__path"] = str(Path(path))
    metadata["__basename"] = Path(path).stem
    metadata["__sections"] = sections
    return metadata


def list_event_files(day_dir: str | Path) -> list[Path]:
    """Return a sorted list of all event shard .md files for a given day.

    Looks in <day_dir>/events/*.md.  Returns an empty list when the events
    directory does not exist (e.g., for a day with no captured shards).

    Args:
        day_dir: Path to a single-day directory under .agents/memory/daily/.

    Returns:
        list[Path]: Sorted paths to shard files; empty list when none exist.
    """
    events_dir = Path(day_dir) / "events"
    if not events_dir.exists():
        return []
    return sorted(events_dir.glob("*.md"))


# ---------------------------------------------------------------------------
# Payload extraction helpers
# ---------------------------------------------------------------------------


def flatten_strings(payload: Any, *, limit: int = 100) -> list[str]:
    """Recursively collect all non-empty string values from an arbitrary JSON payload.

    Walks dicts (values only), lists, and nested combinations.  Stops once
    `limit` unique strings have been accumulated to prevent large payloads from
    dominating downstream regex searches.  Duplicate strings are deduplicated
    while preserving first-seen order.

    Args:
        payload: Arbitrary JSON-compatible value (dict, list, str, or other).
        limit: Maximum number of unique strings to return.

    Returns:
        list[str]: Up to `limit` unique non-empty strings found in the payload.
    """
    values: list[str] = []

    def walk(node: Any) -> None:
        if len(values) >= limit:
            return
        if isinstance(node, str):
            stripped = node.strip()
            if stripped:
                values.append(stripped)
            return
        if isinstance(node, list):
            for item in node:
                walk(item)
            return
        if isinstance(node, dict):
            for item in node.values():
                walk(item)

    walk(payload)
    # Deduplicate while preserving order -- seen set provides O(1) membership test.
    unique: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value not in seen:
            seen.add(value)
            unique.append(value)
    return unique


def find_first(payload: Any, keys: set[str]) -> str | None:
    """Recursively search a JSON payload for the first non-empty string value at any of the given keys.

    Agents and platforms use different field names for the same concepts (e.g.,
    "thread_id" vs "threadId" vs "conversation_id").  This function lets callers
    specify all known aliases and get back the first match regardless of nesting
    depth.

    Args:
        payload: Arbitrary JSON-compatible value to search.
        keys: Set of key names to match at the top level of any dict encountered.

    Returns:
        str | None: First non-empty string value found at any matching key, or None.
    """
    if isinstance(payload, dict):
        for key, value in payload.items():
            if key in keys and isinstance(value, str) and value.strip():
                return value.strip()
            found = find_first(value, keys)
            if found:
                return found
    elif isinstance(payload, list):
        for item in payload:
            found = find_first(item, keys)
            if found:
                return found
    return None


def collect_matches(strings: list[str], pattern: str) -> list[str]:
    """Return deduplicated bullet lines from strings that match a regex pattern.

    Splits each string on newlines before testing, so multi-line payload fields
    yield per-line matches rather than entire blob matches.  Leading bullet
    markers ("- ") and whitespace are stripped before deduplication, then
    re-prefixed with "- " on output.

    Args:
        strings: Pre-flattened string values from a hook payload.
        pattern: Regular expression pattern (case-insensitive) to test against
            each candidate line.

    Returns:
        list[str]: Deduplicated bullet lines matching the pattern, each prefixed "- ".
    """
    regex = re.compile(pattern, re.IGNORECASE)
    matches: list[str] = []
    seen: set[str] = set()
    for string in strings:
        for piece in re.split(r"[\n\r]+", string):
            candidate = piece.strip(" -")
            if not candidate:
                continue
            if regex.search(candidate) and candidate not in seen:
                seen.add(candidate)
                matches.append(f"- {candidate}")
    return matches


# ---------------------------------------------------------------------------
# Hook output and tracing
# ---------------------------------------------------------------------------


def safe_main(main_fn: Any, hook_name: str) -> int:
    """Run a hook's main() inside a top-level exception handler.

    Every hook script should call this instead of ``raise SystemExit(main())``.
    If main_fn raises any exception, safe_main:

      1. Logs the full traceback to stderr (visible in agent hook output).
      2. Appends a structured error record to the hook trace log.
      3. Returns exit code 1 so the hook signals failure without a raw traceback
         crashing through the agent UI.

    Args:
        main_fn: The hook's main() callable (no arguments).
        hook_name: Human-readable hook name for trace records, e.g. "Notify".

    Returns:
        int: Whatever main_fn returns on success, or 1 on unhandled exception.
    """
    import traceback

    try:
        return main_fn()
    except Exception:
        tb = traceback.format_exc()
        warn(f"{hook_name} crashed:\n{tb}")
        append_hook_trace(
            hook_name,
            "crash",
            details={"error": tb.splitlines()[-1], "traceback": tb[:2000]},
        )
        return 1


def warn(message: str) -> None:
    """Write a warning message to stderr, prefixed with the system identifier.

    Messages written here appear in the agent's hook output stream but do not
    affect the hook response payload read by the agent.

    Args:
        message: Human-readable warning text (no trailing newline needed).
    """
    print(f"[shared-repo-memory] {message}", file=sys.stderr)


def info(message: str) -> None:
    """Write an informational message to stderr, prefixed with the system identifier.

    Args:
        message: Human-readable info text (no trailing newline needed).
    """
    print(f"[shared-repo-memory] {message}", file=sys.stderr)



def append_hook_trace(
    hook: str,
    status: str,
    *,
    repo_root: str | Path | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    """Append a structured trace record to the hook debug log.

    The trace log at ~/.agent/state/shared-repo-memory-hook-trace.jsonl is the
    primary diagnostic tool when hooks run but produce unexpected behavior.
    Each invocation of SessionStart and post-turn-notify.py appends one or more
    records covering start, success, error, noop, and bootstrapping phases.

    Write failures are silently ignored so a missing state directory never causes
    a hook to abort.

    Args:
        hook: Name of the hook, e.g. "SessionStart" or "Notify".
        status: Phase label, e.g. "started", "success", "error", "noop".
        repo_root: Repository root path included for context; omitted when None.
        details: Additional key-value pairs to merge into the trace record.
            Path values are coerced to str; list values have their items coerced
            to str; None values are omitted.
    """
    payload: dict[str, Any] = {
        "timestamp": utc_timestamp(),
        "hook": hook,
        "status": status,
    }
    if repo_root is not None:
        payload["repo_root"] = str(Path(repo_root).resolve())
    if details:
        for key, value in details.items():
            if value is None:
                continue
            if isinstance(value, Path):
                payload[key] = str(value)
            elif isinstance(value, list):
                payload[key] = [str(item) for item in value]
            else:
                payload[key] = value

    trace_path = (
        Path.home() / ".agent" / "state" / "shared-repo-memory-hook-trace.jsonl"
    )
    try:
        append_jsonl(trace_path, payload)
    except OSError:
        pass
