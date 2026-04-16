"""Tests for the dedup module — diff-state gate and published-event gate."""
import importlib.util
import json
import sys
from collections import OrderedDict
from pathlib import Path
from types import ModuleType

SCRIPT_DIR = Path(__file__).parent.parent.resolve()


def _load_dedup() -> ModuleType:
    """Import dedup.py from the scripts directory."""
    str_parent: str = str(SCRIPT_DIR)
    added: bool = False
    if str_parent not in sys.path:
        sys.path.insert(0, str_parent)
        added = True
    try:
        spec = importlib.util.spec_from_file_location("dedup", SCRIPT_DIR / "dedup.py")
        if spec is None or spec.loader is None:
            raise ImportError("Could not load dedup.py")
        mod = importlib.util.module_from_spec(spec)
        sys.modules["dedup"] = mod
        spec.loader.exec_module(mod)
    finally:
        if added:
            sys.path.remove(str_parent)
    return mod


dedup = _load_dedup()


# ---------------------------------------------------------------------------
# Jaccard similarity
# ---------------------------------------------------------------------------


class TestJaccardSimilarity:
    def test_identical_sets(self):
        assert dedup._jaccard_similarity({"a", "b"}, {"a", "b"}) == 1.0

    def test_disjoint_sets(self):
        assert dedup._jaccard_similarity({"a"}, {"b"}) == 0.0

    def test_partial_overlap(self):
        result = dedup._jaccard_similarity({"a", "b", "c"}, {"b", "c", "d"})
        assert abs(result - 0.5) < 1e-9

    def test_both_empty(self):
        assert dedup._jaccard_similarity(set(), set()) == 1.0

    def test_one_empty(self):
        assert dedup._jaccard_similarity({"a"}, set()) == 0.0

    def test_threshold_boundary_at_50_percent(self):
        # {a,b,c} ∩ {a,b,d} = {a,b} = 2, union = {a,b,c,d} = 4, → 0.50
        result = dedup._jaccard_similarity({"a", "b", "c"}, {"a", "b", "d"})
        assert result >= dedup._JACCARD_OVERLAP_THRESHOLD


# ---------------------------------------------------------------------------
# Diff-state dedup gate
# ---------------------------------------------------------------------------


class TestDiffStateGate:
    def test_empty_hash_never_deduplicates(self, tmp_path):
        assert dedup.already_captured(tmp_path, "ws-1", "main", "") is False

    def test_first_capture_is_not_duplicate(self, tmp_path):
        assert dedup.already_captured(tmp_path, "ws-1", "main", "abc123") is False

    def test_same_workstream_same_hash_is_duplicate(self, tmp_path):
        dedup.record_capture(tmp_path, "ws-1", "main", "abc123")
        assert dedup.already_captured(tmp_path, "ws-1", "main", "abc123") is True

    def test_different_workstream_same_branch_same_hash_is_duplicate(self, tmp_path):
        """The core Codex fix: different thread_id but same branch + diff."""
        dedup.record_capture(tmp_path, "thread-aaa", "feature/foo", "abc123")
        assert dedup.already_captured(
            tmp_path, "thread-bbb", "feature/foo", "abc123"
        ) is True

    def test_different_branch_same_hash_is_not_duplicate(self, tmp_path):
        dedup.record_capture(tmp_path, "ws-1", "main", "abc123")
        assert dedup.already_captured(
            tmp_path, "ws-2", "feature/bar", "abc123"
        ) is False

    def test_changed_hash_is_not_duplicate(self, tmp_path):
        dedup.record_capture(tmp_path, "ws-1", "main", "abc123")
        assert dedup.already_captured(tmp_path, "ws-1", "main", "def456") is False

    def test_state_file_persists(self, tmp_path):
        dedup.record_capture(tmp_path, "ws-1", "main", "abc123")
        state_path = tmp_path / ".codex" / "local" / "last-shard-diff-state.json"
        assert state_path.exists()
        state = json.loads(state_path.read_text())
        assert state["ws-1"] == "abc123"
        assert state["branch:main"] == "abc123"


# ---------------------------------------------------------------------------
# Published-event dedup gate
# ---------------------------------------------------------------------------


def _write_event(day_dir: Path, name: str, branch: str, files: list[str]) -> None:
    """Write a minimal published event shard for testing."""
    events_dir = day_dir / "events"
    events_dir.mkdir(parents=True, exist_ok=True)
    metadata = OrderedDict([
        ("branch", branch),
        ("files_touched", files),
        ("enriched", True),
    ])
    lines = ["---"]
    for key, val in metadata.items():
        if isinstance(val, list):
            lines.append(f"{key}:")
            for item in val:
                lines.append(f'  - "{item}"')
        elif isinstance(val, bool):
            lines.append(f"{key}: {'true' if val else 'false'}")
        else:
            lines.append(f'{key}: "{val}"')
    lines.append("---")
    lines.append("")
    lines.append("## Why")
    lines.append("- test event")
    (events_dir / name).write_text("\n".join(lines), encoding="utf-8")


class TestPublishedEventGate:
    def test_no_events_dir_returns_false(self, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        assert dedup.published_event_exists(
            repo, "2026-04-15", "main", ["a.py"]
        ) is False

    def test_different_branch_no_match(self, tmp_path):
        repo = tmp_path / "repo"
        day_dir = repo / ".agents" / "memory" / "daily" / "2026-04-15"
        _write_event(day_dir, "event1.md", "feature/other", ["a.py", "b.py"])
        assert dedup.published_event_exists(
            repo, "2026-04-15", "main", ["a.py", "b.py"]
        ) is False

    def test_same_branch_high_overlap_matches(self, tmp_path):
        repo = tmp_path / "repo"
        day_dir = repo / ".agents" / "memory" / "daily" / "2026-04-15"
        _write_event(day_dir, "event1.md", "main", ["a.py", "b.py", "c.py"])
        assert dedup.published_event_exists(
            repo, "2026-04-15", "main", ["a.py", "b.py"]
        ) is True

    def test_same_branch_low_overlap_no_match(self, tmp_path):
        repo = tmp_path / "repo"
        day_dir = repo / ".agents" / "memory" / "daily" / "2026-04-15"
        _write_event(day_dir, "event1.md", "main", ["a.py", "b.py", "c.py"])
        # Only 1 shared out of 5 total unique → 0.20 < threshold
        assert dedup.published_event_exists(
            repo, "2026-04-15", "main", ["a.py", "x.py", "y.py"]
        ) is False

    def test_empty_candidate_files_returns_false(self, tmp_path):
        repo = tmp_path / "repo"
        day_dir = repo / ".agents" / "memory" / "daily" / "2026-04-15"
        _write_event(day_dir, "event1.md", "main", ["a.py"])
        assert dedup.published_event_exists(
            repo, "2026-04-15", "main", []
        ) is False
