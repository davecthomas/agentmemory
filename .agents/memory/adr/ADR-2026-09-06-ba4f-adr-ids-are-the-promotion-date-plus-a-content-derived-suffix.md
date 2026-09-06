---
id: "ADR-2026-09-06-ba4f"
title: "ADR ids are the promotion date plus a content-derived suffix"
status: "accepted"
date: "2026-09-06"
tags: "scripts"
must_read: true
supersedes: ""
superseded_by: ""
---

# ADR-2026-09-06-ba4f: ADR ids are the promotion date plus a content-derived suffix

## Context

next_id() allocated the next sequential number by scanning the local adr/ directory, which is one branch's view of the world. Two developers promoting in the same window both took ADR-0001 and merged into a repository where two decisions claimed one id, making --supersedes ambiguous and every cross-reference unresolvable. A simulation of two clones reproduced it on the first try (#52). Dating the id to the day was not enough: two people promoting on the same day, which is the ordinary case, still collided.

## Decision

An ADR id is ADR-YYYY-MM-DD-hhhh, where the four hex characters are the first of a SHA-256 over the ADR's title and decision text. The date sorts and reads; the suffix makes the id unique wherever it was written, with no coordination and no allocation step. On the rare local collision the seed is salted until free. Filenames are ADR-YYYY-MM-DD-hhhh-<slug>.md, and common.adr_id_from_name() is the single parser, which also reads the older ADR-NNNN shape so existing repositories keep working.

## Alternatives

Keep sequential numbers and renumber at merge with a driver or CI step: rejected because it rewrites history on merge and needs machinery on every clone. Date only: rejected, two people promoting the same day still collide. Author plus date: rejected, one person on two branches on the same day still collides and cannot see it. Pure content hash with no date: rejected, ids stop sorting and reading chronologically.

## Consequences

Ids are longer and no longer countable at a glance; 'ADR-0007' becomes 'ADR-2026-09-06-a3f9'. Tests discover ids rather than predicting them, through the adr_ids() helper. Anything parsing an id must go through adr_id_from_name(); four call sites did and now share it.

## Sources

- #52
- scripts/shared-repo-memory/promote-adr.py
