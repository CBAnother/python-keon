"""GitHub 工具模块：解析仓库地址，获取最新发布版本号与下载链接列表。"""

from dataclasses import asdict, dataclass, field
from fnmatch import fnmatch
from typing import Any, List, Optional
import os
import re

import requests


GITHUB_API = "https://api.github.com"

# 形如 git@github.com:owner/repo.git 的 SSH 地址
_SSH_RE = re.compile(r"^git@github\.com:", re.IGNORECASE)
# 形如 https://github.com/ 或 http://www.github.com/ 的前缀
_HOST_RE = re.compile(r"^(?:https?://)?(?:www\.)?github\.com/", re.IGNORECASE)
# 去掉标签前面的 v/V，例如 v1.2.3 -> 1.2.3
_VERSION_RE = re.compile(r"^[vV](\d.*)$")


def parse_repo(url):
    """
    从各种形式的 GitHub 地址中解析出 (owner, repo)。

    支持的输入形式：
        'https://github.com/jgm/pandoc'
        'https://github.com/jgm/pandoc/'
        'https://github.com/jgm/pandoc.git'
        'https://github.com/jgm/pandoc/releases/latest'
        'http://www.github.com/jgm/pandoc'
        'git@github.com:jgm/pandoc.git'
        'jgm/pandoc'

    Args:
        url (str): GitHub 仓库地址或 'owner/repo' 形式的字符串。

    Returns:
        tuple[str, str]: (owner, repo) 二元组。

    Raises:
        ValueError: 无法从输入中解析出仓库信息时抛出。
    """
    if not isinstance(url, str) or not url.strip():
        raise ValueError(f"无法解析 GitHub 仓库: {url!r}")

    s = url.strip()
    s = _SSH_RE.sub("", s)
    s = _HOST_RE.sub("", s)
    s = s.strip("/")

    if s.lower().endswith(".git"):
        s = s[:-4]

    parts = [p for p in s.split("/") if p]
    if len(parts) < 2:
        raise ValueError(f"无法解析 GitHub 仓库: {url!r}")

    return parts[0], parts[1]


def _clean_version(tag):
    """
    把标签转成干净的版本号，去掉前缀 v，例如 v1.2.3 -> 1.2.3。

    Args:
        tag (str): 原始标签名。

    Returns:
        str: 去掉前缀后的版本号；无法识别时原样返回。
    """
    if not tag:
        return tag
    m = _VERSION_RE.match(tag)
    return m.group(1) if m else tag


@dataclass
class GithubAsset:
    """
    单个发布资源（release asset）。

    Attributes:
        name: 文件名。
        download_url: 浏览器下载地址。
        size: 文件大小（字节）。
        content_type: MIME 类型。
        download_count: 下载次数。
    """
    name: Optional[str] = None
    download_url: Optional[str] = None
    size: Optional[int] = None
    content_type: Optional[str] = None
    download_count: Optional[int] = None

    def to_dict(self) -> dict:
        """转换为普通字典。"""
        return asdict(self)

    def get(self, key: str, default=None):
        """按字段名取值，类似 dict.get。"""
        return getattr(self, key, default)

    def __getitem__(self, key: str):
        """支持中括号方式取字段值。"""
        return getattr(self, key)

    def __contains__(self, key: str) -> bool:
        """判断字段是否存在。"""
        return hasattr(self, key)


@dataclass
class GithubRelease:
    """
    一次 GitHub 发布（release）的规范化结果。

    Attributes:
        owner: 仓库所有者。
        repo: 仓库名。
        version: 去掉前缀 v 的版本号，例如 3.10。
        tag: 原始标签名，例如 v3.10。
        name: 发布标题。
        published_at: 发布时间（ISO 字符串）。
        html_url: 发布页面地址。
        prerelease: 是否为预发布版本。
        draft: 是否为草稿。
        body: 发布说明正文。
        assets: 资源文件列表。
        tarball_url: 源码 tar.gz 下载地址。
        zipball_url: 源码 zip 下载地址。
        raw: GitHub API 原始响应。
    """
    owner: Optional[str] = None
    repo: Optional[str] = None
    version: Optional[str] = None
    tag: Optional[str] = None
    name: Optional[str] = None
    published_at: Optional[str] = None
    html_url: Optional[str] = None
    prerelease: bool = False
    draft: bool = False
    body: Optional[str] = None
    assets: List[GithubAsset] = field(default_factory=list)
    tarball_url: Optional[str] = None
    zipball_url: Optional[str] = None
    raw: Optional[dict] = None

    def download_urls(self, pattern=None, include_source=True) -> List[str]:
        """
        返回该发布的下载地址列表。

        Args:
            pattern: 可选，按文件名过滤资源的通配符（fnmatch 语法），
                例如 '*.exe'、'*windows*'；为 None 时返回全部资源。
            include_source (bool): 是否在末尾追加源码包（tar.gz / zip）地址。

        Returns:
            list[str]: 下载地址列表。
        """
        urls = []
        for asset in self.assets:
            if not asset.download_url:
                continue
            if pattern and not fnmatch(asset.name or "", pattern):
                continue
            urls.append(asset.download_url)

        if include_source and pattern is None:
            if self.tarball_url:
                urls.append(self.tarball_url)
            if self.zipball_url:
                urls.append(self.zipball_url)

        return urls

    def to_dict(self) -> dict:
        """转换为普通字典（资源也会展开为字典）。"""
        data = asdict(self)
        return data

    def get(self, key: str, default=None):
        """按字段名取值，类似 dict.get。"""
        return getattr(self, key, default)

    def __getitem__(self, key: str):
        """支持中括号方式取字段值。"""
        return getattr(self, key)

    def __contains__(self, key: str) -> bool:
        """判断字段是否存在。"""
        return hasattr(self, key)


def _build_headers(token=None):
    """
    构造请求 GitHub API 所需的请求头。

    token 优先级：显式入参 > 环境变量 GITHUB_TOKEN > 环境变量 GH_TOKEN。

    Args:
        token (str): GitHub 访问令牌，可为 None。

    Returns:
        dict: 请求头字典。
    """
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "keon-github/1.0",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = token or os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _request_json(url, token=None, timeout=10, params=None):
    """
    请求 GitHub API 并返回解析后的 JSON。

    Args:
        url (str): 请求地址。
        token (str): GitHub 访问令牌。
        timeout (float): 超时时间（秒）。
        params (dict): 查询参数。

    Returns:
        Any: 解析后的 JSON（dict 或 list）。

    Raises:
        RuntimeError: 资源不存在、触发速率限制或其它请求错误时抛出。
    """
    resp = requests.get(
        url, headers=_build_headers(token), timeout=timeout, params=params
    )

    if resp.status_code == 404:
        raise RuntimeError(f"未找到资源 (404): {url}")

    if resp.status_code == 403 and resp.headers.get("X-RateLimit-Remaining") == "0":
        raise RuntimeError(
            "GitHub API 速率限制已用尽，请稍后再试或设置环境变量 GITHUB_TOKEN 提升额度"
        )

    try:
        resp.raise_for_status()
    except requests.HTTPError as e:
        raise RuntimeError(f"请求 GitHub API 失败: {e}")

    return resp.json()


def _build_release(data, owner=None, repo=None):
    """
    把 GitHub API 的 release JSON 转成 GithubRelease。

    Args:
        data (dict): 单个 release 的原始响应。
        owner (str): 仓库所有者。
        repo (str): 仓库名。

    Returns:
        GithubRelease: 规范化后的发布对象。
    """
    assets = [
        GithubAsset(
            name=a.get("name"),
            download_url=a.get("browser_download_url"),
            size=a.get("size"),
            content_type=a.get("content_type"),
            download_count=a.get("download_count"),
        )
        for a in (data.get("assets") or [])
    ]

    tag = data.get("tag_name")

    return GithubRelease(
        owner=owner,
        repo=repo,
        version=_clean_version(tag),
        tag=tag,
        name=data.get("name"),
        published_at=data.get("published_at"),
        html_url=data.get("html_url"),
        prerelease=bool(data.get("prerelease")),
        draft=bool(data.get("draft")),
        body=data.get("body"),
        assets=assets,
        tarball_url=data.get("tarball_url"),
        zipball_url=data.get("zipball_url"),
        raw=data,
    )


def get_latest_release(repo, token=None, timeout=10, include_prerelease=False):
    """
    获取仓库最新的发布版本。

    Args:
        repo (str): 仓库地址或 'owner/repo'，例如 'https://github.com/jgm/pandoc'。
        token (str): GitHub 访问令牌，可选，用于提升速率限制。
        timeout (float): 请求超时时间（秒）。
        include_prerelease (bool): 是否把预发布版本也纳入考虑。
            False 时使用 /releases/latest（自动跳过预发布与草稿）；
            True 时取发布列表中最新的一条（含预发布）。

    Returns:
        GithubRelease: 最新发布对象。

    Raises:
        RuntimeError: 仓库不存在或没有任何发布时抛出。
    """
    owner, name = parse_repo(repo)

    if include_prerelease:
        releases = list_releases(repo, token=token, timeout=timeout, per_page=1)
        if not releases:
            raise RuntimeError(f"仓库没有任何发布: {owner}/{name}")
        return releases[0]

    url = f"{GITHUB_API}/repos/{owner}/{name}/releases/latest"
    data = _request_json(url, token=token, timeout=timeout)
    return _build_release(data, owner=owner, repo=name)


def list_releases(repo, token=None, timeout=10, per_page=30, page=1):
    """
    列出仓库的发布（按时间从新到旧）。

    Args:
        repo (str): 仓库地址或 'owner/repo'。
        token (str): GitHub 访问令牌，可选。
        timeout (float): 请求超时时间（秒）。
        per_page (int): 每页数量（1-100）。
        page (int): 页码，从 1 开始。

    Returns:
        list[GithubRelease]: 发布对象列表。
    """
    owner, name = parse_repo(repo)
    url = f"{GITHUB_API}/repos/{owner}/{name}/releases"
    data = _request_json(
        url,
        token=token,
        timeout=timeout,
        params={"per_page": max(1, min(per_page, 100)), "page": page},
    )
    return [_build_release(item, owner=owner, repo=name) for item in data]


def get_latest_version(repo, token=None, timeout=10, include_prerelease=False):
    """
    获取仓库最新发布的版本号（去掉前缀 v）。

    Args:
        repo (str): 仓库地址或 'owner/repo'。
        token (str): GitHub 访问令牌，可选。
        timeout (float): 请求超时时间（秒）。
        include_prerelease (bool): 是否把预发布版本纳入考虑。

    Returns:
        str: 版本号，例如 '3.10'。
    """
    release = get_latest_release(
        repo, token=token, timeout=timeout, include_prerelease=include_prerelease
    )
    return release.version


def get_download_urls(
    repo,
    token=None,
    timeout=10,
    pattern=None,
    include_source=True,
    include_prerelease=False,
):
    """
    获取仓库最新发布的下载链接列表。

    Args:
        repo (str): 仓库地址或 'owner/repo'，例如 'https://github.com/jgm/pandoc'。
        token (str): GitHub 访问令牌，可选。
        timeout (float): 请求超时时间（秒）。
        pattern: 可选，按文件名过滤资源的通配符（fnmatch 语法），
            例如 '*.exe'、'*windows*amd64*'；为 None 时返回全部资源。
        include_source (bool): 是否追加源码包（tar.gz / zip）地址。
        include_prerelease (bool): 是否把预发布版本纳入考虑。

    Returns:
        list[str]: 下载地址列表。
    """
    release = get_latest_release(
        repo, token=token, timeout=timeout, include_prerelease=include_prerelease
    )
    return release.download_urls(pattern=pattern, include_source=include_source)


__all__ = [
    "GITHUB_API",
    "GithubAsset",
    "GithubRelease",
    "parse_repo",
    "get_latest_release",
    "get_latest_version",
    "get_download_urls",
    "list_releases",
]
