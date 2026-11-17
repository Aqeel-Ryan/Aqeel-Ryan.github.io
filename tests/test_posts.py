from pathlib import Path

import pytest

from scripts.posts import PostError, canonical_url, parse_post, slug_from_filename

from .conftest import make_post_text

PATH = "src/content/posts/2026-11-17-my-post.md"


def test_slug_strips_date_prefix_and_extension():
    assert slug_from_filename("2026-11-17-my-post.md") == "my-post"
    assert slug_from_filename("src/content/posts/2026-11-17-My-Post.md") == "my-post"
    assert slug_from_filename("no-date.md") == "no-date"


def test_slug_rule_matches_the_astro_site():
    """scripts/posts.py and src/lib/urls.ts must strip the same date prefix."""
    ts = (Path(__file__).resolve().parent.parent / "src/lib/urls.ts").read_text(encoding="utf-8")
    assert r"/^\d{4}-\d{2}-\d{2}-/" in ts


def test_canonical_url_is_derived_from_site_url():
    assert canonical_url("my-post", "https://example.com/") == "https://example.com/posts/my-post/"


def test_valid_post_parses_with_defaults():
    post = parse_post(make_post_text(), PATH)
    assert (post.slug, post.title, post.draft, post.linkedin, post.tags) == ("my-post", "T", False, True, ["a"])
    assert post.date.isoformat() == "2026-11-17"
    assert post.body.startswith("body")


@pytest.mark.parametrize(
    "text,fragment",
    [
        ("no frontmatter here", "frontmatter"),
        ('---\ndescription: "d"\ndate: 2026-11-17\n---\nx', "title"),
        ('---\ntitle: "t"\ndate: 2026-11-17\n---\nx', "description"),
        ('---\ntitle: "t"\ndescription: "d"\n---\nx', "date"),
        ('---\ntitle: "t"\ndescription: "d"\ndate: 2026-13-45\n---\nx', "invalid YAML|YYYY-MM-DD"),
        ('---\ntitle: "t"\ndescription: "d"\ndate: 2026-11-17\ntags: oops\n---\nx', "tags"),
        ('---\ntitle: "t"\ndescription: "d"\ndate: 2026-11-17\ndraft: "yes"\n---\nx', "draft"),
        ('---\ntitle: "t"\ndescription: "d"\ndate: 2026-11-17\ncanonical_url: http://x\n---\nx', "canonical_url"),
        (make_post_text(description="x" * 301), "300"),
    ],
)
def test_invalid_frontmatter_is_rejected(text, fragment):
    with pytest.raises(PostError, match=fragment):
        parse_post(text, PATH)
