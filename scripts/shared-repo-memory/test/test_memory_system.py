import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType

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
    assert (repo_dir / ".agents" / "memory").exists()
    assert (repo_dir / ".agents" / "memory" / "pending").is_dir()
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
    assert "# Added by the shared repo-memory SessionStart/bootstrap flow." in (
        str_gitignore_text
    )
    assert ".githooks/" in str_gitignore_text
    assert ".agents/memory/pending/" in str_gitignore_text
    assert ".agents/memory/logs/" in str_gitignore_text
    assert "# Generated by agentmemory v0.2.8." in str_pre_commit_text
    assert "This repo-local hook is created by the shared repo-memory SessionStart" in (
        str_pre_commit_text
    )
    assert "pre-commit-memory-guard.py" in str_pre_commit_text
    assert "project-pre-commit.sh" in str_pre_commit_text


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
    assert (
        "durable repo decision" in pending_shards[0].read_text(encoding="utf-8").lower()
    )

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


def test_post_turn_notify_ignores_assistant_chatter_for_why(repo):
    repo_dir, home_dir = repo

    tracked_file = repo_dir / "feature.py"
    tracked_file.write_text("# noisy update\n")
    subprocess.run(["git", "add", "feature.py"], cwd=repo_dir, check=True)

    payload = {
        "conversation_id": "test-thread",
        "turn_id": "test-turn-2",
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
    assert (
        "Repo state changed during this agent turn." in shard_text
        or "1 file changed" in shard_text
    )
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
    subprocess.run(
        [sys.executable, SCRIPT_DIR / "build-catchup.py", "--repo-root", str(repo_dir)],
        cwd=repo_dir,
        check=True,
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


def test_post_turn_notify_writes_enrichment_context(repo):
    """Verify that post-turn-notify writes an enrichment context file when
    assistant_text is present in the payload.

    This test installs a temporary shard-enricher skill and a stub `claude`
    executable so `_spawn_enrichment()` succeeds. That leaves the context file
    in place long enough to verify its contents deterministically.
    """
    repo_dir, home_dir = repo

    tracked_file = repo_dir / "api.py"
    tracked_file.write_text("# new API module\n")
    subprocess.run(["git", "add", "api.py"], cwd=repo_dir, check=True)

    path_skill_dir: Path = home_dir / ".agent" / "skills" / "shard-enricher"
    path_skill_dir.mkdir(parents=True, exist_ok=True)
    (path_skill_dir / "SKILL.md").write_text(
        "Return enriched shard sections.", encoding="utf-8"
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

    # The enrichment context must exist with the expected publish metadata until
    # enrich-shard.py consumes it.
    context_dir = repo_dir / ".agents" / "memory" / "logs" / "enrichment-context"
    list_path_context_files: list[Path] = list(context_dir.glob(".enrich-*.json"))
    assert len(list_path_context_files) == 1
    dict_context_data: dict[str, object] = json.loads(
        list_path_context_files[0].read_text(encoding="utf-8")
    )
    assert dict_context_data["assistant_text"] == payload["last_assistant_message"]
    assert dict_context_data["prompt"] == payload["prompt"]
    assert dict_context_data["files_touched"] == ["api.py"]
    assert str(dict_context_data["published_shard_path"]).endswith(".md")

    # The pending raw shard should exist with the user prompt in the Why section.
    pending_dirs = list((repo_dir / ".agents" / "memory" / "pending").glob("202*"))
    assert len(pending_dirs) == 1
    shards = list(pending_dirs[0].glob("*.md"))
    assert len(shards) == 1
    shard_text = shards[0].read_text(encoding="utf-8")
    assert "Create the API module" in shard_text
    assert list((repo_dir / ".agents" / "memory" / "daily").glob("*/events/*.md")) == []


def test_post_turn_notify_contextless_turn_stays_pending_only(repo):
    """Verify that a meaningful turn without semantic context never publishes a shard.

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
    assert dict_trace_payload["enrichment_spawned"] is False


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


def test_post_turn_notify_captures_untracked_design_doc_only(repo):
    """Verify that a newly created untracked design doc is still a meaningful turn.

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
        .replace(".agents/memory/logs/\n", ""),
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

    assert "Shared repo memory" in result.stdout
    repaired_gitignore: str = path_gitignore.read_text(encoding="utf-8")
    assert "# agentmemory-managed local repo wiring and state" in repaired_gitignore
    assert ".githooks/" in repaired_gitignore
    assert ".agents/memory/pending/" in repaired_gitignore
    assert ".agents/memory/logs/" in repaired_gitignore


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
