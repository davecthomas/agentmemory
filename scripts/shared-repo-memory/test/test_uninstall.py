#!/usr/bin/env python3
"""test_uninstall.py -- Tests for the shared-repo-memory uninstaller.

Every test runs against an isolated ``tmp_path`` so the real ``~/.agent/``,
``~/.claude/``, ``~/.codex/``, ``~/.gemini/`` directories are never touched.
Round-trip tests install into the tmp fake home and then uninstall, asserting
that user-added hook entries survive and installer-placed content is removed.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from adapters import (  # noqa: E402
    ClaudeAdapter,
    CodexAdapter,
    GeminiAdapter,
    InstallerContext,
)


def _install_ctx(tmp_home: Path, repo_root: Path, dry_run: bool = False) -> InstallerContext:
    """Build an ``InstallerContext`` that writes only inside ``tmp_home``."""
    def load_json(path: Path) -> dict:
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}

    def save_json(path: Path, payload: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

    install_root: Path = tmp_home / ".agent" / "shared-repo-memory"
    install_root.mkdir(parents=True, exist_ok=True)
    return InstallerContext(
        install_root=install_root,
        home=tmp_home,
        repo_root=repo_root,
        dry_run=dry_run,
        load_json=load_json,
        save_json=save_json,
    )


# ---------------------------------------------------------------------------
# Claude adapter unwire tests
# ---------------------------------------------------------------------------


class TestClaudeUnwireHooks:
    def test_unwire_is_noop_when_settings_missing(self, tmp_path: Path):
        repo = tmp_path / "repo"
        repo.mkdir()
        ctx = _install_ctx(tmp_path / "home", repo)
        # Should not raise, should not create the settings file.
        ClaudeAdapter.unwire_hooks(ctx)
        assert not (ctx.home / ".claude" / "settings.json").exists()

    def test_roundtrip_install_then_uninstall_matches_clean_state(
        self, tmp_path: Path
    ):
        tmp_home = tmp_path / "home"
        repo = tmp_path / "repo"
        repo.mkdir()
        ctx = _install_ctx(tmp_home, repo)

        ClaudeAdapter.wire_hooks(ctx)
        settings_path = tmp_home / ".claude" / "settings.json"
        assert settings_path.exists()
        after_install = json.loads(settings_path.read_text(encoding="utf-8"))
        assert after_install["shared_repo_memory_configured"] is True
        assert "hooks" in after_install

        ClaudeAdapter.unwire_hooks(ctx)
        # Settings file may exist but installer-managed keys must be gone.
        if settings_path.exists():
            after_uninstall = json.loads(settings_path.read_text(encoding="utf-8"))
            assert "shared_repo_memory_configured" not in after_uninstall
            assert "shared_agent_assets_repo_path" not in after_uninstall
            assert "hooks" not in after_uninstall

    def test_unwire_preserves_user_hooks_for_other_tools(self, tmp_path: Path):
        tmp_home = tmp_path / "home"
        repo = tmp_path / "repo"
        repo.mkdir()
        ctx = _install_ctx(tmp_home, repo)
        ClaudeAdapter.wire_hooks(ctx)

        # Operator adds a hook pointing at an unrelated tool.
        settings_path = tmp_home / ".claude" / "settings.json"
        settings = json.loads(settings_path.read_text(encoding="utf-8"))
        settings["hooks"]["SessionStart"].append(
            {
                "hooks": [
                    {
                        "type": "command",
                        "command": "/usr/local/bin/my-other-tool",
                        "timeout": 10,
                    }
                ]
            }
        )
        settings["theme"] = "dark"  # Unrelated top-level setting.
        settings_path.write_text(
            json.dumps(settings, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

        ClaudeAdapter.unwire_hooks(ctx)

        remaining = json.loads(settings_path.read_text(encoding="utf-8"))
        # User's unrelated top-level setting stays.
        assert remaining["theme"] == "dark"
        # Installer keys are gone.
        assert "shared_repo_memory_configured" not in remaining
        # User's own hook survived under SessionStart.
        remaining_session_start = remaining.get("hooks", {}).get("SessionStart", [])
        all_commands = [
            h.get("command")
            for entry in remaining_session_start
            for h in entry.get("hooks", [])
        ]
        assert "/usr/local/bin/my-other-tool" in all_commands
        assert not any(
            isinstance(cmd, str) and str(ctx.install_root) in cmd
            for cmd in all_commands
        )

    def test_unwire_is_idempotent(self, tmp_path: Path):
        tmp_home = tmp_path / "home"
        repo = tmp_path / "repo"
        repo.mkdir()
        ctx = _install_ctx(tmp_home, repo)
        ClaudeAdapter.wire_hooks(ctx)

        ClaudeAdapter.unwire_hooks(ctx)
        first_state = None
        settings_path = tmp_home / ".claude" / "settings.json"
        if settings_path.exists():
            first_state = settings_path.read_text(encoding="utf-8")

        ClaudeAdapter.unwire_hooks(ctx)  # second run
        second_state = None
        if settings_path.exists():
            second_state = settings_path.read_text(encoding="utf-8")
        assert first_state == second_state


# ---------------------------------------------------------------------------
# Gemini adapter unwire tests
# ---------------------------------------------------------------------------


class TestGeminiUnwireHooks:
    def test_roundtrip_install_then_uninstall(self, tmp_path: Path):
        tmp_home = tmp_path / "home"
        repo = tmp_path / "repo"
        repo.mkdir()
        ctx = _install_ctx(tmp_home, repo)
        GeminiAdapter.wire_hooks(ctx)

        settings_path = tmp_home / ".gemini" / "settings.json"
        after_install = json.loads(settings_path.read_text(encoding="utf-8"))
        assert any(
            h.get("name") == "shared-repo-memory-session-start"
            for entry in after_install["hooks"]["SessionStart"]
            for h in entry.get("hooks", [])
        )

        GeminiAdapter.unwire_hooks(ctx)
        if settings_path.exists():
            after = json.loads(settings_path.read_text(encoding="utf-8"))
            assert "shared_repo_memory_configured" not in after
            assert "hooks" not in after

    def test_preserves_user_named_hooks(self, tmp_path: Path):
        tmp_home = tmp_path / "home"
        repo = tmp_path / "repo"
        repo.mkdir()
        ctx = _install_ctx(tmp_home, repo)
        GeminiAdapter.wire_hooks(ctx)

        settings_path = tmp_home / ".gemini" / "settings.json"
        settings = json.loads(settings_path.read_text(encoding="utf-8"))
        settings["hooks"]["SessionStart"].append(
            {
                "matcher": "*",
                "hooks": [
                    {
                        "name": "my-custom-hook",
                        "type": "command",
                        "command": "/opt/my-tool.sh",
                        "timeout": 5000,
                    }
                ],
            }
        )
        settings_path.write_text(
            json.dumps(settings, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

        GeminiAdapter.unwire_hooks(ctx)
        after = json.loads(settings_path.read_text(encoding="utf-8"))
        surviving_names: list[str] = [
            h.get("name")
            for entry in after.get("hooks", {}).get("SessionStart", [])
            for h in entry.get("hooks", [])
        ]
        assert "my-custom-hook" in surviving_names
        assert not any(
            isinstance(n, str) and n.startswith("shared-repo-memory-")
            for n in surviving_names
        )


# ---------------------------------------------------------------------------
# Codex adapter unwire tests
# ---------------------------------------------------------------------------


class TestCodexUnwireHooks:
    def test_roundtrip_install_then_uninstall_removes_installer_keys(
        self, tmp_path: Path
    ):
        tmp_home = tmp_path / "home"
        repo = tmp_path / "repo"
        repo.mkdir()
        ctx = _install_ctx(tmp_home, repo)
        CodexAdapter.wire_hooks(ctx)

        config_path = tmp_home / ".codex" / "config.toml"
        hooks_path = tmp_home / ".codex" / "hooks.json"
        assert config_path.exists()
        assert hooks_path.exists()

        CodexAdapter.unwire_hooks(ctx)

        if config_path.exists():
            text = config_path.read_text(encoding="utf-8")
            assert "experimental_use_hooks" not in text
            assert "hooks_config_path" not in text
            assert "features.codex_hooks" not in text
            assert "shared_repo_memory_configured" not in text
            assert "shared_agent_assets_repo_path" not in text
            assert f'[projects."{ctx.repo_root}"]' not in text
        # hooks.json should be gone or empty of our entries.
        if hooks_path.exists():
            data = json.loads(hooks_path.read_text(encoding="utf-8"))
            inner = data.get("hooks", {})
            assert "SessionStart" not in inner or not any(
                isinstance(h.get("command"), str)
                and str(ctx.install_root) in h["command"]
                for entry in inner.get("SessionStart", [])
                for h in entry.get("hooks", [])
            )

    def test_preserves_preexisting_codex_config_entries(self, tmp_path: Path):
        tmp_home = tmp_path / "home"
        repo = tmp_path / "repo"
        repo.mkdir()
        codex_dir = tmp_home / ".codex"
        codex_dir.mkdir(parents=True)
        # User had unrelated Codex config BEFORE the installer ran.
        config_path = codex_dir / "config.toml"
        config_path.write_text(
            "# user-managed config\n"
            'model = "gpt-5"\n'
            "preferred_auth_method = \"chatgpt\"\n",
            encoding="utf-8",
        )

        ctx = _install_ctx(tmp_home, repo)
        CodexAdapter.wire_hooks(ctx)

        CodexAdapter.unwire_hooks(ctx)

        text = config_path.read_text(encoding="utf-8")
        assert 'model = "gpt-5"' in text
        assert 'preferred_auth_method = "chatgpt"' in text
        assert "experimental_use_hooks" not in text

    def test_preserves_user_added_hooks_in_hooks_json(self, tmp_path: Path):
        tmp_home = tmp_path / "home"
        repo = tmp_path / "repo"
        repo.mkdir()
        ctx = _install_ctx(tmp_home, repo)
        CodexAdapter.wire_hooks(ctx)

        hooks_path = tmp_home / ".codex" / "hooks.json"
        data = json.loads(hooks_path.read_text(encoding="utf-8"))
        # Add a user hook pointing somewhere else.
        data["hooks"].setdefault("SessionStart", []).append(
            {
                "hooks": [
                    {
                        "type": "command",
                        "command": "python3 /opt/other-tool.py",
                        "timeout": 10,
                    }
                ]
            }
        )
        hooks_path.write_text(
            json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

        CodexAdapter.unwire_hooks(ctx)
        if hooks_path.exists():
            after = json.loads(hooks_path.read_text(encoding="utf-8"))
            remaining_cmds = [
                h.get("command")
                for entry in after.get("hooks", {}).get("SessionStart", [])
                for h in entry.get("hooks", [])
            ]
            assert "python3 /opt/other-tool.py" in remaining_cmds
            assert not any(
                isinstance(cmd, str) and str(ctx.install_root) in cmd
                for cmd in remaining_cmds
            )

    def test_unwire_is_noop_without_prior_install(self, tmp_path: Path):
        tmp_home = tmp_path / "home"
        repo = tmp_path / "repo"
        repo.mkdir()
        ctx = _install_ctx(tmp_home, repo)
        # Should not raise and should not create anything.
        CodexAdapter.unwire_hooks(ctx)
        assert not (tmp_home / ".codex" / "config.toml").exists()
        assert not (tmp_home / ".codex" / "hooks.json").exists()


# ---------------------------------------------------------------------------
# Global uninstaller tests (via module import, not subprocess, so we control
# the tmp HOME fully).
# ---------------------------------------------------------------------------


def _load_uninstall_module():
    """Import scripts/shared-repo-memory/uninstall.py as a module."""
    import importlib.util

    source_path: Path = SCRIPT_DIR / "uninstall.py"
    spec = importlib.util.spec_from_file_location(
        "uninstall_under_test", source_path
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestGlobalUninstaller:
    def test_dry_run_does_not_mutate_state(self, tmp_path: Path):
        """Verify dry-run preserves file PATHS *and* file CONTENTS.

        An earlier iteration of this test only compared file paths, which
        missed a real bug where adapter unwire_hooks silently mutated
        ~/.claude/settings.json during dry-run because it delegated dry-run
        enforcement to ctx.save_json and the uninstaller's save_json callable
        did not honor the flag.
        """
        tmp_home = tmp_path / "home"
        repo = tmp_path / "repo"
        repo.mkdir()
        ctx = _install_ctx(tmp_home, repo)
        ClaudeAdapter.wire_hooks(ctx)
        GeminiAdapter.wire_hooks(ctx)
        CodexAdapter.wire_hooks(ctx)
        # Install-root placeholder content.
        (ctx.install_root / "dummy.py").write_text("# placeholder\n")

        def snapshot() -> dict[Path, bytes]:
            return {
                p.relative_to(tmp_home): p.read_bytes()
                for p in tmp_home.rglob("*")
                if p.is_file()
            }

        before_snapshot = snapshot()

        uninstall = _load_uninstall_module()
        uninstall.GlobalUninstaller(
            repo_root=repo, home=tmp_home, dry_run=True
        ).run()

        after_snapshot = snapshot()
        assert before_snapshot == after_snapshot, (
            "dry-run must preserve both file paths and contents"
        )

    def test_global_uninstall_removes_install_root_and_hook_wiring(
        self, tmp_path: Path
    ):
        tmp_home = tmp_path / "home"
        repo = tmp_path / "repo"
        repo.mkdir()
        # Simulate a real skills/ directory in the repo so the uninstaller
        # knows which skill names to remove.
        (repo / "skills" / "memory-writer").mkdir(parents=True)
        (repo / "skills" / "memory-writer" / "SKILL.md").write_text("---\nname: memory-writer\n---\n")
        ctx = _install_ctx(tmp_home, repo)
        ClaudeAdapter.wire_hooks(ctx)
        GeminiAdapter.wire_hooks(ctx)
        CodexAdapter.wire_hooks(ctx)
        # Scripts placeholder.
        (ctx.install_root / "dummy.py").write_text("# placeholder\n")
        # Skill canonical + per-agent symlinks.
        (tmp_home / ".agent" / "skills").mkdir(parents=True, exist_ok=True)
        (tmp_home / ".agent" / "skills" / "memory-writer").mkdir()
        (tmp_home / ".agent" / "skills" / "memory-writer" / "SKILL.md").write_text(
            "---\nname: memory-writer\n---\n"
        )
        for agent_dir in (".claude/skills", ".codex/skills", ".gemini/skills"):
            link_parent = tmp_home / agent_dir
            link_parent.mkdir(parents=True, exist_ok=True)
            (link_parent / "memory-writer").symlink_to(
                tmp_home / ".agent" / "skills" / "memory-writer"
            )
        # Refresh-state file.
        state_dir = tmp_home / ".agent" / "state"
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / "shared_asset_refresh_state.json").write_text("{}\n")

        uninstall = _load_uninstall_module()
        uninstall.GlobalUninstaller(
            repo_root=repo, home=tmp_home, dry_run=False
        ).run()

        # Install root gone.
        assert not ctx.install_root.exists()
        # Refresh state gone.
        assert not (state_dir / "shared_asset_refresh_state.json").exists()
        # Skill symlinks gone.
        for agent_dir in (".claude/skills", ".codex/skills", ".gemini/skills"):
            assert not (tmp_home / agent_dir / "memory-writer").exists()
        # Canonical skill copy gone.
        assert not (tmp_home / ".agent" / "skills" / "memory-writer").exists()

    def test_global_uninstall_preserves_unrelated_skill_symlink(
        self, tmp_path: Path
    ):
        """A symlink pointing outside ~/.agent/skills must be preserved."""
        tmp_home = tmp_path / "home"
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "skills" / "memory-writer").mkdir(parents=True)
        # User has another 'memory-writer' symlink placed BEFORE install.
        claude_skills = tmp_home / ".claude" / "skills"
        claude_skills.mkdir(parents=True)
        external_target = tmp_path / "external" / "memory-writer"
        external_target.mkdir(parents=True)
        (claude_skills / "memory-writer").symlink_to(external_target)

        uninstall = _load_uninstall_module()
        uninstall.GlobalUninstaller(
            repo_root=repo, home=tmp_home, dry_run=False
        ).run()

        # The user's external-target symlink should still exist.
        assert (claude_skills / "memory-writer").exists()
        assert (claude_skills / "memory-writer").resolve() == external_target.resolve()


# ---------------------------------------------------------------------------
# Per-repo uninstaller tests
# ---------------------------------------------------------------------------


def _init_git_repo(path: Path) -> None:
    """Initialize an empty git repo at ``path`` for tests."""
    subprocess.run(
        ["git", "init", "-q", str(path)], check=True, capture_output=True
    )
    subprocess.run(
        ["git", "-C", str(path), "config", "user.email", "test@example.com"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(path), "config", "user.name", "Test"],
        check=True,
        capture_output=True,
    )


class TestRepoUninstaller:
    def test_removes_canonical_hooks_and_preserves_edited_ones(
        self, tmp_path: Path
    ):
        repo = tmp_path / "repo"
        repo.mkdir()
        _init_git_repo(repo)

        # Run the real bootstrap to produce canonical hooks.
        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT_DIR / "bootstrap-repo.py"),
                "--repo-root",
                str(repo),
            ],
            check=False,
            capture_output=True,
            text=True,
            env={**os.environ, "PYTHONPATH": str(SCRIPT_DIR)},
        )
        assert result.returncode == 0, result.stderr

        hooks_dir = repo / ".githooks"
        assert (hooks_dir / "pre-commit").exists()

        # Edit one of the canonical hooks so it stops matching.
        (hooks_dir / "post-merge").write_text(
            "#!/usr/bin/env bash\n# user-modified hook\n", encoding="utf-8"
        )

        uninstall = _load_uninstall_module()
        uninstall.RepoUninstaller(
            repo_root=repo, dry_run=False, purge_memory=False
        ).run()

        # Canonical hooks gone.
        assert not (hooks_dir / "pre-commit").exists()
        assert not (hooks_dir / "post-checkout").exists()
        assert not (hooks_dir / "post-rewrite").exists()
        # User-edited hook preserved.
        assert (hooks_dir / "post-merge").exists()

    def test_strips_gitignore_block(self, tmp_path: Path):
        repo = tmp_path / "repo"
        repo.mkdir()
        _init_git_repo(repo)

        # Run bootstrap for .gitignore appending.
        subprocess.run(
            [
                sys.executable,
                str(SCRIPT_DIR / "bootstrap-repo.py"),
                "--repo-root",
                str(repo),
            ],
            check=True,
            capture_output=True,
            env={**os.environ, "PYTHONPATH": str(SCRIPT_DIR)},
        )
        gitignore = repo / ".gitignore"
        assert (
            "# agentmemory-managed local repo wiring and state"
            in gitignore.read_text(encoding="utf-8")
        )
        # Add a user entry outside the block to verify it survives.
        gitignore.write_text(
            gitignore.read_text(encoding="utf-8")
            + "\n# user preference\n*.log\n",
            encoding="utf-8",
        )

        uninstall = _load_uninstall_module()
        uninstall.RepoUninstaller(
            repo_root=repo, dry_run=False, purge_memory=False
        ).run()

        final = gitignore.read_text(encoding="utf-8")
        assert "# agentmemory-managed local repo wiring and state" not in final
        assert "*.log" in final
        assert "# user preference" in final

    def test_removes_codex_memory_symlink(self, tmp_path: Path):
        repo = tmp_path / "repo"
        repo.mkdir()
        _init_git_repo(repo)
        subprocess.run(
            [
                sys.executable,
                str(SCRIPT_DIR / "bootstrap-repo.py"),
                "--repo-root",
                str(repo),
            ],
            check=True,
            capture_output=True,
            env={**os.environ, "PYTHONPATH": str(SCRIPT_DIR)},
        )
        link = repo / ".codex" / "memory"
        assert link.is_symlink()

        uninstall = _load_uninstall_module()
        uninstall.RepoUninstaller(
            repo_root=repo, dry_run=False, purge_memory=False
        ).run()

        assert not link.exists() and not link.is_symlink()

    def test_unsets_core_hookspath_when_dir_empty(self, tmp_path: Path):
        repo = tmp_path / "repo"
        repo.mkdir()
        _init_git_repo(repo)
        subprocess.run(
            [
                sys.executable,
                str(SCRIPT_DIR / "bootstrap-repo.py"),
                "--repo-root",
                str(repo),
            ],
            check=True,
            capture_output=True,
            env={**os.environ, "PYTHONPATH": str(SCRIPT_DIR)},
        )
        # Confirm bootstrap set it.
        got = subprocess.run(
            ["git", "-C", str(repo), "config", "--get", "core.hooksPath"],
            check=False,
            capture_output=True,
            text=True,
        )
        assert got.stdout.strip() == ".githooks"

        uninstall = _load_uninstall_module()
        uninstall.RepoUninstaller(
            repo_root=repo, dry_run=False, purge_memory=False
        ).run()

        after = subprocess.run(
            ["git", "-C", str(repo), "config", "--get", "core.hooksPath"],
            check=False,
            capture_output=True,
            text=True,
        )
        assert after.returncode != 0, "core.hooksPath should be unset"

    def test_leaves_memory_dir_without_purge_flag(self, tmp_path: Path):
        repo = tmp_path / "repo"
        repo.mkdir()
        _init_git_repo(repo)
        subprocess.run(
            [
                sys.executable,
                str(SCRIPT_DIR / "bootstrap-repo.py"),
                "--repo-root",
                str(repo),
            ],
            check=True,
            capture_output=True,
            env={**os.environ, "PYTHONPATH": str(SCRIPT_DIR)},
        )
        memory_dir = repo / ".agents" / "memory"
        assert memory_dir.exists()

        uninstall = _load_uninstall_module()
        uninstall.RepoUninstaller(
            repo_root=repo, dry_run=False, purge_memory=False
        ).run()

        assert memory_dir.exists(), ".agents/memory must survive without --purge-memory"

    def test_dry_run_does_not_mutate_anything(self, tmp_path: Path):
        repo = tmp_path / "repo"
        repo.mkdir()
        _init_git_repo(repo)
        subprocess.run(
            [
                sys.executable,
                str(SCRIPT_DIR / "bootstrap-repo.py"),
                "--repo-root",
                str(repo),
            ],
            check=True,
            capture_output=True,
            env={**os.environ, "PYTHONPATH": str(SCRIPT_DIR)},
        )
        before = sorted(p.relative_to(repo) for p in repo.rglob("*") if ".git/" not in str(p) + "/")

        uninstall = _load_uninstall_module()
        uninstall.RepoUninstaller(
            repo_root=repo, dry_run=True, purge_memory=False
        ).run()

        after = sorted(p.relative_to(repo) for p in repo.rglob("*") if ".git/" not in str(p) + "/")
        assert before == after


# ---------------------------------------------------------------------------
# CLI entry-point tests (invoke uninstall.py as a subprocess in a tmp env)
# ---------------------------------------------------------------------------


class TestCliEntryPoint:
    def test_purge_memory_requires_repo_flag(self, tmp_path: Path):
        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT_DIR / "uninstall.py"),
                "--purge-memory",
                "--dry-run",
            ],
            check=False,
            capture_output=True,
            text=True,
            cwd=str(tmp_path),
        )
        assert result.returncode == 1
        assert "--purge-memory only applies to --repo" in result.stderr

    def test_repo_flag_requires_git_repo(self, tmp_path: Path):
        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT_DIR / "uninstall.py"),
                "--repo",
                "--dry-run",
            ],
            check=False,
            capture_output=True,
            text=True,
            cwd=str(tmp_path),
        )
        assert result.returncode == 1
        assert "must be run inside" in result.stderr or "requires running inside" in result.stderr
