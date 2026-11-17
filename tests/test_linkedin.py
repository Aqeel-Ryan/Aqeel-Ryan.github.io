import json
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from scripts import linkedin_drafts as ld
from scripts.posts import parse_post

from .conftest import make_post_text

URL = "https://example.com/posts/demo/"
POST = parse_post(make_post_text(title="Demo"), "src/content/posts/2026-11-17-demo.md")


def test_announcement_is_the_fixed_one_liner():
    assert ld.announcement(URL) == f"I posted a new blog today, check it out -> {URL}"


def test_posting_slot_is_next_tue_or_thu_9am_eastern():
    et = ZoneInfo("America/New_York")
    assert ld.next_posting_slot(datetime(2026, 11, 18, 12, 0, tzinfo=et)).startswith("Thursday, November 19 at 9:00 AM")
    assert ld.next_posting_slot(datetime(2026, 11, 17, 8, 0, tzinfo=et)).startswith("Tuesday, November 17 at 9:00 AM")
    assert ld.next_posting_slot(datetime(2026, 11, 19, 10, 0, tzinfo=et)).startswith("Tuesday, November 24 at 9:00 AM")


@pytest.fixture
def blog(tmp_path):
    (tmp_path / "site.config.json").write_text(json.dumps({"siteUrl": "https://example.com", "githubUser": "Aqeel-Ryan"}))
    return tmp_path


def test_process_post_saves_draft_and_opens_one_issue(blog, monkeypatch):
    issues = []
    monkeypatch.setattr(ld, "create_issue", lambda title, body, assignee, repo=None: issues.append((title, assignee, body)) or "u")
    assert ld.process_post(POST, blog, force=False, dry_run=False, no_issue=False)
    saved = (blog / "linkedin/drafts/demo.md").read_text()
    assert ld.announcement(URL) in saved
    title, assignee, body = issues[0]
    assert title == "LinkedIn post: Demo" and assignee == "Aqeel-Ryan"
    assert ld.announcement(URL) in body and "Suggested posting time" in body


def test_existing_draft_is_kept_unless_forced(blog, monkeypatch):
    issues = []
    monkeypatch.setattr(ld, "create_issue", lambda *a, **k: issues.append(1) or "u")
    ld.process_post(POST, blog, force=False, dry_run=False, no_issue=False)
    path = blog / "linkedin/drafts/demo.md"
    path.write_text("edited by hand")
    ld.process_post(POST, blog, force=False, dry_run=False, no_issue=False)
    assert path.read_text() == "edited by hand" and len(issues) == 1
    ld.process_post(POST, blog, force=True, dry_run=False, no_issue=False)
    assert ld.announcement(URL) in path.read_text() and len(issues) == 2


def test_linkedin_false_and_dry_run_write_nothing(blog, monkeypatch):
    monkeypatch.setattr(ld, "create_issue", lambda *a, **k: pytest.fail("must not open an issue"))
    off = parse_post(make_post_text().replace("draft: false", "draft: false\nlinkedin: false"), "src/content/posts/2026-11-17-off.md")
    assert ld.process_post(off, blog, force=False, dry_run=False, no_issue=False)
    assert ld.process_post(POST, blog, force=False, dry_run=True, no_issue=False)
    assert not (blog / "linkedin/drafts").exists()
