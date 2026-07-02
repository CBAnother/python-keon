"""MicroBin 客户端模块，支持上传与删除 paste。"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
from typing import Any, BinaryIO, Optional, Sequence, Union
import os
import re

import requests


class Expiration(str, Enum):
    """MicroBin 过期时间选项。"""

    MIN_1 = "1min"
    MIN_10 = "10min"
    HOUR_1 = "1hour"
    HOUR_24 = "24hour"
    DAYS_3 = "3days"
    WEEK_1 = "1week"
    MONTH_1 = "1month"
    MONTHS_6 = "6months"
    YEAR_1 = "1year"
    NEVER = "never"


class Privacy(str, Enum):
    """MicroBin 隐私级别选项。"""

    PUBLIC = "public"
    UNLISTED = "unlisted"
    READONLY = "readonly"
    PRIVATE = "private"
    SECRET = "secret"


class BurnAfter(int, Enum):
    """MicroBin 阅读次数上限（Burn After）选项。"""

    ONCE = 1
    TEN = 10
    HUNDRED = 100
    THOUSAND = 1000
    TEN_THOUSAND = 10000


EXPIRATIONS = tuple(item.value for item in Expiration)
PRIVACY_LEVELS = tuple(item.value for item in Privacy)
BURN_AFTER_VALUES = tuple(item.value for item in BurnAfter)

ExpirationInput = Union[str, Expiration]
PrivacyInput = Union[str, Privacy]
BurnAfterInput = Union[int, BurnAfter, None]

# 常见别名 -> MicroBin 标准 expiration 值
_EXPIRATION_ALIASES = {
    "1m": "1min",
    "10m": "10min",
    "1h": "1hour",
    "24h": "24hour",
    "3d": "3days",
    "1w": "1week",
    "1mo": "1month",
    "6mo": "6months",
    "1y": "1year",
    "permanent": "never",
    "forever": "never",
}

_LOCATION_SLUG_RE = re.compile(r"/(?:upload|auth)/([^/?#]+)/?$", re.IGNORECASE)
_SLUG_INPUT_RE = re.compile(
    r"(?:https?://[^/]+)?/(?:upload|raw|file|remove)/([^/?#]+)",
    re.IGNORECASE,
)

DEFAULT_SERVER_ENV = "MICROBIN_SERVER"
DEFAULT_UPLOADER_PASSWORD_ENV = "MICROBIN_UPLOADER_PASSWORD"
DEFAULT_AUTH_ENV = "MICROBIN_AUTH"


FileInput = Union[str, Path, BinaryIO]
FilesInput = Union[FileInput, Sequence[FileInput]]


@dataclass
class MicroBinUploadResult:
    """
    MicroBin 上传结果。

    Attributes:
        url: 可访问的 paste 页面地址。
        slug: paste 标识（通常为 animal-name 形式）。
        location: 响应中的 Location 头原始值。
        raw_headers: 响应头字典。
    """

    url: str
    slug: str
    location: Optional[str] = None
    raw_headers: Optional[dict[str, str]] = None

    def to_dict(self) -> dict[str, Any]:
        """转换为普通字典。"""
        return asdict(self)


@dataclass
class MicroBinRemoveResult:
    """
    MicroBin 删除结果。

    Attributes:
        slug: 已删除的 paste 标识。
        location: 响应中的 Location 头原始值。
        raw_headers: 响应头字典。
    """

    slug: str
    location: Optional[str] = None
    raw_headers: Optional[dict[str, str]] = None

    def to_dict(self) -> dict[str, Any]:
        """转换为普通字典。"""
        return asdict(self)


def _normalize_slug(slug_or_url: str) -> str:
    value = slug_or_url.strip()
    if not value:
        raise ValueError("slug 不能为空")

    match = _SLUG_INPUT_RE.search(value)
    if match:
        return match.group(1)

    if "/" in value or value.lower().startswith("http"):
        raise ValueError(f"无法解析 paste ID: {slug_or_url!r}")

    return value


def _is_remove_success(response: requests.Response) -> bool:
    if response.status_code not in (301, 302, 303, 307, 308):
        return False

    location = response.headers.get("Location", "")
    return "/list" in location.lower()


def _normalize_server(server: str) -> str:
    server = server.strip().rstrip("/")
    if not server:
        raise ValueError("MicroBin 服务器地址不能为空")
    return server


def _resolve_server(server: Optional[str]) -> str:
    resolved = server or os.environ.get(DEFAULT_SERVER_ENV)
    if not resolved:
        raise ValueError(
            f"未配置 MicroBin 服务器地址，请传入 server 参数或设置环境变量 {DEFAULT_SERVER_ENV}"
        )
    return _normalize_server(resolved)


def _normalize_expiration(expiration: ExpirationInput) -> str:
    if isinstance(expiration, Expiration):
        return expiration.value

    if not isinstance(expiration, str) or not expiration.strip():
        raise ValueError("expiration 不能为空")

    value = expiration.strip().lower()
    value = _EXPIRATION_ALIASES.get(value, value)

    if value not in EXPIRATIONS:
        raise ValueError(
            f"不支持的 expiration: {expiration!r}，可选值: {', '.join(EXPIRATIONS)}"
        )
    return value


def _normalize_privacy(privacy: PrivacyInput) -> str:
    if isinstance(privacy, Privacy):
        return privacy.value

    if not isinstance(privacy, str) or not privacy.strip():
        raise ValueError("privacy 不能为空")

    value = privacy.strip().lower()
    if value not in PRIVACY_LEVELS:
        raise ValueError(
            f"不支持的 privacy: {privacy!r}，可选值: {', '.join(PRIVACY_LEVELS)}"
        )
    return value


def _normalize_burn_after(burn_after: BurnAfterInput) -> Optional[int]:
    if burn_after is None:
        return None

    if isinstance(burn_after, BurnAfter):
        return burn_after.value

    if not isinstance(burn_after, int):
        raise TypeError(f"burn_after 必须是整数，收到: {type(burn_after).__name__}")

    if burn_after not in BURN_AFTER_VALUES:
        raise ValueError(
            f"不支持的 burn_after: {burn_after}，可选值: {', '.join(map(str, BURN_AFTER_VALUES))}"
        )
    return burn_after


def _normalize_syntax(syntax: Optional[str]) -> str:
    if syntax is None:
        return "auto"
    if not isinstance(syntax, str):
        raise TypeError(f"syntax 必须是字符串，收到: {type(syntax).__name__}")
    return syntax.strip().lower() or "auto"


def _parse_auth(auth: Optional[Union[str, tuple[str, str]]]) -> Optional[tuple[str, str]]:
    if auth is None:
        env_auth = os.environ.get(DEFAULT_AUTH_ENV)
        if env_auth:
            auth = env_auth

    if auth is None:
        return None

    if isinstance(auth, tuple):
        if len(auth) != 2:
            raise ValueError("auth 元组必须是 (username, password)")
        username, password = auth
        if not username or not password:
            raise ValueError("auth 用户名和密码均不能为空")
        return username, password

    if not isinstance(auth, str) or ":" not in auth:
        raise ValueError("auth 字符串格式应为 'username:password'")

    username, password = auth.split(":", 1)
    if not username or not password:
        raise ValueError("auth 用户名和密码均不能为空")
    return username, password


def _extract_slug(location: str) -> str:
    location = location.strip()
    match = _LOCATION_SLUG_RE.search(location)
    if match:
        return match.group(1)
    raise RuntimeError(f"无法从 Location 头解析 paste ID: {location}")


def _resolve_upload_url(location: str, server: str) -> str:
    if location.startswith(("http://", "https://")):
        return location
    if not location.startswith("/"):
        location = f"/{location}"
    return f"{server}{location}"


def _iter_file_inputs(files: FilesInput) -> list[FileInput]:
    if isinstance(files, (str, Path)) or hasattr(files, "read"):
        return [files]  # type: ignore[list-item]
    return list(files)


def _open_file_input(file_input: FileInput) -> tuple[Any, Optional[str]]:
    if hasattr(file_input, "read"):
        return file_input, None

    path = Path(file_input)
    if not path.is_file():
        raise FileNotFoundError(f"附件文件不存在: {path}")
    return open(path, "rb"), path.name


def _build_multipart(
    content: Optional[str],
    files: Optional[FilesInput],
    *,
    expiration: str,
    privacy: str,
    syntax: str,
    burn_after: Optional[int],
    password: Optional[str],
    uploader_password: Optional[str],
) -> tuple[dict[str, str], list[tuple[str, Any]], list[Any]]:
    data: dict[str, str] = {
        "expiration": expiration,
        "privacy": privacy,
        "syntax_highlight": syntax,
    }

    if burn_after is not None:
        data["burn_after"] = str(burn_after)
    if password:
        data["plain_key"] = password
    if uploader_password:
        data["uploader_password"] = uploader_password

    multipart_files: list[tuple[str, Any]] = []
    opened_handles: list[Any] = []

    if content is not None:
        multipart_files.append(("content", (None, content)))

    if files is not None:
        for file_input in _iter_file_inputs(files):
            handle, filename = _open_file_input(file_input)
            if filename is None:
                multipart_files.append(("file", handle))
            else:
                opened_handles.append(handle)
                multipart_files.append(("file", (filename, handle)))

    return data, multipart_files, opened_handles


def upload(
    content: Optional[str] = None,
    files: Optional[FilesInput] = None,
    *,
    server: Optional[str] = None,
    expiration: ExpirationInput = Expiration.NEVER,
    burn_after: BurnAfterInput = None,
    syntax: Optional[str] = None,
    privacy: PrivacyInput = Privacy.PUBLIC,
    password: Optional[str] = None,
    uploader_password: Optional[str] = None,
    auth: Optional[Union[str, tuple[str, str]]] = None,
    timeout: float = 30,
) -> MicroBinUploadResult:
    """
    上传文本或文件到 MicroBin。

    至少需要提供 ``content`` 或 ``files`` 之一。上传成功后从响应 ``Location`` 头解析 paste URL。

    Args:
        content: 文本内容。
        files: 单个或多个附件，可为路径或已打开的二进制流。
        server: MicroBin 服务器地址，例如 ``https://paste.example.com``。
            未传入时读取环境变量 ``MICROBIN_SERVER``。
        expiration: 过期时间，默认 ``Expiration.NEVER``。支持 ``Expiration`` 枚举、
            字符串（``1min``、``1hour``、``never`` 等），以及 ``1h``、``24h`` 等别名。
        burn_after: 阅读次数上限，达到后自动删除。支持 ``BurnAfter`` 枚举或
            ``1``、``10``、``100``、``1000``、``10000``。
        syntax: 语法高亮语言，例如 ``py``、``yaml``、``none``。默认 ``auto``。
        privacy: 隐私级别，支持 ``Privacy`` 枚举或对应字符串。
        password: 访问密码，对应表单字段 ``plain_key``，用于 private/readonly/secret。
        uploader_password: 服务端配置的上传密码，对应 ``uploader_password`` 字段。
            未传入时读取环境变量 ``MICROBIN_UPLOADER_PASSWORD``。
        auth: HTTP Basic 认证，格式为 ``(username, password)`` 或 ``"user:pass"``。
            未传入时读取环境变量 ``MICROBIN_AUTH``。
        timeout: 请求超时时间（秒）。

    Returns:
        MicroBinUploadResult: 上传结果，包含 URL 与 slug。

    Raises:
        ValueError: 参数无效或未配置服务器地址。
        FileNotFoundError: 附件路径不存在。
        RuntimeError: 上传失败或无法解析响应。

    Example:
        >>> from keon.microbin import upload
        >>> result = upload(
        ...     content="print('hello')",
        ...     server="https://paste.example.com",
        ...     syntax="py",
        ...     privacy=Privacy.PUBLIC,
        ...     expiration=Expiration.NEVER,
        ... )
        >>> print(result.url)
    """
    if content is None and files is None:
        raise ValueError("至少需要提供 content 或 files 之一")

    server_url = _resolve_server(server)
    expiration_value = _normalize_expiration(expiration)
    privacy_value = _normalize_privacy(privacy)
    burn_after_value = _normalize_burn_after(burn_after)
    syntax_value = _normalize_syntax(syntax)
    auth_value = _parse_auth(auth)

    resolved_uploader_password = uploader_password or os.environ.get(
        DEFAULT_UPLOADER_PASSWORD_ENV
    )

    data, multipart_files, opened_handles = _build_multipart(
        content,
        files,
        expiration=expiration_value,
        privacy=privacy_value,
        syntax=syntax_value,
        burn_after=burn_after_value,
        password=password,
        uploader_password=resolved_uploader_password,
    )

    upload_endpoint = f"{server_url}/upload"

    try:
        response = requests.post(
            upload_endpoint,
            data=data,
            files=multipart_files or None,
            auth=auth_value,
            timeout=timeout,
            allow_redirects=False,
        )
    finally:
        for handle in opened_handles:
            handle.close()

    if response.status_code not in (301, 302, 303, 307, 308):
        detail = response.text.strip()
        if detail:
            raise RuntimeError(
                f"MicroBin 上传失败 (HTTP {response.status_code}): {detail[:500]}"
            )
        raise RuntimeError(f"MicroBin 上传失败 (HTTP {response.status_code})")

    location = response.headers.get("Location")
    if not location:
        raise RuntimeError("MicroBin 上传失败：响应缺少 Location 头")

    slug = _extract_slug(location)
    url = _resolve_upload_url(location, server_url)

    return MicroBinUploadResult(
        url=url,
        slug=slug,
        location=location,
        raw_headers=dict(response.headers),
    )


def upload_text(
    content: str,
    *,
    server: Optional[str] = None,
    expiration: ExpirationInput = Expiration.NEVER,
    burn_after: BurnAfterInput = None,
    syntax: Optional[str] = None,
    privacy: PrivacyInput = Privacy.PUBLIC,
    password: Optional[str] = None,
    uploader_password: Optional[str] = None,
    auth: Optional[Union[str, tuple[str, str]]] = None,
    timeout: float = 30,
) -> str:
    """
    上传文本到 MicroBin 并返回 paste URL。

    这是 ``upload()`` 的便捷封装，参数与 ``upload()`` 一致（不含文件附件）。

    Args:
        content: 文本内容。
        server: MicroBin 服务器地址。
        expiration: 过期时间，默认 ``Expiration.NEVER``。
        burn_after: 阅读次数上限。
        syntax: 语法高亮语言，默认 ``auto``。
        privacy: 隐私级别，默认 ``Privacy.PUBLIC``。
        password: 访问密码。
        uploader_password: 服务端上传密码。
        auth: HTTP Basic 认证。
        timeout: 请求超时时间（秒）。

    Returns:
        str: paste 页面 URL。

    Example:
        >>> from keon.microbin import upload_text
        >>> url = upload_text(
        ...     "hello world",
        ...     server="https://paste.example.com",
        ...     syntax="yaml",
        ...     privacy=Privacy.PUBLIC,
        ...     expiration=Expiration.NEVER,
        ... )
    """
    if not isinstance(content, str):
        raise TypeError(f"content 必须是字符串，收到: {type(content).__name__}")

    result = upload(
        content=content,
        server=server,
        expiration=expiration,
        burn_after=burn_after,
        syntax=syntax,
        privacy=privacy,
        password=password,
        uploader_password=uploader_password,
        auth=auth,
        timeout=timeout,
    )
    return result.url


def remove(
    slug: str,
    *,
    server: Optional[str] = None,
    password: Optional[str] = None,
    auth: Optional[Union[str, tuple[str, str]]] = None,
    timeout: float = 30,
) -> MicroBinRemoveResult:
    """
    删除 MicroBin 上的 paste。

    成功时服务端会重定向到 ``/list``。``slug`` 可传入 animal-name 标识，
    也可传入完整 URL（如 ``https://paste.example.com/upload/cat-dog-fox``）。

    Args:
        slug: paste 标识或 paste 页面 URL。
        server: MicroBin 服务器地址。未传入时读取环境变量 ``MICROBIN_SERVER``。
        password: 访问密码。受密码保护的 paste 删除时需传入。
        auth: HTTP Basic 认证，格式为 ``(username, password)`` 或 ``"user:pass"``。
        timeout: 请求超时时间（秒）。

    Returns:
        MicroBinRemoveResult: 删除结果。

    Raises:
        ValueError: 参数无效或未配置服务器地址。
        RuntimeError: paste 不存在、密码错误或删除失败。

    Example:
        >>> from keon.microbin import remove
        >>> result = remove(
        ...     "cat-dog-fox",
        ...     server="https://paste.example.com",
        ... )
        >>> print(result.slug)
        cat-dog-fox
    """
    if not isinstance(slug, str):
        raise TypeError(f"slug 必须是字符串，收到: {type(slug).__name__}")

    server_url = _resolve_server(server)
    slug_value = _normalize_slug(slug)
    auth_value = _parse_auth(auth)
    endpoint = f"{server_url}/remove/{slug_value}"

    request_kwargs = {
        "auth": auth_value,
        "timeout": timeout,
        "allow_redirects": False,
    }

    if password:
        response = requests.post(endpoint, data={"password": password}, **request_kwargs)
    else:
        response = requests.get(endpoint, **request_kwargs)

    if response.status_code == 404:
        raise RuntimeError(f"paste 不存在: {slug_value}")

    if _is_remove_success(response):
        return MicroBinRemoveResult(
            slug=slug_value,
            location=response.headers.get("Location"),
            raw_headers=dict(response.headers),
        )

    detail = response.text.strip()
    if detail:
        raise RuntimeError(
            f"MicroBin 删除失败 (HTTP {response.status_code}): {detail[:500]}"
        )
    raise RuntimeError(f"MicroBin 删除失败: {slug_value}（密码错误或无权删除）")


__all__ = [
    "BURN_AFTER_VALUES",
    "BurnAfter",
    "EXPIRATIONS",
    "Expiration",
    "ExpirationInput",
    "PRIVACY_LEVELS",
    "Privacy",
    "PrivacyInput",
    "BurnAfterInput",
    "MicroBinRemoveResult",
    "MicroBinUploadResult",
    "remove",
    "upload",
    "upload_text",
]
