import json
import os
import subprocess
from pathlib import Path

import pytest

SCRIPT_DIR = Path(__file__).parent.parent.resolve()


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

    # Run bootstrap
    env = os.environ.copy()
    env["HOME"] = str(home_dir)
    subprocess.run(
        [SCRIPT_DIR / "bootstrap-repo.sh"], cwd=repo_dir, check=True, env=env
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
        "last_assistant_message": "Treated this as a durable repo decision.",
        "model": "gpt-5.4",
    }

    env = os.environ.copy()
    env["HOME"] = str(home_dir)

    # Run notify script with payload piped to stdin
    subprocess.run(
        ["python3", SCRIPT_DIR / "post-turn-notify.py", "--repo-root", str(repo_dir)],
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


def test_post_turn_notify_noops_outside_git_repo(non_repo):
    work_dir, home_dir = non_repo

    env = os.environ.copy()
    env["HOME"] = str(home_dir)

    result = subprocess.run(
        ["python3", SCRIPT_DIR / "post-turn-notify.py"],
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
        ["python3", SCRIPT_DIR / "session-start.py"],
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
            "python3",
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

    # Setup: Create a mock summary
    day_dir = repo_dir / ".agents" / "memory" / "daily" / "2026-03-30"
    day_dir.mkdir(parents=True, exist_ok=True)
    summary_path = day_dir / "summary.md"
    summary_path.write_text("This is a mock daily summary.")

    env = os.environ.copy()
    env["HOME"] = str(home_dir)

    # Run build-catchup.py
    subprocess.run(
        ["python3", SCRIPT_DIR / "build-catchup.py", "--repo-root", str(repo_dir)],
        cwd=repo_dir,
        check=True,
        env=env,
    )

    catchup_path = repo_dir / ".codex" / "local" / "catchup.md"
    assert catchup_path.exists()
    catchup_text = catchup_path.read_text()
    assert "# Local catch-up" in catchup_text
    assert "2026-03-30" in catchup_text
    assert "summary.md" in catchup_text
