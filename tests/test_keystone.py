import json
import math
import sys
import xml.etree.ElementTree as ET
from fractions import Fraction
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import keystone as ks  # noqa: E402

SVG_NS = "{http://www.w3.org/2000/svg}"

SEGMENTAL = """
name = Test segmental
type = segmental
span = 2.4 m
rise = 0.9 m
thickness = 0.30 m
voussoirs = 9
depth = 0.25 m
load = 12 kN/m
"""


def arch_from(text):
    arch, errors = ks.build_arch(text)
    assert not errors, errors
    return arch


def test_length_units_are_exact():
    assert ks._length("2.4 m") == Fraction(12, 5)
    assert ks._length("300 mm") == Fraction(3, 10)
    assert ks._length("1 in") == Fraction(254, 10000)
    assert ks._length("1 ft") == Fraction(3048, 10000)


def test_bad_length_is_rejected():
    with pytest.raises(ValueError):
        ks._length("2.4 metres")


def test_unknown_key_reports_its_line_number():
    text = "name = X\nfoo = 1\ntype = semicircle\nspan = 2 m\nthickness = 0.2 m\nvoussoirs = 5\ndepth = 0.2 m\n"
    _, errors = ks.build_arch(text)
    assert (2, "unknown key 'foo'") in errors


def test_duplicate_key_points_back_to_first_line():
    text = "type = semicircle\nspan = 2 m\nspan = 3 m\nthickness = 0.2 m\nvoussoirs = 5\ndepth = 0.2 m\n"
    _, errors = ks.build_arch(text)
    assert any(line == 3 and "first set on line 2" in msg for line, msg in errors)


def test_missing_required_keys_are_reported():
    _, errors = ks.build_arch("name = X\n")
    messages = [msg for _, msg in errors]
    for key in ("type", "span", "thickness", "voussoirs", "depth"):
        assert f"missing required key {key!r}" in messages


def test_semicircle_radius_and_sweep():
    arch = arch_from(
        "type = semicircle\nspan = 2 m\nthickness = 0.2 m\nvoussoirs = 5\ndepth = 0.2 m\n"
    )
    arc = ks.geometry(arch)
    assert arch.rise == pytest.approx(1.0)
    assert arc.radius == pytest.approx(1.0)
    assert 2 * (arc.a1 - arc.a0) == pytest.approx(math.pi)


def test_segmental_arc_passes_through_springing_and_crown():
    arch = arch_from(SEGMENTAL)
    arc = ks.geometry(arch)
    springing = math.hypot(arch.span / 2 - arc.cx, 0 - arc.cy)
    crown = math.hypot(0 - arc.cx, arch.rise - arc.cy)
    assert springing == pytest.approx(arc.radius)
    assert crown == pytest.approx(arc.radius)
    assert arc.radius == pytest.approx((1.2**2 + 0.9**2) / 1.8)


def test_pointed_arch_rise_radius_and_sweep():
    arch = arch_from(
        "type = pointed\nspan = 2 m\nthickness = 0.2 m\nvoussoirs = 7\ndepth = 0.2 m\n"
    )
    arc = ks.geometry(arch)
    assert arch.rise == pytest.approx(math.sqrt(3))
    assert arc.radius == pytest.approx(2.0)
    assert arc.a1 - arc.a0 == pytest.approx(math.pi / 3)


def test_odd_count_has_keystone_and_even_does_not():
    odd = arch_from(SEGMENTAL)
    stones = ks.layout(odd, ks.geometry(odd))
    assert len(stones) == 9
    assert [s.label for s in stones if s.key] == ["K"]
    even = arch_from(SEGMENTAL.replace("voussoirs = 9", "voussoirs = 8"))
    stones = ks.layout(even, ks.geometry(even))
    assert len(stones) == 8
    assert not any(s.key for s in stones)


def test_stone_angles_add_up_to_the_full_sweep():
    arch = arch_from(SEGMENTAL)
    arc = ks.geometry(arch)
    total = sum(s.angle for s in ks.layout(arch, arc))
    assert total == pytest.approx(2 * (arc.a1 - arc.a0))


def test_semicircle_total_volume_matches_half_annulus():
    arch = arch_from(
        "type = semicircle\nspan = 2 m\nthickness = 0.2 m\nvoussoirs = 5\ndepth = 0.2 m\n"
    )
    result = ks.analyse(arch)
    expected = 0.2 * math.pi * (1.2**2 - 1.0**2) / 2
    assert result["total_volume_m3"] == pytest.approx(expected)
    assert result["order_volume_m3"] == pytest.approx(expected)


def test_waste_inflates_the_order_volume():
    arch = arch_from(SEGMENTAL.replace("load = 12 kN/m", "waste = 5 %"))
    result = ks.analyse(arch)
    assert result["order_volume_m3"] == pytest.approx(result["total_volume_m3"] * 1.05)


def test_thrust_uses_parabolic_estimate():
    result = ks.analyse(arch_from(SEGMENTAL))
    assert result["thrust_kn"] == pytest.approx(12 * 2.4**2 / (8 * 0.9))


def test_min_rise_brings_thrust_to_the_limit():
    rise = ks.min_rise_for_thrust(12, 2.4, 8)
    assert rise == pytest.approx(1.08)
    assert 12 * 2.4**2 / (8 * rise) == pytest.approx(8)


def test_thickness_at_or_above_radius_is_an_error():
    text = "type = semicircle\nspan = 2 m\nthickness = 1.5 m\nvoussoirs = 5\ndepth = 0.2 m\n"
    _, errors = ks.build_arch(text)
    assert any(line == 3 and "intrados radius" in msg for line, msg in errors)


def test_wrong_pointed_rise_is_an_error():
    text = "type = pointed\nspan = 2 m\nrise = 1.0 m\nthickness = 0.2 m\nvoussoirs = 7\ndepth = 0.2 m\n"
    _, errors = ks.build_arch(text)
    assert any(line == 3 and msg.startswith("rise:") for line, msg in errors)


def test_segmental_rise_must_be_below_half_span():
    text = "type = segmental\nspan = 2 m\nrise = 1.2 m\nthickness = 0.2 m\nvoussoirs = 5\ndepth = 0.2 m\n"
    _, errors = ks.build_arch(text)
    assert any(msg.startswith("rise:") for _, msg in errors)


def test_flat_arch_and_wide_stone_warnings():
    arch = arch_from(
        "type = segmental\nspan = 4 m\nrise = 0.5 m\nthickness = 0.3 m\nvoussoirs = 5\ndepth = 0.2 m\n"
    )
    warnings = ks.analyse(arch)["warnings"]
    assert any("flat arch" in w for w in warnings)
    assert any("exceeds max_stone" in w for w in warnings)


def test_svg_is_well_formed_and_has_one_polygon_per_piece():
    arch = arch_from(SEGMENTAL)
    root = ET.fromstring(ks.render_svg(arch))
    assert root.tag == SVG_NS + "svg"
    # 8 stones with one piece each, plus the keystone split into two pieces
    assert len(root.findall(SVG_NS + "polygon")) == 10


def test_ascii_drawing_marks_the_keystone():
    drawing = ks.render_ascii(arch_from(SEGMENTAL)).split("\n\n")[0]
    assert "K" in drawing
    assert "1" in drawing


def test_cli_check_exit_codes(tmp_path, capsys):
    spec = tmp_path / "arch.arch"
    spec.write_text(SEGMENTAL, encoding="utf-8")
    assert ks.main(["check", str(spec)]) == 0
    assert ks.main(["check", str(spec), "--max-thrust", "1"]) == 2
    assert ks.main(["check", str(spec), "--max-stone-mass", "1"]) == 2
    bad = tmp_path / "bad.arch"
    bad.write_text("span = 2 furlongs\n", encoding="utf-8")
    assert ks.main(["check", str(bad)]) == 1
    assert "bad.arch:1:" in capsys.readouterr().out


def test_cli_report_json_is_parseable(tmp_path, capsys):
    spec = tmp_path / "arch.arch"
    spec.write_text(SEGMENTAL, encoding="utf-8")
    assert ks.main(["report", str(spec), "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["voussoirs"] == 9
    assert len(data["stones"]) == 9


def test_cli_missing_file_returns_one(tmp_path, capsys):
    assert ks.main(["report", str(tmp_path / "nope.arch")]) == 1
    assert "cannot read" in capsys.readouterr().err
