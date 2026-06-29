from types import SimpleNamespace

import pytest

import keon.novel as kn


def test_format_txt_uses_default_output_name(tmp_path):
    src = tmp_path / "book.txt"
    src.write_text(
        "序言\n第一章 开始\n正文一\n第12章 继续\n正文二",
        encoding="utf-8",
    )

    output = kn.format_txt(src)

    assert output == tmp_path / "book.format.txt"
    assert output.read_text(encoding="utf-8") == (
        "序言\n\n"
        "# 第一章 开始 {#ch001}\n\n"
        "正文一\n\n"
        "# 第12章 继续 {#ch002}\n\n"
        "正文二\n\n"
    )


def test_format_txt_accepts_suffix_without_dot(tmp_path):
    src = tmp_path / "book.txt"
    src.write_text("第一章 开始", encoding="utf-8")

    output = kn.format_txt(src, suffix="md")

    assert output == tmp_path / "book.md"
    assert output.read_text(encoding="utf-8") == "# 第一章 开始 {#ch001}\n\n"


def test_format_txt_accepts_explicit_output_and_custom_pattern(tmp_path):
    src = tmp_path / "book.txt"
    output = tmp_path / "formatted" / "book.markdown"
    src.write_text("Chapter 1 Start\nText", encoding="utf-8")

    result = kn.format_txt(
        src,
        output=output,
        chapter_pattern=r"Chapter \d+ .*",
    )

    assert result == output
    assert output.read_text(encoding="utf-8") == (
        "# Chapter 1 Start {#ch001}\n\n"
        "Text\n\n"
    )


def test_format_txt_rejects_conflicting_or_same_output(tmp_path):
    src = tmp_path / "book.txt"
    src.write_text("Text", encoding="utf-8")

    with pytest.raises(ValueError, match="cannot be used together"):
        kn.format_txt(src, suffix=".md", output=tmp_path / "other.md")

    with pytest.raises(ValueError, match="different from src"):
        kn.format_txt(src, suffix=".txt")


def test_txt_to_epub_formats_markdown_and_runs_pandoc(monkeypatch, tmp_path):
    src = tmp_path / "这游戏也太真实了.txt"
    src.write_text("第一章 开始\n正文", encoding="utf-8")
    pandoc = tmp_path / "pandoc.exe"
    calls = []

    def fake_run(command, check=True):
        calls.append(SimpleNamespace(command=command, check=check))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(kn.subprocess, "run", fake_run)

    output = kn.txt_to_epub(
        src,
        pandoc,
        title="这游戏也太真实了",
        author="晨星LL",
    )

    markdown = tmp_path / "这游戏也太真实了.md"
    assert markdown.read_text(encoding="utf-8") == (
        "# 第一章 开始 {#ch001}\n\n"
        "正文\n\n"
    )
    assert output == tmp_path / "这游戏也太真实了.epub"
    assert calls[0].check is True
    assert calls[0].command == [
        str(pandoc),
        "-f", "markdown+header_attributes-tex_math_dollars",
        str(markdown),
        "-o", str(output),
        "-t", "epub3",
        "--toc",
        "--toc-depth=1",
        "--split-level=1",
        "--metadata", "title=这游戏也太真实了",
        "--metadata", "author=晨星LL",
        "--metadata", "lang=zh-Hans-CN",
    ]


def test_txt_to_epub_defaults_title_and_supports_custom_output(monkeypatch, tmp_path):
    src = tmp_path / "book.txt"
    src.write_text("Text", encoding="utf-8")
    output = tmp_path / "epub" / "result.epub"
    calls = []

    def fake_run(command, check=True):
        calls.append((command, check))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(kn.subprocess, "run", fake_run)

    result = kn.txt_to_epub(
        src,
        "pandoc",
        author="Author",
        output=output,
        lang="zh-CN",
        check=False,
    )

    assert result == output
    assert output.parent.is_dir()
    assert "title=book" in calls[0][0]
    assert "lang=zh-CN" in calls[0][0]
    assert calls[0][1] is False
