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
Entries a person added by hand are preserved.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from common import (
    CONFIG_FILE,
    dump_json,
    git,
    load_config,
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


def _add(found: dict[str, dict[str, str]], slug: str, kind: str, evidence: str) -> None:
    """Record one edge, keeping the first evidence seen for a repository."""
    found.setdefault(slug, {"repo": slug, "kind": kind, "evidence": evidence})


def discover(root: Path) -> list[dict[str, str]]:
    """Find this repository's connections, sorted by repository name.

    Args:
        root: Repository root.

    Returns:
        list[dict[str, str]]: ``repo``, ``kind`` and ``evidence`` per edge.
    """
    host, own = own_identity(root)
    found: dict[str, dict[str, str]] = {}

    def same_host(match: re.Match[str]) -> bool:
        return bool(host) and match.group("host") == host

    modules: str = read_text(root / ".gitmodules")
    for match in _URL.finditer(modules + " "):
        if same_host(match) and match.group("slug") != own:
            _add(found, match.group("slug"), "submodule", ".gitmodules")

    for name in MANIFESTS:
        text: str = read_text(root / name)
        for match in _URL.finditer(text + " "):
            if same_host(match) and match.group("slug") != own:
                _add(found, match.group("slug"), "dependency", name)

    for workflow in sorted((root / ".github" / "workflows").glob("*.y*ml")):
        text = read_text(workflow)
        rel: str = workflow.relative_to(root).as_posix()
        for pattern in (_ACTION, _ACTION_REPO):
            for match in pattern.finditer(text):
                slug = match.group("slug")
                # A published action from another org is tooling, not a team edge.
                if own and slug != own and slug.split("/")[0] == own.split("/")[0]:
                    _add(found, slug, "workflow", rel)
    return sorted(found.values(), key=lambda c: c["repo"])


def merge(
    existing: list[Any], discovered: list[dict[str, str]]
) -> list[dict[str, Any]]:
    """Combine discovered edges with any a person added by hand.

    A hand-written entry wins: someone recorded a relationship the manifests do
    not show, and rediscovery must not erase it.

    Args:
        existing: Connections already in the config.
        discovered: Output of ``discover``.

    Returns:
        list[dict[str, Any]]: Merged list, sorted by repository name.
    """
    by_repo: dict[str, dict[str, Any]] = {}
    for entry in discovered:
        by_repo[entry["repo"]] = {**entry, "discovered": today()}
    for entry in existing:
        if isinstance(entry, dict) and entry.get("repo"):
            if (
                entry.get("evidence") == "declared by hand"
                or entry["repo"] not in by_repo
            ):
                by_repo[entry["repo"]] = entry
    return sorted(by_repo.values(), key=lambda c: str(c["repo"]))


def write(root: Path) -> list[dict[str, Any]]:
    """Refresh the ``connections`` list in the repository's memory config.

    Args:
        root: Repository root.

    Returns:
        list[dict[str, Any]]: The merged connections.
    """
    path: Path = root / CONFIG_FILE
    config: dict[str, Any] = json.loads(read_text(path)) if path.is_file() else {}
    merged = merge(config.get("connections", []), discover(root))
    config["connections"] = merged
    dump_json(path, config)
    return merged


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=None)
    parser.add_argument("--write", action="store_true", help="update config.json")
    args = parser.parse_args()
    root = repo_root(args.repo_root)
    if root is None:
        log("repo-connections: not inside a git repository")
        return 1
    found = write(root) if args.write else load_config(root).get("connections", [])
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
