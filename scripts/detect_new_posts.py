"""Find posts that became published in a push.

A post is "new" when, at HEAD, it exists with draft=false AND at BASE it either
did not exist or had draft=true. Edits to already-published posts are ignored.
Renames show up as delete+add, so a renamed published post can be reported as new.
The LinkedIn step skips posts whose draft file already exists.

Usage: detect_new_posts.py --base <sha> --head <sha> [--github-output]
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from scripts.posts import POSTS_DIR, ROOT, Post, PostError, parse_post

EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"
ZERO_SHA = "0" * 40


def _git(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=check)


def _show(root: Path, rev: str, path: str) -> str | None:
    if rev == EMPTY_TREE:
        return None
    r = _git(root, "show", f"{rev}:{path}", check=False)
    return r.stdout if r.returncode == 0 else None


def resolve_base(root: Path, base: str | None, head: str) -> str:
    """Use the empty tree when there is no usable parent (first push, new branch)."""
    if not base or base == ZERO_SHA:
        parent = _git(root, "rev-parse", "--verify", "--quiet", f"{head}^", check=False)
        return parent.stdout.strip() if parent.returncode == 0 else EMPTY_TREE
    if _git(root, "cat-file", "-e", f"{base}^{{commit}}", check=False).returncode != 0:
        return EMPTY_TREE
    return base


def detect(root: Path, base: str | None, head: str = "HEAD") -> list[Post]:
    base = resolve_base(root, base, head)
    diff = _git(
        root, "diff", "--name-status", "--no-renames", base, head, "--", f"{POSTS_DIR}/*.md"
    ).stdout.splitlines()
    new: list[Post] = []
    for line in diff:
        status, _, path = line.partition("\t")
        if status not in ("A", "M"):
            continue
        head_text = _show(root, head, path)
        if head_text is None:
            continue
        try:
            current = parse_post(head_text, path)
        except PostError as e:
            print(f"::warning::skipping unparseable post {path}: {e}", file=sys.stderr)
            continue
        if current.draft:
            continue
        old_text = _show(root, base, path)
        if old_text is not None:
            try:
                if not parse_post(old_text, path).draft:
                    continue  # already published before: an edit, not a new post
            except PostError:
                pass  # previous version was broken, so treat as new
        new.append(current)
    return sorted(new, key=lambda p: p.path)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base", default=None, help="previous commit (default: HEAD^)")
    ap.add_argument("--head", default="HEAD")
    ap.add_argument("--root", default=str(ROOT))
    ap.add_argument("--github-output", action="store_true", help="write to $GITHUB_OUTPUT")
    args = ap.parse_args(argv)

    posts = detect(Path(args.root), args.base, args.head)
    payload = json.dumps([p.summary() for p in posts], separators=(",", ":"))
    print(payload)
    if args.github_output and os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as f:
            f.write(f"posts={payload}\n")
            f.write(f"has_posts={'true' if posts else 'false'}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
