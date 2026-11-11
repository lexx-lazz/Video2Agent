"""Tests for everything that doesn't need FFmpeg, Whisper or the internet."""
import datetime
import os

import pytest

from video2agent import constants, digest, menu, pipeline, preview, video_queue
from video2agent.helpers import format_time
from video2agent.screenshots import pick_screenshot_times, remove_repeats
from video2agent.transcribe import find_subtitle_file, merge_short_lines, read_subtitles, split_into_lines


def line(start, end, text="x"):
    return {"start": start, "end": end, "text": text}


@pytest.fixture
def empty_queue(tmp_path, monkeypatch):
    """A queue and log folder of its own, and no fiddling with Windows sleep settings."""
    monkeypatch.setattr(video_queue, "QUEUE_FILE", str(tmp_path / "queue.json"))
    monkeypatch.setattr(constants, "LOGS_FOLDER", str(tmp_path / "logs"))
    monkeypatch.setattr(video_queue, "keep_awake", lambda on: None)
    return tmp_path


# ---------- Time and subtitles ----------

def test_format_time():
    assert format_time(3725.4) == "01:02:05"
    assert format_time(1.5, with_milliseconds=True, separator=",") == "00:00:01,500"
    assert format_time(-3) == "00:00:00"


def test_read_srt(tmp_path):
    path = tmp_path / "a.srt"
    path.write_text("1\n00:00:01,000 --> 00:00:03,500\nHello <i>there</i>\nfriend\n\n"
                    "2\n00:01:00,000 --> 00:01:02,000\nSecond\n", encoding="utf-8")
    assert read_subtitles(str(path)) == [{"start": 1.0, "end": 3.5, "text": "Hello there friend"},
                                         {"start": 60.0, "end": 62.0, "text": "Second"}]


def test_read_vtt_cuts_youtube_repeats(tmp_path):
    path = tmp_path / "a.vtt"
    path.write_text("WEBVTT\n\n00:01.000 --> 00:02.000\none\n\n"
                    "00:02.000 --> 00:03.000\none two\n", encoding="utf-8")
    assert [cue["text"] for cue in read_subtitles(str(path))] == ["one", "two"]


def test_subtitle_file_with_the_same_name_wins_over_a_language_code(tmp_path):
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"")
    assert find_subtitle_file(str(video)) is None
    (tmp_path / "clip.en.vtt").write_text("", encoding="utf-8")
    assert find_subtitle_file(str(video)).endswith("clip.en.vtt")
    (tmp_path / "clip.srt").write_text("", encoding="utf-8")
    assert find_subtitle_file(str(video)).endswith("clip.srt")


# ---------- Transcript lines ----------

def test_short_lines_join_the_next_but_dont_keep_going():
    merged = merge_short_lines([line(0, 2, "a"), line(2, 4.5, "b"), line(4.5, 9, "c"), line(9, 14, "d")], 4.0)
    assert [(m["start"], m["end"], m["text"]) for m in merged] == [(0, 4.5, "a b"), (4.5, 9, "c"), (9, 14, "d")]


def test_short_lines_never_join_across_a_silence():
    assert len(merge_short_lines([line(0, 2), line(40, 42)], 4.0)) == 2


def test_a_short_last_line_joins_the_one_before():
    merged = merge_short_lines([line(0, 6, "a"), line(6, 7, "b")], 4.0)
    assert [(m["end"], m["text"]) for m in merged] == [(7, "a b")]


def test_long_whisper_chunks_are_cut_into_short_timed_lines():
    # 20 seconds of continuous words, then a pause, then a short sentence
    words = [(i * 0.5, i * 0.5 + 0.4, f" w{i}") for i in range(40)]
    words += [(25.0, 25.4, " After"), (25.5, 26.0, " pause.")]
    lines = split_into_lines(words)
    assert all(each["end"] - each["start"] <= 9.5 for each in lines)
    assert lines[-1] == {"start": 25.0, "end": 26.0, "text": "After pause."}
    assert " ".join(each["text"] for each in lines[:-1]) == " ".join(f"w{i}" for i in range(40))


def test_a_sentence_end_closes_a_line_once_it_is_long_enough():
    words = [(0, 2, " One"), (2, 4.5, " two."), (4.6, 6, " Three"), (6, 7, " four.")]
    assert [each["text"] for each in split_into_lines(words)] == ["One two.", "Three four."]


# ---------- Screenshots ----------

def test_screenshot_times_cover_speech_scenes_and_silence():
    times = pick_screenshot_times([line(0, 10), line(60, 70)], [30.0], 70.0, silence_every=30.0, min_gap=2.0)
    reasons = [reason for _moment, reason in times]
    assert reasons.count("speech") == 2 and "scene" in reasons and "silence" in reasons
    moments = [moment for moment, _reason in times]
    assert moments == sorted(moments)
    assert all(later - earlier >= 2.0 for earlier, later in zip(moments, moments[1:]))


def test_a_scene_change_beats_a_speech_screenshot_next_to_it():
    times = pick_screenshot_times([line(0, 10)], [4.5], 10.0, silence_every=30.0, min_gap=2.0)
    assert [reason for _moment, reason in times] == ["scene"]


def test_new_handwriting_survives_duplicate_removal(tmp_path):
    from PIL import Image, ImageDraw
    board = Image.new("RGB", (640, 360), "white")
    ImageDraw.Draw(board).rectangle([0, 0, 640, 40], fill="gray")
    names = []
    for number, one_more_line in enumerate([False, False, True]):
        picture = board.copy()
        pen = ImageDraw.Draw(picture)
        pen.line([60, 120, 420, 120], fill="black", width=5)
        if one_more_line:
            pen.line([60, 200, 420, 200], fill="black", width=5)
        names.append(f"f_{number}.jpg")
        picture.save(str(tmp_path / names[-1]))
    frames = [{"time": float(number), "file": name, "reason": "speech"} for number, name in enumerate(names)]
    kept = remove_repeats(frames, str(tmp_path), 6, 0.5)
    assert [frame["file"] for frame in kept] == ["f_0.jpg", "f_2.jpg"]


# ---------- Output ----------

def test_lines_go_under_the_screenshot_on_screen_at_the_time():
    frames = [{"time": 2.0, "file": "a.jpg", "reason": "speech"},
              {"time": 20.0, "file": "b.jpg", "reason": "scene"}]
    blocks = digest.pair_lines_with_screenshots(frames, [line(0, 6, "early"), line(21, 25, "late")])
    assert [[each["text"] for each in block["lines"]] for block in blocks] == [["early"], ["late"]]


def test_preview_page_pairs_lines_with_screenshots_and_escapes_text():
    blocks = [{"time": 4.0, "file": "f_000004.jpg", "reason": "speech",
               "lines": [{"start": 0.0, "end": 8.0, "text": "a < b"}]},
              {"time": 92.0, "file": "f_000092.jpg", "reason": "speech", "lines": []}]
    page = preview.build_page(r"C:\v\talk.mp4", "talk.mp4", "summary", blocks)
    assert 'class="block" data-t="0.00"' in page and 'data-seek="92.00"' in page
    assert "a &lt; b" in page and "file:///C:/v/talk.mp4" in page and "(no speech)" in page
    assert "{{" not in page


# ---------- Where things are saved ----------

def test_output_goes_in_data_in_a_folder_named_after_the_video():
    folder = pipeline.output_folder_for(r"C:\Videos\My Talk (2026).final.mp4")
    assert os.path.dirname(folder) == constants.DATA_FOLDER
    assert os.path.basename(folder) == "My Talk (2026).final"
    assert os.path.basename(constants.DATA_FOLDER) == "data"


def test_a_save_folder_holds_one_folder_per_video(tmp_path, monkeypatch):
    monkeypatch.setattr(constants, "DATA_FOLDER", str(tmp_path))
    assert pipeline.output_folder_for("x/Coulombs Law -1.mp4") == os.path.join(str(tmp_path), "Coulombs Law -1")
    assert pipeline.output_folder_for("x/a.mp4", "Physics") == os.path.join(str(tmp_path), "Physics", "a")
    elsewhere = str(tmp_path.parent / "elsewhere")
    assert pipeline.output_folder_for("x/a.mp4", elsewhere) == os.path.join(elsewhere, "a")


def test_processed_list_looks_inside_save_folders(tmp_path, monkeypatch):
    monkeypatch.setattr(constants, "DATA_FOLDER", str(tmp_path))
    for relative in ("loose", os.path.join("Physics", "lecture 1"), os.path.join("Physics", "lecture 2")):
        os.makedirs(str(tmp_path / relative / "frames"))
        (tmp_path / relative / "video_digest.md").write_text("x", encoding="utf-8")
    os.makedirs(str(tmp_path / "Physics" / "unfinished" / "frames"))
    assert sorted(menu.processed_videos()) == sorted(
        ["loose", os.path.join("Physics", "lecture 1"), os.path.join("Physics", "lecture 2")])
    assert menu.save_folder_label(None) == "data"
    assert menu.save_folder_label(str(tmp_path / "Physics")) == os.path.join("data", "Physics")


# ---------- The queue ----------

def test_queue_runs_in_order_and_one_failure_doesnt_stop_it(empty_queue, monkeypatch):
    folder = empty_queue / "videos"
    folder.mkdir()
    for name in ("b.mp4", "a.mp4", "c.mkv", "notes.txt"):
        (folder / name).write_bytes(b"")
    assert video_queue.add_videos([str(folder)], read_length=False) == 3
    assert video_queue.add_videos([str(folder / "a.mp4")], read_length=False) == 0  # already waiting

    seen = []

    def pretend_to_process(video, **options):
        seen.append(video[-5:])
        if video.endswith("b.mp4"):
            raise RuntimeError("boom")
        return "out"

    monkeypatch.setattr(pipeline, "process_video", pretend_to_process)
    done, failed, log_path = video_queue.run_queue({"model": "small"})
    assert seen == ["a.mp4", "b.mp4", "c.mkv"] and (done, failed) == (2, 1)
    assert [item["status"] for item in video_queue.load_queue()] == ["done", "failed", "done"]
    assert video_queue.waiting_videos() == [] and "boom" in open(log_path, encoding="utf-8").read()


def test_queue_remembers_where_each_video_is_saved(empty_queue, monkeypatch):
    for name in ("a.mp4", "b.mp4"):
        (empty_queue / name).write_bytes(b"")
    video_queue.add_videos([str(empty_queue / "a.mp4")], dest="Physics", read_length=False)
    video_queue.add_videos([str(empty_queue / "b.mp4")], read_length=False)

    seen = []
    monkeypatch.setattr(pipeline, "process_video",
                        lambda video, dest=None, **options: seen.append((video[-5:], dest)) or "out")
    video_queue.run_queue({"model": "small"})
    assert seen == [("a.mp4", "Physics"), ("b.mp4", None)]


def test_queue_records_why_a_video_failed(empty_queue):
    gone = empty_queue / "gone.mp4"
    gone.write_bytes(b"")
    video_queue.add_videos([str(gone)], read_length=False)
    gone.unlink()  # renamed or moved after it was queued
    video_queue.run_queue({"model": "small"})
    item = video_queue.load_queue()[0]
    assert item["status"] == "failed" and "video not found" in item["error"]


def test_start_times_roll_over_to_tomorrow_once_past():
    now = datetime.datetime(2026, 11, 10, 22, 0)
    assert video_queue.parse_start_time("23:30", now) == datetime.datetime(2026, 11, 10, 23, 30)
    assert video_queue.parse_start_time("0630", now) == datetime.datetime(2026, 11, 11, 6, 30)
    assert video_queue.parse_start_time("soon", now) is None
    assert video_queue.parse_start_time("25:00", now) is None


# ---------- The menu ----------

def test_banner_lines_are_all_the_same_width():
    for title in (None, "OVERNIGHT QUEUE"):
        lines = menu.banner_lines(title)
        assert {len(each) for each in lines} == {menu.WIDTH}
    assert len(menu.banner_lines()) == 9
