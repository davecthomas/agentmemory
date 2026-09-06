"""Tests for turn-nudge.py, the once-per-session decision-note reminder."""

from __future__ import annotations

import json
from pathlib import Path

import common
from conftest import run_git, run_script


def _stop(repo: Path, session: str = "s1", active: bool = False) -> str:
    payload = {"cwd": str(repo), "session_id": session, "stop_hook_active": active}
    result = run_script("turn-nudge.py", cwd=repo, stdin=json.dumps(payload))
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def _start(repo: Path, session: str = "s1") -> None:
    common.load_module(
        Path(__file__).resolve().parents[1] / "turn-nudge.py"
    ).record_session(repo, session)


def test_silent_when_not_opted_in(repo: Path) -> None:
    (repo / "x.py").write_text("x", encoding="utf-8")
    assert _stop(repo) == ""


def test_nudges_once_when_work_unrecorded(repo: Path) -> None:
    assert run_script("bootstrap-repo.py", "--init", cwd=repo).returncode == 0
    _start(repo)
    assert _stop(repo) == ""  # nothing changed yet
    (repo / "x.py").write_text("x", encoding="utf-8")
    first = json.loads(_stop(repo))
    assert first["decision"] == "block" and "memory-note" in first["reason"]
    assert _stop(repo) == ""  # once per session
    assert _stop(repo, active=True) == ""


def test_reports_a_written_note_once_then_is_silent(repo: Path) -> None:
    assert run_script("bootstrap-repo.py", "--init", cwd=repo).returncode == 0
    _start(repo)
    (repo / "x.py").write_text("x", encoding="utf-8")
    run_script("memory-note.py", "--decision", "D", "--why", "W", cwd=repo)
    first = json.loads(_stop(repo))
    assert first["decision"] == "block"
    assert "1 decision note was recorded" in first["reason"]
    assert common.NOTES_DIR in first["reason"]
    assert "memory-note" not in first["reason"]  # a report, not the nudge
    assert _stop(repo) == ""  # said once


def test_reports_a_hook_written_note(repo: Path) -> None:
    assert run_script("bootstrap-repo.py", "--init", cwd=repo).returncode == 0
    run_git(repo, "add", "-A")
    run_git(repo, "commit", "-q", "-m", "opt in")
    _start(repo)
    (repo / "docs").mkdir(exist_ok=True)
    (repo / "docs" / "d.md").write_text("x\n", encoding="utf-8")
    run_git(repo, "add", "-A")
    run_git(repo, "commit", "-q", "-m", "add doc\n\nChosen because it is simpler.")
    reported = json.loads(_stop(repo))
    assert "decision note was recorded" in reported["reason"]


def test_memory_only_changes_do_not_count(repo: Path) -> None:
    assert run_script("bootstrap-repo.py", "--init", cwd=repo).returncode == 0
    _start(repo)
    run_script(
        "promote-adr.py", "--title", "T", "--context", "c", "--decision", "d", cwd=repo
    )
    assert _stop(repo) == ""


def test_session_start_records_session(repo: Path, home: Path) -> None:
    common.dump_json(home / ".claude" / "settings.json", {common.CONFIGURED_FLAG: True})
    common.dump_json(repo / common.CONFIG_FILE, common.DEFAULT_CONFIG)
    result = run_script(
        "session-start.py",
        cwd=repo,
        stdin=json.dumps({"cwd": str(repo), "session_id": "abc"}),
    )
    assert result.returncode == 0, result.stderr
    state = common.load_json(repo / common.LOCAL_DIR / "state.json", {})
    assert "abc" in state["sessions"] and state["sessions"]["abc"]["nudged"] is False
    run_git(repo, "status")  # repo still healthy
