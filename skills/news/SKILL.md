---
name: news
description: Summarizes what changed in this repo's decision memory recently, from decision notes, ADRs, the local catch-up digest, and git history, and offers memory-bootstrap when a repo is opted in but has no memory yet.
license: MIT
---

# Summarize Recent Repo News

## Keywords

news, what's new, what happened, what did I miss, catch me up, recent decisions, recent changes, anything new lately

## When to Use This Skill

- A developer asks what is new or what they missed
- A developer returns to a repo after time away

---

## Workflow

1. If `.agents/memory/config.json` is missing, say the repo has not opted in and point at `/agentmemory init`. Stop.
2. Run the digest and read it; it is bounded and newest first:

   ```bash
   python3 "$HOME/.agent/shared-repo-memory/memory-news.py" [--days 14]
   ```

   It prints the catch-up since this machine last looked, the newest note entries with `Candidate: true` flagged, the newest ADRs, and recent code commits that memory does not mention.
3. If there are no ADRs and no notes, say "No decision memory yet; running memory-bootstrap" and invoke `memory-bootstrap`, then report its output as the first news.
4. Report in this order: durable decisions (ADRs), recent decisions (notes, flagging `Candidate: true` entries as unreviewed), then notable code changes. Name authors from the note headers. Say when the last recorded item was, so a quiet repo reads as quiet rather than empty.
5. Suggest promotion for any note that reads like an architectural decision, and say which entry number to pass to `adr-promoter`.
