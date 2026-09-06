#!/usr/bin/env python3
"""Remove agentmemory.

Global scope (default) reverses ``install.py``: unwires the Claude hooks and
flags, removes the skill symlinks and copies, and deletes the install root.
``--repo`` reverses ``bootstrap-repo.py`` for the current repository: removes
the generated hooks (only when their content is still canonical), unsets
``core.hooksPath`` when nothing else lives in ``.githooks/``, and strips the
managed ``.gitignore`` block. ``--purge-memory`` additionally stages
``git rm -r --cached .agents/memory`` for review. Committed memory is never
deleted from disk.
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path
from typing import Any

from common import (
    ASSETS_REPO_KEY,
    CONFIGURED_FLAG,
    GITHOOKS_DIR,
    LOCAL_DIR,
    MEMORY_DIR,
    dump_json,
    git,
    install_root,
    load_json,
    load_module,
    log,
    read_text,
    repo_root,
)

HERE: Path = Path(__file__).resolve().parent


def unwire_claude(settings_path: Path, root: Path, *, dry_run: bool) -> None:
    """Remove hook entries pointing into ``root`` and the two flags.

    Args:
        settings_path: ``~/.claude/settings.json``.
        root: Install root whose commands should be removed.
        dry_run: Log only.
    """
    settings: dict[str, Any] = load_json(settings_path, {})
    if not isinstance(settings, dict) or not settings:
        return
    changed: bool = False
    for key in (CONFIGURED_FLAG, ASSETS_REPO_KEY):
        if key in settings:
            del settings[key]
            changed = True
    hooks: Any = settings.get("hooks")
    if isinstance(hooks, dict):
        for event in list(hooks):
            kept: list[Any] = []
            for entry in hooks[event]:
                if not isinstance(entry, dict):
                    kept.append(entry)
                    continue
                inner = [
                    h
                    for h in entry.get("hooks", [])
                    if not (
                        isinstance(h, dict)
                        and str(h.get("command", "")).startswith(str(root))
                    )
                ]
                if len(inner) != len(entry.get("hooks", [])):
                    changed = True
                if inner:
                    kept.append({**entry, "hooks": inner})
            if kept:
                hooks[event] = kept
            else:
                del hooks[event]
        if not hooks:
            del settings["hooks"]
    if changed:
        log(f"{'would update' if dry_run else 'updating'} {settings_path}")
        if not dry_run:
            dump_json(settings_path, settings)


def remove_skills(
    skills_root: Path, claude_skills: Path, names: list[str], *, dry_run: bool
) -> None:
    """Remove shipped skill symlinks and copies.

    Args:
        skills_root: ``~/.agent/skills``.
        claude_skills: ``~/.claude/skills``.
        names: Skill names shipped by this checkout.
        dry_run: Log only.
    """
    for name in names:
        link: Path = claude_skills / name
        if link.is_symlink() and link.resolve() == (skills_root / name).resolve():
            log(f"{'would remove' if dry_run else 'removing'} {link}")
            if not dry_run:
                link.unlink()
        copy: Path = skills_root / name
        if copy.is_dir():
            log(f"{'would remove' if dry_run else 'removing'} {copy}")
            if not dry_run:
                shutil.rmtree(copy)


def uninstall_global(checkout: Path, *, dry_run: bool) -> None:
    home: Path = Path.home()
    root: Path = install_root()
    unwire_claude(home / ".claude" / "settings.json", root, dry_run=dry_run)
    names: list[str] = sorted(
        p.name for p in (checkout / "skills").iterdir() if p.is_dir()
    )
    remove_skills(
        home / ".agent" / "skills", home / ".claude" / "skills", names, dry_run=dry_run
    )
    if root.is_dir():
        log(f"{'would remove' if dry_run else 'removing'} {root}")
        if not dry_run:
            shutil.rmtree(root)


def uninstall_repo(root: Path, *, dry_run: bool, purge: bool) -> None:
    bootstrap = load_module(HERE / "bootstrap-repo.py")
    hooks_dir: Path = root / GITHOOKS_DIR
    for name in bootstrap.HOOK_NAMES:
        path: Path = hooks_dir / name
        if path.is_file() and read_text(path) == bootstrap.hook_text(name):
            log(f"{'would remove' if dry_run else 'removing'} {GITHOOKS_DIR}/{name}")
            if not dry_run:
                path.unlink()
    if hooks_dir.is_dir() and not any(hooks_dir.iterdir()):
        if git(["config", "--get", "core.hooksPath"], root) == GITHOOKS_DIR:
            log(f"{'would unset' if dry_run else 'unsetting'} core.hooksPath")
            if not dry_run:
                git(["config", "--unset", "core.hooksPath"], root)
        if not dry_run:
            hooks_dir.rmdir()
    bootstrap.strip_gitignore(root, dry_run=dry_run)
    bootstrap.strip_agents_block(root, dry_run=dry_run)
    local: Path = root / LOCAL_DIR
    if local.is_dir():
        log(f"{'would remove' if dry_run else 'removing'} {LOCAL_DIR}/")
        if not dry_run:
            shutil.rmtree(local)
    if purge and (root / MEMORY_DIR).is_dir():
        log(
            f"{'would stage' if dry_run else 'staging'} git rm -r --cached {MEMORY_DIR}"
        )
        if not dry_run:
            git(["rm", "-r", "--cached", "--quiet", MEMORY_DIR], root)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--repo", action="store_true", help="per-repo scope")
    parser.add_argument("--purge-memory", action="store_true")
    parser.add_argument("--repo-root", default=None)
    args = parser.parse_args()
    if args.repo:
        root = repo_root(args.repo_root)
        if root is None:
            log("uninstall --repo: not inside a git repository")
            return 1
        uninstall_repo(root, dry_run=args.dry_run, purge=args.purge_memory)
    else:
        uninstall_global(HERE.parents[1], dry_run=args.dry_run)
    log("done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
