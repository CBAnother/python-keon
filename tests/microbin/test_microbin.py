"""Tests for microbin module."""

from io import BytesIO
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from keon.microbin import (
    BURN_AFTER_VALUES,
    BurnAfter,
    EXPIRATIONS,
    Expiration,
    PRIVACY_LEVELS,
    Privacy,
    MicroBinRemoveResult,
    MicroBinUploadResult,
    remove,
    upload,
    upload_text,
)
from keon.microbin import (
    _extract_slug,
    _normalize_expiration,
    _normalize_slug,
    _resolve_upload_url,
)


class TestNormalization:
    def test_normalize_expiration_enum(self):
        assert _normalize_expiration(Expiration.HOUR_1) == "1hour"
        assert _normalize_expiration(Expiration.NEVER) == "never"

    def test_normalize_expiration_aliases(self):
        assert _normalize_expiration("1h") == "1hour"
        assert _normalize_expiration("never") == "never"

    def test_normalize_expiration_invalid(self):
        with pytest.raises(ValueError, match="不支持的 expiration"):
            _normalize_expiration("999days")

    def test_extract_slug_from_absolute_location(self):
        location = "https://paste.example.com/upload/cat-dog-fox"
        assert _extract_slug(location) == "cat-dog-fox"

    def test_extract_slug_from_relative_location(self):
        assert _extract_slug("/upload/cat-dog-fox") == "cat-dog-fox"

    def test_resolve_upload_url_relative(self):
        url = _resolve_upload_url("/upload/cat-dog-fox", "https://paste.example.com")
        assert url == "https://paste.example.com/upload/cat-dog-fox"

    def test_normalize_slug_from_url(self):
        assert _normalize_slug("https://paste.example.com/upload/cat-dog-fox") == "cat-dog-fox"
        assert _normalize_slug("cat-dog-fox") == "cat-dog-fox"

    def test_normalize_slug_invalid(self):
        with pytest.raises(ValueError, match="无法解析 paste ID"):
            _normalize_slug("https://paste.example.com/unknown/cat-dog-fox")


class TestUploadValidation:
    def test_upload_requires_content_or_files(self):
        with pytest.raises(ValueError, match="至少需要提供 content 或 files"):
            upload(server="https://paste.example.com")

    def test_upload_requires_server(self, monkeypatch):
        monkeypatch.delenv("MICROBIN_SERVER", raising=False)
        with pytest.raises(ValueError, match="未配置 MicroBin 服务器地址"):
            upload(content="hello")

    def test_upload_invalid_privacy(self):
        with pytest.raises(ValueError, match="不支持的 privacy"):
            upload(content="hello", server="https://paste.example.com", privacy="hidden")

    def test_upload_invalid_burn_after(self):
        with pytest.raises(ValueError, match="不支持的 burn_after"):
            upload(
                content="hello",
                server="https://paste.example.com",
                burn_after=5,
            )

    def test_upload_missing_file(self, tmp_path):
        missing = tmp_path / "missing.txt"
        with pytest.raises(FileNotFoundError, match="附件文件不存在"):
            upload(files=missing, server="https://paste.example.com")

    def test_upload_text_requires_string(self):
        with pytest.raises(TypeError, match="content 必须是字符串"):
            upload_text(123, server="https://paste.example.com")  # type: ignore[arg-type]


class TestUploadRequest:
    def _mock_response(self, location="https://paste.example.com/upload/cat-dog-fox"):
        response = MagicMock()
        response.status_code = 302
        response.headers = {"Location": location}
        response.text = ""
        return response

    @patch("keon.microbin.requests.post")
    def test_upload_text_success(self, mock_post):
        mock_post.return_value = self._mock_response()

        url = upload_text(
            "hello world",
            server="https://paste.example.com",
            syntax="yaml",
            privacy="public",
            expiration="never",
        )

        assert url == "https://paste.example.com/upload/cat-dog-fox"
        mock_post.assert_called_once()
        kwargs = mock_post.call_args.kwargs
        assert kwargs["data"]["expiration"] == "never"
        assert kwargs["data"]["privacy"] == "public"
        assert kwargs["data"]["syntax_highlight"] == "yaml"
        assert kwargs["files"] == [("content", (None, "hello world"))]

    @patch("keon.microbin.requests.post")
    def test_upload_with_enum_options(self, mock_post):
        mock_post.return_value = self._mock_response()

        result = upload(
            content="secret",
            server="https://paste.example.com",
            expiration=Expiration.HOUR_1,
            burn_after=BurnAfter.TEN,
            privacy=Privacy.PRIVATE,
            password="pass123",
        )

        assert result.slug == "cat-dog-fox"
        kwargs = mock_post.call_args.kwargs
        assert kwargs["data"]["expiration"] == "1hour"
        assert kwargs["data"]["burn_after"] == "10"
        assert kwargs["data"]["privacy"] == "private"

    @patch("keon.microbin.requests.post")
    def test_upload_with_all_options(self, mock_post):
        mock_post.return_value = self._mock_response()

        result = upload(
            content="secret",
            server="https://paste.example.com",
            expiration="1hour",
            burn_after=10,
            syntax="py",
            privacy="private",
            password="pass123",
            uploader_password="upload-pass",
            auth=("user", "token"),
        )

        assert isinstance(result, MicroBinUploadResult)
        assert result.slug == "cat-dog-fox"
        assert result.url == "https://paste.example.com/upload/cat-dog-fox"

        kwargs = mock_post.call_args.kwargs
        assert kwargs["auth"] == ("user", "token")
        assert kwargs["data"]["expiration"] == "1hour"
        assert kwargs["data"]["burn_after"] == "10"
        assert kwargs["data"]["plain_key"] == "pass123"
        assert kwargs["data"]["uploader_password"] == "upload-pass"

    @patch("keon.microbin.requests.post")
    def test_upload_file_attachment(self, mock_post, tmp_path):
        mock_post.return_value = self._mock_response()
        file_path = tmp_path / "demo.txt"
        file_path.write_text("file body", encoding="utf-8")

        result = upload(files=file_path, server="https://paste.example.com")

        assert result.slug == "cat-dog-fox"
        files = mock_post.call_args.kwargs["files"]
        assert len(files) == 1
        field_name, payload = files[0]
        assert field_name == "file"
        assert payload[0] == "demo.txt"

    @patch("keon.microbin.requests.post")
    def test_upload_multiple_file_attachments(self, mock_post, tmp_path):
        mock_post.return_value = self._mock_response()
        first = tmp_path / "a.txt"
        second = tmp_path / "b.txt"
        first.write_text("a", encoding="utf-8")
        second.write_text("b", encoding="utf-8")

        upload(files=[first, second], server="https://paste.example.com")

        files = mock_post.call_args.kwargs["files"]
        assert len(files) == 2
        assert files[0][1][0] == "a.txt"
        assert files[1][1][0] == "b.txt"

    @patch("keon.microbin.requests.post")
    def test_upload_binary_stream(self, mock_post):
        mock_post.return_value = self._mock_response()
        stream = BytesIO(b"stream body")

        upload(files=stream, server="https://paste.example.com")

        files = mock_post.call_args.kwargs["files"]
        assert files[0] == ("file", stream)

    @patch("keon.microbin.requests.post")
    def test_upload_http_error(self, mock_post):
        response = MagicMock()
        response.status_code = 403
        response.text = "forbidden"
        mock_post.return_value = response

        with pytest.raises(RuntimeError, match="MicroBin 上传失败 \\(HTTP 403\\)"):
            upload(content="hello", server="https://paste.example.com")

    @patch("keon.microbin.requests.post")
    def test_upload_missing_location(self, mock_post):
        response = MagicMock()
        response.status_code = 302
        response.headers = {}
        response.text = ""
        mock_post.return_value = response

        with pytest.raises(RuntimeError, match="响应缺少 Location 头"):
            upload(content="hello", server="https://paste.example.com")


class TestRemoveRequest:
    def _mock_remove_response(self, location="https://paste.example.com/list"):
        response = MagicMock()
        response.status_code = 302
        response.headers = {"Location": location}
        response.text = ""
        return response

    @patch("keon.microbin.requests.get")
    def test_remove_success(self, mock_get):
        mock_get.return_value = self._mock_remove_response()

        result = remove("cat-dog-fox", server="https://paste.example.com")

        assert isinstance(result, MicroBinRemoveResult)
        assert result.slug == "cat-dog-fox"
        mock_get.assert_called_once_with(
            "https://paste.example.com/remove/cat-dog-fox",
            auth=None,
            timeout=30,
            allow_redirects=False,
        )

    @patch("keon.microbin.requests.post")
    def test_remove_with_password(self, mock_post):
        mock_post.return_value = self._mock_remove_response()

        result = remove(
            "https://paste.example.com/upload/cat-dog-fox",
            server="https://paste.example.com",
            password="secret",
        )

        assert result.slug == "cat-dog-fox"
        mock_post.assert_called_once()
        assert mock_post.call_args.kwargs["data"] == {"password": "secret"}

    @patch("keon.microbin.requests.get")
    def test_remove_not_found(self, mock_get):
        response = MagicMock()
        response.status_code = 404
        response.headers = {}
        response.text = "not found"
        mock_get.return_value = response

        with pytest.raises(RuntimeError, match="paste 不存在"):
            remove("missing-paste", server="https://paste.example.com")

    @patch("keon.microbin.requests.get")
    def test_remove_failed(self, mock_get):
        response = MagicMock()
        response.status_code = 403
        response.headers = {}
        response.text = "forbidden"
        mock_get.return_value = response

        with pytest.raises(RuntimeError, match="MicroBin 删除失败"):
            remove("cat-dog-fox", server="https://paste.example.com")


class TestConstants:
    def test_documented_values(self):
        assert Expiration.NEVER.value in EXPIRATIONS
        assert Privacy.PUBLIC.value in PRIVACY_LEVELS
        assert BurnAfter.TEN.value in BURN_AFTER_VALUES
