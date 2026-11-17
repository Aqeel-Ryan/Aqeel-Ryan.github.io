"""Cross-post newly published posts to dev.to and Hashnode.

Idempotent: every (slug, platform) pair is checked against published.json
before publishing and recorded immediately after success. Secrets come only from
the environment (DEVTO_API_KEY, HASHNODE_TOKEN, HASHNODE_PUBLICATION_ID) and are
never printed.

Usage:
  crosspost.py --posts '<json from detect_new_posts>' [--ledger published.json] [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import requests

from scripts.ledger import Ledger
from scripts.posts import ROOT, Post, canonical_url, load_post, site_url

TIMEOUT = 30
_FENCE = re.compile(r"(```.*?```|~~~.*?~~~)", re.S)
_MD_LINK = re.compile(r"(\]\()(/(?!/)[^)\s]*)")
_HTML_ATTR = re.compile(r"""((?:src|href)=["'])(/(?!/)[^"']*)""")


class PublishError(RuntimeError):
    """A publish call failed. `ambiguous` means the post may exist on the platform."""

    def __init__(self, message: str, *, ambiguous: bool = False):
        super().__init__(message)
        self.ambiguous = ambiguous


@dataclass
class Result:
    id: str
    url: str | None


class Platform(Protocol):
    name: str

    def publish(self, post: Post, body: str, canonical: str) -> Result: ...


def absolutize(body: str, base: str) -> str:
    """Make root-relative links and images absolute. Code fences are left untouched."""
    base = base.rstrip("/")
    parts = _FENCE.split(body)
    for i, part in enumerate(parts):
        if i % 2 == 1:  # a fenced code block
            continue
        part = _MD_LINK.sub(lambda m: f"{m.group(1)}{base}{m.group(2)}", part)
        parts[i] = _HTML_ATTR.sub(lambda m: f"{m.group(1)}{base}{m.group(2)}", part)
    return "".join(parts)


def devto_tags(tags: list[str]) -> list[str]:
    """dev.to: lowercase alphanumeric only, max 4."""
    out: list[str] = []
    for tag in tags:
        clean = "".join(c for c in tag.lower() if c.isalnum())
        if clean and clean not in out:
            out.append(clean)
        if len(out) == 4:
            break
    return out


def _scrub(text: str, secrets: list[str]) -> str:
    for s in secrets:
        if s:
            text = text.replace(s, "***")
    return text


def _request(method: str, url: str, secrets: list[str], **kwargs: Any) -> requests.Response:
    """POST with retry only on 429 (the request was rejected, so a retry cannot duplicate)."""
    for attempt in range(3):
        try:
            resp = requests.request(method, url, timeout=TIMEOUT, **kwargs)
        except requests.RequestException as e:
            # The request may or may not have been processed: never retry blindly.
            raise PublishError(f"network error: {_scrub(str(e), secrets)}", ambiguous=True) from e
        if resp.status_code == 429 and attempt < 2:
            time.sleep(min(float(resp.headers.get("retry-after", 2 ** (attempt + 1))), 30))
            continue
        return resp
    return resp  # pragma: no cover


class DevTo:
    name = "devto"

    def __init__(self, api_key: str):
        self.api_key = api_key

    def payload(self, post: Post, body: str, canonical: str) -> dict[str, Any]:
        article: dict[str, Any] = {
            "title": post.title,
            "body_markdown": body,
            "published": True,
            "description": post.description[:300],
            "canonical_url": canonical,
        }
        tags = devto_tags(post.tags)
        if tags:
            article["tags"] = tags
        return {"article": article}

    def publish(self, post: Post, body: str, canonical: str) -> Result:
        resp = _request(
            "POST",
            "https://dev.to/api/articles",
            [self.api_key],
            headers={"api-key": self.api_key, "Accept": "application/vnd.forem.api-v1+json"},
            json=self.payload(post, body, canonical),
        )
        if resp.status_code == 201:
            data = resp.json()
            return Result(id=str(data["id"]), url=data.get("url"))
        raise PublishError(
            f"dev.to returned {resp.status_code}: {_scrub(resp.text[:300], [self.api_key])}",
            ambiguous=resp.status_code >= 500,
        )


class Hashnode:
    name = "hashnode"
    _MUTATION = """
    mutation PublishPost($input: PublishPostInput!) {
      publishPost(input: $input) { post { id url slug } }
    }"""

    def __init__(self, token: str, publication_id: str):
        self.token = token
        self.publication_id = publication_id

    def payload(self, post: Post, body: str, canonical: str) -> dict[str, Any]:
        inp: dict[str, Any] = {
            "publicationId": self.publication_id,
            "title": post.title,
            "subtitle": post.description[:150],
            "contentMarkdown": body,
            "slug": post.slug[:100],
            "originalArticleURL": canonical,
        }
        tags = [{"slug": t.lower().replace(" ", "-"), "name": t} for t in post.tags[:5]]
        if tags:
            inp["tags"] = tags
        return {"query": self._MUTATION, "variables": {"input": inp}}

    def publish(self, post: Post, body: str, canonical: str) -> Result:
        resp = _request(
            "POST",
            "https://gql.hashnode.com",
            [self.token],
            headers={"Authorization": self.token, "Content-Type": "application/json"},
            json=self.payload(post, body, canonical),
        )
        if resp.status_code != 200:
            raise PublishError(
                f"Hashnode returned {resp.status_code}: {_scrub(resp.text[:300], [self.token])}",
                ambiguous=resp.status_code >= 500,
            )
        try:
            data = resp.json()
        except ValueError as e:
            raise PublishError("Hashnode returned a non-JSON response", ambiguous=True) from e
        if data.get("errors"):
            msg = _scrub(str(data["errors"][0].get("message", "unknown error")), [self.token])
            raise PublishError(f"Hashnode error: {msg}")
        node = (data.get("data") or {}).get("publishPost", {}).get("post")
        if not node:
            raise PublishError("Hashnode response had no post", ambiguous=True)
        return Result(id=str(node["id"]), url=node.get("url"))


def platforms_from_env(env: dict[str, str] | None = None) -> list[Platform]:
    env = dict(os.environ) if env is None else env
    out: list[Platform] = []
    if env.get("DEVTO_API_KEY"):
        out.append(DevTo(env["DEVTO_API_KEY"]))
    if env.get("HASHNODE_TOKEN") and env.get("HASHNODE_PUBLICATION_ID"):
        out.append(Hashnode(env["HASHNODE_TOKEN"], env["HASHNODE_PUBLICATION_ID"]))
    return out


def crosspost(
    posts: list[Post],
    platforms: list[Platform],
    ledger: Ledger,
    base_url: str,
    *,
    dry_run: bool = False,
    log=print,
) -> int:
    """Publish each post to each platform it is not yet recorded on. Returns failure count."""
    failures = 0
    for post in posts:
        canonical = canonical_url(post.slug, base_url)
        body = absolutize(post.body, base_url)
        for platform in platforms:
            if ledger.has(post.slug, platform.name):
                log(f"skip   {post.slug} -> {platform.name} (already in ledger)")
                continue
            if dry_run:
                log(f"dryrun {post.slug} -> {platform.name} canonical={canonical}")
                continue
            try:
                result = platform.publish(post, body, canonical)
            except PublishError as e:
                failures += 1
                hint = " (may already exist on the platform: check before re-running)" if e.ambiguous else ""
                log(f"::error::{post.slug} -> {platform.name} failed: {e}{hint}")
                continue
            ledger.record(post.slug, platform.name, id=result.id, url=result.url)
            log(f"posted {post.slug} -> {platform.name} {result.url}")
    return failures


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--posts", required=True, help="JSON list from detect_new_posts.py")
    ap.add_argument("--ledger", default=str(ROOT / "published.json"))
    ap.add_argument("--root", default=str(ROOT))
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    root = Path(args.root)
    items = json.loads(args.posts)
    posts = [load_post(root / item["path"], root) for item in items]
    platforms = platforms_from_env()
    if not platforms and not args.dry_run:
        print("::warning::no cross-post credentials configured; nothing to do")
        return 0
    if args.dry_run and not platforms:
        platforms = [DevTo("dry-run"), Hashnode("dry-run", "dry-run")]
    failures = crosspost(posts, platforms, Ledger(Path(args.ledger)), site_url(root), dry_run=args.dry_run)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
