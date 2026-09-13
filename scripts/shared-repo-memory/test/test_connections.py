"""Tests for repo-connections.py."""

from __future__ import annotations

from pathlib import Path

import common
from conftest import SCRIPTS, load, run_git, run_script


def _origin(repo: Path, slug: str = "acme/app") -> None:
    run_git(repo, "remote", "add", "origin", f"git@github.com:{slug}.git")


def test_discovers_submodules_dependencies_and_workflows(repo: Path) -> None:
    conn = load("repo-connections.py")
    _origin(repo)
    (repo / ".gitmodules").write_text(
        '[submodule "shared"]\n\tpath = shared\n'
        "\turl = git@github.com:acme/shared-lib.git\n",
        encoding="utf-8",
    )
    (repo / "pyproject.toml").write_text(
        'dep = {git = "ssh://git@github.com/acme/py-client.git"}\n'
        'other = {git = "https://gitlab.com/acme/elsewhere.git"}\n',  # another host
        encoding="utf-8",
    )
    workflows = repo / ".github" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "ci.yml").write_text(
        "jobs:\n  x:\n    steps:\n"
        "      - uses: actions/checkout@v4\n"  # another org: tooling
        "      - uses: acme/shared-action@v1\n"  # same org: an edge
        "      - uses: actions/checkout@v4\n"
        "        with:\n          repository: acme/tools\n",
        encoding="utf-8",
    )

    found = {c["repo"]: c for c in conn.discover(repo)}
    assert set(found) == {
        "acme/shared-lib",
        "acme/py-client",
        "acme/shared-action",
        "acme/tools",
    }
    # Discovery establishes only this repository's own half of an edge.
    assert {c["role"] for c in found.values()} == {"dependency"}
    assert found["acme/shared-lib"]["evidence"] == ".gitmodules"
    assert found["acme/py-client"]["evidence"] == "pyproject.toml"
    assert found["acme/shared-action"]["evidence"].endswith("ci.yml")
    assert "gitlab" not in str(found)  # a different host is not a team edge
    assert "actions/checkout" not in found  # published tooling is not an edge


def test_own_repository_is_never_its_own_connection(repo: Path) -> None:
    conn = load("repo-connections.py")
    _origin(repo, "acme/app")
    (repo / ".gitmodules").write_text(
        "\turl = git@github.com:acme/app.git\n", encoding="utf-8"
    )
    assert conn.discover(repo) == []


def test_init_records_connections(repo: Path) -> None:
    _origin(repo)
    (repo / ".gitmodules").write_text(
        "\turl = git@github.com:acme/shared-lib.git\n", encoding="utf-8"
    )
    result = run_script("bootstrap-repo.py", "--init", cwd=repo)
    assert result.returncode == 0, result.stderr
    assert "1 connected repository" in result.stderr
    document = common.load_json(repo / common.CONNECTIONS_FILE, {})
    assert [c["repo"] for c in document["related"]] == ["acme/shared-lib"]
    assert document["related"][0]["role"] == "dependency"


def test_document_validates_against_the_schema(repo: Path) -> None:
    """The written document is the shape schemas/repo-connections.schema.json defines."""
    conn = load("repo-connections.py")
    _origin(repo)
    (repo / ".gitmodules").write_text(
        "\turl = git@github.com:acme/shared-lib.git\n", encoding="utf-8"
    )
    conn.write(repo)
    document = common.load_json(repo / common.CONNECTIONS_FILE, {})

    schema = common.load_json(
        SCRIPTS.parents[1] / "schemas" / "repo-connections.schema.json", {}
    )
    required = set(schema["required"])
    assert required <= set(document), f"missing {required - set(document)}"
    assert set(document) <= set(schema["properties"]), "undeclared top-level key"

    rel_schema = schema["$defs"]["relationship"]
    for entry in document["related"]:
        assert set(rel_schema["required"]) <= set(entry)
        assert set(entry) <= set(rel_schema["properties"])
        assert entry["role"] in rel_schema["properties"]["role"]["enum"]
        assert entry["repo"] != document["repo"]
