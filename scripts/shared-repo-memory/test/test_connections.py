"""Tests for repo-connections.py."""

from __future__ import annotations

from pathlib import Path

import common
from conftest import load, run_git, run_script


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
    assert found["acme/shared-lib"]["kind"] == "submodule"
    assert found["acme/py-client"]["kind"] == "dependency"
    assert found["acme/shared-action"]["kind"] == "workflow"
    assert "gitlab" not in str(found)  # a different host is not a team edge
    assert "actions/checkout" not in found  # published tooling is not an edge


def test_own_repository_is_never_its_own_connection(repo: Path) -> None:
    conn = load("repo-connections.py")
    _origin(repo, "acme/app")
    (repo / ".gitmodules").write_text(
        "\turl = git@github.com:acme/app.git\n", encoding="utf-8"
    )
    assert conn.discover(repo) == []


def test_hand_written_entries_survive_rediscovery(repo: Path) -> None:
    conn = load("repo-connections.py")
    _origin(repo)
    common.dump_json(
        repo / common.CONFIG_FILE,
        {
            "connections": [
                {
                    "repo": "acme/manual",
                    "kind": "runtime",
                    "evidence": "declared by hand",
                }
            ]
        },
    )
    (repo / ".gitmodules").write_text(
        "\turl = git@github.com:acme/found.git\n", encoding="utf-8"
    )
    merged = {c["repo"]: c for c in conn.write(repo)}
    assert set(merged) == {"acme/manual", "acme/found"}
    assert merged["acme/manual"]["evidence"] == "declared by hand"
    assert merged["acme/found"]["discovered"] == common.today()

    again = {c["repo"]: c for c in conn.write(repo)}
    assert set(again) == {"acme/manual", "acme/found"}  # stable across runs


def test_init_records_connections(repo: Path) -> None:
    _origin(repo)
    (repo / ".gitmodules").write_text(
        "\turl = git@github.com:acme/shared-lib.git\n", encoding="utf-8"
    )
    result = run_script("bootstrap-repo.py", "--init", cwd=repo)
    assert result.returncode == 0, result.stderr
    assert "1 connected repository" in result.stderr
    config = common.load_config(repo)
    assert [c["repo"] for c in config["connections"]] == ["acme/shared-lib"]
