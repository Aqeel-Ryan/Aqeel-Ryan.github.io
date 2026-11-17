#!/usr/bin/env python3
"""Check a blog draft against the blog's frontmatter schema and writing rules.

Usage: check_draft.py <path-to-post.md>
Exit 1 on errors (invalid frontmatter); warnings never fail the run.
"""
from __future__ import annotations

import re
import sys
from datetime import date
from pathlib import Path

REQUIRED = ("title", "description", "date", "tags", "draft")
BANNED = (
    "in today's fast-paced world", "game-changer", "game changer", "revolutionary",
    "cutting-edge", "delve", "unlock", "seamless", "in the ever-evolving", "leverage",
)
FILENAME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}-[a-z0-9][a-z0-9-]*\.md$")


def split_frontmatter(text: str) -> tuple[dict[str, str], str]:
    m = re.match(r"^---\n(.*?)\n---\n?(.*)$", text, re.S)
    if not m:
        raise ValueError("missing or malformed frontmatter (expected --- ... --- at top)")
    fm: dict[str, str] = {}
    for line in m.group(1).splitlines():
        if not line.strip() or line.lstrip().startswith("#") or ":" not in line:
            continue
        key, _, value = line.partition(":")
        value = value.split(" #")[0].strip()
        fm[key.strip()] = value
    return fm, m.group(2)


def body_words(body: str) -> int:
    no_code = re.sub(r"```.*?```", " ", body, flags=re.S)
    return len(re.findall(r"\b[\w'-]+\b", no_code))


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2
    path = Path(argv[1])
    errors: list[str] = []
    warnings: list[str] = []

    if not FILENAME_RE.match(path.name):
        errors.append(f"filename must look like yyyy-mm-dd-slug.md, got {path.name!r}")

    try:
        fm, body = split_frontmatter(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        print(f"ERROR: {e}")
        return 1

    for key in REQUIRED:
        if key not in fm or fm[key] == "":
            errors.append(f"frontmatter missing required field: {key}")
    if fm.get("draft", "").lower() != "true":
        errors.append("draft must be true for generated posts")
    if "canonical_url" in fm:
        errors.append("canonical_url must not be authored; the blog derives it")
    if fm.get("date"):
        try:
            date.fromisoformat(fm["date"].strip("\"'"))
        except ValueError:
            errors.append(f"date is not YYYY-MM-DD: {fm['date']!r}")
    if fm.get("description") and len(fm["description"].strip("\"'")) > 300:
        errors.append("description longer than 300 characters")
    if fm.get("tags") and not re.match(r"^\[.*\]$", fm["tags"]):
        errors.append("tags must be an inline list like [a, b]")

    words = body_words(body)
    if not 800 <= words <= 1500:
        warnings.append(f"body is {words} words (target 800-1500, code excluded)")
    lower = body.lower()
    for phrase in BANNED:
        if phrase in lower:
            warnings.append(f"banned phrase present: {phrase!r}")
    todos = re.findall(r"TODO\(verify\)", body)

    print(f"{path.name}: {words} words, {len(todos)} TODO(verify)")
    for w in warnings:
        print(f"WARNING: {w}")
    for e in errors:
        print(f"ERROR: {e}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
