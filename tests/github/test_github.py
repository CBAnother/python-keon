import pytest

import keon.github as gh
from keon.github import (
    GithubAsset,
    GithubRelease,
    parse_repo,
    get_latest_release,
    get_latest_version,
    get_download_urls,
    list_releases,
)
from keon.github import _clean_version, _build_release


# ── parse_repo ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("url", [
    "https://github.com/jgm/pandoc",
    "https://github.com/jgm/pandoc/",
    "https://github.com/jgm/pandoc.git",
    "http://github.com/jgm/pandoc",
    "http://www.github.com/jgm/pandoc",
    "https://github.com/jgm/pandoc/releases/latest",
    "https://github.com/jgm/pandoc/tree/main",
    "git@github.com:jgm/pandoc.git",
    "jgm/pandoc",
])
def test_parse_repo_variants(url):
    assert parse_repo(url) == ("jgm", "pandoc")


def test_parse_repo_invalid_empty():
    with pytest.raises(ValueError, match="无法解析 GitHub 仓库"):
        parse_repo("")


def test_parse_repo_invalid_single_segment():
    with pytest.raises(ValueError, match="无法解析 GitHub 仓库"):
        parse_repo("https://github.com/jgm")


def test_parse_repo_invalid_type():
    with pytest.raises(ValueError, match="无法解析 GitHub 仓库"):
        parse_repo(None)


# ── _clean_version ─────────────────────────────────────────────────────────────

def test_clean_version_strips_v_prefix():
    assert _clean_version("v3.10") == "3.10"
    assert _clean_version("V1.2.3") == "1.2.3"


def test_clean_version_keeps_plain_version():
    assert _clean_version("3.10") == "3.10"


def test_clean_version_keeps_non_version_tag():
    assert _clean_version("release-2024") == "release-2024"


def test_clean_version_handles_empty():
    assert _clean_version("") == ""
    assert _clean_version(None) is None


# ── 样例 API 数据 ──────────────────────────────────────────────────────────────

SAMPLE_RELEASE = {
    "tag_name": "3.10",
    "name": "pandoc 3.10",
    "published_at": "2026-06-04T00:00:00Z",
    "html_url": "https://github.com/jgm/pandoc/releases/tag/3.10",
    "prerelease": False,
    "draft": False,
    "body": "release notes",
    "tarball_url": "https://api.github.com/repos/jgm/pandoc/tarball/3.10",
    "zipball_url": "https://api.github.com/repos/jgm/pandoc/zipball/3.10",
    "assets": [
        {
            "name": "pandoc-3.10-windows-x86_64.zip",
            "browser_download_url": "https://github.com/jgm/pandoc/releases/download/3.10/pandoc-3.10-windows-x86_64.zip",
            "size": 12345,
            "content_type": "application/zip",
            "download_count": 100,
        },
        {
            "name": "pandoc-3.10-linux-amd64.tar.gz",
            "browser_download_url": "https://github.com/jgm/pandoc/releases/download/3.10/pandoc-3.10-linux-amd64.tar.gz",
            "size": 23456,
            "content_type": "application/gzip",
            "download_count": 200,
        },
    ],
}

# 预发布样例：基于正式版本改两个字段，标签只在这里出现一次
SAMPLE_PRERELEASE = dict(SAMPLE_RELEASE, tag_name="3.11rc1", prerelease=True)


# ── _build_release ─────────────────────────────────────────────────────────────

def test_build_release_fields():
    rel = _build_release(SAMPLE_RELEASE, owner="jgm", repo="pandoc")

    assert isinstance(rel, GithubRelease)
    assert rel.owner == "jgm"
    assert rel.repo == "pandoc"
    assert rel.tag == "3.10"
    assert rel.version == "3.10"
    assert rel.name == "pandoc 3.10"
    assert rel.prerelease is False
    assert rel.draft is False
    assert len(rel.assets) == 2
    assert isinstance(rel.assets[0], GithubAsset)
    assert rel.assets[0].name == "pandoc-3.10-windows-x86_64.zip"
    assert rel.assets[0].size == 12345
    assert rel.raw is SAMPLE_RELEASE


def test_build_release_strips_v_prefix():
    data = dict(SAMPLE_RELEASE, tag_name="v3.10")
    rel = _build_release(data)
    assert rel.tag == "v3.10"
    assert rel.version == "3.10"


def test_build_release_handles_missing_assets():
    rel = _build_release({"tag_name": "1.0"})
    assert rel.assets == []
    assert rel.version == "1.0"


# ── GithubRelease.download_urls ────────────────────────────────────────────────

def test_download_urls_includes_assets_and_source():
    rel = _build_release(SAMPLE_RELEASE)
    urls = rel.download_urls()

    assert len(urls) == 4
    assert urls[0].endswith("pandoc-3.10-windows-x86_64.zip")
    assert urls[1].endswith("pandoc-3.10-linux-amd64.tar.gz")
    assert SAMPLE_RELEASE["tarball_url"] in urls
    assert SAMPLE_RELEASE["zipball_url"] in urls


def test_download_urls_without_source():
    rel = _build_release(SAMPLE_RELEASE)
    urls = rel.download_urls(include_source=False)

    assert len(urls) == 2
    assert SAMPLE_RELEASE["tarball_url"] not in urls


def test_download_urls_pattern_filter():
    rel = _build_release(SAMPLE_RELEASE)
    urls = rel.download_urls(pattern="*windows*")

    assert len(urls) == 1
    assert urls[0].endswith("pandoc-3.10-windows-x86_64.zip")


def test_download_urls_pattern_disables_source():
    """指定 pattern 时不应再追加源码包。"""
    rel = _build_release(SAMPLE_RELEASE)
    urls = rel.download_urls(pattern="*.tar.gz")

    assert len(urls) == 1
    assert urls[0].endswith("pandoc-3.10-linux-amd64.tar.gz")


# ── dataclass 辅助方法 ─────────────────────────────────────────────────────────

def test_release_dict_like_access():
    rel = _build_release(SAMPLE_RELEASE, owner="jgm", repo="pandoc")

    assert rel["version"] == "3.10"
    assert rel.get("version") == "3.10"
    assert rel.get("missing", "fallback") == "fallback"
    assert "version" in rel
    assert rel.to_dict()["tag"] == "3.10"


def test_asset_dict_like_access():
    asset = GithubAsset(name="a.zip", download_url="https://x/a.zip", size=10)

    assert asset["name"] == "a.zip"
    assert asset.get("size") == 10
    assert asset.get("missing", 0) == 0
    assert "name" in asset
    assert asset.to_dict()["download_url"] == "https://x/a.zip"


# ── get_latest_release / get_latest_version / get_download_urls ─────────────────

@pytest.fixture
def mock_latest(monkeypatch):
    """mock /releases/latest 请求，返回样例数据。"""
    calls = {}

    def fake_request_json(url, token=None, timeout=10, params=None):
        calls["url"] = url
        return SAMPLE_RELEASE

    monkeypatch.setattr(gh, "_request_json", fake_request_json)
    return calls


def test_get_latest_release(mock_latest):
    rel = get_latest_release("https://github.com/jgm/pandoc")

    assert rel.version == "3.10"
    assert rel.owner == "jgm"
    assert rel.repo == "pandoc"
    assert mock_latest["url"].endswith("/repos/jgm/pandoc/releases/latest")


def test_get_latest_version(mock_latest):
    assert get_latest_version("jgm/pandoc") == "3.10"


def test_get_download_urls(mock_latest):
    urls = get_download_urls("https://github.com/jgm/pandoc")
    assert len(urls) == 4


def test_get_download_urls_with_pattern(mock_latest):
    urls = get_download_urls("jgm/pandoc", pattern="*linux*")
    assert urls == [
        "https://github.com/jgm/pandoc/releases/download/3.10/pandoc-3.10-linux-amd64.tar.gz"
    ]


# ── list_releases / include_prerelease ─────────────────────────────────────────

def test_list_releases(monkeypatch):
    def fake_request_json(url, token=None, timeout=10, params=None):
        assert url.endswith("/repos/jgm/pandoc/releases")
        return [SAMPLE_PRERELEASE, SAMPLE_RELEASE]

    monkeypatch.setattr(gh, "_request_json", fake_request_json)

    releases = list_releases("jgm/pandoc")
    assert len(releases) == 2
    assert releases[0].tag == SAMPLE_PRERELEASE["tag_name"]
    assert releases[0].prerelease is True


def test_get_latest_release_include_prerelease(monkeypatch):
    def fake_request_json(url, token=None, timeout=10, params=None):
        assert url.endswith("/repos/jgm/pandoc/releases")
        return [SAMPLE_PRERELEASE, SAMPLE_RELEASE]

    monkeypatch.setattr(gh, "_request_json", fake_request_json)

    rel = get_latest_release("jgm/pandoc", include_prerelease=True)
    assert rel.tag == SAMPLE_PRERELEASE["tag_name"]
    assert rel.prerelease is True
