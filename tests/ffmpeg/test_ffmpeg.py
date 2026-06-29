import os
from pathlib import Path
from types import SimpleNamespace

import pytest

import keon.ffmpeg as kf
from keon.ffmpeg import AudioSegment, Ffmpeg


def _ffmpeg_name():
    return "ffmpeg.exe" if os.name == "nt" else "ffmpeg"


def test_time_helpers():
    assert kf.to_seconds("01:02:03") == 3723
    assert kf.to_time_str(3723) == "01:02:03"


def test_time_helpers_reject_invalid_values():
    with pytest.raises(ValueError):
        kf.to_seconds("01:02")
    with pytest.raises(ValueError):
        kf.to_seconds("00:99:00")
    with pytest.raises(ValueError):
        kf.to_time_str(-1)


def test_safe_filename():
    assert kf.safe_filename('a<>:"/\\|?*b') == "a_________b"
    assert kf.safe_filename("   ") == "untitled"


def test_as_segment_accepts_dataclass_tuple_and_mapping():
    assert kf.as_segment(AudioSegment("00:00:00", "00:01:00", "A")).name == "A"
    assert kf.as_segment(("00:00:00", None, "B")).end is None
    assert kf.as_segment(("00:00:00", "B")).name == "B"
    assert kf.as_segment(("00:00:00",)).name is None
    assert kf.as_segment("00:00:00").start == "00:00:00"
    assert kf.as_segment({"start": "00:00:00", "end": "00:01:00", "title": "C"}).name == "C"
    assert kf.as_segment({"start_time": "00:00:00"}).name is None


def test_as_segment_rejects_invalid_input():
    with pytest.raises(ValueError):
        kf.as_segment(())
    with pytest.raises(ValueError):
        kf.as_segment(("00:00:00", "00:01:00", "A", "extra"))
    with pytest.raises(ValueError):
        kf.as_segment({"end": "00:01:00", "name": "A"})


def test_ffmpeg_accepts_directory(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()

    ffmpeg = Ffmpeg(bin_dir)

    assert ffmpeg.ffmpeg == str(bin_dir / _ffmpeg_name())


def test_build_split_commands(tmp_path):
    src = tmp_path / "album.mp3"
    ffmpeg = Ffmpeg("ffmpeg")

    commands = ffmpeg.build_split_commands(
        src,
        [
            AudioSegment("00:00:00", "00:02:15", 'Start: From / Bottom'),
            ("00:02:16", None, "Last Track"),
        ],
        prefix="MC Hotdog - ",
    )

    assert commands[0] == [
        "ffmpeg",
        "-hide_banner",
        "-y",
        "-ss", "00:00:00",
        "-i", str(src),
        "-map", "0:a:0",
        "-vn",
        "-c:a", "copy",
        "-t", "00:02:15",
        str(tmp_path / "MC Hotdog - Start_ From _ Bottom.mp3"),
    ]
    assert "-t" not in commands[1]
    assert commands[1][-1] == str(tmp_path / "MC Hotdog - Last Track.mp3")


def test_build_split_commands_infers_end_from_next_start(tmp_path):
    src = tmp_path / "album.mp3"
    ffmpeg = Ffmpeg("ffmpeg")

    commands = ffmpeg.build_split_commands(
        src,
        [
            ("00:00:00", "Track 1"),
            ("00:04:19", "Track 2"),
        ],
    )

    assert commands[0][commands[0].index("-t") + 1] == "00:04:19"
    assert commands[0][-1] == str(tmp_path / "Track 1.mp3")
    assert "-t" not in commands[1]
    assert commands[1][-1] == str(tmp_path / "Track 2.mp3")


def test_build_split_commands_supports_start_only_segments(tmp_path):
    src = tmp_path / "album.mp3"
    ffmpeg = Ffmpeg("ffmpeg")

    commands = ffmpeg.build_split_commands(
        src,
        [
            {"start_time": "00:00:00"},
            "00:01:00",
        ],
    )

    assert commands[0][commands[0].index("-t") + 1] == "00:01:00"
    assert commands[0][-1] == str(tmp_path / "00_00_00.mp3")
    assert commands[1][-1] == str(tmp_path / "00_01_00.mp3")


def test_build_split_commands_reencodes_flac_by_default(tmp_path):
    src = tmp_path / "album.flac"
    ffmpeg = Ffmpeg("ffmpeg")

    commands = ffmpeg.build_split_commands(
        src,
        [AudioSegment("00:00:00", "00:04:19", "Track")],
    )

    assert commands[0][commands[0].index("-c:a") + 1] == "flac"
    assert commands[0][-1] == str(tmp_path / "Track.flac")


def test_build_split_commands_allows_forced_copy_for_flac(tmp_path):
    src = tmp_path / "album.flac"
    ffmpeg = Ffmpeg("ffmpeg")

    commands = ffmpeg.build_split_commands(
        src,
        [AudioSegment("00:00:00", "00:04:19", "Track")],
        audio_codec="copy",
    )

    assert commands[0][commands[0].index("-c:a") + 1] == "copy"


def test_build_split_commands_rejects_negative_duration(tmp_path):
    ffmpeg = Ffmpeg("ffmpeg")

    with pytest.raises(ValueError, match="later than start"):
        ffmpeg.build_split_commands(
            tmp_path / "album.mp3",
            [AudioSegment("00:02:00", "00:01:00", "Bad")],
        )


def test_build_merge_ts_command_uses_default_output(tmp_path):
    ts_dir = tmp_path / "video_parts"
    ffmpeg = Ffmpeg("ffmpeg")

    cmd = ffmpeg.build_merge_ts_command(ts_dir)

    assert cmd == [
        "ffmpeg",
        "-hide_banner",
        "-y",
        "-i", str(ts_dir / "index.m3u8"),
        "-c", "copy",
        str(tmp_path / "video_parts.mp4"),
    ]


def test_build_merge_ts_command_accepts_custom_output_and_m3u8(tmp_path):
    ts_dir = tmp_path / "video_parts"
    output = tmp_path / "out" / "movie.mp4"
    ffmpeg = Ffmpeg("ffmpeg")

    cmd = ffmpeg.build_merge_ts_command(
        ts_dir,
        output=output,
        m3u8_name="playlist.m3u8",
        overwrite=False,
    )

    assert "-n" in cmd
    assert "-y" not in cmd
    assert cmd[cmd.index("-i") + 1] == str(ts_dir / "playlist.m3u8")
    assert cmd[-1] == str(output)


def test_merge_ts_runs_command_and_removes_dir(monkeypatch, tmp_path):
    calls = []

    def fake_run(cmd, check=True):
        calls.append(SimpleNamespace(cmd=cmd, check=check))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(kf.subprocess, "run", fake_run)

    ts_dir = tmp_path / "video_parts"
    ts_dir.mkdir()
    (ts_dir / "index.m3u8").write_text("")
    ffmpeg = Ffmpeg("ffmpeg")

    output = ffmpeg.merge_ts(ts_dir, verbose=False)

    assert output == tmp_path / "video_parts.mp4"
    assert calls[0].cmd[-1] == str(output)
    assert calls[0].check is True
    assert not ts_dir.exists()


def test_merge_ts_can_keep_source_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(kf.subprocess, "run", lambda cmd, check=True: SimpleNamespace(returncode=0))

    ts_dir = tmp_path / "video_parts"
    ts_dir.mkdir()
    ffmpeg = Ffmpeg("ffmpeg")

    ffmpeg.merge_ts(ts_dir, remove_dir=False)

    assert ts_dir.exists()


def test_merge_ts_rejects_output_inside_removed_dir(tmp_path):
    ts_dir = tmp_path / "video_parts"
    ts_dir.mkdir()
    ffmpeg = Ffmpeg("ffmpeg")

    with pytest.raises(ValueError, match="output must not be inside ts_dir"):
        ffmpeg.merge_ts(ts_dir, output=ts_dir / "out.mp4", remove_dir=True)


def test_split_runs_commands_and_returns_outputs(monkeypatch, tmp_path):
    calls = []

    def fake_run(cmd, check=True):
        calls.append(SimpleNamespace(cmd=cmd, check=check))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(kf.subprocess, "run", fake_run)

    out_dir = tmp_path / "out"
    ffmpeg = Ffmpeg("ffmpeg")
    outputs = ffmpeg.split(
        tmp_path / "album.mp3",
        [{"start": "00:00:00", "end": None, "name": "A"}],
        out_dir=out_dir,
        verbose=False,
    )

    assert out_dir.exists()
    assert outputs == [out_dir / "A.mp3"]
    assert calls[0].cmd[-1] == str(out_dir / "A.mp3")
    assert calls[0].check is True
