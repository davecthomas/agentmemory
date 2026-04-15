import importlib.util
import io
import json
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

SCRIPT_DIR = Path(__file__).parent.parent.resolve()


def load_script_module(script_path: Path, str_module_name: str) -> ModuleType:
    """Load a Python script from disk as a module for direct helper-level testing.

    Args:
        script_path: Absolute path to the Python script file to import.
        str_module_name: Synthetic module name used for the imported script.

    Returns:
        ModuleType: Imported module object with the script's globals and functions.

    Raises:
        ImportError: Raised when the import spec or loader cannot be created.
    """
    str_script_parent: str = str(script_path.parent)
    bool_added_sys_path: bool = False
    if str_script_parent not in sys.path:
        sys.path.insert(0, str_script_parent)
        bool_added_sys_path = True
    try:
        module_spec = importlib.util.spec_from_file_location(
            str_module_name, script_path
        )
        if module_spec is None or module_spec.loader is None:
            raise ImportError(f"Could not load module spec for {script_path}")
        module = importlib.util.module_from_spec(module_spec)
        sys.modules[str_module_name] = module
        module_spec.loader.exec_module(module)
    finally:
        if bool_added_sys_path:
            sys.path.remove(str_script_parent)
    return module


def write_python_wrapper(path_wrapper: Path, path_source_script: Path) -> None:
    """Write a small executable wrapper that delegates to a source Python script.

    Args:
        path_wrapper: Installed helper path to create under the synthetic HOME tree.
        path_source_script: Real source script path inside the working repository.

    Returns:
        None: The wrapper is written in place and marked executable.
    """
    str_wrapper_text: str = "\n".join(
        [
            "#!/usr/bin/env python3",
            "import subprocess",
            "import sys",
            (
                "raise SystemExit(subprocess.run("
                f"[sys.executable, {str(path_source_script)!r}, *sys.argv[1:]], "
                "check=False).returncode)"
            ),
            "",
        ]
    )
    path_wrapper.write_text(str_wrapper_text, encoding="utf-8")
    path_wrapper.chmod(0o755)


def install_minimal_session_start_assets(home_dir: Path) -> None:
    """Create the minimal installed asset tree required by session-start.py tests.

    Args:
        home_dir: Synthetic HOME directory used by the temporary test runtime.

    Returns:
        None: The helper creates config, skill, state, and installed-script paths
            in place under the provided home directory.
    """
    path_shared_root: Path = home_dir / ".agent" / "shared-repo-memory"
    path_shared_root.mkdir(parents=True, exist_ok=True)
    path_bootstrap_wrapper: Path = path_shared_root / "bootstrap-repo.py"
    write_python_wrapper(path_bootstrap_wrapper, SCRIPT_DIR / "bootstrap-repo.py")
    path_pre_commit_guard_wrapper: Path = (
        path_shared_root / "pre-commit-memory-guard.py"
    )
    write_python_wrapper(
        path_pre_commit_guard_wrapper, SCRIPT_DIR / "pre-commit-memory-guard.py"
    )

    for str_helper_name in (
        "post-turn-notify.py",
        "rebuild-summary.py",
        "build-catchup.py",
        "promote-adr.py",
        "publish-checkpoint.py",
    ):
        path_helper: Path = path_shared_root / str_helper_name
        path_helper.write_text("# stub\n", encoding="utf-8")

    path_codex_root: Path = home_dir / ".codex"
    path_codex_root.mkdir(parents=True, exist_ok=True)
    (path_codex_root / "config.toml").write_text(
        "shared_repo_memory_configured = true\n",
        encoding="utf-8",
    )
    (path_codex_root / "skills" / "memory-writer").mkdir(parents=True, exist_ok=True)
    (path_codex_root / "skills" / "memory-checkpointer").mkdir(
        parents=True, exist_ok=True
    )
    (path_codex_root / "skills" / "adr-promoter").mkdir(parents=True, exist_ok=True)

    path_state_root: Path = home_dir / ".agent" / "state"
    path_state_root.mkdir(parents=True, exist_ok=True)
    (path_state_root / "shared_asset_refresh_state.json").write_text(
        json.dumps({"last_successful_refresh_at": "2026-03-31T00:00:00Z"}),
        encoding="utf-8",
    )


@pytest.fixture
def repo(tmp_path):
    """Sets up a temporary git repository for testing."""
    repo_dir = tmp_path / "test-repo"
    repo_dir.mkdir()

    # Initialize git
    subprocess.run(["git", "init", "-b", "main"], cwd=repo_dir, check=True)
    subprocess.run(
        ["git", "config", "user.name", "Test User"], cwd=repo_dir, check=True
    )
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"], cwd=repo_dir, check=True
    )

    # Mock global home directory so notify hook sees required files
    home_dir = tmp_path / "home"
    install_minimal_session_start_assets(home_dir)

    # Run bootstrap using sys.executable to ensure the correct Python version.
    env = os.environ.copy()
    env["HOME"] = str(home_dir)
    subprocess.run(
        [sys.executable, SCRIPT_DIR / "bootstrap-repo.py"],
        cwd=repo_dir,
        check=True,
        env=env,
    )
    subprocess.run(["git", "add", "."], cwd=repo_dir, check=True)
    subprocess.run(
        ["git", "commit", "-m", "bootstrap repo wiring"],
        cwd=repo_dir,
        check=True,
        env=env,
    )

    return repo_dir, home_dir


@pytest.fixture
def non_repo(tmp_path):
    work_dir = tmp_path / "not-a-repo"
    work_dir.mkdir()

    home_dir = tmp_path / "home"
    install_minimal_session_start_assets(home_dir)
    return work_dir, home_dir


def test_bootstrap_initializes_directories(repo):
    repo_dir, home_dir = repo
    str_gitignore_text: str = (repo_dir / ".gitignore").read_text(encoding="utf-8")
    str_pre_commit_text: str = (repo_dir / ".githooks" / "pre-commit").read_text(
        encoding="utf-8"
    )
    str_post_checkout_text: str = (repo_dir / ".githooks" / "post-checkout").read_text(
        encoding="utf-8"
    )
    assert (repo_dir / ".agents" / "memory").exists()
    assert (repo_dir / ".agents" / "memory" / "pending").is_dir()
    assert (repo_dir / ".agents" / "memory" / "state").is_dir()
    assert (repo_dir / ".codex" / "memory").is_symlink()
    assert (repo_dir / ".githooks" / "pre-commit").is_file()
    assert (repo_dir / ".githooks" / "post-checkout").is_file()
    assert (repo_dir / ".githooks" / "post-merge").is_file()
    assert (repo_dir / ".githooks" / "post-rewrite").is_file()

    result = subprocess.run(
        ["git", "config", "--get", "core.hooksPath"],
        cwd=repo_dir,
        capture_output=True,
        text=True,
    )
    assert ".githooks" in result.stdout
    assert "# agentmemory-managed local repo wiring and state" in str_gitignore_text
    assert "# Added by the agentmemory SessionStart/bootstrap flow." in (
        str_gitignore_text
    )
    assert ".githooks/" in str_gitignore_text
    assert ".agents/memory/pending/" in str_gitignore_text
    assert ".agents/memory/state/" in str_gitignore_text
    assert ".agents/memory/logs/" in str_gitignore_text
    assert ".agents/memory/.auto_bootstrap_running" in str_gitignore_text
    assert "# Generated by agentmemory v0.4.4." in str_pre_commit_text
    assert "This repo-local hook is created by the agentmemory SessionStart" in (
        str_pre_commit_text
    )
    assert "pre-commit-memory-guard.py" in str_pre_commit_text
    assert "project-pre-commit.sh" in str_pre_commit_text
    assert 'export AGENTMEMORY_RUNTIME_ID="pre-commit"' in str_pre_commit_text
    assert 'export AGENTMEMORY_RUNTIME_ID="git-hook"' in str_post_checkout_text
    assert "[runtime=git-hook][runtime-version=n/a]" in str_post_checkout_text


def test_post_turn_notify_creates_pending_shard_without_publish(repo):
    repo_dir, home_dir = repo

    # Stage a tracked file change so the meaningful-turn gate passes.
    tracked_file = repo_dir / "feature.py"
    tracked_file.write_text("# initial\n")
    subprocess.run(["git", "add", "feature.py"], cwd=repo_dir, check=True)

    payload = {
        "conversation_id": "test-thread",
        "turn_id": "test-turn-1",
        "prompt": "Record this durable repo decision in shared memory for future sessions.",
        "last_assistant_message": "Treated this as a durable repo decision.",
        "model": "gpt-5.4",
    }

    env = os.environ.copy()
    env["HOME"] = str(home_dir)

    # Run notify script with payload piped to stdin
    result = subprocess.run(
        [
            sys.executable,
            SCRIPT_DIR / "post-turn-notify.py",
            "--repo-root",
            str(repo_dir),
        ],
        cwd=repo_dir,
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        check=True,
        env=env,
    )

    dict_output = json.loads(result.stdout)
    assert dict_output["status"] == "ok"

    pending_dirs = list((repo_dir / ".agents" / "memory" / "pending").glob("202*"))
    assert len(pending_dirs) == 1
    pending_shards = list(pending_dirs[0].glob("*.md"))
    assert len(pending_shards) == 1
    str_pending_text: str = pending_shards[0].read_text(encoding="utf-8")
    assert "Record this durable repo decision" not in str_pending_text
    assert "Treated this as a durable repo decision" not in str_pending_text
    assert "Pending episode capture only." in str_pending_text
    assert 'workstream_scope: "thread"' in str_pending_text

    assert list((repo_dir / ".agents" / "memory" / "daily").glob("*/events/*.md")) == []
    assert list((repo_dir / ".agents" / "memory" / "daily").glob("*/summary.md")) == []

    staged_paths_result = subprocess.run(
        ["git", "diff", "--cached", "--name-only"],
        cwd=repo_dir,
        check=True,
        capture_output=True,
        text=True,
    )
    assert staged_paths_result.stdout.strip() == "feature.py"


def test_post_turn_notify_never_persists_conversation_text(repo):
    repo_dir, home_dir = repo

    tracked_file = repo_dir / "feature.py"
    tracked_file.write_text("# noisy update\n")
    subprocess.run(["git", "add", "feature.py"], cwd=repo_dir, check=True)

    payload = {
        "conversation_id": "test-thread",
        "turn_id": "test-turn-2",
        "prompt": "Please remember that I asked for a tiny cleanup here.",
        "last_assistant_message": "How's that look?",
        "model": "gpt-5.4",
    }

    env = os.environ.copy()
    env["HOME"] = str(home_dir)

    subprocess.run(
        [
            sys.executable,
            SCRIPT_DIR / "post-turn-notify.py",
            "--repo-root",
            str(repo_dir),
        ],
        cwd=repo_dir,
        input=json.dumps(payload),
        text=True,
        check=True,
        env=env,
    )

    pending_dir = next((repo_dir / ".agents" / "memory" / "pending").glob("202*"))
    shard_path = next(pending_dir.glob("*.md"))
    shard_text = shard_path.read_text(encoding="utf-8")

    assert "How's that look?" not in shard_text
    assert "Please remember that I asked for a tiny cleanup here." not in shard_text
    assert "Pending episode capture only." in shard_text
    assert "Await background episode evaluation" in shard_text
    assert list((repo_dir / ".agents" / "memory" / "daily").glob("*/summary.md")) == []


def test_post_turn_notify_noops_outside_git_repo(non_repo):
    work_dir, home_dir = non_repo

    env = os.environ.copy()
    env["HOME"] = str(home_dir)

    result = subprocess.run(
        [sys.executable, SCRIPT_DIR / "post-turn-notify.py"],
        cwd=work_dir,
        input=json.dumps({"hook_event_name": "AfterAgent", "prompt": "test"}),
        text=True,
        capture_output=True,
        check=True,
        env=env,
    )

    assert json.loads(result.stdout) == {
        "message": "current working directory is not inside a Git repository",
        "status": "noop",
    }
    assert not (work_dir / ".agents").exists()


def test_session_start_noops_outside_git_repo_with_json_stdout(non_repo):
    work_dir, home_dir = non_repo

    env = os.environ.copy()
    env["HOME"] = str(home_dir)

    result = subprocess.run(
        [sys.executable, SCRIPT_DIR / "session-start.py"],
        cwd=work_dir,
        input=json.dumps({"hook_event_name": "SessionStart"}),
        text=True,
        capture_output=True,
        check=True,
        env=env,
    )

    # session-start.py exits silently (no stdout) when not inside a git repo.
    assert result.stdout.strip() == ""
    assert "invalid JSON" not in result.stderr
    assert not (work_dir / ".agents").exists()


def test_session_start_releases_lock_when_auto_bootstrap_script_missing(
    repo, monkeypatch, tmp_path
):
    """Ensure the legacy auto-bootstrap fallback never leaves a stale lock behind.

    Args:
        repo: Pytest fixture returning the bootstrapped temporary repo and home path.
        monkeypatch: Pytest fixture used to control environment variables and module
            globals for this regression case.
        tmp_path: Temporary directory used to point __file__ at a location that does
            not contain auto-bootstrap.py.

    Returns:
        None: Assertions verify the fallback returns False and cleans up its lock.
    """
    repo_dir, home_dir = repo
    session_start_module = load_script_module(
        SCRIPT_DIR / "session-start.py", "session_start_test_module"
    )
    lock_path = repo_dir / ".agents" / "memory" / ".auto_bootstrap_running"
    fake_script_path = tmp_path / "fake-session-start.py"
    fake_script_path.write_text("# fake session-start path\n", encoding="utf-8")

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(session_start_module, "__file__", str(fake_script_path))

    spawned = session_start_module._spawn_auto_bootstrap(repo_dir)

    assert spawned is False
    assert not lock_path.exists()


def test_session_start_does_not_fallback_to_claude_for_codex_bootstrap(
    repo, monkeypatch
):
    """Verify that Codex background bootstrap never silently falls back to Claude.

    Args:
        repo: Pytest fixture returning the bootstrapped temporary repo and home path.
        monkeypatch: Pytest fixture used to replace adapter resolution and
            Claude fallback behavior during the regression check.

    Returns:
        None: Assertions verify background bootstrap is skipped, the lock is
            released, and bootstrap.log records a manual-bootstrap message.
    """
    repo_dir, home_dir = repo
    session_start_module = load_script_module(
        SCRIPT_DIR / "session-start.py", "session_start_codex_bootstrap_test_module"
    )

    path_skill_dir: Path = home_dir / ".agent" / "skills" / "memory-bootstrap"
    path_skill_dir.mkdir(parents=True, exist_ok=True)
    (path_skill_dir / "SKILL.md").write_text(
        "# memory bootstrap skill\n", encoding="utf-8"
    )

    class FakeCodexAdapter:
        @staticmethod
        def agent_id() -> str:
            return "codex"

        @staticmethod
        def build_bootstrap_command(
            skill_content: str, task: str, repo_root: Path
        ) -> list[str] | None:
            del skill_content, task, repo_root
            return None

    def _unexpected_claude_fallback(*args: object, **kwargs: object) -> list[str]:
        raise AssertionError("SessionStart should not fall back to Claude bootstrap")

    monkeypatch.setattr(
        session_start_module, "detect_adapter", lambda: FakeCodexAdapter
    )
    monkeypatch.setattr(
        session_start_module, "runtime_provider_version", lambda _agent_id: "0.118.0"
    )

    class FakeClaudeAdapter:
        @staticmethod
        def build_bootstrap_command(*args: object, **kwargs: object) -> list[str]:
            return _unexpected_claude_fallback(*args, **kwargs)

    monkeypatch.setattr(
        session_start_module,
        "ClaudeAdapter",
        FakeClaudeAdapter,
        raising=False,
    )
    monkeypatch.setenv("HOME", str(home_dir))

    bool_spawned: bool = session_start_module._spawn_subagent_bootstrap(repo_dir)

    assert bool_spawned is False
    path_lock: Path = repo_dir / ".agents" / "memory" / ".auto_bootstrap_running"
    assert not path_lock.exists()
    path_bootstrap_log: Path = (
        repo_dir / ".agents" / "memory" / "logs" / "bootstrap.log"
    )
    str_bootstrap_log: str = path_bootstrap_log.read_text(encoding="utf-8")
    assert "[agentmemory][version=0.4.4][runtime=codex][runtime-version=0.118.0]" in (
        str_bootstrap_log
    )
    assert "background bootstrap skipped" in str_bootstrap_log
    assert "/memory-bootstrap manually" in str_bootstrap_log


def test_agent_support_summary_marks_codex_session_start_only():
    """Verify the canonical support summary does not overstate Codex support.

    Returns:
        None: Assertions verify the summary explicitly marks Codex as
            SessionStart-only and keeps Claude and Gemini summaries present.
    """
    agent_support_module = load_script_module(
        SCRIPT_DIR / "agent_support.py", "agent_support_test_module"
    )

    list_str_summary_lines = agent_support_module.support_summary_lines()

    assert any("Claude Code:" in str_line for str_line in list_str_summary_lines)
    assert any("Gemini CLI:" in str_line for str_line in list_str_summary_lines)
    assert any(
        "Codex CLI:" in str_line and "SessionStart" in str_line
        for str_line in list_str_summary_lines
    )


def test_promote_adr_creates_adr_and_index(repo):
    repo_dir, home_dir = repo

    # Setup: Create a mock decision shard
    day_dir = repo_dir / ".agents" / "memory" / "daily" / "2026-03-30"
    events_dir = day_dir / "events"
    events_dir.mkdir(parents=True, exist_ok=True)
    shard_path = events_dir / "test-shard.md"

    shard_content = """---
timestamp: "2026-03-30T12:00:00Z"
author: "test-user"
branch: "main"
thread_id: "thread-test"
turn_id: "turn-test"
decision_candidate: true
ai_generated: true
ai_model: "gpt-5.4"
ai_tool: "codex"
ai_surface: "codex-cli"
ai_executor: "local-agent"
related_adrs:
files_touched:
  - "scripts/shared-repo-memory/test/test_memory_system.py"
verification:
  - "Fixture shard created for ADR promotion test."
---
## Why
Because testing is critical.
## What changed
Added automated tests.
"""
    shard_path.write_text(shard_content)

    env = os.environ.copy()
    env["HOME"] = str(home_dir)

    # Run promote-adr.py
    subprocess.run(
        [
            sys.executable,
            SCRIPT_DIR / "promote-adr.py",
            "--repo-root",
            str(repo_dir),
            str(shard_path),
        ],
        cwd=repo_dir,
        check=True,
        env=env,
    )

    adr_dir = repo_dir / ".agents" / "memory" / "adr"
    adrs = list(adr_dir.glob("ADR-*.md"))
    assert len(adrs) == 1

    index_path = adr_dir / "INDEX.md"
    assert index_path.exists()
    assert "ADR-0001" in index_path.read_text()


def test_build_catchup_generates_file(repo):
    repo_dir, home_dir = repo

    # Setup: Create a mock shard and summary with a real Markdown target.
    day_dir = repo_dir / ".agents" / "memory" / "daily" / "2026-03-30"
    day_dir.mkdir(parents=True, exist_ok=True)
    events_dir = day_dir / "events"
    events_dir.mkdir(parents=True, exist_ok=True)
    shard_path = (
        events_dir
        / "2026-03-30T12-00-00Z--test-user--thread_test-thread--turn_test-turn.md"
    )
    shard_path.write_text("# mock shard\n", encoding="utf-8")
    summary_path = day_dir / "summary.md"
    summary_path.write_text(
        "\n".join(
            [
                "# 2026-03-30 summary",
                "",
                "## Active blockers",
                "",
                "- None",
                "",
                "## Next likely steps",
                "",
                "- Review the generated shard.",
                "",
                "## Relevant event shards",
                "",
                "- [2026-03-30 12:00:00 UTC by test-user](events/2026-03-30T12-00-00Z--test-user--thread_test-thread--turn_test-turn.md)",
                "",
            ]
        ),
        encoding="utf-8",
    )

    env = os.environ.copy()
    env["HOME"] = str(home_dir)

    # Run build-catchup.py
    result: subprocess.CompletedProcess[str] = subprocess.run(
        [
            sys.executable,
            SCRIPT_DIR / "build-catchup.py",
            "--repo-root",
            str(repo_dir),
            "--trigger",
            "post-checkout",
        ],
        cwd=repo_dir,
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )

    catchup_path = repo_dir / ".codex" / "local" / "catchup.md"
    assert catchup_path.exists()
    catchup_text = catchup_path.read_text()
    assert "# Local catch-up" in catchup_text
    assert "2026-03-30" in catchup_text
    assert (
        "events/2026-03-30T12-00-00Z--test-user--thread_test-thread--turn_test-turn.md"
        in catchup_text
    )
    assert (
        "[agentmemory][version=0.4.4][runtime=git-hook][runtime-version=n/a] "
        "catch-up rebuilt via post-checkout"
    ) in result.stderr


def test_runtime_log_prefix_script_uses_installer_runtime_env(repo):
    """Verify the shell prefix helper emits explicit installer runtime metadata.

    Args:
        repo: Pytest fixture returning the bootstrapped temporary repo and home path.

    Returns:
        None: Assertions verify the shell helper no longer falls back to
            `unknown` and instead uses the provided installer runtime env.
    """
    repo_dir, _home_dir = repo

    env: dict[str, str] = os.environ.copy()
    env["AGENTMEMORY_RUNTIME_ID"] = "installer"
    env["AGENTMEMORY_RUNTIME_VERSION"] = "n/a"

    result: subprocess.CompletedProcess[str] = subprocess.run(
        [SCRIPT_DIR / "runtime-log-prefix.sh"],
        cwd=repo_dir,
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )

    assert (
        result.stdout.strip()
        == "[agentmemory][version=0.4.4][runtime=installer][runtime-version=n/a]"
    )


def test_prompt_guard_injects_one_time_memory_bootstrap_nudge(repo):
    repo_dir, home_dir = repo

    env = os.environ.copy()
    env["HOME"] = str(home_dir)
    payload = {"session_id": "prompt-guard-test", "hook_event_name": "UserPromptSubmit"}

    first_result = subprocess.run(
        [sys.executable, SCRIPT_DIR / "prompt-guard.py"],
        cwd=repo_dir,
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        check=True,
        env=env,
    )
    second_result = subprocess.run(
        [sys.executable, SCRIPT_DIR / "prompt-guard.py"],
        cwd=repo_dir,
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        check=True,
        env=env,
    )

    assert "`memory-bootstrap` skill" in first_result.stdout
    assert second_result.stdout.strip() == ""


def test_post_turn_notify_writes_checkpoint_context_without_conversation_text(repo):
    """Verify that post-turn-notify writes a privacy-safe checkpoint context.

    This test installs a temporary memory-checkpointer skill and a stub
    `claude` executable so `_spawn_checkpoint_evaluation()` succeeds. The stub
    exits without calling publish-checkpoint.py, which leaves the local-only
    context file in place long enough to verify its contents deterministically.
    """
    repo_dir, home_dir = repo

    tracked_file = repo_dir / "api.py"
    tracked_file.write_text("# new API module\n")
    subprocess.run(["git", "add", "api.py"], cwd=repo_dir, check=True)

    path_skill_dir: Path = home_dir / ".agent" / "skills" / "memory-checkpointer"
    path_skill_dir.mkdir(parents=True, exist_ok=True)
    (path_skill_dir / "SKILL.md").write_text(
        "Evaluate episode checkpoint bundles.", encoding="utf-8"
    )

    path_bin_dir: Path = home_dir / "bin"
    path_bin_dir.mkdir(parents=True, exist_ok=True)
    path_claude_stub: Path = path_bin_dir / "claude"
    path_claude_stub.write_text(
        "\n".join(
            (
                "#!/usr/bin/env python3",
                "raise SystemExit(0)",
                "",
            )
        ),
        encoding="utf-8",
    )
    path_claude_stub.chmod(0o755)

    payload = {
        "conversation_id": "enrich-test-thread",
        "turn_id": "enrich-test-turn",
        "prompt": "Create the API module with authentication middleware.",
        "last_assistant_message": (
            "I created api.py with JWT-based authentication middleware. "
            "This follows the adapter pattern established in the refactor "
            "to keep auth logic decoupled from route handlers."
        ),
        "model": "claude-opus-4-6",
    }

    env = os.environ.copy()
    env["HOME"] = str(home_dir)
    env["PATH"] = f"{path_bin_dir}{os.pathsep}{env['PATH']}"

    result = subprocess.run(
        [
            sys.executable,
            SCRIPT_DIR / "post-turn-notify.py",
            "--repo-root",
            str(repo_dir),
        ],
        cwd=repo_dir,
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        check=True,
        env=env,
    )

    # Shard should be written successfully.
    output = json.loads(result.stdout)
    assert output["status"] == "ok"

    # The checkpoint context must exist with the expected publish metadata until
    # publish-checkpoint.py consumes it.
    context_dir = repo_dir / ".agents" / "memory" / "state" / "checkpoint-context"
    list_path_context_files: list[Path] = list(context_dir.glob(".checkpoint-*.json"))
    assert len(list_path_context_files) == 1
    dict_context_data: dict[str, object] = json.loads(
        list_path_context_files[0].read_text(encoding="utf-8")
    )
    assert "assistant_text" not in dict_context_data
    assert "prompt" not in dict_context_data
    assert dict_context_data["files_touched"] == ["api.py"]
    assert str(dict_context_data["published_shard_path"]).endswith(".md")
    assert dict_context_data["workstream_scope"] == "thread"
    assert dict_context_data["episode_scope"] == "thread"
    assert dict_context_data["episode_member_count"] == 1
    assert str(dict_context_data["episode_manifest_path"]).endswith(".json")
    list_dict_bundle: list[dict[str, object]] = dict_context_data["pending_bundle"]
    assert len(list_dict_bundle) == 1
    assert list_dict_bundle[0]["files_touched"] == ["api.py"]
    assert list_dict_bundle[0]["design_docs_touched"] == []
    path_episode_manifest: Path = Path(str(dict_context_data["episode_manifest_path"]))
    assert path_episode_manifest.exists()

    # The pending shard should exist without direct prompt or assistant content.
    pending_dirs = list((repo_dir / ".agents" / "memory" / "pending").glob("202*"))
    assert len(pending_dirs) == 1
    shards = list(pending_dirs[0].glob("*.md"))
    assert len(shards) == 1
    shard_text = shards[0].read_text(encoding="utf-8")
    assert "Create the API module" not in shard_text
    assert payload["last_assistant_message"] not in shard_text
    assert "Pending episode capture only." in shard_text

    dict_local_metadata: dict[str, object] = json.loads(
        (repo_dir / ".codex" / "local" / "last-notify-metadata.json").read_text(
            encoding="utf-8"
        )
    )
    assert dict_local_metadata["files_touched"] == ["api.py"]
    assert "prompt" not in dict_local_metadata
    assert "assistant_text" not in dict_local_metadata
    assert list((repo_dir / ".agents" / "memory" / "daily").glob("*/events/*.md")) == []


def test_post_turn_notify_contextless_turn_stays_pending_only(repo):
    """Verify that a file-changing turn without semantic context never publishes a shard.

    This regression covers the Codex manual-wrapper failure mode where the hook
    payload can be effectively empty. The system should keep only a pending raw
    shard and must not publish or stage a durable daily event shard.
    """
    repo_dir, home_dir = repo

    tracked_file = repo_dir / "contextless.py"
    tracked_file.write_text("# contextless change\n", encoding="utf-8")
    subprocess.run(["git", "add", "contextless.py"], cwd=repo_dir, check=True)

    env = os.environ.copy()
    env["HOME"] = str(home_dir)

    result = subprocess.run(
        [
            sys.executable,
            SCRIPT_DIR / "post-turn-notify.py",
            "--repo-root",
            str(repo_dir),
        ],
        cwd=repo_dir,
        input=json.dumps({"conversation_id": "empty-thread", "turn_id": "empty-turn"}),
        text=True,
        capture_output=True,
        check=True,
        env=env,
    )

    output = json.loads(result.stdout)
    assert output["status"] == "ok"

    pending_dirs = list((repo_dir / ".agents" / "memory" / "pending").glob("202*"))
    assert len(pending_dirs) == 1
    assert len(list(pending_dirs[0].glob("*.md"))) == 1
    assert list((repo_dir / ".agents" / "memory" / "daily").glob("*/events/*.md")) == []
    assert list((repo_dir / ".agents" / "memory" / "daily").glob("*/summary.md")) == []

    trace_path = home_dir / ".agent" / "state" / "shared-repo-memory-hook-trace.jsonl"
    dict_trace_payload = json.loads(
        trace_path.read_text(encoding="utf-8").splitlines()[-1]
    )
    assert dict_trace_payload["checkpoint_spawned"] is False


def test_episode_graph_clusters_related_captures_but_separates_same_branch_noise(
    repo,
):
    """Verify that the episode graph prefers strong repo-grounded associations.

    Args:
        repo: Pytest fixture returning the bootstrapped temporary repo and home path.

    Returns:
        None: Assertions verify that related branch-scoped captures cluster
            together while unrelated same-branch noise remains outside the
            active episode manifest.
    """
    repo_dir, _home_dir = repo

    episode_graph_module = load_script_module(
        SCRIPT_DIR / "episode_graph.py", "episode_graph_test_module"
    )
    path_pending_dir: Path = repo_dir / ".agents" / "memory" / "pending" / "2026-04-08"
    path_pending_dir.mkdir(parents=True, exist_ok=True)

    path_auth_design_capture: Path = (
        path_pending_dir / "2026-04-08T10-00-00Z--test--thread_branch-main--turn_t1.md"
    )
    path_auth_design_capture.write_text(
        "\n".join(
            [
                "---",
                'timestamp: "2026-04-08T10:00:00Z"',
                'author: "test"',
                'branch: "main"',
                'thread_id: "generated-branch-main"',
                'turn_id: "t1"',
                'workstream_id: "branch-main"',
                'workstream_scope: "branch"',
                "decision_candidate: false",
                "enriched: false",
                "ai_generated: true",
                'ai_model: "gpt-5.4"',
                'ai_tool: "codex"',
                'ai_surface: "codex-cli"',
                'ai_executor: "local-agent"',
                "related_adrs:",
                "files_touched:",
                '  - "src/auth/service.py"',
                "design_docs_touched:",
                '  - "docs/auth-design.md"',
                'diff_summary: "1 file changed, 18 insertions(+)"',
                "verification:",
                '  - "git diff: 1 file changed, 18 insertions(+)"',
                "---",
                "",
                "## Why",
                "",
                "- Pending episode capture only.",
                "",
                "## What changed",
                "",
                "- Touched src/auth/service.py",
                "",
                "## Evidence",
                "",
                "- design doc touched: docs/auth-design.md",
                "",
                "## Next",
                "",
                "- Await background episode evaluation before publishing durable memory.",
                "",
            ]
        ),
        encoding="utf-8",
    )

    path_auth_validation_capture: Path = (
        path_pending_dir / "2026-04-08T10-10-00Z--test--thread_branch-main--turn_t2.md"
    )
    path_auth_validation_capture.write_text(
        "\n".join(
            [
                "---",
                'timestamp: "2026-04-08T10:10:00Z"',
                'author: "test"',
                'branch: "main"',
                'thread_id: "generated-branch-main"',
                'turn_id: "t2"',
                'workstream_id: "branch-main"',
                'workstream_scope: "branch"',
                "decision_candidate: false",
                "enriched: false",
                "ai_generated: true",
                'ai_model: "gpt-5.4"',
                'ai_tool: "codex"',
                'ai_surface: "codex-cli"',
                'ai_executor: "local-agent"',
                "related_adrs:",
                "files_touched:",
                '  - "src/auth/service.py"',
                '  - "tests/test_auth_service.py"',
                "design_docs_touched:",
                '  - "docs/auth-design.md"',
                'diff_summary: "2 files changed, 34 insertions(+)"',
                "verification:",
                '  - "git diff: 2 files changed, 34 insertions(+)"',
                "---",
                "",
                "## Why",
                "",
                "- Pending episode capture only.",
                "",
                "## What changed",
                "",
                "- Touched src/auth/service.py",
                "- Touched tests/test_auth_service.py",
                "",
                "## Evidence",
                "",
                "- design doc touched: docs/auth-design.md",
                "",
                "## Next",
                "",
                "- Await background episode evaluation before publishing durable memory.",
                "",
            ]
        ),
        encoding="utf-8",
    )

    path_cleanup_capture: Path = (
        path_pending_dir / "2026-04-08T10-12-00Z--test--thread_branch-main--turn_t3.md"
    )
    path_cleanup_capture.write_text(
        "\n".join(
            [
                "---",
                'timestamp: "2026-04-08T10:12:00Z"',
                'author: "test"',
                'branch: "main"',
                'thread_id: "generated-branch-main"',
                'turn_id: "t3"',
                'workstream_id: "branch-main"',
                'workstream_scope: "branch"',
                "decision_candidate: false",
                "enriched: false",
                "ai_generated: true",
                'ai_model: "gpt-5.4"',
                'ai_tool: "codex"',
                'ai_surface: "codex-cli"',
                'ai_executor: "local-agent"',
                "related_adrs:",
                "files_touched:",
                '  - "README.md"',
                "design_docs_touched:",
                'diff_summary: "1 file changed, 3 insertions(+)"',
                "verification:",
                '  - "git diff: 1 file changed, 3 insertions(+)"',
                "---",
                "",
                "## Why",
                "",
                "- Pending episode capture only.",
                "",
                "## What changed",
                "",
                "- Touched README.md",
                "",
                "## Evidence",
                "",
                "- git diff: 1 file changed, 3 insertions(+)",
                "",
                "## Next",
                "",
                "- Await background episode evaluation before publishing durable memory.",
                "",
            ]
        ),
        encoding="utf-8",
    )

    dict_manifest: dict[str, object] = episode_graph_module.rebuild_episode_graph(
        repo_dir, path_auth_validation_capture
    )

    list_str_member_paths: list[str] = list(dict_manifest["member_pending_shard_paths"])
    assert str(path_auth_design_capture) in list_str_member_paths
    assert str(path_auth_validation_capture) in list_str_member_paths
    assert str(path_cleanup_capture) not in list_str_member_paths
    assert dict_manifest["episode_scope"] == "branch"
    assert dict_manifest["member_count"] == 2
    path_manifest: Path = Path(str(dict_manifest["manifest_path"]))
    assert path_manifest.exists()

    dict_manifest_payload: dict[str, object] = json.loads(
        path_manifest.read_text(encoding="utf-8")
    )
    assert dict_manifest_payload["member_count"] == 2
    assert "docs/auth-design.md" in json.dumps(dict_manifest_payload)


def test_episode_graph_thread_episode_id_ignores_branch_scoped_thread_ids() -> None:
    """Verify thread-scoped episode ids ignore branch fallback thread markers.

    Returns:
        None: Assertions verify that a thread-scoped cluster id is derived only
            from nodes whose `workstream_scope` is `thread`.
    """
    episode_graph_module = load_script_module(
        SCRIPT_DIR / "episode_graph.py", "episode_graph_thread_id_test_module"
    )

    list_dict_cluster_nodes: list[dict[str, object]] = [
        {
            "path": "/tmp/thread-a.md",
            "thread_id": "runtime-thread-42",
            "workstream_scope": "thread",
            "branch": "feature/episode-graph",
            "timestamp": "2026-04-08T10:00:00Z",
            "turn_id": "turn-a",
            "issue_ids": [],
        },
        {
            "path": "/tmp/thread-b.md",
            "thread_id": "runtime-thread-42",
            "workstream_scope": "thread",
            "branch": "feature/episode-graph",
            "timestamp": "2026-04-08T10:05:00Z",
            "turn_id": "turn-b",
            "issue_ids": [],
        },
        {
            "path": "/tmp/branch-fallback.md",
            "thread_id": "branch-generated-aaa",
            "workstream_scope": "branch",
            "branch": "feature/episode-graph",
            "timestamp": "2026-04-08T10:06:00Z",
            "turn_id": "turn-c",
            "issue_ids": [],
        },
    ]

    str_episode_scope: str = episode_graph_module._episode_scope(
        list_dict_cluster_nodes
    )
    str_episode_id: str = episode_graph_module._episode_id(list_dict_cluster_nodes)

    assert str_episode_scope == "thread"
    assert str_episode_id == "episode-thread-runtime-thread-42"


def test_post_turn_notify_detects_design_doc_changes(repo):
    """Verify that post-turn-notify identifies design doc changes in files_touched
    and logs them in the hook trace.
    """
    repo_dir, home_dir = repo

    # Create a design doc so it appears in tracked changed files.
    docs_dir = repo_dir / "docs"
    docs_dir.mkdir(exist_ok=True)
    design_doc = docs_dir / "api-design.md"
    design_doc.write_text("# API Design\n\n## Decision: Use REST over GraphQL\n")
    subprocess.run(["git", "add", "docs/api-design.md"], cwd=repo_dir, check=True)

    payload = {
        "conversation_id": "design-doc-test-thread",
        "turn_id": "design-doc-test-turn",
        "prompt": "Write the API design document.",
        "last_assistant_message": "Created the API design doc with REST decision.",
        "model": "claude-opus-4-6",
    }

    env = os.environ.copy()
    env["HOME"] = str(home_dir)

    result = subprocess.run(
        [
            sys.executable,
            SCRIPT_DIR / "post-turn-notify.py",
            "--repo-root",
            str(repo_dir),
        ],
        cwd=repo_dir,
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        check=True,
        env=env,
    )

    output = json.loads(result.stdout)
    assert output["status"] == "ok"

    trace_path = home_dir / ".agent" / "state" / "shared-repo-memory-hook-trace.jsonl"
    list_str_trace_lines = trace_path.read_text(encoding="utf-8").splitlines()
    dict_trace_payload = json.loads(list_str_trace_lines[-1])
    assert dict_trace_payload["design_docs_touched"] == ["docs/api-design.md"]

    # Verify the pending shard was written while the durable daily namespace stays empty.
    pending_dirs = list((repo_dir / ".agents" / "memory" / "pending").glob("202*"))
    assert len(pending_dirs) == 1
    assert len(list(pending_dirs[0].glob("*.md"))) == 1
    assert list((repo_dir / ".agents" / "memory" / "daily").glob("*/events/*.md")) == []


def test_post_turn_notify_tolerates_episode_graph_io_failure(
    repo, monkeypatch, capsys
) -> None:
    """Verify episode-graph I/O failures do not crash the notify hook.

    Args:
        repo: Pytest fixture returning the bootstrapped temporary repo and home path.
        monkeypatch: Pytest fixture used to replace adapter and graph behavior.
        capsys: Pytest fixture used to capture stdout and stderr for assertions.

    Returns:
        None: Assertions verify the hook still emits a success payload, writes a
            pending capture, and logs the graph rebuild failure as non-fatal.
    """
    repo_dir, home_dir = repo
    post_turn_notify_module = load_script_module(
        SCRIPT_DIR / "post-turn-notify.py", "post_turn_notify_io_failure_test_module"
    )

    path_feature_file: Path = repo_dir / "feature.py"
    path_feature_file.write_text("print('hello')\n", encoding="utf-8")

    class FakeAdapter:
        @staticmethod
        def agent_id() -> str:
            return "codex"

        @staticmethod
        def normalize_hook_request(payload: dict[str, object]) -> SimpleNamespace:
            del payload
            namespace_request: SimpleNamespace = SimpleNamespace(
                cwd=None,
                thread_id="thread-episode-io",
                turn_id="turn-episode-io",
                hook_event="AfterAgent",
                session_id="session-episode-io",
                model="gpt-5.4",
            )
            return namespace_request

        @staticmethod
        def resolve_model(payload: dict[str, object]) -> str:
            del payload
            return "gpt-5.4"

        @staticmethod
        def shard_attribution() -> SimpleNamespace:
            namespace_attribution: SimpleNamespace = SimpleNamespace(
                ai_tool="codex",
                ai_surface="codex-app",
                default_model="gpt-5.4",
            )
            return namespace_attribution

        @staticmethod
        def render_hook_response(response: object) -> str:
            str_rendered_response: str = json.dumps(
                {
                    "status": getattr(response, "status"),
                    "message": getattr(response, "message"),
                    **getattr(response, "extra"),
                }
            )
            return str_rendered_response

    monkeypatch.setenv("HOME", str(home_dir))
    monkeypatch.setattr(post_turn_notify_module, "detect_adapter", lambda: FakeAdapter)
    monkeypatch.setattr(
        post_turn_notify_module,
        "detect_adapter_from_hook_event",
        lambda _hook_event: FakeAdapter,
    )
    monkeypatch.setattr(
        post_turn_notify_module,
        "rebuild_episode_graph",
        lambda _repo_root, _path_pending_shard: (_ for _ in ()).throw(
            OSError("synthetic episode-graph write failure")
        ),
    )
    monkeypatch.setattr(
        sys,
        "stdin",
        io.StringIO(json.dumps({"hookEventName": "AfterAgent", "model": "gpt-5.4"})),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "post-turn-notify.py",
            "--repo-root",
            str(repo_dir),
        ],
    )

    int_result: int = post_turn_notify_module.main()
    captured = capsys.readouterr()
    dict_output: dict[str, object] = json.loads(captured.out.strip())

    assert int_result == 0
    assert dict_output["status"] == "ok"
    list_path_pending_shards: list[Path] = sorted(
        (repo_dir / ".agents" / "memory" / "pending").glob("*/*.md")
    )
    assert len(list_path_pending_shards) == 1
    assert "failed to rebuild episode graph" in captured.err
    assert "synthetic episode-graph write failure" in captured.err


def test_post_turn_notify_captures_untracked_design_doc_only(repo):
    """Verify that a newly created untracked design doc is still a file-changing turn.

    Args:
        repo: Pytest fixture returning the bootstrapped temporary repo and home path.

    Returns:
        None: Assertions verify the untracked design doc produces a shard and
            reaches the ADR inspection trigger list.
    """
    repo_dir, home_dir = repo

    docs_dir = repo_dir / "docs"
    docs_dir.mkdir(exist_ok=True)
    design_doc = docs_dir / "untracked-design.md"
    design_doc.write_text(
        "# API Design\n\n## Decision\n\nPrefer REST over GraphQL.\n",
        encoding="utf-8",
    )

    payload = {
        "conversation_id": "untracked-design-thread",
        "turn_id": "untracked-design-turn",
        "prompt": "Write the new API design document.",
        "last_assistant_message": "Created docs/untracked-design.md with the API decision.",
        "model": "claude-opus-4-6",
    }

    env = os.environ.copy()
    env["HOME"] = str(home_dir)

    result = subprocess.run(
        [
            sys.executable,
            SCRIPT_DIR / "post-turn-notify.py",
            "--repo-root",
            str(repo_dir),
        ],
        cwd=repo_dir,
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        check=True,
        env=env,
    )

    output = json.loads(result.stdout)
    assert output["status"] == "ok"

    trace_path = home_dir / ".agent" / "state" / "shared-repo-memory-hook-trace.jsonl"
    list_str_trace_lines = trace_path.read_text(encoding="utf-8").splitlines()
    dict_trace_payload = json.loads(list_str_trace_lines[-1])
    assert dict_trace_payload["design_docs_touched"] == ["docs/untracked-design.md"]
    assert "docs/untracked-design.md" in dict_trace_payload["files_touched"]

    pending_dirs = list((repo_dir / ".agents" / "memory" / "pending").glob("202*"))
    assert len(pending_dirs) == 1
    list_path_shards = list(pending_dirs[0].glob("*.md"))
    assert len(list_path_shards) == 1
    assert list((repo_dir / ".agents" / "memory" / "daily").glob("*/events/*.md")) == []


def test_pre_commit_hook_rejects_pending_raw_shards(repo):
    """Verify that the repo-installed pre-commit hook blocks staged pending shards.

    Args:
        repo: Pytest fixture returning the bootstrapped temporary repo and home path.

    Returns:
        None: Assertions verify that forcing a pending raw shard into the index
            causes `git commit` to fail before the commit is created.
    """
    repo_dir, home_dir = repo

    path_code_file: Path = repo_dir / "feature.py"
    path_code_file.write_text("# code change\n", encoding="utf-8")
    subprocess.run(["git", "add", "feature.py"], cwd=repo_dir, check=True)

    path_pending_shard: Path = (
        repo_dir / ".agents" / "memory" / "pending" / "2026-04-07" / "raw.md"
    )
    path_pending_shard.parent.mkdir(parents=True, exist_ok=True)
    path_pending_shard.write_text("pending raw shard\n", encoding="utf-8")
    subprocess.run(
        ["git", "add", "-f", str(path_pending_shard.relative_to(repo_dir))],
        cwd=repo_dir,
        check=True,
    )

    result = subprocess.run(
        ["git", "commit", "-m", "should fail"],
        cwd=repo_dir,
        check=False,
        capture_output=True,
        text=True,
        env={**os.environ.copy(), "HOME": str(home_dir)},
    )

    assert result.returncode != 0
    assert "pending raw shard" in f"{result.stdout}\n{result.stderr}"


def test_pre_commit_hook_rejects_episode_graph_state(repo):
    """Verify that the repo-installed pre-commit hook blocks derived graph state.

    Args:
        repo: Pytest fixture returning the bootstrapped temporary repo and home path.

    Returns:
        None: Assertions verify that staged episode-graph manifests are rejected
            before a commit can be created.
    """
    repo_dir, home_dir = repo

    path_code_file: Path = repo_dir / "feature.py"
    path_code_file.write_text("# code change\n", encoding="utf-8")
    subprocess.run(["git", "add", "feature.py"], cwd=repo_dir, check=True)

    path_episode_manifest: Path = (
        repo_dir
        / ".agents"
        / "memory"
        / "state"
        / "episode-graph"
        / "episodes"
        / "episode-fixture.json"
    )
    path_episode_manifest.parent.mkdir(parents=True, exist_ok=True)
    path_episode_manifest.write_text(
        json.dumps({"episode_id": "episode-fixture"}, indent=2) + "\n",
        encoding="utf-8",
    )
    subprocess.run(
        ["git", "add", "-f", str(path_episode_manifest.relative_to(repo_dir))],
        cwd=repo_dir,
        check=True,
    )

    result = subprocess.run(
        ["git", "commit", "-m", "should fail"],
        cwd=repo_dir,
        check=False,
        capture_output=True,
        text=True,
        env={**os.environ.copy(), "HOME": str(home_dir)},
    )

    assert result.returncode != 0
    assert "derived local episode-graph state" in f"{result.stdout}\n{result.stderr}"


def test_pre_commit_hook_rejects_unenriched_daily_shards(repo):
    """Verify that the pre-commit hook blocks staged daily shards marked raw.

    Args:
        repo: Pytest fixture returning the bootstrapped temporary repo and home path.

    Returns:
        None: Assertions verify that staged event shards containing
            `enriched: false` are rejected at commit time.
    """
    repo_dir, home_dir = repo

    path_code_file: Path = repo_dir / "feature.py"
    path_code_file.write_text("# code change\n", encoding="utf-8")
    subprocess.run(["git", "add", "feature.py"], cwd=repo_dir, check=True)

    path_day_dir: Path = repo_dir / ".agents" / "memory" / "daily" / "2026-04-07"
    path_event_dir: Path = path_day_dir / "events"
    path_event_dir.mkdir(parents=True, exist_ok=True)
    path_raw_shard: Path = (
        path_event_dir / "2026-04-07T12-00-00Z--test--thread_x--turn_y.md"
    )
    path_raw_shard.write_text(
        "\n".join(
            [
                "---",
                'timestamp: "2026-04-07T12:00:00Z"',
                'author: "test"',
                'branch: "main"',
                'thread_id: "thread_x"',
                'turn_id: "turn_y"',
                "decision_candidate: false",
                "enriched: false",
                "ai_generated: true",
                'ai_model: "gpt-5.4"',
                'ai_tool: "codex"',
                'ai_surface: "codex-cli"',
                'ai_executor: "local-agent"',
                "related_adrs:",
                "files_touched:",
                '  - "feature.py"',
                "verification:",
                '  - "raw shard fixture"',
                "---",
                "",
                "## Why",
                "",
                "- Raw fixture.",
                "",
                "## What changed",
                "",
                "- Raw fixture.",
                "",
                "## Evidence",
                "",
                "- Raw fixture.",
                "",
                "## Next",
                "",
                "- Raw fixture.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    subprocess.run(
        ["git", "add", str(path_raw_shard.relative_to(repo_dir))],
        cwd=repo_dir,
        check=True,
    )

    result = subprocess.run(
        ["git", "commit", "-m", "should fail"],
        cwd=repo_dir,
        check=False,
        capture_output=True,
        text=True,
        env={**os.environ.copy(), "HOME": str(home_dir)},
    )

    assert result.returncode != 0
    assert "enriched: false" in f"{result.stdout}\n{result.stderr}"


def test_pre_commit_hook_ignores_body_text_that_mentions_enriched_false(repo):
    """Verify that the pre-commit guard only inspects frontmatter enrichment state.

    Args:
        repo: Pytest fixture returning the bootstrapped temporary repo and home path.

    Returns:
        None: Assertions verify that quoted body text containing `enriched: false`
            does not trigger a false-positive commit rejection.
    """
    repo_dir, home_dir = repo

    path_code_file: Path = repo_dir / "feature.py"
    path_code_file.write_text("# code change\n", encoding="utf-8")
    subprocess.run(["git", "add", "feature.py"], cwd=repo_dir, check=True)

    path_day_dir: Path = repo_dir / ".agents" / "memory" / "daily" / "2026-04-07"
    path_event_dir: Path = path_day_dir / "events"
    path_event_dir.mkdir(parents=True, exist_ok=True)
    path_event_shard: Path = (
        path_event_dir / "2026-04-07T12-00-00Z--test--thread_x--turn_y.md"
    )
    path_event_shard.write_text(
        "\n".join(
            [
                "---",
                'timestamp: "2026-04-07T12:00:00Z"',
                'author: "test"',
                'branch: "main"',
                'thread_id: "thread_x"',
                'turn_id: "turn_y"',
                "decision_candidate: false",
                "enriched: true",
                "ai_generated: true",
                'ai_model: "gpt-5.4"',
                'ai_tool: "codex"',
                'ai_surface: "codex-cli"',
                'ai_executor: "local-agent"',
                "related_adrs:",
                "files_touched:",
                '  - "feature.py"',
                "verification:",
                '  - "quoted policy text"',
                "---",
                "",
                "## Why",
                "",
                "- Published fixture.",
                "",
                "## What changed",
                "",
                "- Added fixture shard.",
                "",
                "## Evidence",
                "",
                "- The quoted policy text says `enriched: false` for an unrelated legacy example.",
                "",
                "## Next",
                "",
                "- None.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    subprocess.run(
        ["git", "add", str(path_event_shard.relative_to(repo_dir))],
        cwd=repo_dir,
        check=True,
    )

    result = subprocess.run(
        ["git", "commit", "-m", "should pass"],
        cwd=repo_dir,
        check=False,
        capture_output=True,
        text=True,
        env={**os.environ.copy(), "HOME": str(home_dir)},
    )

    assert result.returncode == 0


def test_session_start_repairs_missing_gitignore_entries(repo):
    """Verify SessionStart re-runs bootstrap when required .gitignore entries drift.

    Args:
        repo: Pytest fixture returning the bootstrapped temporary repo and home path.

    Returns:
        None: Assertions verify SessionStart uses the installed bootstrap helper
            to restore the shared local-state ignore entries.
    """
    repo_dir, home_dir = repo

    path_gitignore = repo_dir / ".gitignore"
    str_gitignore = path_gitignore.read_text(encoding="utf-8")
    path_gitignore.write_text(
        str_gitignore.replace(".githooks/\n", "")
        .replace(".agents/memory/pending/\n", "")
        .replace(".agents/memory/state/\n", "")
        .replace(".agents/memory/logs/\n", "")
        .replace(".agents/memory/.auto_bootstrap_running\n", ""),
        encoding="utf-8",
    )

    day_dir = repo_dir / ".agents" / "memory" / "daily" / "2026-04-06"
    events_dir = day_dir / "events"
    events_dir.mkdir(parents=True, exist_ok=True)
    (events_dir / "fixture-shard.md").write_text(
        "\n".join(
            [
                "---",
                'timestamp: "2026-04-06T12:00:00Z"',
                'author: "test"',
                'branch: "main"',
                'thread_id: "fixture-thread"',
                'turn_id: "fixture-turn"',
                "decision_candidate: false",
                "enriched: false",
                "ai_generated: true",
                'ai_model: "gpt-5.4"',
                'ai_tool: "codex"',
                'ai_surface: "codex-cli"',
                'ai_executor: "local-agent"',
                "related_adrs:",
                "files_touched:",
                '  - "README.md"',
                "verification:",
                '  - "Fixture shard for SessionStart test."',
                "---",
                "",
                "## Why",
                "",
                "- Fixture shard for session-start.",
                "",
                "## What changed",
                "",
                "- Added fixture shard.",
                "",
                "## Evidence",
                "",
                "- Fixture evidence.",
                "",
                "## Next",
                "",
                "- None.",
                "",
            ]
        ),
        encoding="utf-8",
    )

    env = os.environ.copy()
    env["HOME"] = str(home_dir)

    result = subprocess.run(
        [sys.executable, SCRIPT_DIR / "session-start.py"],
        cwd=repo_dir,
        input=json.dumps({"hook_event_name": "SessionStart"}),
        text=True,
        capture_output=True,
        check=True,
        env=env,
    )

    assert "agentmemory" in result.stdout
    repaired_gitignore: str = path_gitignore.read_text(encoding="utf-8")
    assert "# agentmemory-managed local repo wiring and state" in repaired_gitignore
    assert ".githooks/" in repaired_gitignore
    assert ".agents/memory/pending/" in repaired_gitignore
    assert ".agents/memory/state/" in repaired_gitignore
    assert ".agents/memory/logs/" in repaired_gitignore
    assert ".agents/memory/.auto_bootstrap_running" in repaired_gitignore


def test_publish_checkpoint_publishes_trusted_thread_scoped_checkpoint(repo):
    """Verify that publish-checkpoint.py publishes one trusted thread checkpoint.

    Args:
        repo: Pytest fixture returning the bootstrapped temporary repo and home path.

    Returns:
        None: Assertions verify that a valid thread-scoped candidate publishes,
            rebuilds the daily summary, stages only durable artifacts, and
            deletes the consumed pending capture plus checkpoint context.
    """
    repo_dir, home_dir = repo

    path_pending_shard: Path = (
        repo_dir
        / ".agents"
        / "memory"
        / "pending"
        / "2026-04-08"
        / "2026-04-08T14-00-00Z--test--thread_auth-work--turn_t1.md"
    )
    path_pending_shard.parent.mkdir(parents=True, exist_ok=True)
    path_pending_shard.write_text(
        "\n".join(
            [
                "---",
                'timestamp: "2026-04-08T14:00:00Z"',
                'author: "test"',
                'branch: "main"',
                'thread_id: "auth-work"',
                'turn_id: "t1"',
                'workstream_id: "thread-auth-work"',
                'workstream_scope: "thread"',
                "decision_candidate: false",
                "enriched: false",
                "ai_generated: true",
                'ai_model: "claude-opus-4-6"',
                'ai_tool: "claude"',
                'ai_surface: "claude-code"',
                'ai_executor: "local-agent"',
                "related_adrs:",
                "files_touched:",
                '  - "api.py"',
                "design_docs_touched:",
                'diff_summary: "1 file changed, 24 insertions(+)"',
                "verification:",
                '  - "git diff: 1 file changed, 24 insertions(+)"',
                "---",
                "",
                "## Why",
                "",
                "- Pending episode capture only.",
                "",
                "## What changed",
                "",
                "- Touched api.py",
                "",
                "## Evidence",
                "",
                "- git diff: 1 file changed, 24 insertions(+)",
                "",
                "## Next",
                "",
                "- Await background checkpoint evaluation.",
                "",
            ]
        ),
        encoding="utf-8",
    )

    path_context_dir: Path = (
        repo_dir / ".agents" / "memory" / "state" / "checkpoint-context"
    )
    path_context_dir.mkdir(parents=True, exist_ok=True)
    path_context: Path = path_context_dir / ".checkpoint-t1.json"
    path_published_shard: Path = (
        repo_dir
        / ".agents"
        / "memory"
        / "daily"
        / "2026-04-08"
        / "events"
        / "2026-04-08T14-00-00Z--test--thread_auth-work--turn_t1.md"
    )
    dict_context: dict[str, object] = {
        "repo_root": str(repo_dir),
        "current_pending_shard": str(path_pending_shard),
        "pending_shard_paths": [str(path_pending_shard)],
        "pending_bundle": [
            {
                "path": str(path_pending_shard),
                "timestamp": "2026-04-08T14:00:00Z",
                "branch": "main",
                "thread_id": "auth-work",
                "turn_id": "t1",
                "workstream_id": "thread-auth-work",
                "workstream_scope": "thread",
                "files_touched": ["api.py"],
                "design_docs_touched": [],
                "verification": ["git diff: 1 file changed, 24 insertions(+)"],
                "diff_summary": "1 file changed, 24 insertions(+)",
            }
        ],
        "published_shard_path": str(path_published_shard),
        "workstream_id": "thread-auth-work",
        "workstream_scope": "thread",
        "episode_manifest_path": str(
            repo_dir
            / ".agents"
            / "memory"
            / "state"
            / "episode-graph"
            / "episodes"
            / "episode-thread-auth-work.json"
        ),
        "episode_id": "episode-thread-auth-work",
        "episode_scope": "thread",
        "episode_status": "active",
        "episode_member_count": 1,
        "secondary_candidate_episode_ids": [],
        "episode_primary_subsystem_hints": ["api.py"],
        "episode_cluster_edges": [],
        "branch": "main",
        "files_touched": ["api.py"],
        "design_docs_touched": [],
        "diff_summary": "1 file changed, 24 insertions(+)",
        "adr_index_path": str(repo_dir / ".agents" / "memory" / "adr" / "INDEX.md"),
        "recent_summary_paths": [],
    }
    path_context.write_text(json.dumps(dict_context, indent=2), encoding="utf-8")

    env: dict[str, str] = os.environ.copy()
    env["HOME"] = str(home_dir)

    subprocess.run(
        [
            sys.executable,
            SCRIPT_DIR / "publish-checkpoint.py",
            str(path_context),
            "--workstream-goal",
            (
                "Harden the shared-memory publication boundary so raw captures never "
                "become durable memory."
            ),
            "--subsystem-surface",
            (
                "The shared repo-memory post-turn pipeline, checkpoint publisher, "
                "and commit boundary."
            ),
            "--turn-outcome",
            (
                "Published a validated workstream checkpoint from the pending "
                "thread bundle."
            ),
            "--why",
            (
                "This checkpoint records the broader publication-hardening effort "
                "instead of preserving a one-turn diff fragment."
            ),
            "--what-changed",
            (
                "Validated the pending workstream bundle and published one durable "
                "checkpoint that future sessions can trust."
            ),
            "--evidence",
            (
                "The checkpoint validator accepted the bundle, rebuild-summary.py "
                "regenerated the daily summary, and the bundle grounded the change "
                "through api.py."
            ),
            "--next",
            "Extend the same publication rules to the remaining supported runtimes.",
            "--source-pending-shard",
            str(path_pending_shard),
        ],
        cwd=repo_dir,
        check=True,
        env=env,
    )

    str_published_text: str = path_published_shard.read_text(encoding="utf-8")
    assert 'workstream_id: "thread-auth-work"' in str_published_text
    assert 'episode_id: "episode-thread-auth-work"' in str_published_text
    assert 'episode_scope: "thread"' in str_published_text
    assert (
        'checkpoint_goal: "Harden the shared-memory publication boundary so raw captures never become durable memory."'
        in str_published_text
    )
    assert "enriched: true" in str_published_text
    assert "Published a validated workstream checkpoint" in str_published_text

    path_summary: Path = (
        repo_dir / ".agents" / "memory" / "daily" / "2026-04-08" / "summary.md"
    )
    assert path_summary.exists()
    assert not path_pending_shard.exists()
    assert not path_context.exists()

    result_staged_paths: subprocess.CompletedProcess[str] = subprocess.run(
        ["git", "diff", "--cached", "--name-only"],
        cwd=repo_dir,
        check=True,
        capture_output=True,
        text=True,
    )
    assert str(path_published_shard.relative_to(repo_dir)) in result_staged_paths.stdout
    assert str(path_summary.relative_to(repo_dir)) in result_staged_paths.stdout
    assert (
        str(path_pending_shard.relative_to(repo_dir)) not in result_staged_paths.stdout
    )


def test_publish_checkpoint_rejects_branch_scoped_single_capture(repo):
    """Verify that weak branch-scoped single captures fail closed.

    Args:
        repo: Pytest fixture returning the bootstrapped temporary repo and home path.

    Returns:
        None: Assertions verify that a branch-scoped single pending capture with
            no design-doc grounding is rejected and left pending.
    """
    repo_dir, home_dir = repo

    path_pending_shard: Path = (
        repo_dir
        / ".agents"
        / "memory"
        / "pending"
        / "2026-04-08"
        / "2026-04-08T15-00-00Z--test--thread_branch-main--turn_t2.md"
    )
    path_pending_shard.parent.mkdir(parents=True, exist_ok=True)
    path_pending_shard.write_text(
        "\n".join(
            [
                "---",
                'timestamp: "2026-04-08T15:00:00Z"',
                'author: "test"',
                'branch: "main"',
                'thread_id: "generated-thread"',
                'turn_id: "t2"',
                'workstream_id: "branch-main"',
                'workstream_scope: "branch"',
                "decision_candidate: false",
                "enriched: false",
                "ai_generated: true",
                'ai_model: "gpt-5.4"',
                'ai_tool: "codex"',
                'ai_surface: "codex-cli"',
                'ai_executor: "local-agent"',
                "related_adrs:",
                "files_touched:",
                '  - "contextless.py"',
                "design_docs_touched:",
                'diff_summary: "1 file changed, 2 insertions(+)"',
                "verification:",
                '  - "git diff: 1 file changed, 2 insertions(+)"',
                "---",
                "",
                "## Why",
                "",
                "- Pending episode capture only.",
                "",
                "## What changed",
                "",
                "- Touched contextless.py",
                "",
                "## Evidence",
                "",
                "- git diff: 1 file changed, 2 insertions(+)",
                "",
                "## Next",
                "",
                "- Await background checkpoint evaluation.",
                "",
            ]
        ),
        encoding="utf-8",
    )

    path_context_dir: Path = (
        repo_dir / ".agents" / "memory" / "state" / "checkpoint-context"
    )
    path_context_dir.mkdir(parents=True, exist_ok=True)
    path_context: Path = path_context_dir / ".checkpoint-t2.json"
    path_published_shard: Path = (
        repo_dir
        / ".agents"
        / "memory"
        / "daily"
        / "2026-04-08"
        / "events"
        / "2026-04-08T15-00-00Z--test--thread_branch-main--turn_t2.md"
    )
    path_context.write_text(
        json.dumps(
            {
                "repo_root": str(repo_dir),
                "current_pending_shard": str(path_pending_shard),
                "pending_shard_paths": [str(path_pending_shard)],
                "pending_bundle": [],
                "published_shard_path": str(path_published_shard),
                "workstream_id": "branch-main",
                "workstream_scope": "branch",
                "episode_manifest_path": str(
                    repo_dir
                    / ".agents"
                    / "memory"
                    / "state"
                    / "episode-graph"
                    / "episodes"
                    / "episode-branch-main-t2.json"
                ),
                "episode_id": "episode-branch-main-t2",
                "episode_scope": "branch",
                "episode_status": "active",
                "episode_member_count": 1,
                "secondary_candidate_episode_ids": [],
                "episode_primary_subsystem_hints": ["contextless.py"],
                "episode_cluster_edges": [],
                "branch": "main",
                "files_touched": ["contextless.py"],
                "design_docs_touched": [],
                "diff_summary": "1 file changed, 2 insertions(+)",
                "adr_index_path": str(
                    repo_dir / ".agents" / "memory" / "adr" / "INDEX.md"
                ),
                "recent_summary_paths": [],
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    env: dict[str, str] = os.environ.copy()
    env["HOME"] = str(home_dir)

    result_publish: subprocess.CompletedProcess[str] = subprocess.run(
        [
            sys.executable,
            SCRIPT_DIR / "publish-checkpoint.py",
            str(path_context),
            "--workstream-goal",
            "Advance the repo memory feature work.",
            "--subsystem-surface",
            "The repo memory pipeline.",
            "--turn-outcome",
            "Changed the implementation.",
            "--why",
            "This changed the implementation.",
            "--what-changed",
            "Updated contextless.py.",
            "--evidence",
            "Validator inspected contextless.py.",
            "--next",
            "Keep going.",
            "--source-pending-shard",
            str(path_pending_shard),
        ],
        cwd=repo_dir,
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )

    assert result_publish.returncode != 0
    assert "branch-scoped single-capture checkpoints require" in result_publish.stderr
    assert path_pending_shard.exists()
    assert path_context.exists()
    assert not path_published_shard.exists()


def test_publish_checkpoint_tolerates_invalid_episode_member_count(repo):
    """Verify malformed episode_member_count degrades to validation failure.

    Args:
        repo: Pytest fixture returning the bootstrapped temporary repo and home path.

    Returns:
        None: Assertions verify malformed context metadata does not crash
            checkpoint publication and still produces the expected branch-scoped
            single-capture rejection.
    """
    repo_dir, home_dir = repo

    path_pending_shard: Path = (
        repo_dir
        / ".agents"
        / "memory"
        / "pending"
        / "2026-04-08"
        / "2026-04-08T16-00-00Z--test--thread_branch-main--turn_t3.md"
    )
    path_pending_shard.parent.mkdir(parents=True, exist_ok=True)
    path_pending_shard.write_text(
        "\n".join(
            [
                "---",
                'timestamp: "2026-04-08T16:00:00Z"',
                'author: "test"',
                'branch: "main"',
                'thread_id: "generated-thread"',
                'turn_id: "t3"',
                'workstream_id: "branch-main"',
                'workstream_scope: "branch"',
                "decision_candidate: false",
                "enriched: false",
                "ai_generated: true",
                'ai_model: "gpt-5.4"',
                'ai_tool: "codex"',
                'ai_surface: "codex-cli"',
                'ai_executor: "local-agent"',
                "related_adrs:",
                "files_touched:",
                '  - "contextless.py"',
                "design_docs_touched:",
                'diff_summary: "1 file changed, 2 insertions(+)"',
                "verification:",
                '  - "git diff: 1 file changed, 2 insertions(+)"',
                "---",
                "",
                "## Why",
                "",
                "- Pending episode capture only.",
                "",
                "## What changed",
                "",
                "- Touched contextless.py",
                "",
                "## Evidence",
                "",
                "- git diff: 1 file changed, 2 insertions(+)",
                "",
                "## Next",
                "",
                "- Await background checkpoint evaluation.",
                "",
            ]
        ),
        encoding="utf-8",
    )

    path_context_dir: Path = (
        repo_dir / ".agents" / "memory" / "state" / "checkpoint-context"
    )
    path_context_dir.mkdir(parents=True, exist_ok=True)
    path_context: Path = path_context_dir / ".checkpoint-t3.json"
    path_published_shard: Path = (
        repo_dir
        / ".agents"
        / "memory"
        / "daily"
        / "2026-04-08"
        / "events"
        / "2026-04-08T16-00-00Z--test--thread_branch-main--turn_t3.md"
    )
    path_context.write_text(
        json.dumps(
            {
                "repo_root": str(repo_dir),
                "current_pending_shard": str(path_pending_shard),
                "pending_shard_paths": [str(path_pending_shard)],
                "pending_bundle": [],
                "published_shard_path": str(path_published_shard),
                "workstream_id": "branch-main",
                "workstream_scope": "branch",
                "episode_manifest_path": str(
                    repo_dir
                    / ".agents"
                    / "memory"
                    / "state"
                    / "episode-graph"
                    / "episodes"
                    / "episode-branch-main-t3.json"
                ),
                "episode_id": "episode-branch-main-t3",
                "episode_scope": "branch",
                "episode_status": "active",
                "episode_member_count": None,
                "secondary_candidate_episode_ids": [],
                "episode_primary_subsystem_hints": ["contextless.py"],
                "episode_cluster_edges": [],
                "branch": "main",
                "files_touched": ["contextless.py"],
                "design_docs_touched": [],
                "diff_summary": "1 file changed, 2 insertions(+)",
                "adr_index_path": str(
                    repo_dir / ".agents" / "memory" / "adr" / "INDEX.md"
                ),
                "recent_summary_paths": [],
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    env: dict[str, str] = os.environ.copy()
    env["HOME"] = str(home_dir)

    result_publish: subprocess.CompletedProcess[str] = subprocess.run(
        [
            sys.executable,
            SCRIPT_DIR / "publish-checkpoint.py",
            str(path_context),
            "--workstream-goal",
            "Advance the repo memory feature work.",
            "--subsystem-surface",
            "The repo memory pipeline.",
            "--turn-outcome",
            "Changed the implementation.",
            "--why",
            "This changed the implementation.",
            "--what-changed",
            "Updated contextless.py.",
            "--evidence",
            "Validator inspected contextless.py.",
            "--next",
            "Keep going.",
            "--source-pending-shard",
            str(path_pending_shard),
        ],
        cwd=repo_dir,
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )

    assert result_publish.returncode != 0
    assert "branch-scoped single-capture checkpoints require" in result_publish.stderr
    assert "TypeError" not in result_publish.stderr
    assert "ValueError" not in result_publish.stderr
    assert path_pending_shard.exists()
    assert path_context.exists()
    assert not path_published_shard.exists()


def test_enrich_shard_publishes_from_pending_raw_shard(repo):
    """Verify that enrich-shard.py publishes an enriched shard from pending raw state.

    The publish step must write the final daily event shard, rebuild the summary,
    stage only the published artifacts, and remove the pending raw input.
    """
    repo_dir, home_dir = repo

    day_dir = repo_dir / ".agents" / "memory" / "daily" / "2026-04-06"
    path_published_shard = (
        day_dir / "events" / "2026-04-06T12-00-00Z--test--thread_t1--turn_t1.md"
    )
    path_pending_shard = (
        repo_dir
        / ".agents"
        / "memory"
        / "pending"
        / "2026-04-06"
        / "2026-04-06T12-00-00Z--test--thread_t1--turn_t1.md"
    )
    raw_shard = """---
timestamp: "2026-04-06T12:00:00Z"
author: "test"
branch: "main"
thread_id: "t1"
turn_id: "t1"
decision_candidate: false
ai_generated: true
ai_model: "claude-opus-4-6"
ai_tool: "claude"
ai_surface: "claude-code"
ai_executor: "local-agent"
related_adrs:
files_touched:
  - "api.py"
verification:
  - "git diff: 1 file changed"
---

## Why

- 1 file changed, 10 insertions(+)

## Repo changes

- Updated api.py

## Evidence

- git diff: 1 file changed, 10 insertions(+)

## Next

- Review the generated shard and summary.
"""
    path_pending_shard.parent.mkdir(parents=True, exist_ok=True)
    path_pending_shard.write_text(raw_shard, encoding="utf-8")

    # Create enrichment context.
    context_dir = repo_dir / ".agents" / "memory" / "logs" / "enrichment-context"
    context_dir.mkdir(parents=True, exist_ok=True)
    context_path = context_dir / ".enrich-t1.json"
    context_data = {
        "shard_path": str(path_pending_shard),
        "published_shard_path": str(path_published_shard),
        "repo_root": str(repo_dir),
        "assistant_text": "Created JWT auth middleware.",
        "prompt": "Add authentication to the API.",
        "files_touched": ["api.py"],
        "diff_summary": "1 file changed, 10 insertions(+)",
    }
    context_path.write_text(json.dumps(context_data), encoding="utf-8")

    env = os.environ.copy()
    env["HOME"] = str(home_dir)

    # Run enrich-shard.py directly.
    subprocess.run(
        [
            sys.executable,
            SCRIPT_DIR / "enrich-shard.py",
            str(context_path),
            "--why",
            "Added JWT authentication middleware to enforce API security boundaries.",
            "--what",
            "Created auth module with token validation and middleware integration.",
            "--evidence",
            "Tests pass. Follows adapter pattern from design doc.",
            "--next",
            "Add rate limiting and API key rotation support.",
            "--decision-candidate",
        ],
        cwd=repo_dir,
        check=True,
        env=env,
    )

    # Verify enriched content.
    enriched_text = path_published_shard.read_text(encoding="utf-8")
    assert "JWT authentication middleware" in enriched_text
    assert "decision_candidate: true" in enriched_text
    assert "enriched: true" in enriched_text
    assert 'timestamp: "2026-04-06T12:00:00Z"' in enriched_text
    assert (
        "1 file changed, 10 insertions"
        not in enriched_text.split("## Why")[1].split("## Repo")[0]
    )

    summary_path = day_dir / "summary.md"
    assert summary_path.exists()

    staged_paths_result = subprocess.run(
        ["git", "diff", "--cached", "--name-only"],
        cwd=repo_dir,
        check=True,
        capture_output=True,
        text=True,
    )
    assert str(path_published_shard.relative_to(repo_dir)) in staged_paths_result.stdout
    assert str(summary_path.relative_to(repo_dir)) in staged_paths_result.stdout
    assert (
        str(path_pending_shard.relative_to(repo_dir)) not in staged_paths_result.stdout
    )

    # Context and pending raw shard should be cleaned up.
    assert not context_path.exists()
    assert not path_pending_shard.exists()


def test_enrich_shard_derives_published_path_from_pending_context(repo):
    """Verify enrich-shard can publish from legacy context missing `published_shard_path`.

    Args:
        repo: Pytest fixture returning the bootstrapped temporary repo and home path.

    Returns:
        None: Assertions verify the script derives the canonical daily event path
            from the pending shard location and rebuilds the correct summary date.
    """
    repo_dir, home_dir = repo

    path_pending_shard: Path = (
        repo_dir
        / ".agents"
        / "memory"
        / "pending"
        / "2026-04-06"
        / "2026-04-06T13-00-00Z--test--thread_t2--turn_t2.md"
    )
    path_pending_shard.parent.mkdir(parents=True, exist_ok=True)
    path_pending_shard.write_text(
        "\n".join(
            [
                "---",
                'timestamp: "2026-04-06T13:00:00Z"',
                'author: "test"',
                'branch: "main"',
                'thread_id: "t2"',
                'turn_id: "t2"',
                "decision_candidate: false",
                "enriched: false",
                "ai_generated: true",
                'ai_model: "claude-opus-4-6"',
                'ai_tool: "claude"',
                'ai_surface: "claude-code"',
                'ai_executor: "local-agent"',
                "related_adrs:",
                "files_touched:",
                '  - "api.py"',
                "verification:",
                '  - "git diff: 1 file changed"',
                "---",
                "",
                "## Why",
                "",
                "- Raw shard.",
                "",
                "## Repo changes",
                "",
                "- Updated api.py",
                "",
                "## Evidence",
                "",
                "- git diff: 1 file changed, 10 insertions(+)",
                "",
                "## Next",
                "",
                "- Review the generated shard and summary.",
                "",
            ]
        ),
        encoding="utf-8",
    )

    context_dir = repo_dir / ".agents" / "memory" / "logs" / "enrichment-context"
    context_dir.mkdir(parents=True, exist_ok=True)
    context_path = context_dir / ".enrich-t2.json"
    context_path.write_text(
        json.dumps(
            {
                "shard_path": str(path_pending_shard),
                "repo_root": str(repo_dir),
                "assistant_text": "Created middleware.",
                "prompt": "Add auth middleware.",
                "files_touched": ["api.py"],
                "diff_summary": "1 file changed, 10 insertions(+)",
            }
        ),
        encoding="utf-8",
    )

    env = os.environ.copy()
    env["HOME"] = str(home_dir)

    subprocess.run(
        [
            sys.executable,
            SCRIPT_DIR / "enrich-shard.py",
            str(context_path),
            "--why",
            "Added authentication middleware.",
            "--what",
            "Created middleware integration.",
            "--evidence",
            "Tests pass.",
            "--next",
            "Add rate limiting.",
        ],
        cwd=repo_dir,
        check=True,
        env=env,
    )

    path_published_shard: Path = (
        repo_dir
        / ".agents"
        / "memory"
        / "daily"
        / "2026-04-06"
        / "events"
        / "2026-04-06T13-00-00Z--test--thread_t2--turn_t2.md"
    )
    summary_path: Path = (
        repo_dir / ".agents" / "memory" / "daily" / "2026-04-06" / "summary.md"
    )

    assert path_published_shard.exists()
    assert summary_path.exists()
    assert not path_pending_shard.exists()


def test_post_turn_notify_generates_canonical_hash_identifiers(repo):
    """Verify synthesized identifiers avoid duplicate thread_/turn_ prefixes.

    Args:
        repo: Pytest fixture returning the bootstrapped temporary repo and home path.

    Returns:
        None: Assertions verify payloads without explicit IDs still produce
            canonical shard filenames and normalized frontmatter identifiers.
    """
    repo_dir, home_dir = repo

    path_tracked_file: Path = repo_dir / "hash_ids.py"
    path_tracked_file.write_text("# generated identifiers\n", encoding="utf-8")
    subprocess.run(["git", "add", "hash_ids.py"], cwd=repo_dir, check=True)

    env = os.environ.copy()
    env["HOME"] = str(home_dir)

    subprocess.run(
        [
            sys.executable,
            SCRIPT_DIR / "post-turn-notify.py",
            "--repo-root",
            str(repo_dir),
        ],
        cwd=repo_dir,
        input=json.dumps(
            {
                "prompt": "Record hash-based shard identifiers.",
                "last_assistant_message": "Created a test file.",
                "model": "gpt-5.4",
            }
        ),
        text=True,
        capture_output=True,
        check=True,
        env=env,
    )

    list_path_pending_shards: list[Path] = list(
        (repo_dir / ".agents" / "memory" / "pending").glob("202*/*.md")
    )
    assert len(list_path_pending_shards) == 1
    path_pending_shard: Path = list_path_pending_shards[0]
    assert "--thread_thread_" not in path_pending_shard.name
    assert "--turn_turn_" not in path_pending_shard.name

    str_shard_text: str = path_pending_shard.read_text(encoding="utf-8")
    assert 'thread_id: "thread_' not in str_shard_text
    assert 'turn_id: "turn_' not in str_shard_text


def test_agent_support_includes_enrichment_capabilities():
    """Verify that agent support declarations include the new shard enrichment
    and design doc inspection capability flags.
    """
    agent_support_module = load_script_module(
        SCRIPT_DIR / "agent_support.py", "agent_support_enrichment_test"
    )

    entries = agent_support_module.list_agent_support()
    claude_entry = next(e for e in entries if e.str_agent_id == "claude")
    gemini_entry = next(e for e in entries if e.str_agent_id == "gemini")
    codex_entry = next(e for e in entries if e.str_agent_id == "codex")

    assert claude_entry.bool_supports_shard_enrichment is True
    assert claude_entry.bool_supports_design_doc_inspection is True
    assert gemini_entry.bool_supports_shard_enrichment is True
    assert gemini_entry.bool_supports_design_doc_inspection is True
    assert codex_entry.bool_supports_shard_enrichment is False
    assert codex_entry.bool_supports_design_doc_inspection is True
