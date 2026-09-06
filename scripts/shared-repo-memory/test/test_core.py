"""Tests for common helpers, notes, commit capture, ADR promotion, and query."""

from __future__ import annotations

from pathlib import Path

import common
from conftest import adr_ids, load, run_git

# --- common -----------------------------------------------------------------


def test_frontmatter_roundtrip() -> None:
    meta = {
        "id": "ADR-0001",
        "title": 'A "quoted": title',
        "must_read": True,
        "tags": ["a", "b"],
    }
    text = common.render_frontmatter(meta) + "\n\nbody\n"
    parsed, body = common.parse_frontmatter(text)
    assert parsed == meta
    assert body == "body\n"


def test_parse_frontmatter_without_block() -> None:
    assert common.parse_frontmatter("# just a heading\n") == ({}, "# just a heading\n")


def test_section_extracts_until_next_heading() -> None:
    body = "# T\n\n## Context\n\nctx\n\n## Decision\n\nline one\nline two\n\n## Sources\n\n- x\n"
    assert common.section(body, "Decision") == "line one\nline two"
    assert common.section(body, "Missing") == ""


def test_git_preserves_leading_status_column(repo: Path) -> None:
    (repo / "README.md").write_text("changed\n", encoding="utf-8")
    raw = common.git(["status", "--porcelain"], repo, strip=False)
    assert raw.startswith(" M README.md"), raw
    assert common.git(["status", "--porcelain"], repo).startswith("M README.md")


def test_matches_surface_globs() -> None:
    assert common.matches_surface("docs/a/b.md", ["docs/**"])
    assert common.matches_surface("docs/plan.md", ["docs/**"])
    assert not common.matches_surface("src/docs/x.md", ["docs/**"])
    assert common.matches_surface("src/mod.py", ["src/*.py"])
    assert not common.matches_surface("src/pkg/mod.py", ["src/*.py"])
    assert common.matches_surface("src/pkg/mod.py", ["**/*.py"])


def test_build_memory_context_orders_and_budgets(repo: Path) -> None:
    adr_dir = repo / common.ADR_DIR
    adr_dir.mkdir(parents=True)
    (adr_dir / "INDEX.md").write_text(
        "# ADR index\n\n| ADR-0001 | t1 |\n", encoding="utf-8"
    )
    promote = load("promote-adr.py")
    for i in (1, 2):
        (adr_dir / f"ADR-000{i}-t{i}.md").write_text(
            promote.render_adr(
                adr_id=f"ADR-000{i}",
                title=f"t{i}",
                context="c",
                decision=f"decision {i}",
                must_read=(i == 2),
            ),
            encoding="utf-8",
        )
    notes = repo / common.NOTES_DIR
    notes.mkdir(parents=True)
    (notes / f"{common.today()}.md").write_text(
        "# notes\n\nrecent note\n", encoding="utf-8"
    )
    (notes / "2000-01-01.md").write_text(
        "# old\n\n## 2000-01-01T00:00Z · a · main\n\n**Decision:** ancient decision\n"
        "**Why:** ancient note\n",
        encoding="utf-8",
    )
    week_ago = common.today(common.utc_now() - __import__("datetime").timedelta(days=7))
    (notes / f"{week_ago}.md").write_text(
        f"# n\n\n## {week_ago}T00:00Z · a · main\n\n**Decision:** week-old decision\n"
        "**Why:** week-old why text\n",
        encoding="utf-8",
    )
    (repo / common.LOCAL_DIR).mkdir(parents=True)
    (repo / common.LOCAL_DIR / "catchup.md").write_text(
        "catch me up\n", encoding="utf-8"
    )

    context = common.build_memory_context(repo)
    assert "week-old decision" in context and "week-old why text" not in context
    assert "### Recent decisions" in context
    assert context.index("### ADR index") < context.index("### ADR-0002: t2")
    assert "decision 2" in context and "decision 1" not in context  # only must_read
    assert "recent note" in context and "ancient note" not in context  # window
    assert "- 2000-01-01: ancient decision" in context  # one-line index survives
    assert context.index("recent note") < context.index("ancient decision")
    assert context.index("ancient decision") < context.index("catch me up")

    tight = common.build_memory_context(
        repo, {**common.DEFAULT_CONFIG, "context_budget_words": 8}
    )
    assert "### ADR index" in tight
    assert "Omitted to stay under 8 words" in tight
    assert "catch me up" not in tight


# --- memory-note ----------------------------------------------------------------


def test_memory_note_appends_and_stages(repo: Path) -> None:
    note = load("memory-note.py")
    entry = note.render_entry(
        decision="Use X",
        why="Because Y",
        author="alice",
        branch="main",
        alternatives="Z",
        scope=["a/", "b.py"],
        when="2026-01-01T00:00Z",
    )
    assert entry.startswith(
        "## 2026-01-01T00:00Z · alice · main\n\n**Decision:** Use X\n**Why:** Because Y\n"
    )
    assert "**Alternatives:** Z\n**Scope:** a/, b.py\n" in entry

    path = note.append_note(repo, entry, date="2026-01-01")
    path = note.append_note(repo, entry, date="2026-01-01")
    text = path.read_text(encoding="utf-8")
    assert text.startswith("# Decision notes 2026-01-01\n\n## ")
    assert text.count("**Decision:** Use X") == 2


def test_author_slug_drops_noreply_id(repo: Path) -> None:
    run_git(
        repo, "config", "user.email", "2355287-davecthomas@users.noreply.github.com"
    )
    assert common.author_slug(repo) == "davecthomas"


def test_memory_note_cli(repo: Path) -> None:
    from conftest import run_script

    result = run_script(
        "memory-note.py", "--decision", "D", "--why", "W", "--scope", "x", cwd=repo
    )
    assert result.returncode == 0, result.stderr
    rel = result.stdout.strip()
    assert rel == f"{common.NOTES_DIR}/{common.today()}--alice.md"
    assert "**Decision:** D" in (repo / rel).read_text(encoding="utf-8")
    assert rel not in run_git(
        repo, "diff", "--cached", "--name-only"
    )  # memory-commit stages
    run_script("memory-note.py", "--decision", "E", "--why", "W", "--stage", cwd=repo)
    assert rel in run_git(repo, "diff", "--cached", "--name-only")


# --- commit-capture -------------------------------------------------------------


def _commit(repo: Path, rel: str, message: str) -> None:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{message}\n", encoding="utf-8")
    run_git(repo, "add", rel)
    run_git(repo, "commit", "-q", "-m", message)


def test_capture_skips_commits_off_surface(repo: Path) -> None:
    capture = load("commit-capture.py")
    _commit(repo, "src/x.py", "plain change")
    assert capture.capture(repo) is None


def test_capture_on_surface_uses_body_and_records_source(repo: Path) -> None:
    capture = load("commit-capture.py")
    _commit(
        repo,
        "docs/design.md",
        "add design\n\nWe chose pull over push because push needs a broker.\n\n"
        "ai-generated: true\nai-model: x\n",
    )
    path = capture.capture(repo)
    assert path is not None
    text = path.read_text(encoding="utf-8")
    assert "**Decision:** add design" in text
    assert "**Why:** We chose pull over push because push needs a broker." in text
    assert "ai-generated" not in text
    assert "**Scope:** docs/design.md" in text
    assert "**Source:** commit-capture" in text
    assert "**Commit:** " in text


def test_capture_decision_line_off_surface(repo: Path) -> None:
    capture = load("commit-capture.py")
    _commit(
        repo,
        "src/y.py",
        "refactor y\n\nDecision: keep y synchronous\n\nAsync gained nothing here.",
    )
    path = capture.capture(repo)
    assert path is not None
    text = path.read_text(encoding="utf-8")
    assert "**Decision:** keep y synchronous" in text
    assert "**Why:** Async gained nothing here." in text
    assert "**Scope:**" not in text


def test_capture_reasoned_body_off_surface(repo: Path) -> None:
    capture = load("commit-capture.py")
    _commit(
        repo,
        "src/z.py",
        "use a queue\n\nChosen instead of a cron job because retries need state.\n\n"
        "ai-generated: true",
    )
    path = capture.capture(repo)
    assert path is not None
    text = path.read_text(encoding="utf-8")
    assert "**Decision:** use a queue" in text
    assert "**Why:** Chosen instead of a cron job because retries need state." in text


def test_capture_strips_structured_message_scaffolding(repo: Path) -> None:
    capture = load("commit-capture.py")
    run_git(repo, "checkout", "-q", "-b", "feat/thing")
    _commit(
        repo,
        "docs/thing.md",
        "feat/thing: add the thing\n\nSummary:\n=======\nWe added it because the old "
        "path was slow.\n\nActions:\n=======\n- touch docs\n- touch code\n\n"
        "Note: This commit message was created by AI\nai-generated: true",
    )
    text = capture.capture(repo).read_text(encoding="utf-8")
    assert "**Decision:** add the thing" in text
    assert "**Why:** We added it because the old path was slow." in text
    assert "=======" not in text and "Actions" not in text and "touch docs" not in text


def test_capture_strips_foreign_branch_prefix(repo: Path) -> None:
    capture = load("commit-capture.py")
    _commit(repo, "docs/x.md", "feat/elsewhere: pick Y\n\nY because Z.")
    text = capture.capture(repo).read_text(encoding="utf-8")
    assert "**Decision:** pick Y" in text


def test_capture_ignores_memory_only_commits(repo: Path) -> None:
    capture = load("commit-capture.py")
    _commit(repo, f"{common.NOTES_DIR}/2026-01-01.md", "note only")
    assert capture.capture(repo) is None


# --- promote-adr ----------------------------------------------------------------


def test_promote_from_note_and_reindex(repo: Path) -> None:
    from conftest import run_script

    note = load("memory-note.py")
    entry = note.render_entry(
        decision="Store memory in git",
        why="No service to run",
        author="alice",
        branch="main",
        alternatives="A vector DB",
        scope=["docs/"],
        commit="abc1234",
    )
    notes_file = note.append_note(repo, entry, date="2026-02-02")
    result = run_script(
        "promote-adr.py",
        "--from-note",
        str(notes_file),
        "--entry",
        "1",
        "--tags",
        "storage",
        cwd=repo,
    )
    assert result.returncode == 0, result.stderr
    adr_path = repo / result.stdout.strip()
    assert adr_path.name.endswith("-store-memory-in-git.md")
    first_id = adr_ids(repo)[0]
    meta, body = common.parse_frontmatter(adr_path.read_text(encoding="utf-8"))
    assert (
        meta["id"] == first_id
        and meta["must_read"] is True
        and meta["tags"] == "storage"
    )
    assert common.section(body, "Decision") == "Store memory in git"
    assert common.section(body, "Context") == "No service to run"
    assert common.section(body, "Alternatives") == "A vector DB"
    sources = common.section(body, "Sources")
    assert (
        "Commit abc1234" in sources
        and "entry 1" in sources
        and "Scope: docs/" in sources
    )

    index = (repo / common.ADR_DIR / "INDEX.md").read_text(encoding="utf-8")
    assert (
        f"| {first_id} | [Store memory in git]({adr_path.name}) | accepted |" in index
    )
    assert "| yes |" in index

    second = run_script(
        "promote-adr.py",
        "--title",
        "Second",
        "--context",
        "c",
        "--decision",
        "d",
        "--no-must-read",
        cwd=repo,
    )
    assert second.returncode == 0, second.stderr
    assert len(adr_ids(repo)) == 2
    index = (repo / common.ADR_DIR / "INDEX.md").read_text(encoding="utf-8")
    assert index.count("| ADR-") == 2 and "| no |" in index


def test_promote_supersedes_marks_old_adr(repo: Path) -> None:
    from conftest import run_script

    run_script(
        "promote-adr.py",
        "--title",
        "Old",
        "--context",
        "c",
        "--decision",
        "d",
        "--alternatives",
        "a",
        cwd=repo,
    )
    first_id = adr_ids(repo)[0]
    result = run_script(
        "promote-adr.py",
        "--title",
        "New",
        "--context",
        "c",
        "--decision",
        "d2",
        "--alternatives",
        "a",
        "--supersedes",
        first_id,
        cwd=repo,
    )
    assert result.returncode == 0, result.stderr
    old_meta, _ = common.parse_frontmatter(
        (repo / common.ADR_DIR / f"{first_id}-old.md").read_text(encoding="utf-8")
    )
    second_id = next(i for i in adr_ids(repo) if i != first_id)
    assert old_meta["status"] == "superseded" and old_meta["superseded_by"] == second_id
    assert old_meta["must_read"] is False
    new_meta, _ = common.parse_frontmatter(
        (repo / common.ADR_DIR / f"{second_id}-new.md").read_text(encoding="utf-8")
    )
    assert new_meta["supersedes"] == first_id
    index = (repo / common.ADR_DIR / "INDEX.md").read_text(encoding="utf-8")
    assert f"superseded (by {second_id})" in index
    assert "d2" in common.build_memory_context(repo)


def test_promote_requires_fields(repo: Path) -> None:
    from conftest import run_script

    result = run_script("promote-adr.py", "--title", "only", cwd=repo)
    assert result.returncode != 0


# --- memory-query -----------------------------------------------------------------


def test_query_finds_adrs_notes_docs_and_history(repo: Path) -> None:
    from conftest import run_script

    run_script(
        "promote-adr.py",
        "--title",
        "Runtime detection fails closed",
        "--context",
        "c",
        "--decision",
        "Unknown runtime skips bootstrap.",
        cwd=repo,
    )
    note = load("memory-note.py")
    note.append_note(
        repo,
        note.render_entry(
            decision="Detect runtime from payload",
            why="env vars lie",
            author="a",
            branch="main",
        ),
    )
    _commit(repo, "docs/runtime.md", "runtime notes: detection order")
    query = load("memory-query.py")
    out = query.query_memory(repo, ["runtime", "docs/runtime.md"])
    assert (
        "## ADRs" in out
        and adr_ids(repo)[0] in out
        and "Unknown runtime skips bootstrap." in out
    )
    assert "## Decision notes" in out and "Detect runtime from payload" in out
    assert "## Design docs" in out and "`docs/runtime.md`" in out
    assert "## Recent commits touching `docs/runtime.md`" in out
    assert "Nothing in ADRs" in query.query_memory(repo, ["zzzunmatched"])


def test_query_ranks_title_hits_first_and_emits_json(repo: Path) -> None:
    from conftest import run_script

    run_script(
        "promote-adr.py",
        "--title",
        "Cache policy",
        "--context",
        "c",
        "--decision",
        "cache for a day",
        "--alternatives",
        "a",
        cwd=repo,
    )
    run_script(
        "promote-adr.py",
        "--title",
        "Logging",
        "--context",
        "mentions cache once",
        "--decision",
        "d",
        "--alternatives",
        "a",
        cwd=repo,
    )
    query = load("memory-query.py")
    data = query.collect(repo, ["cache"])
    assert [a["id"] for a in data["adrs"]] == adr_ids(repo)
    assert data["adrs"][0]["score"] > data["adrs"][1]["score"]
    out = run_script("memory-query.py", "--json", "cache", cwd=repo)
    assert out.returncode == 0 and '"adrs"' in out.stdout


def test_log_colours_only_a_write_and_only_on_a_terminal(capsys, monkeypatch) -> None:
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setenv("AGENTMEMORY_COLOR", "always")
    common.log("wrote a note", wrote=True)
    common.log("ordinary line")
    err = capsys.readouterr().err
    assert common.GREEN in err.splitlines()[0] and common.RESET in err.splitlines()[0]
    assert common.GREEN not in err.splitlines()[1]

    monkeypatch.setenv("NO_COLOR", "1")
    common.log("wrote a note", wrote=True)
    assert common.GREEN not in capsys.readouterr().err  # NO_COLOR wins

    monkeypatch.delenv("AGENTMEMORY_COLOR")
    monkeypatch.delenv("NO_COLOR")
    common.log("wrote a note", wrote=True)
    assert common.GREEN not in capsys.readouterr().err  # captured output is not a tty


def test_concurrent_promotions_on_two_branches_do_not_collide(repo: Path) -> None:
    """The failure #52 was filed for: two branches each allocating an id."""
    from conftest import run_script

    run_script("bootstrap-repo.py", "--init", cwd=repo)
    run_git(repo, "add", "-A")
    run_git(repo, "commit", "-q", "-m", "opt in")
    base = run_git(repo, "rev-parse", "HEAD")

    run_git(repo, "checkout", "-q", "-b", "one")
    run_script(
        "promote-adr.py",
        "--title",
        "Queues",
        "--context",
        "c",
        "--decision",
        "d",
        "--alternatives",
        "a",
        cwd=repo,
    )
    run_git(repo, "add", "-A")
    run_git(repo, "commit", "-q", "-m", "adr one")

    run_git(repo, "checkout", "-q", base, "-b", "two")
    run_script(
        "promote-adr.py",
        "--title",
        "Caching",
        "--context",
        "c",
        "--decision",
        "d",
        "--alternatives",
        "a",
        cwd=repo,
    )
    run_git(repo, "add", "-A")
    run_git(repo, "commit", "-q", "-m", "adr two")

    # Both branches allocated an id for the same day, so the second is suffixed
    # locally; across branches the collision is what matters.
    ids = {
        common.adr_id_from_name(p.name)
        for ref in ("one", "two")
        for p in [
            Path(n) for n in run_git(repo, "ls-tree", "-r", "--name-only", ref).split()
        ]
        if p.name.startswith("ADR-") and p.name != "INDEX.md"
    }
    assert len(ids) == 2, f"two decisions must not share an id: {ids}"


def test_adr_id_from_name_reads_both_shapes() -> None:
    assert (
        common.adr_id_from_name("ADR-2026-09-06-a3f9-some-slug.md")
        == "ADR-2026-09-06-a3f9"
    )
    assert common.adr_id_from_name("ADR-2026-09-06-a3f9-x.md") == "ADR-2026-09-06-a3f9"
    assert common.adr_id_from_name("ADR-0007-legacy-slug.md") == "ADR-0007"
    assert common.adr_id_from_name("ADR-0007-2026-thing.md") == "ADR-0007"


def test_promoting_the_same_decision_twice_is_refused(repo: Path) -> None:
    from conftest import run_script

    args = [
        "promote-adr.py",
        "--title",
        "Retries use a queue",
        "--context",
        "c",
        "--decision",
        "Queue-backed retries",
        "--alternatives",
        "cron",
    ]
    assert run_script(*args, cwd=repo).returncode == 0
    again = run_script(*args, cwd=repo)
    assert again.returncode != 0
    assert "already records this decision today" in again.stderr
    assert len(adr_ids(repo)) == 1

    forced = run_script(*args, "--force", cwd=repo)
    assert forced.returncode == 0, forced.stderr
    assert len(adr_ids(repo)) == 2  # deliberate second copy


def test_a_different_decision_with_the_same_title_still_promotes(repo: Path) -> None:
    from conftest import run_script

    base = [
        "promote-adr.py",
        "--title",
        "Caching policy",
        "--context",
        "c",
        "--alternatives",
        "a",
    ]
    assert run_script(*base, "--decision", "cache for a day", cwd=repo).returncode == 0
    second = run_script(*base, "--decision", "cache for an hour", cwd=repo)
    assert second.returncode == 0, second.stderr
    assert len(adr_ids(repo)) == 2


def test_must_read_adrs_are_ordered_by_relevance(repo: Path) -> None:
    from conftest import run_script

    run_script("bootstrap-repo.py", "--init", cwd=repo)
    for title, tags in (
        ("Storage rule", "storage"),  # foundational
        ("Scripts rule", "scripts"),  # relevant once scripts/ is touched
        ("Frontend rule", "frontend"),  # neither
    ):
        run_script(
            "promote-adr.py",
            "--title",
            title,
            "--context",
            "c",
            "--decision",
            f"{title} decision",
            "--alternatives",
            "a",
            "--tags",
            tags,
            cwd=repo,
        )
    run_git(repo, "add", "-A")
    run_git(repo, "commit", "-q", "-m", "adrs")

    # Nothing touched yet: foundational leads, the rest keep a stable order.
    order = [t for t in common.build_memory_context(repo).split("### ") if "rule" in t]
    assert order[0].startswith("ADR") and "Storage rule" in order[0]

    # A branch that touches scripts/ pulls the scripts ADR ahead of frontend.
    run_git(repo, "checkout", "-q", "-b", "work")
    (repo / "scripts").mkdir(exist_ok=True)
    (repo / "scripts" / "x.py").write_text("x\n", encoding="utf-8")
    run_git(repo, "add", "-A")
    run_git(repo, "commit", "-q", "-m", "touch scripts")
    assert "scripts" in common.touched_areas(repo)
    context = common.build_memory_context(repo)
    assert context.index("Scripts rule") < context.index("Frontend rule")
    assert context.index("Storage rule") < context.index("Scripts rule")


def test_budget_counts_headings(repo: Path) -> None:
    from conftest import run_script

    run_script("bootstrap-repo.py", "--init", cwd=repo)
    for i in range(4):
        run_script(
            "promote-adr.py",
            "--title",
            f"Rule {i}",
            "--context",
            "c",
            "--decision",
            "word " * 40,
            "--alternatives",
            "a",
            cwd=repo,
        )
    cfg = {**common.DEFAULT_CONFIG, "context_budget_words": 120}
    context = common.build_memory_context(repo, cfg)
    assert common.word_count(context) <= 120 * 1.1
