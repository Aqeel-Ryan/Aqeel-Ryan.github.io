import json
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from scripts import linkedin_drafts as ld
from scripts.posts import parse_post

from .conftest import make_post_text

URL = "https://example.com/posts/demo/"
POST = parse_post(
    make_post_text(title="Demo", extra="We cut failing checks from 66 to 0 on a 732-check baseline."),
    "src/content/posts/2026-11-17-demo.md",
)


def variant(*, extra_words=0, bad_number=False, with_url=True, tags="#rag #llm"):
    filler = " ".join(["detail"] * 26)
    text = (
        "I took 66 failing checks down to 0 on a 732-check baseline and wrote down what worked.\n\n"
        f"The first approach failed because the constraint was the approval gate. {filler}\n\n"
        f"What I built instead is smaller and easier to roll back. {filler}\n\n"
        f"The open problem is drift, which I still check hourly. {filler}\n\n"
    )
    if bad_number:
        text = text.replace("66", "99")
    text += (URL + "\n" if with_url else "") + tags
    return text + " detail" * extra_words


def payload(**kw):
    return json.dumps({"variants": [{"style": s, "text": variant(**kw)} for s in ld.STYLES]})


class Message:
    def __init__(self, content):
        self.content = content


class Choice:
    def __init__(self, content, finish_reason):
        self.message = Message(content)
        self.finish_reason = finish_reason


class Response:
    def __init__(self, text, finish_reason="stop"):
        self.choices = [Choice(text, finish_reason)]


class FakeClient:
    """Mimics openai.OpenAI().chat.completions.create."""

    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.calls = []
        self.chat = self.completions = self

    def create(self, **kwargs):
        self.calls.append(kwargs)
        out = self.outputs.pop(0)
        return Response(*out) if isinstance(out, tuple) else Response(out)


def test_valid_variant_has_no_problems():
    assert ld.validate_variant_text(variant(), URL, POST.body) == []


@pytest.mark.parametrize(
    "kwargs,fragment",
    [
        (dict(extra_words=120), "words"),
        (dict(bad_number=True), "numbers not found in the post: 99"),
        (dict(with_url=False), "must appear exactly once"),
        (dict(tags="#a #b #c #d"), "4 hashtags"),
        (dict(tags="#a \U0001F680\U0001F525"), "2 emoji"),
    ],
)
def test_rule_violations_are_caught(kwargs, fragment):
    problems = ld.validate_variant_text(variant(**kwargs), URL, POST.body)
    assert any(fragment in p for p in problems), problems


def test_hashtag_in_the_middle_is_rejected():
    text = variant().replace("approval gate.", "approval gate #oops.")
    assert any("final line" in p for p in ld.validate_variant_text(text, URL, POST.body))


def test_parse_accepts_valid_payload_in_fixed_style_order():
    drafts = ld.parse_and_validate(payload(), URL, POST.body)
    assert [v.style for v in drafts.ordered()] == ["lesson", "contrarian", "buildlog"]


@pytest.mark.parametrize(
    "raw,fragment",
    [
        ("not json", "not valid JSON"),
        (json.dumps({"variants": []}), "expected exactly one variant"),
        (json.dumps({"variants": [{"style": "lesson", "text": "x"}] * 3}), "expected exactly one variant"),
        (json.dumps({"nope": 1}), "schema"),
    ],
)
def test_malformed_payloads_are_rejected(raw, fragment):
    with pytest.raises(ValueError, match=fragment):
        ld.parse_and_validate(raw, URL, POST.body)


def test_generate_uses_configured_model_and_json_mode():
    client = FakeClient([payload()])
    ld.generate_drafts(client, "my-model", POST, URL, "voice text")
    call = client.calls[0]
    system, user = call["messages"][0]["content"], call["messages"][1]["content"]
    assert call["model"] == "my-model"
    assert call["response_format"] == {"type": "json_object"}
    assert "voice text" in system
    assert "json" in user.lower() and '"variants"' in user  # DeepSeek JSON mode needs the word and an example
    assert call["max_tokens"] >= 8000


def test_default_model_is_deepseek_flash_and_overridable_by_env(monkeypatch):
    assert ld.DEFAULT_MODEL == "deepseek-flash"
    monkeypatch.setenv("DEEPSEEK_MODEL", "deepseek-v4-pro")
    assert ld.main(["--slug", "sample-pipeline-dry-run", "--dry-run"]) == 0


def test_missing_api_key_fails_cleanly(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    assert ld.main(["--slug", "sample-pipeline-dry-run"]) == 1


def test_malformed_response_is_retried_once_with_feedback():
    client = FakeClient(["not json", payload()])
    ld.generate_drafts(client, "m", POST, URL, "v")
    assert len(client.calls) == 2
    assert "rejected" in client.calls[1]["messages"][1]["content"]


def test_invalid_twice_raises_after_exactly_two_calls():
    client = FakeClient([payload(bad_number=True), payload(bad_number=True)])
    with pytest.raises(ld.DraftError, match="still invalid"):
        ld.generate_drafts(client, "m", POST, URL, "v")
    assert len(client.calls) == 2


def test_content_filter_fails_without_retry():
    client = FakeClient([("", "content_filter")])
    with pytest.raises(ld.DraftError, match="declined"):
        ld.generate_drafts(client, "m", POST, URL, "v")
    assert len(client.calls) == 1


def test_truncated_response_is_retried():
    client = FakeClient([('{"variants": [', "length"), payload()])
    ld.generate_drafts(client, "m", POST, URL, "v")
    assert len(client.calls) == 2


def test_blank_response_from_json_mode_is_retried():
    """DeepSeek JSON mode can return only spaces when the output is not valid JSON."""
    client = FakeClient(["      ", payload()])
    ld.generate_drafts(client, "m", POST, URL, "v")
    assert len(client.calls) == 2


def test_posting_slot_is_next_tue_or_thu_9am_eastern():
    et = ZoneInfo("America/New_York")
    assert ld.next_posting_slot(datetime(2026, 11, 18, 12, 0, tzinfo=et)).startswith("Thursday, November 19 at 9:00 AM")
    assert ld.next_posting_slot(datetime(2026, 11, 17, 8, 0, tzinfo=et)).startswith("Tuesday, November 17 at 9:00 AM")
    assert ld.next_posting_slot(datetime(2026, 11, 19, 10, 0, tzinfo=et)).startswith("Tuesday, November 24 at 9:00 AM")


@pytest.fixture
def blog(tmp_path):
    import shutil
    from pathlib import Path

    src = Path(__file__).resolve().parent.parent
    shutil.copytree(src / "linkedin", tmp_path / "linkedin", ignore=shutil.ignore_patterns("drafts"))
    (tmp_path / "site.config.json").write_text(json.dumps({"siteUrl": "https://example.com", "githubUser": "Aqeel-Ryan"}))
    return tmp_path


def test_process_post_saves_drafts_and_opens_one_issue(blog, monkeypatch):
    issues = []
    monkeypatch.setattr(ld, "create_issue", lambda title, body, assignee, repo=None: issues.append((title, assignee, body)) or "u")
    client = FakeClient([payload()])
    assert ld.process_post(POST, blog, client, "m", force=False, dry_run=False, no_issue=False)
    saved = (blog / "linkedin/drafts/demo.md").read_text()
    assert saved.count("```text") == 3
    title, assignee, body = issues[0]
    assert title == "LinkedIn drafts: Demo" and assignee == "Aqeel-Ryan"
    assert body.count("```text") == 3 and URL in body and "Suggested posting time" in body


def test_existing_drafts_are_not_regenerated_unless_forced(blog, monkeypatch):
    monkeypatch.setattr(ld, "create_issue", lambda *a, **k: "u")
    client = FakeClient([payload(), payload()])
    ld.process_post(POST, blog, client, "m", force=False, dry_run=False, no_issue=False)
    ld.process_post(POST, blog, client, "m", force=False, dry_run=False, no_issue=False)
    assert len(client.calls) == 1
    ld.process_post(POST, blog, client, "m", force=True, dry_run=False, no_issue=False)
    assert len(client.calls) == 2


def test_linkedin_false_and_dry_run_make_no_calls(blog, monkeypatch):
    monkeypatch.setattr(ld, "create_issue", lambda *a, **k: pytest.fail("must not open an issue"))
    client = FakeClient([])
    off = parse_post(make_post_text().replace("draft: false", "draft: false\nlinkedin: false"), "src/content/posts/2026-11-17-off.md")
    assert ld.process_post(off, blog, client, "m", force=False, dry_run=False, no_issue=False)
    assert ld.process_post(POST, blog, client, "m", force=False, dry_run=True, no_issue=False)
    assert client.calls == [] and not (blog / "linkedin/drafts").exists()


def test_failed_generation_returns_false_and_saves_nothing(blog, monkeypatch):
    monkeypatch.setattr(ld, "create_issue", lambda *a, **k: pytest.fail("must not open an issue"))
    client = FakeClient([payload(bad_number=True), payload(bad_number=True)])
    assert not ld.process_post(POST, blog, client, "m", force=False, dry_run=False, no_issue=False)
    assert not (blog / "linkedin/drafts/demo.md").exists()
