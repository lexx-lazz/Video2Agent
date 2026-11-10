"""Offline tests for the pure logic: no FFmpeg, no Whisper, no network."""
from video2agent import cli


def test_hms():
    assert cli.hms(3725.4) == "01:02:05"
    assert cli.hms(1.5, ms=True, sep=",") == "00:00:01,500"
    assert cli.hms(-3) == "00:00:00"


def test_parse_srt(tmp_path):
    p = tmp_path / "a.srt"
    p.write_text("1\n00:00:01,000 --> 00:00:03,500\nHello <i>there</i>\nfriend\n\n"
                 "2\n00:01:00,000 --> 00:01:02,000\nSecond\n", encoding="utf-8")
    segs = cli.parse_subs(str(p))
    assert segs == [{"start": 1.0, "end": 3.5, "text": "Hello there friend"},
                    {"start": 60.0, "end": 62.0, "text": "Second"}]


def test_parse_vtt_strips_rolling_repeats(tmp_path):
    p = tmp_path / "a.vtt"
    p.write_text("WEBVTT\n\n00:01.000 --> 00:02.000\none\n\n"
                 "00:02.000 --> 00:03.000\none two\n", encoding="utf-8")
    assert [s["text"] for s in cli.parse_subs(str(p))] == ["one", "two"]


def test_find_sidecar_prefers_exact_then_language_suffix(tmp_path):
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"")
    assert cli.find_sidecar(str(video)) is None
    (tmp_path / "clip.en.vtt").write_text("", encoding="utf-8")
    assert cli.find_sidecar(str(video)).endswith("clip.en.vtt")
    (tmp_path / "clip.srt").write_text("", encoding="utf-8")
    assert cli.find_sidecar(str(video)).endswith("clip.srt")


def seg(a, b, t="x"):
    return {"start": a, "end": b, "text": t}


def test_merge_short_joins_fragments_but_does_not_chain():
    out = cli.merge_short([seg(0, 2, "a"), seg(2, 4.5, "b"), seg(4.5, 9, "c"), seg(9, 14, "d")], 4.0)
    assert [(s["start"], s["end"], s["text"]) for s in out] == [(0, 4.5, "a b"), (4.5, 9, "c"), (9, 14, "d")]


def test_merge_short_never_bridges_a_silence():
    out = cli.merge_short([seg(0, 2), seg(40, 42)], 4.0)
    assert len(out) == 2


def test_merge_short_folds_back_a_short_tail():
    out = cli.merge_short([seg(0, 6, "a"), seg(6, 7, "b")], 4.0)
    assert [(s["end"], s["text"]) for s in out] == [(7, "a b")]


def test_candidates_cover_speech_scenes_and_silence():
    segs = [seg(0, 10), seg(60, 70)]
    times = cli.candidate_times(segs, [30.0], 70.0, silence_every=30.0, min_gap=2.0)
    reasons = [why for _t, why in times]
    assert reasons.count("speech") == 2 and "scene" in reasons and "silence" in reasons
    ts = [t for t, _why in times]
    assert ts == sorted(ts)
    assert all(b - a >= 2.0 for a, b in zip(ts, ts[1:]))


def test_scene_change_wins_over_nearby_speech_frame():
    times = cli.candidate_times([seg(0, 10)], [4.5], 10.0, silence_every=30.0, min_gap=2.0)
    assert [why for _t, why in times] == ["scene"]


def test_blocks_attach_lines_to_the_frame_on_screen():
    frames = [{"time": 2.0, "file": "a.jpg", "reason": "speech"},
              {"time": 20.0, "file": "b.jpg", "reason": "scene"}]
    blocks = cli.build_blocks(frames, [seg(0, 6, "early"), seg(21, 25, "late")])
    assert [[s["text"] for s in b["lines"]] for b in blocks] == [["early"], ["late"]]


def test_output_goes_to_data_folder_named_after_the_video():
    import os
    out = cli.default_out_dir(r"C:\Videos\My Talk (2026).final.mp4")
    assert os.path.dirname(out) == cli.DATA_DIR
    assert os.path.basename(out) == "My Talk (2026).final"
    assert os.path.basename(cli.DATA_DIR) == "data"


def test_banner_rows_line_up_and_fit_the_box():
    from video2agent import tui
    rows = tui.banner_lines()
    assert len(rows) == 5 and len({len(r) for r in rows}) == 1
    assert len(rows[0]) + 2 <= tui.WIDTH - 4


def test_long_whisper_chunks_are_cut_into_short_timed_lines():
    # 20 s of continuous words, then a pause, then a short sentence
    words = [(i * 0.5, i * 0.5 + 0.4, " w%d" % i) for i in range(40)]
    words += [(25.0, 25.4, " After"), (25.5, 26.0, " pause.")]
    segs = cli.regroup_words(words)
    assert all(s["end"] - s["start"] <= 9.5 for s in segs)
    assert segs[-1] == {"start": 25.0, "end": 26.0, "text": "After pause."}
    assert " ".join(s["text"] for s in segs[:-1]) == " ".join("w%d" % i for i in range(40))


def test_sentence_end_closes_a_line_once_it_is_long_enough():
    words = [(0, 2, " One"), (2, 4.5, " two."), (4.6, 6, " Three"), (6, 7, " four.")]
    assert [s["text"] for s in cli.regroup_words(words)] == ["One two.", "Three four."]


def test_new_handwriting_survives_duplicate_removal(tmp_path):
    from PIL import Image, ImageDraw
    board = Image.new("RGB", (640, 360), "white")
    ImageDraw.Draw(board).rectangle([0, 0, 640, 40], fill="gray")
    names = []
    for i, extra in enumerate([False, False, True]):
        im = board.copy()
        d = ImageDraw.Draw(im)
        d.line([60, 120, 420, 120], fill="black", width=5)
        if extra:
            d.line([60, 200, 420, 200], fill="black", width=5)   # one more written line
        names.append("f_%d.jpg" % i)
        im.save(str(tmp_path / names[-1]))
    frames = [{"time": float(i), "file": n, "reason": "speech"} for i, n in enumerate(names)]
    kept = cli.dedupe_frames(frames, str(tmp_path), 6, 0.5)
    assert [f["file"] for f in kept] == ["f_0.jpg", "f_2.jpg"]


def test_queue_add_run_order_and_failure_isolation(tmp_path, monkeypatch):
    from video2agent import batch
    import argparse
    monkeypatch.setattr(batch, "QUEUE_FILE", str(tmp_path / "queue.json"))
    monkeypatch.setattr(batch, "LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setattr(cli, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(batch, "keep_awake", lambda on: None)
    folder = tmp_path / "vids"
    folder.mkdir()
    for n in ("b.mp4", "a.mp4", "c.mkv", "notes.txt"):
        (folder / n).write_bytes(b"")
    assert batch.add([str(folder)], probe=False) == 3
    assert batch.add([str(folder / "a.mp4")], probe=False) == 0      # already waiting
    seen = []

    def fake_process(a):
        seen.append(a.video[-5:])
        if a.video.endswith("b.mp4"):
            raise RuntimeError("boom")
        return "out"
    monkeypatch.setattr(cli, "process", fake_process)
    done, failed, log_path = batch.run_queue(argparse.Namespace(model="small"))
    assert seen == ["a.mp4", "b.mp4", "c.mkv"] and (done, failed) == (2, 1)
    assert [i["status"] for i in batch.load()] == ["done", "failed", "done"]
    assert batch.pending() == [] and "boom" in open(log_path, encoding="utf-8").read()


def test_clock_times_roll_to_tomorrow_when_already_past():
    import datetime
    from video2agent import batch
    now = datetime.datetime(2026, 11, 10, 22, 0)
    assert batch.parse_clock("23:30", now) == datetime.datetime(2026, 11, 10, 23, 30)
    assert batch.parse_clock("0630", now) == datetime.datetime(2026, 11, 11, 6, 30)
    assert batch.parse_clock("soon", now) is None and batch.parse_clock("25:00", now) is None


def test_preview_pairs_lines_with_frames_and_escapes_text():
    from video2agent import preview
    blocks = [{"time": 4.0, "file": "f_000004.jpg", "reason": "speech",
               "lines": [{"start": 0.0, "end": 8.0, "text": "a < b"}]},
              {"time": 92.0, "file": "f_000092.jpg", "reason": "speech", "lines": []}]
    page = preview.build(r"C:\v\talk.mp4", "talk.mp4", "meta", blocks)
    assert 'class="block" data-t="0.00"' in page and 'data-seek="92.00"' in page
    assert "a &lt; b" in page and "file:///C:/v/talk.mp4" in page and "(no speech)" in page
    assert "__" not in page.replace("__proto__", "")


def test_save_folder_is_a_category_with_one_folder_per_video(tmp_path, monkeypatch):
    import os
    monkeypatch.setattr(cli, "DATA_DIR", str(tmp_path))
    assert cli.default_out_dir("x/Coulombs Law -1.mp4") == os.path.join(str(tmp_path), "Coulombs Law -1")
    assert cli.default_out_dir("x/a.mp4", "EE-337") == os.path.join(str(tmp_path), "EE-337", "a")
    elsewhere = str(tmp_path.parent / "elsewhere")
    assert cli.default_out_dir("x/a.mp4", elsewhere) == os.path.join(elsewhere, "a")


def test_queue_remembers_where_each_video_is_saved(tmp_path, monkeypatch):
    from video2agent import batch
    import argparse
    monkeypatch.setattr(batch, "QUEUE_FILE", str(tmp_path / "queue.json"))
    monkeypatch.setattr(batch, "LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setattr(batch, "keep_awake", lambda on: None)
    for n in ("a.mp4", "b.mp4"):
        (tmp_path / n).write_bytes(b"")
    batch.add([str(tmp_path / "a.mp4")], probe=False, dest="EE-337")
    batch.add([str(tmp_path / "b.mp4")], probe=False)
    seen = []
    monkeypatch.setattr(cli, "process", lambda a: seen.append((a.video[-5:], a.dest)) or "out")
    batch.run_queue(argparse.Namespace(model="small", dest="ignored"))
    assert seen == [("a.mp4", "EE-337"), ("b.mp4", None)]


def test_queue_records_the_reason_a_video_failed(tmp_path, monkeypatch):
    from video2agent import batch
    import argparse
    monkeypatch.setattr(batch, "QUEUE_FILE", str(tmp_path / "queue.json"))
    monkeypatch.setattr(batch, "LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setattr(batch, "keep_awake", lambda on: None)
    gone = tmp_path / "gone.mp4"
    gone.write_bytes(b"")
    batch.add([str(gone)], probe=False)
    gone.unlink()                                   # renamed or moved after being queued
    monkeypatch.setattr(cli, "find_tool", lambda name: name)
    batch.run_queue(argparse.Namespace(model="small", dest=None, out=None))
    item = batch.load()[0]
    assert item["status"] == "failed" and "video not found" in item["error"]


def test_library_finds_videos_inside_category_folders(tmp_path, monkeypatch):
    import os
    from video2agent import tui
    monkeypatch.setattr(cli, "DATA_DIR", str(tmp_path))
    for rel in ("loose", os.path.join("EE-337", "lecture 1"), os.path.join("EE-337", "lecture 2")):
        os.makedirs(str(tmp_path / rel / "frames"))
        (tmp_path / rel / "video_digest.md").write_text("x", encoding="utf-8")
    os.makedirs(str(tmp_path / "EE-337" / "unfinished" / "frames"))
    assert sorted(tui.processed_videos()) == sorted(
        ["loose", os.path.join("EE-337", "lecture 1"), os.path.join("EE-337", "lecture 2")])
    assert tui.dest_label(None) == "data"
    assert tui.dest_label(str(tmp_path / "EE-337")) == os.path.join("data", "EE-337")
