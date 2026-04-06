#!/usr/bin/env python3
"""bootstrap-repo.py -- Create missing repo-local shared-memory wiring.

Creates the directory structure and symlink that the shared repo-memory system
requires inside any git repository that wants to use it.  Idempotent: running
it on an already-wired repo is safe and produces no output.

Called automatically by session-start.py whenever repo_wiring_issues() returns
a non-empty list.  Can also be run manually to repair a partially-wired repo.

What this script creates (all relative to the repo root):
  .agents/memory/adr/                     -- ADR storage directory
  .agents/memory/daily/                   -- daily event shard storage
  .codex/local/                           -- local catch-up state (never committed)
  .claude/local/                          -- Claude-specific local state
  .githooks/                              -- git hooks directory
  .githooks/post-checkout                 -- rebuilds local catch-up after checkout
  .githooks/post-merge                    -- rebuilds local catch-up after merge/pull
  .githooks/post-rewrite                  -- rebuilds local catch-up after rebase/rewrite
  .codex/memory -> ../.agents/memory      -- Codex access-path symlink
  .agents/memory/adr/INDEX.md             -- empty ADR index table
  git config core.hooksPath = .githooks   -- points git at the hooks directory

Usage:
  bootstrap-repo.py [--repo-root <path>] [--dry-run]
"""
from __future__ import annotations

import argparse
import os
import subprocess
from pathlib import Path

from common import ensure_dir, safe_main, try_repo_root, warn, write_text

# Expected relative target for the .codex/memory symlink.
# This must match the value validated by session-start.py's repo_wiring_issues().
EXPECTED_MEMORY_TARGET = "../.agents/memory"

# Initial content for the ADR index file.
# promote-adr.py rebuilds this table from scratch after every ADR promotion.
_INDEX_INITIAL = """\
# ADR index

| ADR | Title | Status | Date | Tags | Must Read | Supersedes | Superseded By |
|---|---|---|---|---|---|---|---|
| - | None | - | - | - | - | - | - |
"""

_GIT_HOOK_NAMES: tuple[str, ...] = (
    "post-checkout",
    "post-merge",
    "post-rewrite",
)


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments.

    Returns:
        argparse.Namespace: Parsed arguments with optional repo_root and dry_run.
    """
    parser = argparse.ArgumentParser(
        description="Bootstrap repo-local shared-memory wiring."
    )
    parser.add_argument(
        "--repo-root",
        help="Path to the repository root.  Defaults to git rev-parse --show-toplevel.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print each action without modifying any files.",
    )
    return parser.parse_args()


def log(message: str, *, dry_run: bool = False) -> None:
    """Print a prefixed log message to stdout.

    Args:
        message: Human-readable action description.
        dry_run: When True, prefixes the message with "[DRY-RUN]".
    """
    prefix = "[DRY-RUN] " if dry_run else ""
    print(f"[shared-repo-memory] {prefix}{message}")


def ensure_symlink(link_path: Path, target: str, *, dry_run: bool) -> None:
    """Create or repair the symlink at link_path pointing to target.

    Removes any existing file, directory, or stale symlink at link_path before
    creating the new symlink.  Content is canonical in .agents/memory/ so the
    removal is safe.

    Args:
        link_path: Absolute path where the symlink should live.
        target: Relative symlink target string, e.g. "../.agents/memory".
        dry_run: When True, log the action without touching the filesystem.
    """
    current_target = None
    if link_path.is_symlink():
        try:
            current_target = link_path.readlink().as_posix()
        except OSError:
            pass

    if current_target == target:
        # Already correctly wired; nothing to do.
        return

    log(f"creating symlink {link_path} -> {target}", dry_run=dry_run)
    if dry_run:
        return

    # Remove whatever is at link_path (file, dir, or stale symlink) before creating.
    if link_path.exists() or link_path.is_symlink():
        if link_path.is_dir() and not link_path.is_symlink():
            import shutil

            shutil.rmtree(link_path)
        else:
            link_path.unlink()
    os.symlink(target, link_path)


def set_git_hooks_path(repo_root: Path, hooks_dir: str, *, dry_run: bool) -> None:
    """Set git's core.hooksPath to hooks_dir so the repo-local hooks fire.

    Args:
        repo_root: Absolute path to the repository root.
        hooks_dir: Relative path to the hooks directory, e.g. ".githooks".
        dry_run: When True, log the action without running git config.
    """
    # Check whether the value is already correct before writing.
    result = subprocess.run(
        ["git", "config", "--get", "core.hooksPath"],
        cwd=str(repo_root),
        check=False,
        capture_output=True,
        text=True,
    )
    if result.stdout.strip() == hooks_dir:
        return

    log(f"setting git config core.hooksPath = {hooks_dir}", dry_run=dry_run)
    if not dry_run:
        subprocess.run(
            ["git", "config", "core.hooksPath", hooks_dir],
            cwd=str(repo_root),
            check=True,
        )


# Lines that must appear in the repo's .gitignore.
# These cover agent-local state that is never committed.  The list does NOT
# include .agents/memory/ or .codex/memory because those are intentionally
# committed and shared.
_GITIGNORE_ENTRIES = [
    "# Agent local state (never committed)",
    ".codex/local/",
    ".claude/local/",
    ".claude/settings.local.json",
    ".agents/memory/logs/",
]


def ensure_gitignore(repo_root: Path, *, dry_run: bool) -> None:
    """Append missing agent-local ignore entries to the repo's .gitignore.

    Reads the existing .gitignore (if any), checks which required entries are
    missing, and appends only the missing ones.  Creates the file if absent.

    Args:
        repo_root: Absolute path to the repository root.
        dry_run: When True, log the action without modifying the filesystem.
    """
    gitignore_path = repo_root / ".gitignore"
    existing = ""
    if gitignore_path.exists():
        existing = gitignore_path.read_text(encoding="utf-8")
    existing_lines = set(existing.splitlines())

    missing = [entry for entry in _GITIGNORE_ENTRIES if entry not in existing_lines]
    if not missing:
        return

    log(
        f"appending {len(missing)} entries to .gitignore",
        dry_run=dry_run,
    )
    if dry_run:
        return

    # Ensure a blank line before our block if the file doesn't end with one.
    separator = "\n" if existing and not existing.endswith("\n\n") else ""
    with gitignore_path.open("a", encoding="utf-8") as f:
        f.write(separator + "\n".join(missing) + "\n")


def git_hook_text(str_hook_name: str) -> str:
    """Return the canonical repo-local Git hook script for catch-up rebuilds.

    Args:
        str_hook_name: Git hook filename and trigger label. Supported values are
            "post-checkout", "post-merge", and "post-rewrite".

    Returns:
        str: Full shell script text for the requested Git hook.
    """
    str_script = f"""#!/usr/bin/env bash
set -euo pipefail

repo_root="$(git rev-parse --show-toplevel)"
if ! "$repo_root/scripts/shared-repo-memory/run-catchup.sh" {str_hook_name} "$@"; then
    echo "[shared-repo-memory] warning: {str_hook_name} memory catch-up failed (non-fatal)" >&2
fi
"""
    return str_script  # Normal exit.


def ensure_git_hooks(repo_root: Path, *, dry_run: bool) -> None:
    """Create or repair the repo-local Git hook scripts used for catch-up rebuilds.

    Args:
        repo_root: Absolute path to the repository root.
        dry_run: When True, log the action without modifying files.

    Returns:
        None: Hook files are updated in place when needed.
    """
    hooks_dir: Path = repo_root / ".githooks"

    # Ensure each required Git hook exists with the shared catch-up command.
    for str_hook_name in _GIT_HOOK_NAMES:
        hook_path: Path = hooks_dir / str_hook_name
        str_expected_text: str = git_hook_text(str_hook_name)
        bool_needs_write: bool = True
        if hook_path.exists():
            str_current_text: str = hook_path.read_text(encoding="utf-8")
            bool_needs_write = str_current_text != str_expected_text
        if bool_needs_write:
            log(f"writing Git hook {hook_path.relative_to(repo_root)}", dry_run=dry_run)
            if not dry_run:
                write_text(hook_path, str_expected_text)
        if not dry_run and hook_path.exists():
            hook_path.chmod(hook_path.stat().st_mode | 0o111)


def main() -> int:
    """Bootstrap repo-local wiring.

    Returns:
        int: 0 on success; 1 if the repo root cannot be determined.
    """
    args = parse_args()
    dry_run = args.dry_run

    repo_root = try_repo_root(args.repo_root)
    if repo_root is None:
        warn("bootstrap-repo.py: current directory is not inside a git repository")
        return 1

    # Create all required directories.
    for rel_path in (
        ".agents/memory/adr",
        ".agents/memory/daily",
        ".codex/local",
        ".claude/local",
        ".githooks",
    ):
        target = repo_root / rel_path
        if not target.exists():
            log(f"creating directory {rel_path}", dry_run=dry_run)
            if not dry_run:
                ensure_dir(target)

    # Create or repair the .codex/memory -> ../.agents/memory symlink.
    ensure_symlink(
        repo_root / ".codex" / "memory",
        EXPECTED_MEMORY_TARGET,
        dry_run=dry_run,
    )

    # Write the initial ADR index only when the file does not already exist.
    index_path = repo_root / ".agents" / "memory" / "adr" / "INDEX.md"
    if not index_path.exists():
        log("creating .agents/memory/adr/INDEX.md", dry_run=dry_run)
        if not dry_run:
            write_text(index_path, _INDEX_INITIAL)

    # Ensure .gitignore covers local-only paths that should never be committed.
    ensure_gitignore(repo_root, dry_run=dry_run)

    # Install the repo-local catch-up hooks that rebuild local state after Git changes.
    ensure_git_hooks(repo_root, dry_run=dry_run)

    # Point git at .githooks so post-checkout, post-merge, and post-rewrite fire.
    set_git_hooks_path(repo_root, ".githooks", dry_run=dry_run)

    log("repository setup complete")
    print(f"  repo: {repo_root}")
    hooks_path = subprocess.run(
        ["git", "config", "--get", "core.hooksPath"],
        cwd=str(repo_root),
        check=False,
        capture_output=True,
        text=True,
    ).stdout.strip()
    print(f"  Git hooks folder: {hooks_path or '.githooks'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(safe_main(main, "BootstrapRepo"))
