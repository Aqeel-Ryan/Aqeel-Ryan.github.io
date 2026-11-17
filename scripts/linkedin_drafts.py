"""Write the LinkedIn announcement for each newly published blog post.

No LLM is involved. The post is a fixed one-liner with the canonical URL. For each
post this saves linkedin/drafts/<slug>.md and opens a GitHub Issue so the text can
be copy-pasted. Nothing is ever posted to LinkedIn by this script.

Usage:
  linkedin_drafts.py --posts '<json from detect_new_posts>'
  linkedin_drafts.py --slug my-post            # regenerate (overwrites the drafts file)
  linkedin_drafts.py --slug my-post --dry-run  # print the text, write nothing
Environment: GH_TOKEN (for gh).
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from scripts.posts import POSTS_DIR, ROOT, Post, PostError, canonical_url, load_post, site_config, site_url

LABEL = "linkedin-draft"


def announcement(url: str) -> str:
    return f"I posted a new blog today, check it out -> {url}"


def next_posting_slot(now: datetime | None = None) -> str:
    """Next Tuesday or Thursday at 9:00 AM US Eastern, strictly after `now`."""
    eastern = ZoneInfo("America/New_York")
    now = (now or datetime.now(eastern)).astimezone(eastern)
    for offset in range(0, 8):
        day = (now + timedelta(days=offset)).replace(hour=9, minute=0, second=0, microsecond=0)
        if day.weekday() in (1, 3) and day > now:
            return day.strftime("%A, %B %d at 9:00 AM %Z")
    raise AssertionError("unreachable")  # pragma: no cover


def render_drafts_file(post: Post, url: str, slot: str) -> str:
    return "\n".join(
        [f"# LinkedIn post: {post.title}", "", f"- Post: {url}", f"- Suggested time: {slot}", "",
         "```text", announcement(url), "```", ""]
    )


def render_issue_body(post: Post, url: str, slot: str) -> str:
    return "\n".join(
        [
            f"New post published: **{post.title}**",
            url,
            "",
            f"**Suggested posting time:** {slot}",
            "",
            "Copy the text below into LinkedIn. Nothing was posted for you.",
            "",
            "```text",
            announcement(url),
            "```",
            "",
            f"Saved to `linkedin/drafts/{post.slug}.md`.",
        ]
    )


def create_issue(title: str, body: str, assignee: str, repo: str | None = None) -> str:
    """Open the GitHub Issue with the gh CLI and return its URL."""
    base = ["gh"] + (["--repo", repo] if repo else [])
    subprocess.run(
        [*base, "label", "create", LABEL, "--force", "--color", "0A66C2", "--description", "LinkedIn post drafts"],
        check=True, capture_output=True, text=True,
    )
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as f:
        f.write(body)
        body_path = f.name
    try:
        out = subprocess.run(
            [*base, "issue", "create", "--title", title, "--body-file", body_path, "--label", LABEL, "--assignee", assignee],
            check=True, capture_output=True, text=True,
        )
    finally:
        os.unlink(body_path)
    return out.stdout.strip()


def find_post_by_slug(root: Path, slug: str) -> Post:
    for path in sorted((root / POSTS_DIR).glob("*.md")):
        try:
            post = load_post(path, root)
        except PostError:
            continue
        if post.slug == slug:
            return post
    raise SystemExit(f"no post with slug {slug!r} in {POSTS_DIR}")


def process_post(post: Post, root: Path, *, force: bool, dry_run: bool, no_issue: bool) -> bool:
    url = canonical_url(post.slug, site_url(root))
    out_path = root / "linkedin" / "drafts" / f"{post.slug}.md"
    if not post.linkedin:
        print(f"skip {post.slug}: linkedin: false")
        return True
    if out_path.exists() and not force:
        print(f"skip {post.slug}: draft already exists ({out_path.relative_to(root)}); use --slug to regenerate")
        return True
    if dry_run:
        print(f"dryrun {post.slug}: {announcement(url)}")
        return True
    slot = next_posting_slot()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(render_drafts_file(post, url, slot), encoding="utf-8")
    print(f"saved {out_path.relative_to(root)}")
    if not no_issue:
        issue_url = create_issue(
            f"LinkedIn post: {post.title}",
            render_issue_body(post, url, slot),
            site_config(root)["githubUser"],
        )
        print(f"issue {issue_url}")
    return True


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--posts", help="JSON list from detect_new_posts.py")
    ap.add_argument("--slug", help="regenerate the draft for this slug (overwrites)")
    ap.add_argument("--root", default=str(ROOT))
    ap.add_argument("--dry-run", action="store_true", help="print the text, write nothing and open no issue")
    ap.add_argument("--no-issue", action="store_true", help="save the drafts file but do not open an issue")
    args = ap.parse_args(argv)
    if bool(args.posts) == bool(args.slug):
        ap.error("pass exactly one of --posts or --slug")

    root = Path(args.root)
    if args.slug:
        posts = [find_post_by_slug(root, args.slug)]
    else:
        posts = [load_post(root / item["path"], root) for item in json.loads(args.posts)]

    ok = True
    for post in posts:
        ok &= process_post(post, root, force=bool(args.slug), dry_run=args.dry_run, no_issue=args.no_issue)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
