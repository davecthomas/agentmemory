#!/usr/bin/env python3
"""Print a story-shaped, newest-first digest of recent decision memory.

Backs the ``news`` skill. Instead of three flat lists, the digest groups
what happened by day and, within a day, by branch or pull request, joining
decision notes to the commits that produced them and leading with the
largest cluster. ADRs that supersede others collapse to one line. Authors
and decision text are cleaned so the skill can read the digest aloud.
Deterministic; no LLM.

The digest remembers when it was last read (``news_last_read`` in
``.agents/memory/local/state.json``) and defaults to what is new since
then, so a quiet repo says "nothing new" instead of repeating the same
two weeks. ``--all`` ignores the watermark; ``--no-mark`` reads without
advancing it.
"""

from __future__ import annotations

import argparse
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from common import (
    LOCAL_DIR,
    MEMORY_DIR,
    dump_json,
    git,
    is_opted_in,
    list_adrs,
    list_notes,
    load_json,
    load_module,
    log,
    note_date,
    read_text,
    repo_root,
    safe_main,
    section,
    stamp,
)

PROMOTION_THRESHOLD: int = 3
MAX_DAYS: int = 7
MAX_CLUSTERS_PER_DAY: int = 6
MAX_ITEMS_PER_CLUSTER: int = 6
MAX_COMMITS: int = 60
DECISION_WORDS: int = 30


@dataclass
class Note:
    date: str
    scope: list[str]
    when: str
    author: str
    branch: str
    decision: str
    why: str
    commit: str


@dataclass
class Commit:
    sha: str
    date: str
    subject: str
    branch: str
    pr: str


@dataclass
class Cluster:
    key: str
    commits: list[Commit] = field(default_factory=list)
    notes: list[Note] = field(default_factory=list)

    @property
    def size(self) -> int:
        return len(self.commits) + len(self.notes)


def clean_author(raw: str) -> str:
    """``2355287-davecthomas`` -> ``davecthomas``.

    Args:
        raw: Author slug from a note header.

    Returns:
        str: Slug without a leading numeric id.
    """
    return re.sub(r"^\d+-", "", raw.strip())


def strip_prefix(text: str, branch: str) -> str:
    """Drop a leading ``<branch>: `` from decision or subject text.

    Args:
        text: Decision line or commit subject.
        branch: Branch name that may prefix it.

    Returns:
        str: Text without the prefix.
    """
    if branch and text.startswith(f"{branch}: "):
        return text[len(branch) + 2 :]
    return re.sub(r"^[a-z]+/[\w.-]+: ", "", text)


def parse_notes(root: Path, days: int) -> list[Note]:
    """Load note entries within the window, newest first.

    Args:
        root: Repository root.
        days: Window in days.

    Returns:
        list[Note]: Parsed entries.
    """
    notes: list[Note] = []
    for path in list_notes(root, days):
        for block in reversed(re.split(r"(?m)^## ", read_text(path))[1:]):
            header = block.splitlines()[0]
            parts = [p.strip() for p in header.split("·")]
            author = clean_author(parts[1]) if len(parts) > 1 else "unknown"
            branch = parts[2] if len(parts) > 2 else ""

            def grab(key: str) -> str:
                m = re.search(rf"^\*\*{key}:\*\*\s*(.+)$", block, re.MULTILINE)
                return m.group(1).strip() if m else ""

            scope_line = grab("Scope")
            notes.append(
                Note(
                    date=note_date(path),
                    scope=[s.strip() for s in scope_line.split(",") if s.strip()],
                    when=parts[0] if parts else note_date(path),
                    author=author,
                    branch=branch,
                    decision=strip_prefix(grab("Decision"), branch),
                    why=grab("Why"),
                    commit=grab("Commit"),
                )
            )
    return notes


def parse_commits(root: Path, limit: int) -> list[Commit]:
    """Load recent commits outside ``.agents/memory``, newest first.

    Args:
        root: Repository root.
        limit: Maximum commits.

    Returns:
        list[Commit]: Parsed commits with branch and PR number when present.
    """
    raw = git(
        [
            "log",
            f"--max-count={limit}",
            "--format=%h%x1f%at%x1f%s",
            "--",
            ".",
            f":(exclude){MEMORY_DIR}",
        ],
        root,
    )
    commits: list[Commit] = []
    for line in raw.splitlines():
        parts = line.split("\x1f")
        if len(parts) != 3:
            continue
        sha, epoch, subject = parts
        # Notes are dated in UTC; take the commit date in UTC too so one
        # day's work never splits across two headings at midnight.
        date = datetime.fromtimestamp(int(epoch), UTC).strftime("%Y-%m-%d")
        branch_m = re.match(r"^([a-z]+/[\w.-]+): ", subject)
        pr_m = re.search(r"\(#(\d+)\)\s*$", subject)
        commits.append(
            Commit(
                sha=sha,
                date=date,
                subject=subject,
                branch=branch_m.group(1) if branch_m else "",
                pr=pr_m.group(1) if pr_m else "",
            )
        )
    return commits


def build_clusters(
    commits: list[Commit], notes: list[Note]
) -> dict[str, list[Cluster]]:
    """Group commits and notes by day, then by branch or PR.

    Args:
        commits: Parsed commits.
        notes: Parsed notes.

    Returns:
        dict[str, list[Cluster]]: Day -> clusters, largest first.
    """
    by_day: dict[str, dict[str, Cluster]] = defaultdict(dict)
    for c in commits:
        key = c.branch or (f"#{c.pr}" if c.pr else "other")
        by_day[c.date].setdefault(key, Cluster(key)).commits.append(c)
    sha_to_key = {
        c.sha: (c.date, c.branch or (f"#{c.pr}" if c.pr else "other")) for c in commits
    }
    for n in notes:
        if n.commit and n.commit in sha_to_key:
            day, key = sha_to_key[n.commit]
        else:
            day, key = n.date, n.branch or "notes"
        by_day[day].setdefault(key, Cluster(key)).notes.append(n)
    return {
        day: sorted(clusters.values(), key=lambda cl: (-cl.size, cl.key))
        for day, clusters in by_day.items()
    }


def adr_lines(root: Path, days_set: set[str]) -> dict[str, list[str]]:
    """Render ADRs dated within the shown days, collapsing supersession.

    Args:
        root: Repository root.
        days_set: Days present in the digest.

    Returns:
        dict[str, list[str]]: Day -> rendered lines.
    """
    out: dict[str, list[str]] = defaultdict(list)
    for adr in reversed(list_adrs(root)):
        meta = adr["meta"]
        date = str(meta.get("date", ""))
        if date not in days_set:
            continue
        decision = " ".join(section(adr["body"], "Decision").split()[:DECISION_WORDS])
        verb = f" replaces {meta['supersedes']}: " if meta.get("supersedes") else ": "
        must = "" if meta.get("must_read") is True else " _(not injected)_"
        out[date].append(f"- {meta['id']}{verb}{meta['title']}{must} — {decision}…")
    return out


def read_watermark(root: Path) -> tuple[str, str]:
    """Return ``(last_read_stamp, last_read_sha)`` or empty strings.

    Args:
        root: Repository root.

    Returns:
        tuple[str, str]: Minute-precision UTC stamp and the HEAD sha at that read.
    """
    state = load_json(root / LOCAL_DIR / "state.json", {})
    if not isinstance(state, dict):
        return "", ""
    return str(state.get("news_last_read", "")), str(
        state.get("news_last_read_sha", "")
    )


def write_watermark(root: Path) -> None:
    """Record now and HEAD as the last news read, keeping other state keys.

    Args:
        root: Repository root.
    """
    path = root / LOCAL_DIR / "state.json"
    state = load_json(path, {})
    if not isinstance(state, dict):
        state = {}
    state["news_last_read"] = stamp()
    state["news_last_read_sha"] = git(["rev-parse", "HEAD"], root)
    dump_json(path, state)


def promotion_candidates(
    notes: list[Note], threshold: int
) -> list[tuple[str, list[Note]]]:
    """Group notes by the path they scope, where a group is large enough to promote.

    Notes are cheap and ADR promotion is explicit (ADR-0005), and nothing
    bridged the two except somebody noticing. Several notes scoping one path
    inside the window is the signal that a decision there has settled and
    deserves an ADR.

    Args:
        notes: Parsed notes, newest first.
        threshold: How many notes on one path make a candidate.

    Returns:
        list[tuple[str, list[Note]]]: ``(path, notes)``, largest group first.
    """
    by_path: dict[str, list[Note]] = defaultdict(list)
    for note in notes:
        for scope in note.scope:
            by_path[scope].append(note)
    groups = [(p, ns) for p, ns in by_path.items() if len(ns) >= threshold]
    return sorted(groups, key=lambda g: (-len(g[1]), g[0]))


def news(root: Path, days: int, *, since_last_read: bool = True) -> str:
    """Build the digest.

    Args:
        root: Repository root.
        days: Window for notes and commits when there is no watermark or
            ``since_last_read`` is False.
        since_last_read: Show only what is new since the last read.

    Returns:
        str: Markdown.
    """
    if not is_opted_in(root):
        return "agentmemory: not opted in. Run `/agentmemory init` first.\n"
    last_read, last_sha = read_watermark(root) if since_last_read else ("", "")
    notes = parse_notes(root, days if not last_read else 3650)
    commits = parse_commits(root, MAX_COMMITS)
    if last_read:
        notes = [n for n in notes if n.when > last_read]
        if last_sha and git(["cat-file", "-t", last_sha], root) == "commit":
            new_shas = set(
                git(["log", "--format=%h", f"{last_sha}..HEAD"], root).split()
            )
            commits = [c for c in commits if c.sha in new_shas]
        if not notes and not commits:
            return (
                f"# Repo news\n\nNothing new since you last read news at {last_read}. "
                "Run with --all for the recent history.\n"
            )
    clusters = build_clusters(commits, notes)
    shown_days = sorted(clusters, reverse=True)[:MAX_DAYS]
    adrs = adr_lines(root, set(shown_days))

    out: list[str] = ["# Repo news", ""]
    if last_read:
        out += [f"_New since you last read news at {last_read}._", ""]
    catchup = read_text(root / LOCAL_DIR / "catchup.md").strip()
    if catchup:
        out += ["## Since this machine last pulled", "", catchup, ""]

    for day in shown_days:
        day_clusters = clusters[day]
        n_commits = sum(len(c.commits) for c in day_clusters)
        n_notes = sum(len(c.notes) for c in day_clusters)
        n_adrs = len(adrs.get(day, []))
        summary = ", ".join(
            s
            for s in (
                (
                    f"{n_commits} commit{'s' if n_commits != 1 else ''}"
                    if n_commits
                    else ""
                ),
                (
                    f"{n_notes} decision note{'s' if n_notes != 1 else ''}"
                    if n_notes
                    else ""
                ),
                f"{n_adrs} ADR{'s' if n_adrs != 1 else ''}" if n_adrs else "",
            )
            if s
        )
        out += [f"## {day} — {summary}", ""]
        for i, cl in enumerate(day_clusters[:MAX_CLUSTERS_PER_DAY]):
            prs = sorted({c.pr for c in cl.commits if c.pr})
            label = cl.key + (
                f" (#{', #'.join(prs)})" if prs and not cl.key.startswith("#") else ""
            )
            lead = " — largest" if i == 0 and len(day_clusters) > 1 else ""
            out.append(f"### {label}{lead}")
            for n in cl.notes[:MAX_ITEMS_PER_CLUSTER]:
                out.append(f"- decision ({n.author}): {n.decision}")
            for c in cl.commits[:MAX_ITEMS_PER_CLUSTER]:
                out.append(f"- {c.sha} {strip_prefix(c.subject, c.branch)}")
            out.append("")
        if adrs.get(day):
            out += ["### ADRs", *adrs[day], ""]

    audit = load_module(Path(__file__).resolve().parent / "memory-audit.py")
    stale = audit.stale_adrs(root)
    if stale:
        out += ["## ADRs worth re-reading", ""]
        for commits, adr_id, title, scope in stale[:2]:
            out.append(
                f"- {adr_id} ({title}) governs `{scope}`, changed in {commits} "
                "commits since the decision."
            )
        out.append("")

    candidates = promotion_candidates(notes, PROMOTION_THRESHOLD)
    if candidates:
        out += ["## Worth promoting to an ADR", ""]
        for path, group in candidates[:3]:
            dates = ", ".join(sorted({n.date for n in group}))
            out.append(
                f"- `{path}` has {len(group)} decisions noted ({dates}). "
                "If one governs the code now, promote it with `adr-promoter`."
            )
        out.append("")
    if len(out) == 2:
        out.append(
            "No decision memory yet. Run `/memory-bootstrap` to seed it from docs and history."
        )
    return "\n".join(out).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=None)
    parser.add_argument("--days", type=int, default=14)
    parser.add_argument("--all", action="store_true", help="ignore the read watermark")
    parser.add_argument("--no-mark", action="store_true", help="do not advance it")
    args = parser.parse_args()
    root = repo_root(args.repo_root)
    if root is None:
        log("memory-news: not inside a git repository")
        return 1
    print(news(root, args.days, since_last_read=not args.all), end="")
    if not args.no_mark and is_opted_in(root):
        write_watermark(root)
    return 0


if __name__ == "__main__":
    raise SystemExit(safe_main(main, "memory-news"))
