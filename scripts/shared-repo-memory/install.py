#!/usr/bin/env python3
"""install.py -- Install shared-repo-memory user-level assets and wire agent hooks.

Run via the repo root entry point:
    ./install.sh [--dry-run]

Or directly:
    python3 scripts/shared-repo-memory/install.py [--dry-run]

What this installer does:
  1. Creates ~/.agent/shared-repo-memory/ and copies all helper scripts into it.
  2. Creates ~/.agent/state/ and initialises shared_asset_refresh_state.json.
  3. Copies skills into ~/.agent/skills/ and creates per-agent symlinks under
     ~/.claude/skills/, ~/.codex/skills/, and ~/.gemini/skills/.
  4. Wires SessionStart and Stop (or AfterAgent) hooks for Claude Code, Codex,
     and Gemini CLI.

The --dry-run flag prints every action without making any changes, useful for
verifying what would be modified before committing to the install.

After installation, restart any open agent sessions.  The SessionStart hook
will validate and bootstrap repo-local wiring on the next session open.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

# Scripts copied verbatim from scripts/shared-repo-memory/ into ~/.agent/shared-repo-memory/.
# The order here is for readability; installation processes them in sequence.
SCRIPTS = [
    "common.py",
    "bootstrap-repo.py",
    "session-start.py",
    "post-turn-notify.py",
    "prompt-guard.py",
    "post-compact.py",
    "auto-bootstrap.py",
    "rebuild-summary.py",
    "build-catchup.py",
    "promote-adr.py",
]


def log(message: str) -> None:
    """Print a prefixed log message to stdout.

    Args:
        message: Human-readable message text.
    """
    print(f"[shared-repo-memory] {message}")


class Installer:
    """Orchestrates installation of all shared-repo-memory user assets and agent wiring.

    Each agent (Claude Code, Codex, Gemini) requires a different configuration
    format and hook event name.  This class handles them independently in
    _wire_claude, _wire_codex, and _wire_gemini so each can be updated without
    risking the others.

    The dry_run flag prevents any filesystem writes; callers can pass it to
    preview the full installation plan before executing it.
    """

    def __init__(
        self, repo_root: Path, dry_run: bool = False, force: bool = False
    ) -> None:
        """Initialise the installer with the repo root and flags.

        Args:
            repo_root: Absolute path to the agentmemory repository root.
                Script sources are read from repo_root/scripts/shared-repo-memory/.
            dry_run: When True, log all actions without making any changes.
            force: When True, overwrite existing installed skill copies.
        """
        self.repo_root = repo_root
        self.dry_run = dry_run
        self.force = force
        self.home = Path.home()
        # Install target: scripts are copied here, separate from any single agent's config.
        self.install_root = self.home / ".agent" / "shared-repo-memory"
        self.skills_root = self.home / ".agent" / "skills"
        self.claude_settings = self.home / ".claude" / "settings.json"
        self.codex_config = self.home / ".codex" / "config.toml"
        self.codex_hooks = self.home / ".codex" / "hooks.json"
        self.gemini_settings = self.home / ".gemini" / "settings.json"

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _same_content(self, a: Path, b: Path) -> bool:
        """Return True when both paths exist and have identical byte content.

        Args:
            a: First file path.
            b: Second file path.

        Returns:
            bool: True if both files exist and are byte-identical.
        """
        if not a.exists() or not b.exists():
            return False
        return a.read_bytes() == b.read_bytes()

    def _ensure_dir(self, path: Path) -> None:
        """Create path and any missing parents, or log the would-be action in dry-run mode.

        Args:
            path: Directory to create.
        """
        if self.dry_run:
            log(f"[DRY-RUN] would create {path}")
            return
        path.mkdir(parents=True, exist_ok=True)

    def _load_json(self, path: Path) -> dict:
        """Load a JSON file as a dict, returning {} on any error or absence.

        Args:
            path: JSON file to read.

        Returns:
            dict: Parsed JSON, or empty dict if the file is absent or invalid.
        """
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}

    def _save_json(self, path: Path, data: dict) -> None:
        """Write data to path as pretty-printed JSON, creating parents as needed.

        In dry-run mode, logs the path that would be written without touching disk.

        Args:
            path: Destination file path.
            data: JSON-serialisable dict to write.
        """
        if self.dry_run:
            log(f"[DRY-RUN] would write {path}")
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

    # ------------------------------------------------------------------
    # Script installation
    # ------------------------------------------------------------------

    def _copy_scripts(self) -> None:
        """Copy all listed helper scripts from the repo source to the install target.

        Sets the executable bit on each destination file so scripts can be run
        directly without specifying the Python interpreter.  In dry-run mode,
        logs each copy operation without modifying files.
        """
        src_dir = self.repo_root / "scripts" / "shared-repo-memory"
        for name in SCRIPTS:
            src = src_dir / name
            dst = self.install_root / name
            if self.dry_run:
                action: str = (
                    "unchanged" if self._same_content(src, dst) else "would update"
                )
                log(f"[DRY-RUN] {action}: {name}")
            else:
                changed: bool = not self._same_content(src, dst)
                shutil.copy2(src, dst)
                # Ensure the script is executable for all hook runners.
                dst.chmod(dst.stat().st_mode | 0o111)
                status: str = "updated" if changed else "unchanged"
                log(f"script {name}: {status}")

    # ------------------------------------------------------------------
    # Claude Code wiring (~/.claude/settings.json)
    # ------------------------------------------------------------------

    def _wire_claude(self) -> None:
        """Wire Claude Code hooks by updating ~/.claude/settings.json.

        Adds or updates:
          shared_repo_memory_configured: true
          shared_agent_assets_repo_path: <repo_root>
          hooks.SessionStart:        session-start.py
          hooks.Stop:                post-turn-notify.py  (post-turn shard capture)
          hooks.SubagentStop:        post-turn-notify.py  (shard capture for Task agents)
          hooks.UserPromptSubmit:    prompt-guard.py      (empty-memory bootstrap nudge)
          hooks.PostCompact:         post-compact.py      (re-inject memory after compaction)

        Idempotency: existing hook entries with the same command path are not
        duplicated.
        """
        session_start_cmd = str(self.install_root / "session-start.py")
        post_turn_cmd = str(self.install_root / "post-turn-notify.py")
        prompt_guard_cmd = str(self.install_root / "prompt-guard.py")
        post_compact_cmd = str(self.install_root / "post-compact.py")

        settings = self._load_json(self.claude_settings)
        settings["shared_repo_memory_configured"] = True
        settings["shared_agent_assets_repo_path"] = str(self.repo_root)

        hooks = settings.setdefault("hooks", {})

        # SessionStart -- validates wiring and bootstraps repo if needed.
        session_hooks = hooks.setdefault("SessionStart", [])
        already_wired = any(
            any(h.get("command") == session_start_cmd for h in entry.get("hooks", []))
            for entry in session_hooks
        )
        if not already_wired:
            session_hooks.append(
                {
                    "hooks": [
                        {
                            "type": "command",
                            "command": session_start_cmd,
                            "timeout": 30,
                        }
                    ]
                }
            )

        # Stop -- post-turn event shard capture.
        stop_hooks = hooks.setdefault("Stop", [])
        already_wired = any(
            any(h.get("command") == post_turn_cmd for h in entry.get("hooks", []))
            for entry in stop_hooks
        )
        if not already_wired:
            stop_hooks.append(
                {
                    "hooks": [
                        {
                            "type": "command",
                            "command": post_turn_cmd,
                            "timeout": 60,
                        }
                    ]
                }
            )

        # SubagentStop -- post-turn shard capture for Task/subagent turns.
        subagent_stop_hooks = hooks.setdefault("SubagentStop", [])
        already_wired = any(
            any(h.get("command") == post_turn_cmd for h in entry.get("hooks", []))
            for entry in subagent_stop_hooks
        )
        if not already_wired:
            subagent_stop_hooks.append(
                {
                    "hooks": [
                        {
                            "type": "command",
                            "command": post_turn_cmd,
                            "timeout": 60,
                        }
                    ]
                }
            )

        # UserPromptSubmit -- detect empty-memory sessions and nudge bootstrap.
        prompt_hooks = hooks.setdefault("UserPromptSubmit", [])
        already_wired = any(
            any(h.get("command") == prompt_guard_cmd for h in entry.get("hooks", []))
            for entry in prompt_hooks
        )
        if not already_wired:
            prompt_hooks.append(
                {
                    "hooks": [
                        {
                            "type": "command",
                            "command": prompt_guard_cmd,
                            "timeout": 10,
                        }
                    ]
                }
            )

        # PostCompact -- re-inject memory context after context compaction.
        compact_hooks = hooks.setdefault("PostCompact", [])
        already_wired = any(
            any(h.get("command") == post_compact_cmd for h in entry.get("hooks", []))
            for entry in compact_hooks
        )
        if not already_wired:
            compact_hooks.append(
                {
                    "hooks": [
                        {
                            "type": "command",
                            "command": post_compact_cmd,
                            "timeout": 15,
                        }
                    ]
                }
            )

        self._save_json(self.claude_settings, settings)
        if not self.dry_run:
            log(f"updated Claude settings at {self.claude_settings}")

    # ------------------------------------------------------------------
    # Codex wiring (~/.codex/config.toml + ~/.codex/hooks.json)
    # ------------------------------------------------------------------

    def _wire_codex(self) -> None:
        """Wire Codex hooks by updating ~/.codex/config.toml and ~/.codex/hooks.json.

        config.toml receives:
          experimental_use_hooks = true
          hooks_config_path = "<path to hooks.json>"
          features.codex_hooks = true
          shared_repo_memory_configured = true
          shared_agent_assets_repo_path = "<repo_root>"
          [projects."<repo_root>"] trust_level = "trusted"

        hooks.json receives:
          hooks.SessionStart: session-start.py

        TOML is edited in-place using regex rather than a proper TOML serialiser
        to preserve any existing user configuration and comments.
        """
        if self.dry_run:
            log(f"[DRY-RUN] would update Codex config at {self.codex_config}")
            log(f"[DRY-RUN] would update Codex hooks at {self.codex_hooks}")
            return

        self.codex_config.parent.mkdir(parents=True, exist_ok=True)
        self.codex_config.touch()
        text = self.codex_config.read_text(encoding="utf-8")

        def upsert(key: str, line: str) -> None:
            """Replace an existing top-level key=value line, or append it."""
            nonlocal text
            pattern = re.compile(rf"^{re.escape(key)}\s*=.*$", re.MULTILINE)
            if pattern.search(text):
                text = pattern.sub(line, text, count=1)
            else:
                suffix = "" if not text or text.endswith("\n") else "\n"
                text = f"{text}{suffix}\n{line}\n"

        def append_if_missing(pat: str, line: str, comment: str = "") -> None:
            """Append a line (with optional comment) only if the pattern is not found."""
            nonlocal text
            if re.search(pat, text, re.MULTILINE):
                return
            prefix = f"\n# {comment}\n" if comment else "\n"
            text += f"{prefix}{line}\n"

        upsert("experimental_use_hooks", "experimental_use_hooks = true")
        upsert("hooks_config_path", f'hooks_config_path = "{self.codex_hooks}"')
        append_if_missing(
            r"^\s*features\.codex_hooks\s*=",
            "features.codex_hooks = true",
            "Enable Codex hook execution so SessionStart can validate installed shared memory assets.",
        )
        append_if_missing(
            r"^\s*shared_repo_memory_configured\s*=",
            "shared_repo_memory_configured = true",
            "Enable automatic shared repo-memory startup checks and repo bootstrap in Git repositories.",
        )
        append_if_missing(
            r"^\s*shared_agent_assets_repo_path\s*=",
            f'shared_agent_assets_repo_path = "{self.repo_root}"',
            "Shared repo-memory authoring checkout used to refresh installed shared assets.",
        )

        # Mark the agentmemory repo itself as trusted so Codex can work in it.
        escaped = re.escape(str(self.repo_root))
        if not re.search(rf'\[projects\."{escaped}"\]', text):
            text += (
                f"\n# Trust this shared repo-memory authoring repo for local Codex work.\n"
                f'[projects."{self.repo_root}"]\ntrust_level = "trusted"\n'
            )

        self.codex_config.write_text(text, encoding="utf-8")

        # Write the hooks.json with the SessionStart command.
        session_start_cmd = str(self.install_root / "session-start.py")
        hooks_data = self._load_json(self.codex_hooks)
        hooks_data.setdefault("hooks", {})
        hooks_data["hooks"]["SessionStart"] = [
            {
                "hooks": [
                    {
                        "type": "command",
                        "command": session_start_cmd,
                        "timeout": 30,
                    }
                ]
            }
        ]
        self._save_json(self.codex_hooks, hooks_data)

        log(f"updated Codex config at {self.codex_config}")
        log(f"updated Codex hooks at {self.codex_hooks}")

    # ------------------------------------------------------------------
    # Gemini wiring (~/.gemini/settings.json)
    # ------------------------------------------------------------------

    def _wire_gemini(self) -> None:
        """Wire Gemini CLI hooks by updating ~/.gemini/settings.json.

        Adds or updates:
          shared_repo_memory_configured: true
          shared_agent_assets_repo_path: <repo_root>
          hooks.SessionStart:  session-start.py  (matched by name for idempotency)
          hooks.AfterAgent:    post-turn-notify.py  (post-turn shard capture)
          hooks.BeforeAgent:   prompt-guard.py  (empty-memory bootstrap nudge)

        Gemini CLI uses "AfterAgent" instead of "Stop" for the post-turn hook and
        "BeforeAgent" instead of "UserPromptSubmit" for the pre-turn hook.
        Gemini has no PostCompact equivalent (PreCompress is advisory and fires
        before compression, not after).
        Each hook entry includes a "name" field used to detect existing entries.
        """
        session_start_cmd = str(self.install_root / "session-start.py")
        post_turn_cmd = str(self.install_root / "post-turn-notify.py")
        prompt_guard_cmd = str(self.install_root / "prompt-guard.py")

        settings = self._load_json(self.gemini_settings)
        settings["shared_agent_assets_repo_path"] = str(self.repo_root)
        settings["shared_repo_memory_configured"] = True

        hooks = settings.setdefault("hooks", {})

        # SessionStart hook -- uses a named entry so we can detect duplicates by name.
        session_hooks = hooks.setdefault("SessionStart", [])
        if not any(
            h.get("matcher") == "*"
            and any(
                sh.get("name") == "shared-repo-memory-session-start"
                for sh in h.get("hooks", [])
            )
            for h in session_hooks
        ):
            session_hooks.append(
                {
                    "matcher": "*",
                    "hooks": [
                        {
                            "name": "shared-repo-memory-session-start",
                            "type": "command",
                            "command": session_start_cmd,
                            "timeout": 30000,
                        }
                    ],
                }
            )

        # AfterAgent hook (Gemini's equivalent of Claude Code's Stop hook).
        after_hooks = hooks.setdefault("AfterAgent", [])
        if not any(
            h.get("matcher") == "*"
            and any(
                sh.get("name") == "shared-repo-memory-post-turn"
                for sh in h.get("hooks", [])
            )
            for h in after_hooks
        ):
            after_hooks.append(
                {
                    "matcher": "*",
                    "hooks": [
                        {
                            "name": "shared-repo-memory-post-turn",
                            "type": "command",
                            "command": post_turn_cmd,
                            "timeout": 30000,
                        }
                    ],
                }
            )

        # BeforeAgent hook (Gemini's equivalent of Claude Code's UserPromptSubmit).
        before_hooks = hooks.setdefault("BeforeAgent", [])
        if not any(
            h.get("matcher") == "*"
            and any(
                sh.get("name") == "shared-repo-memory-prompt-guard"
                for sh in h.get("hooks", [])
            )
            for h in before_hooks
        ):
            before_hooks.append(
                {
                    "matcher": "*",
                    "hooks": [
                        {
                            "name": "shared-repo-memory-prompt-guard",
                            "type": "command",
                            "command": prompt_guard_cmd,
                            "timeout": 10000,
                        }
                    ],
                }
            )

        self._save_json(self.gemini_settings, settings)
        if not self.dry_run:
            log(f"updated Gemini settings at {self.gemini_settings}")

    # ------------------------------------------------------------------
    # Skills installation
    # ------------------------------------------------------------------

    def _install_skills(self) -> None:
        """Copy skills from the repo into ~/.agent/skills/ and symlink into each agent.

        Each skill directory is copied verbatim from repo_root/skills/<skill>/ to
        ~/.agent/skills/<skill>/.  Per-agent symlinks are then created under
        ~/.claude/skills/, ~/.codex/skills/, and ~/.gemini/skills/.

        When force=True, existing copies in ~/.agent/skills/ are replaced.
        Symlinks are always (re)created since they are cheap and may be stale.
        """
        skills_src: Path = self.repo_root / "skills"
        if not skills_src.is_dir():
            log("no skills/ directory found in repo root — skipping skill install")
            return

        agent_skill_dirs: list[Path] = [
            self.home / ".claude" / "skills",
            self.home / ".codex" / "skills",
            self.home / ".gemini" / "skills",
        ]

        for skill_dir in skills_src.iterdir():
            if not skill_dir.is_dir():
                continue
            skill_name: str = skill_dir.name
            dest: Path = self.skills_root / skill_name

            if self.dry_run:
                if not dest.exists():
                    log(f"[DRY-RUN] skill {skill_name}: would install")
                else:
                    # Check if any file in the skill differs.
                    skill_files: list[Path] = list(skill_dir.iterdir())
                    needs_update: bool = any(
                        not self._same_content(f, dest / f.name)
                        for f in skill_files
                        if f.is_file()
                    )
                    dry_status: str = "would update" if needs_update else "unchanged"
                    log(f"[DRY-RUN] skill {skill_name}: {dry_status}")
            else:
                if not dest.exists():
                    shutil.copytree(skill_dir, dest)
                    log(f"skill {skill_name}: installed")
                else:
                    # Copy each file individually, tracking whether anything changed.
                    updated_files: list[str] = []
                    for src_file in skill_dir.iterdir():
                        if not src_file.is_file():
                            continue
                        dst_file: Path = dest / src_file.name
                        if not self._same_content(src_file, dst_file):
                            shutil.copy2(src_file, dst_file)
                            updated_files.append(src_file.name)
                    if updated_files:
                        log(f"skill {skill_name}: updated ({', '.join(updated_files)})")
                    else:
                        log(f"skill {skill_name}: unchanged")

            # Create per-agent symlinks into the canonical copy.
            for agent_skills_dir in agent_skill_dirs:
                link: Path = agent_skills_dir / skill_name
                if self.dry_run:
                    log(f"[DRY-RUN] would symlink {link} -> {dest}")
                    continue
                self._ensure_dir(agent_skills_dir)
                if link.is_symlink():
                    link.unlink()
                elif link.exists():
                    if self.force:
                        shutil.rmtree(link) if link.is_dir() else link.unlink()
                    else:
                        log(
                            f"skipping symlink {link}: already exists (use --force to replace)"
                        )
                        continue
                link.symlink_to(dest)

    # ------------------------------------------------------------------
    # Refresh state initialisation
    # ------------------------------------------------------------------

    def _init_refresh_state(self) -> None:
        """Create ~/.agent/state/shared_asset_refresh_state.json if absent.

        session-start.py checks for this file and fails if it is missing.
        The initial value is an empty object; the refresh mechanism updates it.
        """
        state_path: Path = (
            self.home / ".agent" / "state" / "shared_asset_refresh_state.json"
        )
        if state_path.exists():
            return
        if self.dry_run:
            log(f"[DRY-RUN] would initialise refresh state at {state_path}")
            return
        self._save_json(state_path, {})
        log(f"initialised refresh state at {state_path}")

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------

    def run(self) -> None:
        """Execute the full installation sequence.

        Creates required directories, copies scripts, installs skills, wires all
        three agents, and initialises the refresh state file.
        """
        # Create all required user-level directories before copying files.
        self._ensure_dir(self.install_root)
        self._ensure_dir(self.skills_root)
        self._ensure_dir(self.home / ".agent" / "state")
        self._ensure_dir(self.home / ".claude")
        self._ensure_dir(self.home / ".codex")
        self._ensure_dir(self.home / ".gemini")

        self._copy_scripts()
        self._install_skills()
        self._init_refresh_state()
        self._wire_claude()
        self._wire_codex()
        self._wire_gemini()

        log(f"installed helper files under {self.install_root}")


def main() -> int:
    """Entry point: parse arguments, resolve the repo root, and run the installer.

    Returns:
        int: 0 on success; 1 if the repo root cannot be determined.
    """
    parser = argparse.ArgumentParser(
        description="Install shared-repo-memory user assets and wire agent hooks."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would happen without making changes.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Replace existing installed skill copies rather than skipping them.",
    )
    parser.add_argument(
        "--repo-root",
        help="Override the agentmemory repo root (defaults to git toplevel).",
    )
    args = parser.parse_args()

    if args.repo_root:
        root = Path(args.repo_root).resolve()
    else:
        # Default to the git repo containing this script so the installer can be
        # run from any subdirectory within the agentmemory checkout.
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            print(
                "error: must be run from inside the agentmemory git repo",
                file=sys.stderr,
            )
            return 1
        root = Path(result.stdout.strip()).resolve()

    Installer(repo_root=root, dry_run=args.dry_run, force=args.force).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
