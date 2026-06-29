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
    (bin_dir / _ffmpeg_name()).write_text("")

    ffmpeg = Ffmpeg(bin_dir)

    assert ffmpeg.ffmpeg == str(bin_dir / _ffmpeg_name())


def test_ffmpeg_default_resolves_install_dir_from_app(monkeypatch, tmp_path):
    import keon.app as ka

    install_dir = tmp_path / "ffmpeg"
    bin_dir = install_dir / "bin"
    bin_dir.mkdir(parents=True)
    executable = bin_dir / _ffmpeg_name()
    executable.write_text("")

    monkeypatch.setattr(ka, "find", lambda _name: str(install_dir))

    ffmpeg = Ffmpeg()

    assert ffmpeg.ffmpeg == str(executable)


def test_ffmpeg_default_raises_when_app_cannot_find_installation(monkeypatch):
    import keon.app as ka

    monkeypatch.setattr(ka, "find", lambda _name: None)

    with pytest.raises(FileNotFoundError, match="FFmpeg installation not found"):
        Ffmpeg()


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


def test_parse_time_helpers():
    assert kf.parse_time_to_seconds("1h") == 3600
    assert kf.parse_time_to_seconds("90m") == 5400
    assert kf.parse_time_to_seconds("00:01:30") == 90
    assert kf.parse_time_to_seconds_allow_zero("00:00:00") == 0
    assert kf.format_seconds_for_name(3661) == "010101"


def test_parse_time_helpers_reject_invalid_values():
    with pytest.raises(ValueError):
        kf.parse_time_to_seconds("0")
    with pytest.raises(ValueError):
        kf.parse_time_to_seconds_allow_zero("-1")


def test_split_by_time_runs_ffmpeg(monkeypatch, tmp_path):
    calls = []

    def fake_run(args):
        calls.append(args)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    input_file = tmp_path / "movie.mp4"
    input_file.write_text("")

    ffmpeg = Ffmpeg("ffmpeg")
    monkeypatch.setattr(ffmpeg, "_run", fake_run)

    out_dir = tmp_path / "movie"
    out_dir.mkdir()
    (out_dir / "001.mp4").write_text("")

    outputs = ffmpeg.split_by_time(input_file, segment_time="1h", overwrite=True)

    assert outputs == [out_dir / "001.mp4"]
    assert calls[0][calls[0].index("-segment_time") + 1] == "3600"


def test_clip_by_time_builds_single_segment_command(monkeypatch, tmp_path):
    calls = []

    def fake_run(args):
        calls.append(args)
        out_path = Path(args[-1])
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text("")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    input_file = tmp_path / "movie.mp4"
    input_file.write_text("")

    ffmpeg = Ffmpeg("ffmpeg")
    monkeypatch.setattr(ffmpeg, "_run", fake_run)

    output = ffmpeg.clip_by_time(
        input_file,
        start_time="00:00:10",
        end_time="00:01:00",
        overwrite=True,
    )

    assert output == tmp_path / "movie_clip_000010_000100.mp4"
    assert calls[0][calls[0].index("-ss") + 1] == "10"
    assert calls[0][calls[0].index("-t") + 1] == "50"


def test_concat_videos_writes_concat_list(monkeypatch, tmp_path):
    calls = []

    def fake_run(args):
        calls.append(args)
        out_path = Path(args[-1])
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text("")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    first = tmp_path / "part1.mp4"
    second = tmp_path / "part2.mp4"
    first.write_text("")
    second.write_text("")

    ffmpeg = Ffmpeg("ffmpeg")
    monkeypatch.setattr(ffmpeg, "_run", fake_run)

    output = ffmpeg.concat_videos([first, second], overwrite=True)

    assert output == tmp_path / "part1_concat.mp4"
    concat_list = tmp_path / "part1_concat__concat" / "concat_list.txt"
    assert concat_list.exists()
    text = concat_list.read_text(encoding="utf-8")
    assert str(first) in text
    assert str(second) in text


def test_to_gif_rejects_end_time_and_duration_together(tmp_path):
    input_file = tmp_path / "movie.mp4"
    input_file.write_text("")

    ffmpeg = Ffmpeg("ffmpeg")

    with pytest.raises(ValueError, match="end_time and duration cannot be specified"):
        ffmpeg.to_gif(
            input_file,
            end_time="00:01:00",
            duration="30s",
        )
