---
name: news
description: Tells a developer what changed in this repo's decision memory since they last looked, as a short narrative with a fixed shape, from the memory-news.py digest.
license: MIT
---

# Summarize Recent Repo News

## Keywords

news, what's new, what happened, what did I miss, catch me up, recent decisions, recent changes, anything new lately, since I was away

## When to Use This Skill

- A developer asks what is new or what they missed
- A developer returns to a repo after time away

---

## Workflow

1. If `.agents/memory/config.json` is missing, say the repo has not opted in and point at `/agentmemory init`. Stop.
2. Run the digest. It is grouped by day and branch, newest first, and defaults to what is new since the last read:

   ```bash
   python3 "$HOME/.agent/shared-repo-memory/memory-news.py"
   ```

   Add `--all` when the developer asks for the recent history rather than what is new, or `--days N` for a longer window.
3. If the digest says "Nothing new since …", report exactly that with the stamp, and offer `--all`. Do not pad a quiet repo.
4. If there are no ADRs and no notes at all, say "No decision memory yet; running memory-bootstrap" and invoke `memory-bootstrap`, then report its output as the first news.
5. Otherwise write the report in this shape, and only this shape:

   **What happened** — one paragraph, lead cluster first. Say who (from the `decision (name)` lines), when (the day headings), and what the largest cluster was about. Mention smaller clusters in a clause each. No bullet list here.

   **Decisions you should know** — one bullet per ADR line and per non-candidate note that changes how someone works in this repo. Keep the ADR id and, when the line says `replaces`, say what it replaced. Mark `_(not injected)_` ADRs as "reachable with the `memory` skill".

   **Unreviewed candidates: N** — one bullet each, then one sentence: promote with `adr-promoter`, or dismiss it with `memory-note.py --dismiss <file> <entry>`. Omit the section when N is 0.

6. Keep the whole report under 250 words. Quote the digest's decision text; do not invent mechanisms it does not mention.

## Rules

- The digest is the source. Do not read note files or ADRs directly unless the developer asks about one.
- Never edit memory files from this skill.
