from __future__ import annotations

import subprocess
from pathlib import Path

import pytest


def make_post_text(*, draft: bool = False, title: str = "T", description: str = "d", extra: str = "", tags: str = "[a]") -> str:
    return (
        f'---\ntitle: "{title}"\ndescription: "{description}"\ndate: 2026-11-17\ntags: {tags}\n'
        f"draft: {str(draft).lower()}\n---\nbody {extra}\n"
    )


class Repo:
    """A throwaway git repo with the blog's post directory."""

    def __init__(self, root: Path):
        self.root = root
        self.posts = root / "src/content/posts"
        self.posts.mkdir(parents=True)
        self._git("init", "-b", "main")
        self._git("config", "user.email", "test@example.com")
        self._git("config", "user.name", "Test")

    def _git(self, *args: str) -> str:
        return subprocess.run(["git", *args], cwd=self.root, check=True, capture_output=True, text=True).stdout.strip()

    def write(self, name: str, text: str) -> None:
        (self.posts / name).write_text(text, encoding="utf-8")

    def commit(self, message: str = "c") -> str:
        self._git("add", "-A")
        self._git("commit", "-qm", message)
        return self.head()

    def head(self) -> str:
        return self._git("rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path: Path) -> Repo:
    return Repo(tmp_path / "repo")
