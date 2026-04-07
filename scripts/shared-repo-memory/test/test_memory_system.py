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
    (home_dir / ".codex" / "skills" / "memory-writer").mkdir(
        parents=True, exist_ok=True
    )
    (home_dir / ".agent" / "state").mkdir(parents=True, exist_ok=True)

    # Run bootstrap using sys.executable to ensure the correct Python version.
    env = os.environ.copy()
    env["HOME"] = str(home_dir)
    subprocess.run(
        [sys.executable, SCRIPT_DIR / "bootstrap-repo.py"],
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
    (home_dir / ".codex" / "skills" / "memory-writer").mkdir(
        parents=True, exist_ok=True
    )
    (home_dir / ".agent" / "state").mkdir(parents=True, exist_ok=True)
    (home_dir / ".agent" / "shared-repo-memory").mkdir(parents=True, exist_ok=True)
    (home_dir / ".codex").mkdir(parents=True, exist_ok=True)
    (home_dir / ".codex" / "config.toml").write_text(
        "shared_repo_memory_configured = true\n",
        encoding="utf-8",
    )
    for helper in [
        "bootstrap-repo.sh",
        "post-turn-notify.py",
        "rebuild-summary.py",
        "build-catchup.py",
        "promote-adr.py",
    ]:
        (home_dir / ".agent" / "shared-repo-memory" / helper).write_text(
            "# stub\n", encoding="utf-8"
        )
    (home_dir / ".codex" / "skills" / "adr-promoter").mkdir(parents=True, exist_ok=True)
    (home_dir / ".agent" / "state" / "shared_asset_refresh_state.json").write_text(
        json.dumps({"last_successful_refresh_at": "2026-03-31T00:00:00Z"}),
        encoding="utf-8",
    )
    return work_dir, home_dir


def test_bootstrap_initializes_directories(repo):
    repo_dir, _ = repo
    assert (repo_dir / ".agents" / "memory").exists()
    assert (repo_dir / ".codex" / "memory").is_symlink()
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


def test_post_turn_notify_creates_shard_and_summary(repo):
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
    subprocess.run(
        [sys.executable, SCRIPT_DIR / "post-turn-notify.py", "--repo-root", str(repo_dir)],
        cwd=repo_dir,
        input=json.dumps(payload),
        text=True,
        check=True,
        env=env,
    )

    daily_dirs = list((repo_dir / ".agents" / "memory" / "daily").glob("202*"))
    assert len(daily_dirs) == 1
    day_dir = daily_dirs[0]

    shards = list((day_dir / "events").glob("*.md"))
    assert len(shards) == 1

    summary_path = day_dir / "summary.md"
    assert summary_path.exists()
    assert "durable repo decision" in summary_path.read_text().lower()


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
        [sys.executable, SCRIPT_DIR / "post-turn-notify.py", "--repo-root", str(repo_dir)],
        cwd=repo_dir,
        input=json.dumps(payload),
        text=True,
        check=True,
        env=env,
    )

    day_dir = next((repo_dir / ".agents" / "memory" / "daily").glob("202*"))
    shard_path = next((day_dir / "events").glob("*.md"))
    shard_text = shard_path.read_text(encoding="utf-8")
    summary_text = (day_dir / "summary.md").read_text(encoding="utf-8")

    assert "How's that look?" not in shard_text
    assert "How's that look?" not in summary_text
    assert (
        "Repo state changed during this agent turn." in shard_text
        or "1 file changed" in shard_text
    )


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
    repo_dir, _ = repo
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


def test_prompt_guard_injects_one_time_news_nudge(repo):
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

    The enrichment subagent will not actually spawn in test (no claude/gemini
    binary), but the context file should be written and then cleaned up when
    spawning fails.
    """
    repo_dir, home_dir = repo

    tracked_file = repo_dir / "api.py"
    tracked_file.write_text("# new API module\n")
    subprocess.run(["git", "add", "api.py"], cwd=repo_dir, check=True)

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

    result = subprocess.run(
        [sys.executable, SCRIPT_DIR / "post-turn-notify.py", "--repo-root", str(repo_dir)],
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

    # Verify context file was written (it persists until the subagent reads
    # and deletes it, or is cleaned up on spawn failure).
    day_dirs = list((repo_dir / ".agents" / "memory" / "daily").glob("202*"))
    assert len(day_dirs) >= 1
    day_dir = day_dirs[-1]
    context_files = list((day_dir / "events").glob(".enrich-*.json"))
    if context_files:
        # Subagent was spawned; context file exists for it to consume.
        context_data = json.loads(context_files[0].read_text(encoding="utf-8"))
        assert "assistant_text" in context_data
        assert "JWT-based authentication" in context_data["assistant_text"]
        # Clean up so it doesn't interfere with other tests.
        context_files[0].unlink()

    # The raw shard should exist with the user prompt in the Why section.
    shards = list((day_dir / "events").glob("*.md"))
    assert len(shards) >= 1
    shard_text = shards[-1].read_text(encoding="utf-8")
    assert "Create the API module" in shard_text


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
        [sys.executable, SCRIPT_DIR / "post-turn-notify.py", "--repo-root", str(repo_dir)],
        cwd=repo_dir,
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        check=True,
        env=env,
    )

    output = json.loads(result.stdout)
    assert output["status"] == "ok"

    # Verify the shard was written.
    day_dirs = list((repo_dir / ".agents" / "memory" / "daily").glob("202*"))
    assert len(day_dirs) >= 1


def test_enrich_shard_overwrites_raw_shard(repo):
    """Verify that enrich-shard.py correctly overwrites a raw shard's body
    sections while preserving frontmatter.
    """
    repo_dir, home_dir = repo

    # Create a raw shard.
    day_dir = repo_dir / ".agents" / "memory" / "daily" / "2026-04-06"
    events_dir = day_dir / "events"
    events_dir.mkdir(parents=True, exist_ok=True)

    shard_path = events_dir / "2026-04-06T12-00-00Z--test--thread_t1--turn_t1.md"
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
    shard_path.write_text(raw_shard, encoding="utf-8")

    # Create enrichment context.
    context_path = events_dir / ".enrich-t1.json"
    context_data = {
        "shard_path": str(shard_path),
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
            "--why", "Added JWT authentication middleware to enforce API security boundaries.",
            "--what", "Created auth module with token validation and middleware integration.",
            "--evidence", "Tests pass. Follows adapter pattern from design doc.",
            "--next", "Add rate limiting and API key rotation support.",
            "--decision-candidate",
        ],
        cwd=repo_dir,
        check=True,
        env=env,
    )

    # Verify enriched content.
    enriched_text = shard_path.read_text(encoding="utf-8")
    assert "JWT authentication middleware" in enriched_text
    assert "decision_candidate: true" in enriched_text
    assert 'timestamp: "2026-04-06T12:00:00Z"' in enriched_text
    assert "1 file changed, 10 insertions" not in enriched_text.split("## Why")[1].split("## Repo")[0]

    # Context file should be cleaned up.
    assert not context_path.exists()


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
