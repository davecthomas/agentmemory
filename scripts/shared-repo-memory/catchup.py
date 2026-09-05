#!/usr/bin/env python3
"""Rebuild the local catch-up digest after a git checkout, merge, or rewrite.

Lists commits and file changes under ``.agents/memory/{adr,notes}`` since the
last recorded HEAD, writes ``.agents/memory/local/catchup.md``, and records
the new HEAD. Deterministic; no LLM involved.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from common import (
    ADR_DIR,
    LOCAL_DIR,
    NOTES_DIR,
    dump_json,
    git,
    load_json,
    log,
    repo_root,
    safe_main,
    stamp,
    write_text,
)

MAX_COMMITS: int = 30


def build_catchup(root: Path, trigger: str) -> str:
    """Compute the digest and advance the last-seen marker.

    Args:
        root: Repository root.
        trigger: Hook name for the digest header.

    Returns:
        str: Markdown digest, or ``""`` when nothing changed.
    """
    state_path: Path = root / LOCAL_DIR / "state.json"
    state = load_json(state_path, {})
    head: str = git(["rev-parse", "HEAD"], root)
    if not head:
        return ""
    last: str = state.get("last_seen_sha", "") if isinstance(state, dict) else ""
    dump_json(state_path, {"last_seen_sha": head, "updated_at": stamp()})
    # First run, no movement, or the old sha is gone after a rewrite: nothing to say.
    if not last or last == head or git(["cat-file", "-t", last], root) != "commit":
        return ""
    paths: list[str] = [ADR_DIR, NOTES_DIR]
    commits: str = git(
        [
            "log",
            f"--max-count={MAX_COMMITS}",
            "--format=- %h %ad %s",
            "--date=short",
            f"{last}..{head}",
            "--",
            *paths,
        ],
        root,
    )
    changes: str = git(["diff", "--name-status", f"{last}..{head}", "--", *paths], root)
    if not commits and not changes:
        return ""
    lines: list[str] = [
        f"# Catch-up ({trigger}, {stamp()})",
        "",
        f"Memory changes between `{last[:7]}` and `{head[:7]}`.",
        "",
        "## Commits",
        "",
        commits or "- (none)",
        "",
        "## Files",
        "",
    ]
    if changes:
        lines.extend(f"- {line}" for line in changes.splitlines())
    else:
        lines.append("- (none)")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=None)
    parser.add_argument("--trigger", default="manual")
    args = parser.parse_args()
    root = repo_root(args.repo_root)
    if root is None:
        log("catchup: not inside a git repository")
        return 1
    digest: str = build_catchup(root, args.trigger)
    target: Path = root / LOCAL_DIR / "catchup.md"
    if digest:
        write_text(target, digest)
        log(f"catch-up written to {LOCAL_DIR}/catchup.md")
    elif target.exists():
        target.unlink()
    return 0


if __name__ == "__main__":
    raise SystemExit(safe_main(main, "catchup"))
