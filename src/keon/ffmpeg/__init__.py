import os
import re
import shutil
import shlex
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Mapping, Optional, Sequence, Tuple, Union


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


TimeLike = Union[int, float, str]


def _parse_clock_time_to_seconds(text: str) -> Optional[int]:
    """
    解析 MM:SS / HH:MM:SS 或 MM-SS / HH-MM-SS 格式，返回秒数。
    支持最后一段带小数，如 00:10:30.5 / 00-10-30.5。
    """
    s = text.strip().lower()
    if not s:
        return None

    sep = ":" if ":" in s else "-" if "-" in s else None
    if sep is None:
        return None

    parts = s.split(sep)
    if len(parts) not in (2, 3):
        raise ValueError("Invalid time format: {}".format(text))

    def _to_float(x: str) -> float:
        return float(x.strip())

    if len(parts) == 2:
        mm = _to_float(parts[0])
        ss = _to_float(parts[1])
        return int(round(mm * 60 + ss))

    hh = _to_float(parts[0])
    mm = _to_float(parts[1])
    ss = _to_float(parts[2])
    return int(round(hh * 3600 + mm * 60 + ss))


def parse_time_to_seconds(t: TimeLike) -> int:
    """
    支持：
    - 3600 / 3600.0
    - "3600"
    - "01:00:00" / "00:10:30.5"
    - "01-00-00" / "00-10-30.5"
    - "1h" / "90m" / "30s"
    - "1h30m" / "2h10m5s"
    """
    if isinstance(t, (int, float)):
        sec = int(round(float(t)))
        if sec <= 0:
            raise ValueError("time must be > 0, got {}".format(t))
        return sec

    s = str(t).strip().lower()
    if not s:
        raise ValueError("time is empty")

    sec = _parse_clock_time_to_seconds(s)
    if sec is not None:
        if sec <= 0:
            raise ValueError("time must be > 0, got {}".format(t))
        return sec

    if s.isdigit():
        sec = int(s)
        if sec <= 0:
            raise ValueError("time must be > 0, got {}".format(t))
        return sec

    pattern = r"^\s*(?:(\d+(?:\.\d+)?)h)?(?:(\d+(?:\.\d+)?)m)?(?:(\d+(?:\.\d+)?)s)?\s*$"
    match = re.match(pattern, s)
    if not match:
        raise ValueError("Invalid time format: {}".format(t))

    h = float(match.group(1) or 0.0)
    mi = float(match.group(2) or 0.0)
    se = float(match.group(3) or 0.0)
    sec = int(round(h * 3600 + mi * 60 + se))
    if sec <= 0:
        raise ValueError("time must be > 0, got {}".format(t))
    return sec


def parse_time_to_seconds_allow_zero(t: TimeLike) -> int:
    """
    支持与 parse_time_to_seconds 相同的格式，但允许 0。
    适合 clip 的 start_time。
    """
    if isinstance(t, (int, float)):
        sec = int(round(float(t)))
        if sec < 0:
            raise ValueError("time must be >= 0, got {}".format(t))
        return sec

    s = str(t).strip().lower()
    if not s:
        raise ValueError("time is empty")

    sec = _parse_clock_time_to_seconds(s)
    if sec is not None:
        if sec < 0:
            raise ValueError("time must be >= 0, got {}".format(t))
        return sec

    if s.isdigit():
        sec = int(s)
        if sec < 0:
            raise ValueError("time must be >= 0, got {}".format(t))
        return sec

    pattern = r"^\s*(?:(\d+(?:\.\d+)?)h)?(?:(\d+(?:\.\d+)?)m)?(?:(\d+(?:\.\d+)?)s)?\s*$"
    match = re.match(pattern, s)
    if not match:
        raise ValueError("Invalid time format: {}".format(t))

    h = float(match.group(1) or 0.0)
    mi = float(match.group(2) or 0.0)
    se = float(match.group(3) or 0.0)
    sec = int(round(h * 3600 + mi * 60 + se))
    if sec < 0:
        raise ValueError("time must be >= 0, got {}".format(t))
    return sec


def format_seconds_for_name(sec: int) -> str:
    """
    例如：
    0 -> 000000
    65 -> 000105
    3661 -> 010101
    """
    hh = sec // 3600
    mm = (sec % 3600) // 60
    ss = sec % 60
    return "{:02d}{:02d}{:02d}".format(hh, mm, ss)


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


def _resolve_ffmpeg(ffmpeg: Optional[Union[str, Path]] = None) -> str:
    """
    Resolve an ffmpeg command, executable path, or executable directory.

    Args:
        ffmpeg: ffmpeg command, executable path, directory containing ffmpeg,
            or None to locate FFmpeg via `keon.app.find`.

    Returns:
        Resolved ffmpeg command text.

    Raises:
        FileNotFoundError: FFmpeg cannot be located or resolved.
    """
    if ffmpeg is None:
        from keon.app import AppName, find

        install_dir = find(AppName.FFMPEG)
        if install_dir is None:
            raise FileNotFoundError("FFmpeg installation not found")
        ffmpeg = install_dir

    path = Path(ffmpeg)
    if path.is_dir():
        candidates = (
            path / _ffmpeg_executable_name(),
            path / "bin" / _ffmpeg_executable_name(),
        )
        for candidate in candidates:
            if candidate.is_file():
                return str(candidate)
        raise FileNotFoundError(
            "ffmpeg executable not found in directory: {}".format(path)
        )
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


def _path_is_relative_to(path: Path, parent: Path) -> bool:
    """
    Check whether a path is inside another path.

    Args:
        path: Child path.
        parent: Parent path.

    Returns:
        True if path is inside parent, otherwise False.
    """
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


class Ffmpeg:
    """
    Small wrapper around the ffmpeg executable.

    Args:
        ffmpeg: ffmpeg command, executable path, directory containing ffmpeg,
            or None to locate FFmpeg via `keon.app.find`.
    """

    def __init__(self, ffmpeg: Optional[Union[str, Path]] = None):
        """
        Initialize the ffmpeg wrapper.

        Args:
            ffmpeg: ffmpeg command, executable path, directory containing ffmpeg,
                or None to locate FFmpeg via `keon.app.find`.

        Returns:
            None

        Raises:
            FileNotFoundError: `ffmpeg` is None and FFmpeg cannot be located.
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

    def build_merge_ts_command(
            self,
            ts_dir: Union[str, Path],
            output: Optional[Union[str, Path]] = None,
            m3u8_name: str = "index.m3u8",
            overwrite: bool = True,
            ) -> List[str]:
        """
        Build an ffmpeg command for merging TS files through a local m3u8 file.

        Args:
            ts_dir: Directory containing the m3u8 file and TS files.
            output: Output video path; defaults to <ts_dir parent>/<ts_dir name>.mp4.
            m3u8_name: M3U8 file name inside ts_dir.
            overwrite: Whether to overwrite an existing output file.

        Returns:
            ffmpeg command argument list.
        """
        ts_path = Path(ts_dir)
        m3u8 = ts_path / m3u8_name
        output_path = Path(output) if output is not None else ts_path.parent / f"{ts_path.name}.mp4"

        return [
            self.ffmpeg,
            "-hide_banner",
            "-y" if overwrite else "-n",
            "-i", str(m3u8),
            "-c", "copy",
            str(output_path),
        ]

    def merge_ts(
            self,
            ts_dir: Union[str, Path],
            output: Optional[Union[str, Path]] = None,
            m3u8_name: str = "index.m3u8",
            remove_dir: bool = True,
            overwrite: bool = True,
            check: bool = True,
            verbose: bool = False,
            ) -> Path:
        """
        Merge TS files through a local m3u8 file.

        Args:
            ts_dir: Directory containing the m3u8 file and TS files.
            output: Output video path; defaults to <ts_dir parent>/<ts_dir name>.mp4.
            m3u8_name: M3U8 file name inside ts_dir.
            remove_dir: Whether to remove ts_dir after ffmpeg succeeds.
            overwrite: Whether to overwrite an existing output file.
            check: Whether subprocess.run should raise on a non-zero exit code.
            verbose: Whether to print the ffmpeg command before running it.

        Returns:
            Output video path.
        """
        ts_path = Path(ts_dir)
        cmd = self.build_merge_ts_command(
            ts_dir=ts_path,
            output=output,
            m3u8_name=m3u8_name,
            overwrite=overwrite,
        )
        output_path = Path(cmd[-1])

        if remove_dir and _path_is_relative_to(output_path, ts_path):
            raise ValueError("output must not be inside ts_dir when remove_dir is True")

        output_path.parent.mkdir(parents=True, exist_ok=True)
        if verbose:
            print(format_command(cmd))
        subprocess.run(cmd, check=check)

        if remove_dir:
            shutil.rmtree(ts_path, ignore_errors=True)

        return output_path

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

    def _run(self, args: List[str]) -> subprocess.CompletedProcess:
        cp = subprocess.run(
            [self.ffmpeg, *args],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if cp.returncode != 0:
            msg = (
                "ffmpeg failed\n"
                "cmd: {} {}\n"
                "returncode: {}\n"
                "stderr:\n{}\n"
                "stdout:\n{}\n"
            ).format(self.ffmpeg, " ".join(args), cp.returncode, cp.stderr, cp.stdout)
            raise RuntimeError(msg)
        return cp

    @staticmethod
    def _next_start_number(folder: Path, ext: str) -> int:
        """
        在已有 001.ext / 002.ext... 的情况下，自动从 max+1 开始，避免覆盖。
        """
        max_n = 0
        ext = ext.lower()
        for file in folder.glob("*{}".format(ext)):
            match = re.match(r"^(\d{3})" + re.escape(ext) + r"$", file.name.lower())
            if match:
                max_n = max(max_n, int(match.group(1)))
        return max_n + 1 if max_n > 0 else 1

    def split_by_time(
            self,
            input_file: Union[str, Path],
            segment_time: TimeLike = "1h",
            output_root: Optional[Union[str, Path]] = None,
            overwrite: bool = False,
            ) -> List[Path]:
        """
        把 input_file 按 segment_time 分割成 N 段，输出到：
          - 默认：input 同目录 / input文件名(不含后缀)/
          - 或 output_root / input文件名(不含后缀)/

        文件名：001.xxx、002.xxx...
        返回：生成的分段文件列表（按名字排序）
        """
        in_path = Path(input_file).expanduser().resolve()
        if not in_path.exists():
            raise FileNotFoundError("input file not found: {}".format(in_path))

        seg_seconds = parse_time_to_seconds(segment_time)
        ext = in_path.suffix  # 保持原后缀：.mp4 / .mkv ...
        if not ext:
            raise ValueError("input file has no extension: {}".format(in_path))

        base_dir = Path(output_root).expanduser().resolve() if output_root else in_path.parent
        out_dir = base_dir / in_path.stem
        out_dir.mkdir(parents=True, exist_ok=True)

        start_number = 1 if overwrite else self._next_start_number(out_dir, ext)
        out_tpl = str(out_dir / "%03d{}".format(ext))

        # 注意：-c copy 是“无重编码切割”，切点受关键帧影响；要绝对精准切点需重编码（更慢更耗资源）。
        args = [
            "-hide_banner",
            "-loglevel", "error",
            "-nostdin",
        ]
        args += ["-y"] if overwrite else ["-n"]
        args += [
            "-i", str(in_path),
            "-map", "0",
            "-c", "copy",
            "-f", "segment",
            "-segment_time", str(seg_seconds),
            "-reset_timestamps", "1",
            "-segment_start_number", str(start_number),
            out_tpl,
        ]

        self._run(args)

        # 收集输出文件
        outs = sorted(out_dir.glob("[0-9][0-9][0-9]{}".format(ext)))
        # 只返回这次生成的（若未覆盖且目录里原本就有）
        return [path for path in outs if int(path.stem) >= start_number]

    def clip_by_time(
            self,
            input_file: Union[str, Path],
            start_time: Optional[Union[TimeLike, List[TimeLike]]] = None,
            end_time: Optional[Union[TimeLike, List[TimeLike]]] = None,
            output_file: Optional[Union[str, Path]] = None,
            output_root: Optional[Union[str, Path]] = None,
            overwrite: bool = False,
            ) -> Path:
        """
        按开始时间和结束时间裁剪 input_file，输出一个片段文件。

        时间规则：
        - start_time / end_time 可以是单个时间，也可以是 list
        - start_time 为 None 时，默认从 0 开始
        - end_time 为 None 时，默认裁剪到文件结尾
        - 若 start_time / end_time 为 list：
        - 两者必须同时为 list
        - 长度必须一致
        - 会先按每对时间裁出多个片段，再按顺序拼接成一个输出文件

        示例：
            start_time = ["00:00:00", "00:10:00"]
            end_time   = ["00:05:00", "00:15:00"]
            start_time = ["00-00-00", "00-10-00"]
            end_time   = ["00-05-00", "00-15-00"]

            最终结果为：
            - 00:00:00 -> 00:05:00
            - 00:10:00 -> 00:15:00
            再拼接成一个总长约 10 分钟的新视频

        输出规则：
        - 若指定 output_file，则直接输出到该文件
        - 否则默认输出到：
            - input 同目录
            - 或 output_root
        文件名为：
            - 单段时：
            - 若 start/end 都有：原文件名_clip_HHMMSS_HHMMSS.xxx
            - 若 end_time 为 None：原文件名_clip_HHMMSS_to_end.xxx
            - 多段时：
            - 原文件名_clip_multi.xxx

        说明：
        - 默认使用 -c copy，保持原视频/音频编码与封装格式，速度快
        - 但切点会受关键帧影响，不一定绝对精准
        - 若要绝对精准切点，通常需要重编码
        """
        in_path = Path(input_file).expanduser().resolve()
        if not in_path.exists():
            raise FileNotFoundError("input file not found: {}".format(in_path))

        ext = in_path.suffix
        if not ext:
            raise ValueError("input file has no extension: {}".format(in_path))

        def _is_list_like(value) -> bool:
            return isinstance(value, list)

        def _normalize_to_segments(
                start: Optional[Union[TimeLike, List[TimeLike]]],
                end: Optional[Union[TimeLike, List[TimeLike]]],
                ) -> List[Tuple[int, Optional[int]]]:
            """
            统一转换为:
                [(start_seconds, end_seconds_or_None), ...]
            """
            start_is_list = _is_list_like(start)
            end_is_list = _is_list_like(end)

            # 单段模式
            if not start_is_list and not end_is_list:
                start_seconds = 0 if start is None else parse_time_to_seconds_allow_zero(start)
                end_seconds = None if end is None else parse_time_to_seconds_allow_zero(end)
                if end_seconds is not None and end_seconds <= start_seconds:
                    raise ValueError(
                        "end_time must be greater than start_time, "
                        "got start_time={}, end_time={}".format(start, end)
                    )
                return [(start_seconds, end_seconds)]

            # 多段模式：要求两者都为 list
            if start_is_list != end_is_list:
                raise ValueError("start_time and end_time must both be list, or both be single value")

            start_list = start or []
            end_list = end or []
            if len(start_list) != len(end_list):
                raise ValueError(
                    "start_time and end_time list length must match, "
                    "got {} != {}".format(len(start_list), len(end_list))
                )
            if not start_list:
                raise ValueError("start_time and end_time list cannot be empty")

            segments: List[Tuple[int, Optional[int]]] = []
            for index, (st, et) in enumerate(zip(start_list, end_list)):
                start_seconds = 0 if st is None else parse_time_to_seconds_allow_zero(st)
                end_seconds = None if et is None else parse_time_to_seconds_allow_zero(et)
                if end_seconds is not None and end_seconds <= start_seconds:
                    raise ValueError(
                        "segment[{}] end_time must be greater than start_time, "
                        "got start_time={}, end_time={}".format(index, st, et)
                    )
                segments.append((start_seconds, end_seconds))
            return segments

        segments = _normalize_to_segments(start_time, end_time)
        is_multi = len(segments) > 1

        if output_file is not None:
            out_path = Path(output_file).expanduser().resolve()
            out_path.parent.mkdir(parents=True, exist_ok=True)
        else:
            base_dir = Path(output_root).expanduser().resolve() if output_root else in_path.parent
            base_dir.mkdir(parents=True, exist_ok=True)

            if not is_multi:
                start_seconds, end_seconds = segments[0]
                start_tag = format_seconds_for_name(start_seconds)
                if end_seconds is None:
                    out_name = "{}_clip_{}_to_end{}".format(in_path.stem, start_tag, ext)
                else:
                    end_tag = format_seconds_for_name(end_seconds)
                    out_name = "{}_clip_{}_{}{}".format(in_path.stem, start_tag, end_tag, ext)
            else:
                out_name = "{}_clip_multi{}".format(in_path.stem, ext)

            out_path = base_dir / out_name

        # 单段：直接输出
        if not is_multi:
            start_seconds, end_seconds = segments[0]
            args = [
                "-hide_banner",
                "-loglevel", "error",
                "-nostdin",
            ]
            args += ["-y"] if overwrite else ["-n"]
            args += [
                "-i", str(in_path),
                "-ss", str(start_seconds),
                "-map", "0",
                "-c", "copy",
            ]
            if end_seconds is not None:
                args += ["-t", str(end_seconds - start_seconds)]
            args += [str(out_path)]
            self._run(args)
            if not out_path.exists():
                raise RuntimeError("clip output file not found: {}".format(out_path))
            return out_path

        # 多段：先分别裁剪到临时目录，再 concat 拼接
        temp_dir = out_path.parent / "{}__parts".format(out_path.stem)
        temp_dir.mkdir(parents=True, exist_ok=True)

        part_paths: List[Path] = []
        for index, (start_seconds, end_seconds) in enumerate(segments, start=1):
            part_path = temp_dir / "part_{:03d}{}".format(index, ext)
            args = [
                "-hide_banner",
                "-loglevel", "error",
                "-nostdin",
                "-y",  # 临时文件这里直接覆盖，避免残留影响
                "-i", str(in_path),
                "-ss", str(start_seconds),
                "-map", "0",
                "-c", "copy",
            ]
            if end_seconds is not None:
                args += ["-t", str(end_seconds - start_seconds)]
            args += [str(part_path)]
            self._run(args)
            if not part_path.exists():
                raise RuntimeError("segment output file not found: {}".format(part_path))
            part_paths.append(part_path)

        concat_list_path = temp_dir / "concat_list.txt"
        with concat_list_path.open("w", encoding="utf-8") as file:
            for part in part_paths:
                # ffmpeg concat demuxer 格式：file 'xxx'
                escaped = str(part).replace("'", r"'\''")
                file.write("file '{}'\n".format(escaped))

        concat_args = [
            "-hide_banner",
            "-loglevel", "error",
            "-nostdin",
        ]
        concat_args += ["-y"] if overwrite else ["-n"]
        concat_args += [
            "-f", "concat",
            "-safe", "0",
            "-i", str(concat_list_path),
            "-c", "copy",
            str(out_path),
        ]
        self._run(concat_args)
        if not out_path.exists():
            raise RuntimeError("concat output file not found: {}".format(out_path))
        return out_path

    def concat_videos(
            self,
            input_files: List[Union[str, Path]],
            output_file: Optional[Union[str, Path]] = None,
            output_root: Optional[Union[str, Path]] = None,
            overwrite: bool = False,
            ) -> Path:
        """
        按传入顺序拼接多个视频文件，输出为一个新视频文件。

        输出规则：
        - 若指定 output_file，则直接输出到该文件
        - 否则默认输出到：
            - 第一个输入文件的同目录
            - 或 output_root
        - 若未指定 output_file，默认文件名为：
            第一个输入文件名_concat.xxx

        说明：
        - 默认使用 concat demuxer + -c copy，速度快，不重新编码
        - 输入文件通常需要具备兼容的封装格式、编码参数与流结构，否则 ffmpeg 可能失败
        """
        if not input_files:
            raise ValueError("input_files cannot be empty")

        in_paths: List[Path] = []
        for index, input_file in enumerate(input_files):
            path = Path(input_file).expanduser().resolve()
            if not path.exists():
                raise FileNotFoundError("input file[{}] not found: {}".format(index, path))
            if path.is_dir():
                raise IsADirectoryError(
                    "input file[{}] should be a file, got directory: {}".format(index, path)
                )
            in_paths.append(path)

        first_path = in_paths[0]
        ext = first_path.suffix
        if not ext:
            raise ValueError("input file has no extension: {}".format(first_path))

        if output_file is not None:
            out_path = Path(output_file).expanduser().resolve()
            out_path.parent.mkdir(parents=True, exist_ok=True)
        else:
            base_dir = Path(output_root).expanduser().resolve() if output_root else first_path.parent
            base_dir.mkdir(parents=True, exist_ok=True)
            out_path = base_dir / "{}_concat{}".format(first_path.stem, ext)

        if any(out_path == path for path in in_paths):
            raise ValueError("output file must be different from input files: {}".format(out_path))

        temp_dir = out_path.parent / "{}__concat".format(out_path.stem)
        temp_dir.mkdir(parents=True, exist_ok=True)

        concat_list_path = temp_dir / "concat_list.txt"
        with concat_list_path.open("w", encoding="utf-8") as file:
            for path in in_paths:
                escaped = str(path).replace("'", r"'\''")
                file.write("file '{}'\n".format(escaped))

        args = [
            "-hide_banner",
            "-loglevel", "error",
            "-nostdin",
        ]
        args += ["-y"] if overwrite else ["-n"]
        args += [
            "-f", "concat",
            "-safe", "0",
            "-i", str(concat_list_path),
            "-c", "copy",
            str(out_path),
        ]
        self._run(args)
        if not out_path.exists():
            raise RuntimeError("concat output file not found: {}".format(out_path))
        return out_path

    def extract_images_by_interval(
            self,
            input_file: Union[str, Path],
            interval: TimeLike = 1,
            output_dir: Optional[Union[str, Path]] = None,
            overwrite: bool = False,
            image_ext: str = ".jpg",
            ) -> List[Path]:
        """
        按固定时间间隔从视频中提取图片，并按时间戳命名。

        例如：
        - interval=2 时，提取 0s、2s、4s、6s... 的帧
        - 文件名示例：
            00-00-00.jpg
            00-00-02.jpg
            00-00-04.jpg

        输出规则：
        - 若指定 output_dir，则输出到该目录
        - 否则默认输出到：
            input 同目录 / input文件名(不含后缀)/

        参数：
        - input_file:
            输入视频文件
        - interval:
            抽帧时间间隔，单位秒，支持：
            2 / 2.0 / "2" / "00:00:02" / "00-00-02" / "2s"
        - output_dir:
            输出目录
        - overwrite:
            是否覆盖已有文件
        - image_ext:
            输出图片后缀，默认 ".jpg"；
            常见可选：".jpg"、".png"

        返回：
        - 生成的图片文件列表（按名字排序）
        """
        in_path = Path(input_file).expanduser().resolve()
        if not in_path.exists():
            raise FileNotFoundError("input file not found: {}".format(in_path))

        interval_seconds = parse_time_to_seconds(interval)
        ext = image_ext.strip().lower()
        if not ext.startswith("."):
            ext = "." + ext
        if ext not in {".jpg", ".jpeg", ".png", ".bmp", ".webp"}:
            raise ValueError("unsupported image_ext: {}".format(image_ext))

        if output_dir is not None:
            out_dir = Path(output_dir).expanduser().resolve()
        else:
            out_dir = in_path.parent / in_path.stem
        out_dir.mkdir(parents=True, exist_ok=True)

        # 先抽到临时序号文件
        tmp_tpl = str(out_dir / "__tmp_%06d{}".format(ext))
        args = [
            "-hide_banner",
            "-loglevel", "error",
            "-nostdin",
        ]
        args += ["-y"] if overwrite else ["-n"]
        args += [
            "-i", str(in_path),
            "-vf", "fps=1/{}".format(interval_seconds),
            tmp_tpl,
        ]
        self._run(args)

        # 再按时间戳重命名
        tmp_files = sorted(out_dir.glob("__tmp_[0-9][0-9][0-9][0-9][0-9][0-9]{}".format(ext)))
        out_files: List[Path] = []
        for index, tmp_file in enumerate(tmp_files):
            sec = index * interval_seconds
            hh = sec // 3600
            mm = (sec % 3600) // 60
            ss = sec % 60
            final_name = "{:02d}-{:02d}-{:02d}{}".format(hh, mm, ss, ext)
            final_path = out_dir / final_name
            if final_path.exists():
                if overwrite:
                    final_path.unlink()
                else:
                    raise FileExistsError("output image already exists: {}".format(final_path))
            tmp_file.rename(final_path)
            out_files.append(final_path)
        return out_files

    def to_gif(
            self,
            input_file: Union[str, Path],
            start_time: Optional[TimeLike] = None,
            end_time: Optional[TimeLike] = None,
            duration: Optional[TimeLike] = None,
            output_file: Optional[Union[str, Path]] = None,
            output_root: Optional[Union[str, Path]] = None,
            fps: int = 15,
            width: Optional[int] = 480,
            height: Optional[int] = -1,
            crop: Optional[Tuple[int, int, int, int]] = None,
            dither: str = "bayer",
            bayer_scale: int = 5,
            max_colors: int = 256,
            loop: int = 0,
            scale_flags: str = "lanczos",
            overwrite: bool = False,
            ) -> Path:
        """
        将视频（mp4 / mkv 等）转换为 gif 动图。

        时间规则：
        - start_time:
            起始时间，默认为 0；支持 "00:00:10" / "10s" / 10 / "00-00-10" 等
        - end_time / duration:
            二选一，不能同时指定
            - end_time:     结束时间（绝对位置），必须 > start_time
            - duration:     持续时长（相对长度），必须 > 0
            - 都为 None 时：从 start_time 截到文件结尾

        输出规则：
        - 若指定 output_file，则直接输出到该文件（后缀强制为 .gif）
        - 否则默认输出到：
            - input 同目录
            - 或 output_root
        文件名为：
            - start + end:      原文件名_gif_HHMMSS_HHMMSS.gif
            - start + duration: 原文件名_gif_HHMMSS_dur_HHMMSS.gif
            - 仅 start:         原文件名_gif_HHMMSS_to_end.gif

        画质控制参数：
        - fps:
            gif 帧率，越高越流畅但文件越大，常用 10 ~ 24
        - width / height:
            输出分辨率（像素）；-1 表示按比例自动计算
            二者均为 None 或 0 时不缩放，保持原分辨率
            默认 width=480, height=-1，即宽 480 等比缩放
            注意：若指定了 crop，缩放是基于裁剪后的画面
        - crop:
            裁剪矩形区域，格式 (x1, y1, x2, y2)，坐标以原视频左上角为原点
            默认 None，表示不裁剪（全屏）
            必须满足：0 <= x1 < x2, 0 <= y1 < y2
            裁剪发生在缩放之前，所以坐标是原视频的像素坐标
            例如 crop=(100, 50, 800, 500) 表示裁剪
            宽 700 (800-100) x 高 450 (500-50) 的矩形
        - dither:
            抖动算法，可选：
            "bayer" / "heckbert" / "floyd_steinberg" / "sierra2" / "sierra2_4a" / "none"
            默认 "bayer"，文件最小但有规则状纹路；
            "floyd_steinberg" / "sierra2_4a" 视觉质量更高，但文件更大
        - bayer_scale:
            仅当 dither="bayer" 时生效，取值 0 ~ 5
            值越小纹路越明显、文件越小；值越大越自然、文件越大
        - max_colors:
            调色板最大颜色数，2 ~ 256；越小文件越小但色彩越差
        - loop:
            gif 循环次数；0 = 无限循环（默认），-1 = 不循环，N = 循环 N 次
        - scale_flags:
            缩放算法，常用：
            "lanczos"（默认，最锐利）/ "bicubic" / "bilinear" / "neighbor"

        说明：
        - 使用 ffmpeg 的 palettegen + paletteuse 两遍编码
          先生成最佳调色板，再用其抖动着色，画质明显优于直接转 gif
          （相比单遍 split 方案，长视频/高分辨率时内存占用更低）
        - 默认使用 -ss 在 -i 之前的“输入快速跳转”，速度更快
          gif 不要求帧级精准切点，绝大多数情况够用
        """
        in_path = Path(input_file).expanduser().resolve()
        if not in_path.exists():
            raise FileNotFoundError("input file not found: {}".format(in_path))

        if end_time is not None and duration is not None:
            raise ValueError("end_time and duration cannot be specified at the same time")

        start_seconds = 0 if start_time is None else parse_time_to_seconds_allow_zero(start_time)
        end_seconds: Optional[int] = None
        duration_seconds: Optional[int] = None

        if end_time is not None:
            end_seconds = parse_time_to_seconds_allow_zero(end_time)
            if end_seconds <= start_seconds:
                raise ValueError(
                    "end_time must be greater than start_time, "
                    "got start_time={}, end_time={}".format(start_time, end_time)
                )
            duration_seconds = end_seconds - start_seconds
        elif duration is not None:
            duration_seconds = parse_time_to_seconds(duration)
            end_seconds = start_seconds + duration_seconds

        if fps <= 0:
            raise ValueError("fps must be > 0, got {}".format(fps))
        if max_colors < 2 or max_colors > 256:
            raise ValueError("max_colors must be in [2, 256], got {}".format(max_colors))

        valid_dithers = {
            "bayer", "heckbert", "floyd_steinberg",
            "sierra2", "sierra2_4a", "none",
        }
        if dither not in valid_dithers:
            raise ValueError("invalid dither: {}, choose from {}".format(dither, sorted(valid_dithers)))
        if dither == "bayer" and not 0 <= bayer_scale <= 5:
            raise ValueError("bayer_scale must be in [0, 5], got {}".format(bayer_scale))

        out_ext = ".gif"
        if output_file is not None:
            out_path = Path(output_file).expanduser().resolve()
            if out_path.suffix.lower() != out_ext:
                out_path = out_path.with_suffix(out_ext)
            out_path.parent.mkdir(parents=True, exist_ok=True)
        else:
            base_dir = Path(output_root).expanduser().resolve() if output_root else in_path.parent
            base_dir.mkdir(parents=True, exist_ok=True)
            start_tag = format_seconds_for_name(start_seconds)
            if end_time is not None:
                end_tag = format_seconds_for_name(end_seconds)
                out_name = "{}_gif_{}_{}{}".format(in_path.stem, start_tag, end_tag, out_ext)
            elif duration is not None:
                dur_tag = format_seconds_for_name(duration_seconds)
                out_name = "{}_gif_{}_dur_{}{}".format(in_path.stem, start_tag, dur_tag, out_ext)
            else:
                out_name = "{}_gif_{}_to_end{}".format(in_path.stem, start_tag, out_ext)
            out_path = base_dir / out_name

        filter_parts: List[str] = ["fps={}".format(fps)]
        if crop is not None:
            if len(crop) != 4:
                raise ValueError("crop must be a 4-tuple (x1, y1, x2, y2), got {!r}".format(crop))
            x1, y1, x2, y2 = (int(value) for value in crop)
            if x1 < 0 or y1 < 0:
                raise ValueError("crop x1/y1 must be >= 0, got x1={}, y1={}".format(x1, y1))
            if x2 <= x1 or y2 <= y1:
                raise ValueError(
                    "crop requires x2 > x1 and y2 > y1, got x1={}, y1={}, x2={}, y2={}".format(
                        x1, y1, x2, y2
                    )
                )
            filter_parts.append("crop={}:{}:{}:{}".format(x2 - x1, y2 - y1, x1, y1))

        use_scale = (width is not None and width != 0) or (height is not None and height != 0)
        if use_scale:
            w = width if (width is not None and width != 0) else -1
            h = height if (height is not None and height != 0) else -1
            filter_parts.append("scale={}:{}:flags={}".format(w, h, scale_flags))

        pre_filter = ",".join(filter_parts)
        palette_opts = "max_colors={}".format(max_colors)
        use_opts = "dither=bayer:bayer_scale={}".format(bayer_scale) if dither == "bayer" else "dither={}".format(dither)

        # 单遍 split+palettegen 会把整段视频帧缓存在内存中，长视频或高分辨率时
        # 容易 OOM（旧版 ffmpeg 尤为明显）。两遍法先生成调色板再着色，内存占用低得多。
        base_args: List[str] = [
            "-hide_banner",
            "-loglevel", "error",
            "-nostdin",
        ]
        base_args += ["-y"] if overwrite else ["-n"]

        input_args: List[str] = []
        if start_seconds > 0:
            input_args += ["-ss", str(start_seconds)]
        input_args += ["-i", str(in_path)]
        if duration_seconds is not None:
            input_args += ["-t", str(duration_seconds)]

        palette_path: Optional[Path] = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                palette_path = Path(tmp.name)

            pass1_args = base_args + input_args + [
                "-an",
                "-sn",
                "-vf", "{},palettegen={}".format(pre_filter, palette_opts),
                str(palette_path),
            ]
            self._run(pass1_args)

            pass2_filter = "{}[x];[x][1:v]paletteuse={}".format(pre_filter, use_opts)
            pass2_args = base_args + input_args + [
                "-i", str(palette_path),
                "-filter_complex", pass2_filter,
                "-loop", str(loop),
                "-an",
                "-sn",
                str(out_path),
            ]
            self._run(pass2_args)
        finally:
            if palette_path is not None:
                palette_path.unlink(missing_ok=True)

        if not out_path.exists():
            raise RuntimeError("gif output file not found: {}".format(out_path))
        return out_path

    def video_to_gif(
            self,
            input_file: Union[str, Path],
            output_file: Optional[Union[str, Path]] = None,
            fps: int = 10,
            width: Optional[int] = None,
            height: Optional[int] = None,
            overwrite: bool = False,
            ) -> Path:
        """
        将视频转换为 GIF 动图。

        兼容旧接口；需要时间截取、裁剪或抖动参数时请使用 to_gif。
        """
        out_file = output_file
        if out_file is None:
            out_file = Path(input_file).expanduser().resolve().with_suffix(".gif")
        return self.to_gif(
            input_file=input_file,
            output_file=out_file,
            fps=fps,
            width=width,
            height=height,
            overwrite=overwrite,
        )


__all__ = [
    "AudioSegment",
    "Ffmpeg",
    "TimeLike",
    "as_segment",
    "format_command",
    "format_seconds_for_name",
    "parse_time_to_seconds",
    "parse_time_to_seconds_allow_zero",
    "safe_filename",
    "to_seconds",
    "to_time_str",
]
