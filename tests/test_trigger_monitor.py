import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import trigger_monitor as tm


SEP = "=" * 60


def _block(kind, details, ring=()):
    lines = ["[12:00:01.234] TD-ANOMALY type={} {} t=1750000000.00".format(kind, details)]
    lines += ["[12:00:01.235] {}".format(r) for r in ring]
    return SEP + "\n" + "\n".join(lines) + "\n\n"


def test_parse_blocks_extracts_kind_vid_evidence():
    text = _block("missed", "vid=v_a.ogv mt=[0.68] delta=n/a eff=1.000", ["ctx one", "ctx two"])
    blocks = tm.parse_blocks(text)
    assert len(blocks) == 1
    b = blocks[0]
    assert b["kind"] == "missed"
    assert b["vid"] == "v_a.ogv"
    assert b["details"].startswith("vid=v_a.ogv")
    assert b["evidence"][0].startswith("[12:00:01.234] TD-ANOMALY")
    assert b["evidence"][1] == "[12:00:01.235] ctx one"


def test_parse_blocks_skips_non_anomaly_chunks():
    text = SEP + "\n[12:00:01.235] plain debug line, no marker\n\n"
    assert tm.parse_blocks(text) == []


def test_group_by_problem_groups_same_kind_vid():
    text = _block("missed", "vid=v_a.ogv mt=[0.68]")
    text += _block("missed", "vid=v_a.ogv mt=[0.92]")
    text += _block("late", "vid=v_a.ogv delta=0.20")
    text += _block("missed", "vid=v_b.ogv mt=[1.10]")
    groups = tm.group_by_problem(tm.parse_blocks(text))
    keys = {(g["kind"], g["vid"]) for g in groups}
    assert keys == {("missed", "v_a.ogv"), ("late", "v_a.ogv"), ("missed", "v_b.ogv")}
    missed_a = [g for g in groups if (g["kind"], g["vid"]) == ("missed", "v_a.ogv")][0]
    assert len(missed_a["markers"]) == 2


def test_group_by_problem_dedupes_evidence():
    text = _block("stall", "gap=0.80 vid=v_a.ogv", ["dup line", "unique line"])
    text += _block("stall", "gap=0.90 vid=v_a.ogv", ["dup line"])
    group = tm.group_by_problem(tm.parse_blocks(text))[0]
    assert group["evidence"].count("[12:00:01.235] dup line") == 1
    assert "[12:00:01.235] unique line" in group["evidence"]


def test_find_logs_filters_empty_and_other_paths(tmp_path):
    good = tmp_path / "GameA" / "v1" / "game" / "renpy_cue"
    good.mkdir(parents=True)
    (good / "trigger-debug.log").write_text("content")
    (good / "trigger-debug.log.bak").write_text("other name should not match")
    empty = tmp_path / "GameB" / "v1" / "game" / "renpy_cue"
    empty.mkdir(parents=True)
    (empty / "trigger-debug.log").write_text("")
    other = tmp_path / "GameC" / "v1" / "game" / "other_dir"
    other.mkdir(parents=True)
    (other / "trigger-debug.log").write_text("not renpy_cue")
    found = tm.find_logs(tmp_path)
    assert found == [good / "trigger-debug.log"]


def test_title_for_uses_vid_or_game():
    group = {"kind": "missed", "vid": "v_a.ogv"}
    assert tm.title_for(group, "GameA") == "trigger-anomaly: missed v_a.ogv"
    group = {"kind": "restart-burst", "vid": None}
    assert tm.title_for(group, "GameA") == "trigger-anomaly: restart-burst GameA"


def test_build_body_includes_meaning_count_evidence():
    group = {
        "kind": "missed",
        "vid": "v_a.ogv",
        "markers": ["vid=v_a.ogv mt=[0.68]", "vid=v_a.ogv mt=[0.92]"],
        "evidence": ["[12:00:01.234] TD-ANOMALY type=missed vid=v_a.ogv", "[12:00:01.235] ctx"],
    }
    body = tm.build_body(group, "GameA")
    assert "Anomaly type: missed -- marker skipped entirely (past-due, never fired)" in body
    assert "Occurrences: 2" in body
    assert "[12:00:01.234] TD-ANOMALY type=missed vid=v_a.ogv" in body
    assert "Game: GameA" in body
    # Issue bodies must not leak local file paths -- filename only, no path.
    assert "/mnt/e" not in body
    assert "Evidence (trigger-debug.log):" in body
