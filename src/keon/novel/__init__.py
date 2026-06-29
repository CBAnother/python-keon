import re
import subprocess
from pathlib import Path
from typing import Optional, Pattern, Union


PathInput = Union[str, Path]
ChapterPattern = Union[str, Pattern[str]]

DEFAULT_CHAPTER_PATTERN = re.compile(
    r"第[一二三四五六七八九十百千万\d]+章\s+.*"
)


def _compile_chapter_pattern(pattern: ChapterPattern) -> Pattern[str]:
    if isinstance(pattern, str):
        return re.compile(pattern)
    return pattern


def _format_output_path(
        src: Path,
        suffix: Optional[str],
        output: Optional[PathInput],
        ) -> Path:
    if output is not None:
        if suffix is not None:
            raise ValueError("suffix and output cannot be used together")
        return Path(output)

    if suffix is None:
        if src.suffix:
            return src.with_name(f"{src.stem}.format{src.suffix}")
        return src.with_name(f"{src.name}.format")

    if not suffix:
        raise ValueError("suffix must not be empty")
    if not suffix.startswith("."):
        suffix = "." + suffix
    return src.with_suffix(suffix)


def format_txt(
        src: PathInput,
        suffix: Optional[str] = None,
        output: Optional[PathInput] = None,
        chapter_pattern: ChapterPattern = DEFAULT_CHAPTER_PATTERN,
        encoding: str = "utf-8",
        ) -> Path:
    """
    Format a novel text file as Markdown-style paragraphs and chapter headings.

    Chapter headings receive stable identifiers such as `{#ch001}`. When no
    output suffix or path is given, `book.txt` is written to
    `book.format.txt`.

    Args:
        src: Source novel text file.
        suffix: Output suffix, with or without a leading dot.
        output: Explicit output path. Cannot be combined with suffix.
        chapter_pattern: Regular expression used to recognize chapter lines.
        encoding: Source and output text encoding.

    Returns:
        Formatted output path.
    """
    src_path = Path(src)
    output_path = _format_output_path(src_path, suffix, output)

    if src_path.resolve() == output_path.resolve():
        raise ValueError("output must be different from src")

    pattern = _compile_chapter_pattern(chapter_pattern)
    text = src_path.read_text(encoding=encoding)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    chapter_id = 1
    with output_path.open("w", encoding=encoding, newline="\n") as file:
        for line in text.splitlines():
            if pattern.match(line):
                file.write(f"# {line} {{#ch{chapter_id:03d}}}\n\n")
                chapter_id += 1
            else:
                file.write(f"{line}\n\n")

    return output_path


def txt_to_epub(
        src: PathInput,
        pandoc: PathInput,
        *,
        author: str,
        title: Optional[str] = None,
        output: Optional[PathInput] = None,
        lang: str = "zh-Hans-CN",
        chapter_pattern: ChapterPattern = DEFAULT_CHAPTER_PATTERN,
        encoding: str = "utf-8",
        check: bool = True,
        verbose: bool = False,
        ) -> Path:
    """
    Format a novel text file and convert it to EPUB 3 with Pandoc.

    Args:
        src: Source novel text file.
        pandoc: Pandoc executable path.
        author: Novel author stored in EPUB metadata.
        title: Novel title; defaults to the source file stem.
        output: EPUB output path; defaults to the source path with .epub.
        lang: EPUB language metadata.
        chapter_pattern: Regular expression used to recognize chapter lines.
        encoding: Source and intermediate Markdown text encoding.
        check: Whether to raise when Pandoc returns a non-zero exit code.
        verbose: Whether to print the Pandoc command before running it.

    Returns:
        EPUB output path.
    """
    src_path = Path(src)
    markdown_path = format_txt(
        src_path,
        suffix=".md",
        chapter_pattern=chapter_pattern,
        encoding=encoding,
    )
    output_path = Path(output) if output is not None else src_path.with_suffix(".epub")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    command = [
        str(pandoc),
        "-f", "markdown+header_attributes-tex_math_dollars",
        str(markdown_path),
        "-o", str(output_path),
        "-t", "epub3",
        "--toc",
        "--toc-depth=1",
        "--split-level=1",
        "--metadata", f"title={title or src_path.stem}",
        "--metadata", f"author={author}",
        "--metadata", f"lang={lang}",
    ]

    if verbose:
        print(subprocess.list2cmdline(command))
    subprocess.run(command, check=check)
    return output_path


__all__ = [
    "DEFAULT_CHAPTER_PATTERN",
    "format_txt",
    "txt_to_epub",
]
