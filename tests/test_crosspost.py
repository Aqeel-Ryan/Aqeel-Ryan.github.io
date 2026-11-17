import json

import pytest

from scripts import crosspost as cp
from scripts.ledger import Ledger
from scripts.posts import parse_post

from .conftest import make_post_text

BASE = "https://example.com"
PATH = "src/content/posts/2026-11-17-my-post.md"


class FakeResponse:
    def __init__(self, status, payload, headers=None):
        self.status_code, self._payload, self.headers = status, payload, headers or {}
        self.text = json.dumps(payload)

    def json(self):
        return self._payload


def ok(url):
    if "dev.to" in url:
        return FakeResponse(201, {"id": 42, "url": "https://dev.to/x"})
    return FakeResponse(200, {"data": {"publishPost": {"post": {"id": "h1", "url": "https://h.dev/x"}}}})


@pytest.fixture
def post():
    return parse_post(make_post_text(tags="[RAG, llm ops, agents, a, b]", extra="[l](/img/a.png)"), PATH)


@pytest.fixture
def platforms():
    return [cp.DevTo("DEVTO-SECRET"), cp.Hashnode("HN-SECRET", "PUB-1")]


@pytest.fixture
def calls(monkeypatch):
    seen = []

    def fake(method, url, timeout=None, **kw):
        seen.append((url, kw))
        return ok(url)

    monkeypatch.setattr(cp.requests, "request", fake)
    return seen


def run(posts, platforms, ledger, **kw):
    return cp.crosspost(posts, platforms, ledger, BASE, log=lambda m: None, **kw)


def test_posts_to_both_platforms_with_canonical_url(post, platforms, calls, tmp_path):
    ledger = Ledger(tmp_path / "published.json")
    assert run([post], platforms, ledger) == 0
    devto = next(kw for url, kw in calls if "dev.to" in url)["json"]["article"]
    hashnode = next(kw for url, kw in calls if "hashnode" in url)["json"]["variables"]["input"]
    assert devto["canonical_url"] == hashnode["originalArticleURL"] == "https://example.com/posts/my-post/"
    assert devto["published"] is True
    assert hashnode["publicationId"] == "PUB-1"


def test_rerun_never_double_posts(post, platforms, calls, tmp_path):
    path = tmp_path / "published.json"
    assert run([post], platforms, Ledger(path)) == 0
    assert len(calls) == 2
    assert run([post], platforms, Ledger(path)) == 0  # fresh Ledger object: state comes from disk
    assert len(calls) == 2


def test_ledger_records_ids_and_urls(post, platforms, calls, tmp_path):
    path = tmp_path / "published.json"
    run([post], platforms, Ledger(path))
    data = json.loads(path.read_text())
    assert data["my-post"]["devto"]["id"] == "42"
    assert data["my-post"]["hashnode"]["url"] == "https://h.dev/x"


def test_failure_on_one_platform_is_not_recorded_and_retried_later(post, platforms, monkeypatch, tmp_path):
    state = {"devto_ok": False}

    def fake(method, url, timeout=None, **kw):
        if "dev.to" in url and not state["devto_ok"]:
            return FakeResponse(422, {"error": "bad"})
        return ok(url)

    monkeypatch.setattr(cp.requests, "request", fake)
    path = tmp_path / "published.json"
    assert run([post], platforms, Ledger(path)) == 1
    data = json.loads(path.read_text())
    assert "devto" not in data["my-post"] and "hashnode" in data["my-post"]
    state["devto_ok"] = True
    assert run([post], platforms, Ledger(path)) == 0
    assert set(json.loads(path.read_text())["my-post"]) == {"devto", "hashnode"}


def test_network_error_is_ambiguous_and_never_retried(post, platforms, monkeypatch, tmp_path):
    attempts = []

    def boom(method, url, timeout=None, **kw):
        attempts.append(url)
        raise cp.requests.ConnectionError("reset by peer with DEVTO-SECRET inside")

    monkeypatch.setattr(cp.requests, "request", boom)
    messages = []
    failures = cp.crosspost([post], [platforms[0]], Ledger(tmp_path / "l.json"), BASE, log=messages.append)
    assert failures == 1 and len(attempts) == 1
    assert "may already exist" in messages[0]
    assert "DEVTO-SECRET" not in messages[0]


def test_429_is_retried_then_succeeds(post, monkeypatch, tmp_path):
    codes = iter([FakeResponse(429, {}, {"retry-after": "0"}), ok("https://dev.to/api/articles")])
    monkeypatch.setattr(cp.requests, "request", lambda *a, **k: next(codes))
    monkeypatch.setattr(cp.time, "sleep", lambda s: None)
    ledger = Ledger(tmp_path / "l.json")
    assert cp.crosspost([post], [cp.DevTo("k")], ledger, BASE, log=lambda m: None) == 0
    assert ledger.has("my-post", "devto")


def test_error_text_never_leaks_secrets(post, monkeypatch, tmp_path):
    monkeypatch.setattr(
        cp.requests, "request", lambda *a, **k: FakeResponse(401, {"echo": "api-key DEVTO-SECRET rejected"})
    )
    messages = []
    cp.crosspost([post], [cp.DevTo("DEVTO-SECRET")], Ledger(tmp_path / "l.json"), BASE, log=messages.append)
    assert "DEVTO-SECRET" not in " ".join(messages)


def test_hashnode_graphql_errors_are_failures(post, monkeypatch, tmp_path):
    monkeypatch.setattr(
        cp.requests, "request", lambda *a, **k: FakeResponse(200, {"errors": [{"message": "nope"}]})
    )
    ledger = Ledger(tmp_path / "l.json")
    assert cp.crosspost([post], [cp.Hashnode("t", "p")], ledger, BASE, log=lambda m: None) == 1
    assert not ledger.has("my-post", "hashnode")


def test_dry_run_sends_nothing_and_writes_no_ledger(post, platforms, calls, tmp_path):
    path = tmp_path / "published.json"
    assert run([post], platforms, Ledger(path), dry_run=True) == 0
    assert calls == [] and not path.exists()


def test_platforms_only_enabled_when_credentials_exist():
    assert cp.platforms_from_env({}) == []
    names = [p.name for p in cp.platforms_from_env({"DEVTO_API_KEY": "k", "HASHNODE_TOKEN": "t"})]
    assert names == ["devto"]  # Hashnode needs the publication id too
    full = cp.platforms_from_env({"DEVTO_API_KEY": "k", "HASHNODE_TOKEN": "t", "HASHNODE_PUBLICATION_ID": "p"})
    assert [p.name for p in full] == ["devto", "hashnode"]


def test_tag_limits(post, platforms):
    devto = platforms[0].payload(post, "b", "c")["article"]["tags"]
    hashnode = platforms[1].payload(post, "b", "c")["variables"]["input"]["tags"]
    assert devto == ["rag", "llmops", "agents", "a"]  # alphanumeric, max 4
    assert len(hashnode) == 5


def test_absolutize_rewrites_links_but_not_code():
    body = "![i](/img/a.png) [l](https://x.io/y) [p](//cdn/x)\n```\n[k](/keep)\n```\n<a href=\"/p/\">p</a>"
    out = cp.absolutize(body, "https://s.io/")
    assert "![i](https://s.io/img/a.png)" in out
    assert "(https://x.io/y)" in out and "(//cdn/x)" in out
    assert "[k](/keep)" in out
    assert 'href="https://s.io/p/"' in out


def test_ledger_survives_corrupt_state_loudly(tmp_path):
    bad = tmp_path / "published.json"
    bad.write_text("[1, 2]")
    with pytest.raises(ValueError):
        Ledger(bad)
    assert Ledger(tmp_path / "missing.json").data == {}
