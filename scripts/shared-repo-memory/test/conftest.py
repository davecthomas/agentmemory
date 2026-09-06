"""Shared fixtures: a throwaway git repo and the scripts loaded as modules."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

SCRIPTS: Path = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))

import common  # noqa: E402

# Generated hooks resolve scripts from this variable first, so a test repo's
# hooks run the checkout's code rather than whatever is installed in $HOME.
os.environ["AGENTMEMORY_SCRIPTS"] = str(SCRIPTS)

# git exports GIT_DIR, GIT_INDEX_FILE and friends to every hook subprocess.
# The suite runs from this repo's pre-commit hook, and a fixture that shells
# out to `git init` while those point at the real repository writes into it
# instead of the temporary one. Scrub them so a test repo is always hermetic.
for _var in [k for k in os.environ if k.startswith("GIT_")]:
    if _var not in {"GIT_ASKPASS", "GIT_SSH", "GIT_SSH_COMMAND"}:
        del os.environ[_var]


def run_git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=root, capture_output=True, text=True, check=True
    ).stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """An initialised git repo with one commit and an identity configured."""
    root: Path = tmp_path / "repo"
    root.mkdir()
    run_git(root, "init", "-q", "-b", "main")
    run_git(root, "config", "user.email", "alice@example.com")
    run_git(root, "config", "user.name", "Alice Example")
    run_git(root, "config", "commit.gpgsign", "false")
    (root / "README.md").write_text("# demo\n", encoding="utf-8")
    run_git(root, "add", "README.md")
    run_git(root, "commit", "-q", "-m", "initial")
    return root


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A fake HOME so install/uninstall never touch the real one."""
    fake: Path = tmp_path / "home"
    fake.mkdir()
    monkeypatch.setenv("HOME", str(fake))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake))
    return fake


def load(name: str) -> ModuleType:
    return common.load_module(SCRIPTS / name)


def run_script(
    name: str, *args: str, cwd: Path, stdin: str = "", env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    merged: dict[str, str] = {**os.environ, **(env or {})}
    return subprocess.run(
        [sys.executable, str(SCRIPTS / name), *args],
        cwd=cwd,
        input=stdin,
        capture_output=True,
        text=True,
        env=merged,
    )


def adr_ids(root: Path) -> list[str]:
    """Ids of the ADRs in a repo, in filename order.

    Ids carry a content-derived suffix, so a test discovers them rather than
    predicting them.
    """
    return [str(a["meta"]["id"]) for a in common.list_adrs(root)]
