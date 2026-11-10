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
