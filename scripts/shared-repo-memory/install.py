#!/usr/bin/env python3
"""Install agentmemory for Claude Code.

Copies the scripts to ``~/.agent/shared-repo-memory/``, copies the skills to
``~/.agent/skills/`` with symlinks from ``~/.claude/skills/``, and wires the
``SessionStart`` and ``PostCompact`` hooks in ``~/.claude/settings.json``.
Idempotent; ``--dry-run`` prints the plan.
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path
from typing import Any

from common import (
    ASSETS_REPO_KEY,
    CONFIGURED_FLAG,
    VERSION,
    dump_json,
    install_root,
    load_json,
    log,
)

SCRIPTS: tuple[str, ...] = (
    "common.py",
    "session-start.py",
    "post-compact.py",
    "bootstrap-repo.py",
    "catchup.py",
    "memory-note.py",
    "commit-capture.py",
    "promote-adr.py",
    "memory-query.py",
    "check-memory.py",
    "memory-status.py",
    "memory-news.py",
    "memory-bootstrap.py",
    "memory-commit.py",
    "turn-nudge.py",
    "uninstall.py",
)

# (hook event, script, timeout seconds)
CLAUDE_HOOKS: tuple[tuple[str, str, int], ...] = (
    ("SessionStart", "session-start.py", 30),
    ("PostCompact", "post-compact.py", 15),
    ("Stop", "turn-nudge.py", 10),
)


def same(a: Path, b: Path) -> bool:
    return a.is_file() and b.is_file() and a.read_bytes() == b.read_bytes()


def copy_template(checkout: Path, dst_dir: Path, *, dry_run: bool) -> None:
    """Install the CI workflow template beside the scripts.

    ``bootstrap-repo.py`` writes it into an opted-in repository, and it runs
    from the install root, so the template has to be there too.

    Args:
        checkout: The agentmemory checkout.
        dst_dir: Install root.
        dry_run: Log only.
    """
    src = checkout / "templates" / "agentmemory-check.yml"
    if not src.is_file():
        return
    dst = dst_dir / "agentmemory-check.yml"
    state = "unchanged" if same(src, dst) else "update"
    log(f"template agentmemory-check.yml: {'would ' if dry_run else ''}{state}")
    if not dry_run and state != "unchanged":
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)


def copy_scripts(src_dir: Path, dst_dir: Path, *, dry_run: bool) -> None:
    """Copy every script in ``SCRIPTS`` and mark it executable.

    Args:
        src_dir: ``scripts/shared-repo-memory`` in the checkout.
        dst_dir: Install root.
        dry_run: Log only.
    """
    for name in SCRIPTS:
        src, dst = src_dir / name, dst_dir / name
        state: str = "unchanged" if same(src, dst) else "update"
        log(f"script {name}: {'would ' if dry_run else ''}{state}")
        if dry_run or state == "unchanged":
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        dst.chmod(dst.stat().st_mode | 0o111)


def install_skills(
    skills_src: Path,
    skills_root: Path,
    claude_skills: Path,
    *,
    dry_run: bool,
    force: bool,
) -> None:
    """Copy each skill to ``skills_root`` and symlink it from ``claude_skills``.

    Args:
        skills_src: ``skills/`` in the checkout.
        skills_root: ``~/.agent/skills``.
        claude_skills: ``~/.claude/skills``.
        dry_run: Log only.
        force: Replace a non-symlink entry already at the link path.
    """
    for skill_dir in sorted(p for p in skills_src.iterdir() if p.is_dir()):
        name: str = skill_dir.name
        dest: Path = skills_root / name
        link: Path = claude_skills / name
        log(f"skill {name}: {'would install' if dry_run else 'installing'}")
        if dry_run:
            continue
        dest.mkdir(parents=True, exist_ok=True)
        for src_file in skill_dir.iterdir():
            if src_file.is_file() and not same(src_file, dest / src_file.name):
                shutil.copy2(src_file, dest / src_file.name)
        claude_skills.mkdir(parents=True, exist_ok=True)
        if link.is_symlink():
            link.unlink()
        elif link.exists():
            if not force:
                log(f"skill {name}: {link} exists and is not a symlink (use --force)")
                continue
            shutil.rmtree(link) if link.is_dir() else link.unlink()
        link.symlink_to(dest)


def wire_claude(
    settings_path: Path, repo_root: Path, root: Path, *, dry_run: bool
) -> None:
    """Add the hooks and flags to ``~/.claude/settings.json``.

    Args:
        settings_path: The settings file.
        repo_root: The agentmemory checkout, recorded for reference.
        root: Install root the hook commands point at.
        dry_run: Log only.
    """
    settings: dict[str, Any] = load_json(settings_path, {})
    if not isinstance(settings, dict):
        settings = {}
    settings[CONFIGURED_FLAG] = True
    settings[ASSETS_REPO_KEY] = str(repo_root)
    hooks: dict[str, Any] = settings.setdefault("hooks", {})
    for event, script, timeout in CLAUDE_HOOKS:
        command: str = str(root / script)
        entries: list[Any] = hooks.setdefault(event, [])
        if any(
            h.get("command") == command
            for entry in entries
            if isinstance(entry, dict)
            for h in entry.get("hooks", [])
            if isinstance(h, dict)
        ):
            continue
        entries.append(
            {"hooks": [{"type": "command", "command": command, "timeout": timeout}]}
        )
    log(f"{'would write' if dry_run else 'writing'} {settings_path}")
    if not dry_run:
        dump_json(settings_path, settings)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--repo-root", default=None, help="agentmemory checkout")
    args = parser.parse_args()
    checkout: Path = (
        Path(args.repo_root).resolve()
        if args.repo_root
        else Path(__file__).resolve().parents[2]
    )
    home: Path = Path.home()
    root: Path = install_root()
    log(f"agentmemory v{VERSION} installer{' (dry run)' if args.dry_run else ''}")
    copy_scripts(
        checkout / "scripts" / "shared-repo-memory", root, dry_run=args.dry_run
    )
    copy_template(checkout, root, dry_run=args.dry_run)
    install_skills(
        checkout / "skills",
        home / ".agent" / "skills",
        home / ".claude" / "skills",
        dry_run=args.dry_run,
        force=args.force,
    )
    wire_claude(
        home / ".claude" / "settings.json", checkout, root, dry_run=args.dry_run
    )
    log("done. Restart Claude Code sessions to pick up the hooks.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
