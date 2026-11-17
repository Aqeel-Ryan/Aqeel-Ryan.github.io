from scripts.detect_new_posts import EMPTY_TREE, ZERO_SHA, detect, resolve_base

from .conftest import make_post_text


def slugs(repo, base):
    return [p.slug for p in detect(repo.root, base)]


def test_new_published_post_is_detected(repo):
    repo.write("2026-11-17-a.md", make_post_text(draft=False))
    repo.commit()
    base = repo.head()
    repo.write("2026-11-18-b.md", make_post_text(draft=False))
    repo.commit()
    assert slugs(repo, base) == ["b"]


def test_draft_to_published_is_detected(repo):
    repo.write("2026-11-17-a.md", make_post_text(draft=True))
    base = repo.commit()
    repo.write("2026-11-17-a.md", make_post_text(draft=False))
    repo.commit()
    assert slugs(repo, base) == ["a"]


def test_edit_of_already_published_post_is_ignored(repo):
    repo.write("2026-11-17-a.md", make_post_text(draft=False))
    base = repo.commit()
    repo.write("2026-11-17-a.md", make_post_text(draft=False, extra="edited"))
    repo.commit()
    assert slugs(repo, base) == []


def test_new_draft_and_draft_edits_do_nothing(repo):
    repo.write("2026-11-17-a.md", make_post_text(draft=True))
    base = repo.commit()
    repo.write("2026-11-17-a.md", make_post_text(draft=True, extra="edited"))
    repo.write("2026-11-18-b.md", make_post_text(draft=True))
    repo.commit()
    assert slugs(repo, base) == []


def test_published_to_draft_is_not_new(repo):
    repo.write("2026-11-17-a.md", make_post_text(draft=False))
    base = repo.commit()
    repo.write("2026-11-17-a.md", make_post_text(draft=True))
    repo.commit()
    assert slugs(repo, base) == []


def test_multiple_new_posts_sorted_by_path(repo):
    repo.write("2026-11-17-z.md", make_post_text(draft=True))
    base = repo.commit()
    repo.write("2026-11-17-z.md", make_post_text(draft=False))
    repo.write("2026-11-18-a.md", make_post_text(draft=False))
    repo.commit()
    assert slugs(repo, base) == ["z", "a"]


def test_first_commit_without_parent_uses_empty_tree(repo):
    repo.write("2026-11-17-a.md", make_post_text(draft=False))
    repo.write("2026-11-17-d.md", make_post_text(draft=True))
    repo.commit()
    assert slugs(repo, None) == ["a"]
    assert resolve_base(repo.root, None, "HEAD") == EMPTY_TREE


def test_all_zero_base_sha_falls_back_to_parent(repo):
    repo.write("2026-11-17-a.md", make_post_text(draft=False))
    repo.commit()
    repo.write("2026-11-18-b.md", make_post_text(draft=False))
    repo.commit()
    assert slugs(repo, ZERO_SHA) == ["b"]


def test_unknown_base_sha_uses_empty_tree(repo):
    repo.write("2026-11-17-a.md", make_post_text(draft=False))
    repo.commit()
    assert slugs(repo, "1" * 40) == ["a"]


def test_malformed_post_is_skipped_not_fatal(repo):
    repo.write("2026-11-17-bad.md", "no frontmatter")
    repo.write("2026-11-17-ok.md", make_post_text(draft=False))
    repo.commit()
    assert slugs(repo, None) == ["ok"]


def test_non_post_files_are_ignored(repo):
    (repo.root / "README.md").write_text("hi")
    repo.commit()
    assert slugs(repo, None) == []


def test_post_with_impossible_date_is_skipped_not_fatal(repo):
    repo.write("2026-11-17-bad.md", make_post_text().replace("2026-11-17", "2026-13-45"))
    repo.write("2026-11-17-ok.md", make_post_text(draft=False))
    repo.commit()
    assert slugs(repo, None) == ["ok"]
