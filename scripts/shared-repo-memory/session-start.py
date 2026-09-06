#!/usr/bin/env python3
"""SessionStart hook: repair repo wiring and inject decision memory.

Reads the Claude Code hook payload from stdin, checks that the user opted in
via ``shared_repo_memory_configured`` in ``~/.claude/settings.json``, runs
``bootstrap-repo.py`` when repo-local wiring is missing, then prints the
bounded memory context as ``additionalContext``.

``--print-context`` prints the same Markdown block to stdout and exits; the
evals use it to build the "with memory" condition.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from common import (
    ADR_DIR,
    CONFIGURED_FLAG,
    GITHOOKS_DIR,
    LOCAL_DIR,
    NOTES_DIR,
    VERSION,
    build_memory_context,
    git,
    is_opted_in,
    load_json,
    load_module,
    log,
    memory_counts,
    read_stdin_json,
    read_text,
    repo_root,
    safe_main,
)

HERE: Path = Path(__file__).resolve().parent

NOTE_INSTRUCTION: str = (
    "When you make a non-obvious choice in this repo (a design trade-off, a "
    "rejected alternative, a constraint you discovered), record it with the "
    "`memory-note` skill so the next session starts from it."
)
EMPTY_INSTRUCTION: str = (
    "INSTRUCTION: This repository has no decision memory yet. Invoke "
    "/memory-bootstrap to seed ADRs from existing docs and commit history."
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=None)
    parser.add_argument(
        "--print-context",
        action="store_true",
        help="print the memory context block and exit",
    )
    return parser.parse_args()


def is_configured(home: Path) -> bool:
    """Return True when ``~/.claude/settings.json`` opts in.

    Args:
        home: User home directory.

    Returns:
        bool: The value of the configured flag.
    """
    settings = load_json(home / ".claude" / "settings.json", {})
    return bool(isinstance(settings, dict) and settings.get(CONFIGURED_FLAG))


def wiring_issues(root: Path) -> list[str]:
    """List repo-local wiring that ``bootstrap-repo.py`` needs to create.

    Args:
        root: Repository root.

    Returns:
        list[str]: Human-readable descriptions; empty when fully wired.
    """
    bootstrap = load_module(HERE / "bootstrap-repo.py")
    issues: list[str] = []
    for rel in (ADR_DIR, NOTES_DIR, LOCAL_DIR, GITHOOKS_DIR):
        if not (root / rel).is_dir():
            issues.append(rel)
    if not (root / ADR_DIR / "INDEX.md").is_file():
        issues.append(f"{ADR_DIR}/INDEX.md")
    for name in bootstrap.HOOK_NAMES:
        if read_text(root / GITHOOKS_DIR / name) != bootstrap.hook_text(name):
            issues.append(f"{GITHOOKS_DIR}/{name}")
    if git(["config", "--get", "core.hooksPath"], root) != GITHOOKS_DIR:
        issues.append("core.hooksPath")
    if bootstrap.GITIGNORE_BEGIN not in read_text(root / ".gitignore"):
        issues.append(".gitignore block")
    return issues


def run_bootstrap(root: Path) -> bool:
    """Run the sibling ``bootstrap-repo.py`` for a repo.

    Args:
        root: Repository root.

    Returns:
        bool: True when it exited 0.
    """
    result = subprocess.run(
        [sys.executable, str(HERE / "bootstrap-repo.py"), "--repo-root", str(root)],
        capture_output=True,
        text=True,
    )
    for stream in (result.stdout, result.stderr):
        if stream.strip():
            log(stream.strip())
    return result.returncode == 0


def main() -> int:
    if os.environ.get("AGENTMEMORY_DISABLED"):
        return 0
    args = parse_args()
    if args.print_context:
        root = repo_root(args.repo_root)
        if root is None:
            log("not inside a git repository")
            return 1
        print(build_memory_context(root))
        return 0

    payload = read_stdin_json()
    if not is_configured(Path.home()):
        return 0
    root = repo_root(args.repo_root or payload.get("cwd") or None)
    if root is None or not is_opted_in(root):
        # Not a git repo, or the repo has no .agents/memory/config.json: stay silent.
        return 0

    bootstrapped: bool = False
    issues: list[str] = wiring_issues(root)
    if issues:
        log(f"repo wiring incomplete ({', '.join(issues)}); bootstrapping")
        if not run_bootstrap(root):
            print(
                json.dumps(
                    {"systemMessage": "agentmemory bootstrap failed; see stderr."}
                )
            )
            return 1
        bootstrapped = True

    nudge = load_module(HERE / "turn-nudge.py")
    nudge.record_session(root, str(payload.get("session_id", "")))

    adr_count, note_count = memory_counts(root)
    context: str = build_memory_context(root)
    parts: list[str] = [context] if context else []
    parts.append(NOTE_INSTRUCTION if adr_count or note_count else EMPTY_INSTRUCTION)
    status: str = (
        f"agentmemory v{VERSION}: {adr_count} ADRs, {note_count} note files."
        + (" Repo wiring bootstrapped." if bootstrapped else "")
    )
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "SessionStart",
                    "additionalContext": "\n\n".join(parts),
                },
                "systemMessage": status,
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(safe_main(main, "session-start"))
