from pathlib import Path

import pytest

from vvb.combiner import CombineError, combine
from vvb.matcher import build_alias_map, build_match, normalize_key
from vvb.models import GroupsCfg
from vvb.naming import build_out_path, dedupe_paths, sanitize_filename
from vvb.preset_io import load_preset, validate_preset_dict
from vvb.scanner import resolve_project, scan_slot

LANGS = ["Arab", "English", "French", "Hindi", "Por", "Russian", "Spanish", "Thailand", "Turkish", "Urdu"]


def touch(p: Path, data: bytes = b"x"):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return p


@pytest.fixture
def palm_project(tmp_path):
    for l in LANGS:
        touch(tmp_path / "Intro" / f"{l}.mov")
        touch(tmp_path / "Source" / f"{l}.mov")
    for i in range(1, 13):
        touch(tmp_path / "Video" / f"source_intro_{i:02d}.mp4")
    touch(tmp_path / "outtro.mov")
    # rác
    touch(tmp_path / "Video" / "Thumbs.db")
    touch(tmp_path / "Video" / "._source_intro_01.mp4")
    touch(tmp_path / "Video" / "clip.part.mp4")
    touch(tmp_path / "Video" / "dl.mp4.crdownload")
    touch(tmp_path / "Video" / "empty.mp4", b"")
    return tmp_path


def scan_all(preset, paths, exclude=()):
    return {n: scan_slot(n, s, paths.get(n), exclude) for n, s in preset.slots.items()}


def test_normalize_aliases():
    cfg = GroupsCfg()
    amap = build_alias_map(cfg)
    assert normalize_key("Arabic", cfg, amap) == "arab"
    assert normalize_key("AR", cfg, amap) == "arab"
    assert normalize_key("Ả Rập", cfg, amap) == "arab"
    assert normalize_key("Français", cfg, amap) == "french"
    assert normalize_key("Por", cfg, amap) == "portuguese"
    assert normalize_key("Thailand", cfg, amap) == "thai"
    assert normalize_key(" _Hindi. ", cfg, amap) == "hindi"
    assert normalize_key("Klingon", cfg, amap) == "klingon"


def test_resolve_and_scan_palm(palm_project):
    p = load_preset("palm_bottom")
    paths = resolve_project(p, str(palm_project))
    assert set(paths) == {"intro", "source", "outtro", "pool"}
    scans = scan_all(p, paths)
    assert [f.name for f in scans["pool"].files][:2] == ["source_intro_01.mp4", "source_intro_02.mp4"]
    assert len(scans["pool"].files) == 12
    assert any("0 byte" in w for w in scans["pool"].warnings)


def test_palm_120_tasks(palm_project, tmp_path):
    p = load_preset("palm_bottom")
    scans = scan_all(p, resolve_project(p, str(palm_project)))
    m = build_match(p, scans)
    assert len(m.valid_rows) == 10 and not m.errors
    tasks, _ = combine(p, m)
    assert len(tasks) == 120
    t = tasks[0]
    assert t.assets["intro"].parent.name == "Intro" and t.assets["source"].stem == t.assets["intro"].stem
    assert t.assets["outtro"].name == "outtro.mov"
    out = build_out_path(tmp_path / "Output", t, p, "palm", (1080, 1920))
    assert out.parent.name == t.group_display and out.name == f"{t.group_display}_{t.clip_name}.mp4"


def test_numbered_names_natural_sort(tmp_path):
    for n in ["clip10", "clip2", "clip1"]:
        touch(tmp_path / f"{n}.mp4")
    p = load_preset("palm_bottom")
    r = scan_slot("pool", p.slots["pool"], str(tmp_path))
    assert [f.stem for f in r.files] == ["clip1", "clip2", "clip10"]


def test_missing_and_unused_and_duplicate(tmp_path):
    touch(tmp_path / "Intro" / "Arab.mp4")
    touch(tmp_path / "Intro" / "arabic.mov")       # trùng khoá arab
    touch(tmp_path / "Intro" / "French.mp4")       # thiếu Source
    touch(tmp_path / "Intro" / "Hindi.mp4")
    touch(tmp_path / "Source" / "Arab.mp4")
    touch(tmp_path / "Source" / "hi.mp4")          # alias hindi
    touch(tmp_path / "Source" / "German.mp4")      # thừa
    touch(tmp_path / "Video" / "c1.mp4")
    touch(tmp_path / "Outtro.mp4")
    p = load_preset("palm_bottom")
    scans = scan_all(p, resolve_project(p, str(tmp_path)))
    m = build_match(p, scans)
    rows = {r.key: r for r in m.rows}
    assert not rows["arab"].valid and rows["arab"].cells["intro"].status == "duplicate"
    assert not rows["french"].valid and rows["french"].cells["source"].status == "missing"
    assert rows["hindi"].valid
    assert [f.name for _, f in m.unused] == ["German.mp4"]
    assert m.conflicts and m.conflicts[0][1] == "arab"
    # ghép tay giải quyết trùng
    m2 = build_match(p, scans, manual={"arab": {"intro": str(tmp_path / "Intro" / "Arab.mp4")}})
    assert {r.key for r in m2.valid_rows} == {"arab", "hindi"}


def test_output_excluded_from_scan(tmp_path):
    touch(tmp_path / "Video" / "a.mp4")
    touch(tmp_path / "Video" / "Output" / "x.mp4")
    p = load_preset("palm_bottom")
    p.slots["pool"].recursive = True
    r = scan_slot("pool", p.slots["pool"], str(tmp_path / "Video"), exclude=[tmp_path / "Video" / "Output"])
    assert [f.name for f in r.files] == ["a.mp4"]


def _fake_match(n_groups, n_clips, preset_name="palm_bottom"):
    from vvb.matcher import Cell, GroupRow, MatchResult
    m = MatchResult(key_slot="intro")
    for g in range(n_groups):
        r = GroupRow(key=f"g{g}", display=f"G{g}", raw=f"G{g}")
        r.cells = {"intro": Cell("ok", Path(f"i{g}.mp4")), "source": Cell("ok", Path(f"s{g}.mp4"))}
        m.rows.append(r)
    m.pool = [Path(f"clip{i}.mp4") for i in range(n_clips)]
    m.shared = {"outtro": Path("o.mp4")}
    return m


def _preset(**combine):
    p = load_preset("palm_bottom")
    return p.model_copy(update={"combine": p.combine.model_copy(update=combine)})


def test_modes():
    m = _fake_match(5, 10)
    assert len(combine(_preset(mode="cartesian"), m)[0]) == 50
    t, w = combine(_preset(mode="zip"), m)
    assert len(t) == 5 and w
    t, _ = combine(_preset(mode="per_group_subset", subset_k=2, subset_strategy="rotate"), m)
    assert len(t) == 10 and len({x.clip for x in t}) == 10  # không trùng clip giữa các nhóm
    a, _ = combine(_preset(mode="per_group_subset", subset_k=3, subset_strategy="random", seed=7), m)
    b, _ = combine(_preset(mode="per_group_subset", subset_k=3, subset_strategy="random", seed=7), m)
    assert [x.clip for x in a] == [x.clip for x in b]
    assert len(combine(_preset(mode="no_pool"), m)[0]) == 5
    assert len(combine(_preset(limit=3), m)[0]) == 3


def test_filters_and_empty_pool():
    m = _fake_match(3, 4)
    t, _ = combine(_preset(), m, groups_filter=["G1"], clips_filter=["clip0", "clip2"])
    assert [(x.group, x.clip.stem) for x in t] == [("g1", "clip0"), ("g1", "clip2")]
    m.pool = []
    with pytest.raises(CombineError):
        combine(_preset(), m)


def test_pool_match_group():
    m = _fake_match(2, 0)
    m.pool = [Path("g0_a.mp4"), Path("g1_b.mp4"), Path("generic.mp4")]
    m.pool_keys = {m.pool[0]: "g0", m.pool[1]: "g1", m.pool[2]: None}
    t, _ = combine(_preset(pool_match_group=True), m)
    assert {(x.group, x.clip.name) for x in t} == {("g0", "g0_a.mp4"), ("g0", "generic.mp4"),
                                                   ("g1", "g1_b.mp4"), ("g1", "generic.mp4")}


def test_sanitize():
    assert sanitize_filename('a:b?"c.mp4') == "a_b__c.mp4"
    assert sanitize_filename("CON") == "_CON"
    assert sanitize_filename("x" * 300).__len__() == 120
    assert sanitize_filename("name. ") == "name"
    out, w = dedupe_paths([Path("o/a.mp4"), Path("o/A.mp4"), Path("o/a.mp4")])
    assert [p.name for p in out] == ["a.mp4", "A_2.mp4", "a_3.mp4"] and len(w) == 2


def test_regex_and_subfolder_keys(tmp_path):
    touch(tmp_path / "Intro" / "intro_FR_v2.mp4")
    touch(tmp_path / "Body" / "French" / "abc.mp4")
    d = {"groups": {"key_from_slot": "intro", "key_mode": "regex", "regex": r"intro_(\w+?)_"},
         "slots": {"intro": {"type": "per_group"}}, "timeline": [{"kind": "asset", "slot": "intro"}]}
    p = validate_preset_dict(d)
    m = build_match(p, {"intro": scan_slot("intro", p.slots["intro"], str(tmp_path / "Intro"))})
    assert m.rows[0].key == "french"
    d2 = {"groups": {"key_mode": "subfolder"},
          "slots": {"body": {"type": "per_group", "recursive": True}}, "timeline": [{"kind": "asset", "slot": "body"}]}
    p2 = validate_preset_dict(d2)
    m2 = build_match(p2, {"body": scan_slot("body", p2.slots["body"], str(tmp_path / "Body"))})
    assert m2.rows[0].key == "french"
