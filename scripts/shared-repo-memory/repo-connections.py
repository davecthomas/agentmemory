#!/usr/bin/env python3
"""Discover which other repositories this one is connected to.

A decision recorded here often governs code that lives elsewhere, and the
reverse: a platform repository's decision governs the services that depend on
it. Rather than a registry of every repository an organisation owns, each
repository declares its own edges, so the record travels with the repository
that has them and needs nobody's permission to write.

Discovery is deterministic and offline. It reads what the repository already
says about its dependencies:

* ``.gitmodules`` submodules
* git dependency URLs in ``package.json``, ``pyproject.toml``,
  ``requirements*.txt``, ``go.mod`` and ``Cargo.toml``
* ``uses:`` and ``repository:`` references in GitHub Actions workflows

Only references on the same host as this repository's own remote count, so a
public dependency on an unrelated project is not mistaken for a team edge.

The result is written to ``.agents/memory/connections.json`` in the shape
``schemas/repo-connections.schema.json`` defines. Discovery can only establish
the halves a repository's own files show, so every discovered relationship has
role ``dependency``. The opposite halves, and any API relationship, are added
by hand or by a generator with wider access, and rediscovery leaves those
alone.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Any

from common import (
    CONNECTIONS_FILE,
    CONNECTIONS_SCHEMA_VERSION,
    dump_json,
    git,
    load_json,
    log,
    read_text,
    repo_root,
    safe_main,
    today,
)

# owner/repo out of an ssh or https git URL, with any .git suffix dropped.
_URL: re.Pattern[str] = re.compile(
    r"(?:git@|https://|ssh://git@)(?P<host>[\w.-]+)[:/](?P<slug>[\w.-]+/[\w.-]+?)(?:\.git)?(?:[/@#\s\"']|$)"
)
_ACTION: re.Pattern[str] = re.compile(
    r"^\s*(?:-\s*)?uses:\s*(?P<slug>[\w.-]+/[\w.-]+)@", re.MULTILINE
)
_ACTION_REPO: re.Pattern[str] = re.compile(
    r"^\s*repository:\s*(?P<slug>[\w.-]+/[\w.-]+)\s*$", re.MULTILINE
)
MANIFESTS: tuple[str, ...] = (
    "package.json",
    "pyproject.toml",
    "go.mod",
    "Cargo.toml",
    "requirements.txt",
    "requirements-dev.txt",
)


def own_identity(root: Path) -> tuple[str, str]:
    """Return this repository's ``(host, owner/repo)`` from its remote.

    Args:
        root: Repository root.

    Returns:
        tuple[str, str]: Host and slug, empty strings when there is no remote.
    """
    for name in git(["remote"], root).split():
        match = _URL.search(git(["remote", "get-url", name], root) + " ")
        if match:
            return match.group("host"), match.group("slug")
    return "", ""


def _add(found: dict[str, dict[str, str]], slug: str, evidence: str) -> None:
    """Record one edge, keeping the first evidence seen for a repository.

    Every discovered edge has role ``dependency``: it comes from this
    repository declaring that it needs another. Whether that other repository
    depends on this one is not visible from here, and is not guessed.
    """
    found.setdefault(slug, {"repo": slug, "role": "dependency", "evidence": evidence})


def discover(root: Path) -> list[dict[str, str]]:
    """Find this repository's connections, sorted by repository name.

    Args:
        root: Repository root.

    Returns:
        list[dict[str, str]]: ``repo``, ``role`` and ``evidence`` per edge.
    """
    host, own = own_identity(root)
    found: dict[str, dict[str, str]] = {}

    def same_host(match: re.Match[str]) -> bool:
        return bool(host) and match.group("host") == host

    modules: str = read_text(root / ".gitmodules")
    for match in _URL.finditer(modules + " "):
        if same_host(match) and match.group("slug") != own:
            _add(found, match.group("slug"), ".gitmodules")

    for name in MANIFESTS:
        text: str = read_text(root / name)
        for match in _URL.finditer(text + " "):
            if same_host(match) and match.group("slug") != own:
                _add(found, match.group("slug"), name)

    for workflow in sorted((root / ".github" / "workflows").glob("*.y*ml")):
        text = read_text(workflow)
        rel: str = workflow.relative_to(root).as_posix()
        for pattern in (_ACTION, _ACTION_REPO):
            for match in pattern.finditer(text):
                slug = match.group("slug")
                # A published action from another org is tooling, not a team edge.
                if own and slug != own and slug.split("/")[0] == own.split("/")[0]:
                    _add(found, slug, rel)
    return sorted(found.values(), key=lambda c: c["repo"])


def write(root: Path) -> list[dict[str, Any]]:
    """Rewrite ``.agents/memory/connections.json`` from what discovery finds.

    The file is generated: every run overwrites it. A relationship the
    manifests cannot show is recorded elsewhere, not here.

    Args:
        root: Repository root.

    Returns:
        list[dict[str, Any]]: The discovered relationships.
    """
    related = discover(root)
    _, own = own_identity(root)
    dump_json(
        root / CONNECTIONS_FILE,
        {
            "schema_version": CONNECTIONS_SCHEMA_VERSION,
            "repo": own,
            "generated_at": today(),
            "related": related,
        },
    )
    return related


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=None)
    parser.add_argument("--write", action="store_true", help="update config.json")
    args = parser.parse_args()
    root = repo_root(args.repo_root)
    if root is None:
        log("repo-connections: not inside a git repository")
        return 1
    found = (
        write(root)
        if args.write
        else load_json(root / CONNECTIONS_FILE, {}).get("related", [])
    )
    if args.write:
        log(f"recorded {len(found)} connection{'s' if len(found) != 1 else ''}")
    if not found:
        print("No connections to other repositories found.")
        return 0
    print("# Connected repositories\n")
    for entry in found:
        print(
            f"- {entry['repo']} ({entry.get('kind', 'unknown')}, from {entry.get('evidence', '?')})"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(safe_main(main, "repo-connections"))
