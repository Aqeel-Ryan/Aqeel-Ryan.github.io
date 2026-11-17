"""Shared post parsing. The slug rule must match src/lib/urls.ts `slugFromId`."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent
POSTS_DIR = "src/content/posts"
_FM_RE = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n?(.*)\Z", re.S)
_DATE_PREFIX = re.compile(r"^\d{4}-\d{2}-\d{2}-")


class PostError(ValueError):
    """Raised when a post file is malformed."""


def site_config(root: Path = ROOT) -> dict[str, Any]:
    return json.loads((root / "site.config.json").read_text(encoding="utf-8"))


def site_url(root: Path = ROOT) -> str:
    return str(site_config(root)["siteUrl"]).rstrip("/")


def slug_from_filename(name: str) -> str:
    """`2026-11-17-my-post.md` -> `my-post` (same as slugFromId in src/lib/urls.ts)."""
    stem = Path(name).name
    if stem.endswith(".md"):
        stem = stem[:-3]
    return _DATE_PREFIX.sub("", stem).lower()


def canonical_url(slug: str, base: str) -> str:
    return f"{base.rstrip('/')}/posts/{slug}/"


def split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    m = _FM_RE.match(text)
    if not m:
        raise PostError("missing or malformed frontmatter")
    try:
        data = yaml.safe_load(m.group(1)) or {}
    except (yaml.YAMLError, ValueError) as e:
        # PyYAML raises a bare ValueError for impossible dates such as 2026-13-45.
        raise PostError(f"invalid YAML frontmatter: {e}") from e
    if not isinstance(data, dict):
        raise PostError("frontmatter must be a mapping")
    return data, m.group(2)


@dataclass
class Post:
    slug: str
    path: str
    title: str
    description: str
    date: date
    tags: list[str] = field(default_factory=list)
    draft: bool = False
    linkedin: bool = True
    cover: str | None = None
    project_repo: str | None = None
    body: str = ""

    def summary(self) -> dict[str, Any]:
        return {"slug": self.slug, "path": self.path, "title": self.title, "linkedin": self.linkedin}


def parse_post(text: str, path: str) -> Post:
    fm, body = split_frontmatter(text)
    for key in ("title", "description", "date"):
        if not fm.get(key):
            raise PostError(f"{path}: frontmatter missing required field '{key}'")
    raw_date = fm["date"]
    if isinstance(raw_date, datetime):
        d = raw_date.date()
    elif isinstance(raw_date, date):
        d = raw_date
    else:
        try:
            d = date.fromisoformat(str(raw_date))
        except ValueError as e:
            raise PostError(f"{path}: date is not YYYY-MM-DD: {raw_date!r}") from e
    if len(str(fm["description"])) > 300:
        raise PostError(f"{path}: description longer than 300 characters")
    tags = fm.get("tags", []) or []
    if not isinstance(tags, list) or not all(isinstance(t, str) and t for t in tags):
        raise PostError(f"{path}: tags must be a list of non-empty strings")
    for flag in ("draft", "linkedin"):
        if flag in fm and not isinstance(fm[flag], bool):
            raise PostError(f"{path}: {flag} must be true or false")
    if "canonical_url" in fm:
        raise PostError(f"{path}: canonical_url must not be authored; it is derived")
    return Post(
        slug=slug_from_filename(path),
        path=path,
        title=str(fm["title"]),
        description=str(fm["description"]),
        date=d,
        tags=[str(t) for t in tags],
        draft=bool(fm.get("draft", False)),
        linkedin=bool(fm.get("linkedin", True)),
        cover=fm.get("cover"),
        project_repo=fm.get("project_repo"),
        body=body.lstrip("\n"),
    )


def load_post(path: Path, root: Path = ROOT) -> Post:
    rel = path.resolve().relative_to(root.resolve()).as_posix() if path.is_absolute() else path.as_posix()
    return parse_post(path.read_text(encoding="utf-8"), rel)
