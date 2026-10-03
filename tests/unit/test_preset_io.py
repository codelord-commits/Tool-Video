import json

import pytest

from vvb.preset_io import PresetError, list_presets, load_preset, save_preset, validate_preset_dict

ALL = ["palm_bottom", "hook3s", "hook_keep_voice", "top_half", "insert_middle", "concat_only", "pip_corner"]


@pytest.mark.parametrize("name", ALL)
def test_builtin_presets_load(name):
    p = load_preset(name)
    assert p.timeline


def test_palm_defaults():
    p = load_preset("palm_bottom")
    seg = p.timeline[0]
    assert seg.region.split == 0.5
    assert seg.protect[0].from_ == "base"
    assert p.key_slot() == "intro" and p.pool_slot() == "pool"
    assert p.out_size() == (1080, 1920)
    assert p.run.existing == "skip"


def test_invalid_split_reports_path():
    d = json.loads(load_preset("palm_bottom").model_dump_json(by_alias=True))
    d["timeline"][0]["region"]["split"] = 1.5
    with pytest.raises(PresetError) as e:
        validate_preset_dict(d)
    assert any(loc == "timeline.0.region.split" for loc, _ in e.value.errors)


def test_unknown_slot_ref():
    d = {"slots": {"a": {"type": "per_group"}}, "timeline": [{"kind": "asset", "slot": "zzz"}]}
    with pytest.raises(PresetError) as e:
        validate_preset_dict(d)
    assert "zzz" in str(e.value)


def test_missing_version_is_upgraded():
    d = {"slots": {"a": {"type": "per_group"}}, "timeline": [{"kind": "asset", "slot": "a"}]}
    assert validate_preset_dict(d).schema_version == 1


def test_future_version_rejected():
    d = {"schema_version": 99, "slots": {"a": {"type": "per_group"}}, "timeline": [{"kind": "asset", "slot": "a"}]}
    with pytest.raises(PresetError):
        validate_preset_dict(d)


def test_round_trip(tmp_path):
    p = load_preset("palm_bottom")
    out = save_preset(p, tmp_path / "x.json")
    assert load_preset(out) == p


def test_list_presets():
    ids = {p["id"] for p in list_presets()}
    assert set(ALL) <= ids
