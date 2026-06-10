import os
import re
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Mapping, Optional, Sequence, Union


@dataclass(frozen=True)
class AudioSegment:
    """
    Store one audio split segment.

    Args:
        start: Segment start time, such as "00:00:00".
        end: Segment end time, such as "00:02:15"; None means until the end.
        name: Segment output name; None uses the start time.
    """
    start: str
    end: Optional[str] = None
    name: Optional[str] = None


SegmentInput = Union[AudioSegment, str, Sequence[Optional[str]], Mapping[str, Optional[str]]]


def to_seconds(time_text: str) -> int:
    """
    Convert a HH:MM:SS time string to seconds.

    Args:
        time_text: Time text in HH:MM:SS format.

    Returns:
        Time value in seconds.
    """
    parts = time_text.split(":")
    if len(parts) != 3:
        raise ValueError("time must be in HH:MM:SS format")

    try:
        h, m, s = [int(part) for part in parts]
    except ValueError as e:
        raise ValueError("time must contain integer values") from e

    if h < 0 or not 0 <= m <= 59 or not 0 <= s <= 59:
        raise ValueError("time is out of range")

    return h * 3600 + m * 60 + s


def to_time_str(seconds: int) -> str:
    """
    Convert seconds to a HH:MM:SS time string.

    Args:
        seconds: Time value in seconds.

    Returns:
        Time text in HH:MM:SS format.
    """
    if seconds < 0:
        raise ValueError("seconds must be non-negative")

    h = seconds // 3600
    m = seconds % 3600 // 60
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


def safe_filename(name: str) -> str:
    """
    Convert text to a Windows-safe file name.

    Args:
        name: Original file name text.

    Returns:
        Safe file name text.
    """
    safe = re.sub(r'[<>:"/\\|?*]', "_", name).strip()
    return safe or "untitled"


def format_command(cmd: Sequence[str]) -> str:
    """
    Format a command list as shell-like text for display.

    Args:
        cmd: Command arguments.

    Returns:
        Display-friendly command text.
    """
    return " ".join(shlex.quote(str(part)) for part in cmd)


def _ffmpeg_executable_name() -> str:
    """
    Get the platform-specific ffmpeg executable name.

    Returns:
        ffmpeg executable file name.
    """
    return "ffmpeg.exe" if os.name == "nt" else "ffmpeg"


def _resolve_ffmpeg(ffmpeg: Union[str, Path]) -> str:
    """
    Resolve an ffmpeg command, executable path, or executable directory.

    Args:
        ffmpeg: ffmpeg command, executable path, or directory containing ffmpeg.

    Returns:
        Resolved ffmpeg command text.
    """
    path = Path(ffmpeg)
    if path.is_dir():
        return str(path / _ffmpeg_executable_name())
    return str(ffmpeg)


def _resolve_audio_codec(suffix: str, audio_codec: str) -> str:
    """
    Resolve the audio codec used for one output file.

    Args:
        suffix: Output file suffix.
        audio_codec: Requested audio codec; "auto" picks a format-safe default.

    Returns:
        Audio codec passed to ffmpeg -c:a.
    """
    if audio_codec != "auto":
        return audio_codec

    if suffix.casefold() == ".flac":
        return "flac"

    return "copy"


def _segment_from_mapping(item: Mapping[str, Optional[str]]) -> AudioSegment:
    """
    Convert a mapping to an AudioSegment.

    Args:
        item: Mapping with start, optional end, and optional name fields.

    Returns:
        AudioSegment value.
    """
    name = item.get("name")
    if name is None:
        name = item.get("title")

    start = item.get("start")
    if start is None:
        start = item.get("start_time")
    if start is None:
        raise ValueError("segment mapping must contain start or start_time")

    end = item.get("end")
    if end is None:
        end = item.get("end_time")

    return AudioSegment(
        start=str(start),
        end=str(end) if end is not None else None,
        name=str(name) if name is not None else None,
    )


def _segment_from_sequence(item: Sequence[Optional[str]]) -> AudioSegment:
    """
    Convert a sequence to an AudioSegment.

    Args:
        item: Sequence containing start, start and name, or start, end, and name.

    Returns:
        AudioSegment value.
    """
    if len(item) == 1:
        start = item[0]
        end = None
        name = None
    elif len(item) == 2:
        start, name = item
        end = None
    elif len(item) == 3:
        start, end, name = item
    else:
        raise ValueError("segment sequence must contain start, start and name, or start, end, and name")

    if start is None:
        raise ValueError("segment start is required")

    return AudioSegment(
        start=str(start),
        end=str(end) if end is not None else None,
        name=str(name) if name is not None else None,
    )


def as_segment(item: SegmentInput) -> AudioSegment:
    """
    Convert supported segment input to an AudioSegment.

    Args:
        item: AudioSegment, start time string, mapping, or sequence.

    Returns:
        AudioSegment value.
    """
    if isinstance(item, AudioSegment):
        return item
    if isinstance(item, str):
        return AudioSegment(start=item)
    if isinstance(item, Mapping):
        return _segment_from_mapping(item)
    if not isinstance(item, Sequence):
        raise TypeError("segment must be an AudioSegment, string, mapping, or sequence")
    return _segment_from_sequence(item)


def _fill_segment_ends(raw_segments: Iterable[SegmentInput]) -> List[AudioSegment]:
    """
    Fill missing segment end times from the next segment start time.

    Args:
        raw_segments: Segment inputs.

    Returns:
        Audio segments with inferred end times when possible.
    """
    segments = [as_segment(item) for item in raw_segments]
    filled = []

    for index, segment in enumerate(segments):
        end = segment.end
        if end is None and index + 1 < len(segments):
            end = segments[index + 1].start
        filled.append(AudioSegment(start=segment.start, end=end, name=segment.name))

    return filled


def _segment_output_name(segment: AudioSegment) -> str:
    """
    Get the output name for a segment.

    Args:
        segment: Audio segment.

    Returns:
        Segment name if set, otherwise the segment start time.
    """
    return segment.name or segment.start


class Ffmpeg:
    """
    Small wrapper around the ffmpeg executable.

    Args:
        ffmpeg: ffmpeg command, executable path, or directory containing ffmpeg.
    """

    def __init__(self, ffmpeg: Union[str, Path] = "ffmpeg"):
        """
        Initialize the ffmpeg wrapper.

        Args:
            ffmpeg: ffmpeg command, executable path, or directory containing ffmpeg.

        Returns:
            None
        """
        self.ffmpeg = _resolve_ffmpeg(ffmpeg)

    def build_split_commands(
            self,
            src: Union[str, Path],
            segments: Iterable[SegmentInput],
            out_dir: Optional[Union[str, Path]] = None,
            prefix: str = "",
            ext: Optional[str] = None,
            overwrite: bool = True,
            audio_codec: str = "auto",
            ) -> List[List[str]]:
        """
        Build ffmpeg commands for splitting one audio file.

        Args:
            src: Source audio file path.
            segments: Audio segments to export. Missing end values are inferred
                from the next segment start time when possible.
            out_dir: Output directory; defaults to the source file directory.
            prefix: Output file name prefix.
            ext: Output file extension; defaults to the source suffix.
            overwrite: Whether to overwrite existing output files.
            audio_codec: Audio codec passed to ffmpeg -c:a; "auto" uses flac for
                FLAC output and copy for other output formats.

        Returns:
            List of ffmpeg command argument lists.
        """
        src_path = Path(src)
        output_dir = Path(out_dir) if out_dir is not None else src_path.parent
        suffix = ext if ext is not None else src_path.suffix
        if suffix and not suffix.startswith("."):
            suffix = "." + suffix
        if not suffix:
            suffix = ".mp3"
        resolved_audio_codec = _resolve_audio_codec(suffix, audio_codec)

        commands = []
        for segment in _fill_segment_ends(segments):
            output = output_dir / f"{prefix}{safe_filename(_segment_output_name(segment))}{suffix}"

            cmd = [
                self.ffmpeg,
                "-hide_banner",
                "-y" if overwrite else "-n",
                "-ss", segment.start,
                "-i", str(src_path),
                "-map", "0:a:0",
                "-vn",
                "-c:a", resolved_audio_codec,
            ]

            if segment.end is not None:
                duration = to_seconds(segment.end) - to_seconds(segment.start)
                if duration <= 0:
                    raise ValueError("segment end must be later than start")
                cmd.extend(["-t", to_time_str(duration)])

            cmd.append(str(output))
            commands.append(cmd)

        return commands

    def split(
            self,
            src: Union[str, Path],
            segments: Iterable[SegmentInput],
            out_dir: Optional[Union[str, Path]] = None,
            prefix: str = "",
            ext: Optional[str] = None,
            overwrite: bool = True,
            audio_codec: str = "auto",
            check: bool = True,
            verbose: bool = False,
            ) -> List[Path]:
        """
        Split one audio file into multiple files.

        Args:
            src: Source audio file path.
            segments: Audio segments to export. Missing end values are inferred
                from the next segment start time when possible.
            out_dir: Output directory; defaults to the source file directory.
            prefix: Output file name prefix.
            ext: Output file extension; defaults to the source suffix.
            overwrite: Whether to overwrite existing output files.
            audio_codec: Audio codec passed to ffmpeg -c:a; "auto" uses flac for
                FLAC output and copy for other output formats.
            check: Whether subprocess.run should raise on a non-zero exit code.
            verbose: Whether to print each ffmpeg command before running it.

        Returns:
            Output file paths.
        """
        commands = self.build_split_commands(
            src=src,
            segments=segments,
            out_dir=out_dir,
            prefix=prefix,
            ext=ext,
            overwrite=overwrite,
            audio_codec=audio_codec,
        )

        outputs = []
        for cmd in commands:
            Path(cmd[-1]).parent.mkdir(parents=True, exist_ok=True)
            if verbose:
                print(format_command(cmd))
            subprocess.run(cmd, check=check)
            outputs.append(Path(cmd[-1]))

        return outputs


__all__ = [
    "AudioSegment",
    "Ffmpeg",
    "as_segment",
    "format_command",
    "safe_filename",
    "to_seconds",
    "to_time_str",
]
