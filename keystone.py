#!/usr/bin/env python3
"""Keystone: offline voussoir arch planner.

Reads a plain-text arch spec and works out the arch geometry, the voussoir
layout and cut angles, stone volumes and masses, a parabolic thrust estimate,
lint findings, SVG and ASCII drawings, and the minimum rise for a thrust limit.

Standard library only. Nothing is read from or sent over the network.
"""

import argparse
import html
import json
import math
import re
import sys
from dataclasses import dataclass
from fractions import Fraction

ARCH_TYPES = ("semicircle", "segmental", "pointed")
LENGTH_UNITS = {
    "mm": Fraction(1, 1000),
    "cm": Fraction(1, 100),
    "m": Fraction(1),
    "in": Fraction(254, 10000),
    "ft": Fraction(3048, 10000),
}
REQUIRED_KEYS = ("type", "span", "thickness", "voussoirs", "depth")
DEFAULT_DENSITY = 2300.0  # kg/m3, typical dressed stone
DEFAULT_MAX_STONE = 0.6  # m, widest extrados face allowed per stone
MARKS = "123456789abcdefghijklmnopqrstuvwxyz"

_NUM = r"(\d+(?:\.\d+)?)"
_LENGTH_RE = re.compile(_NUM + r"\s*(mm|cm|m|in|ft)")
_DENSITY_RE = re.compile(_NUM + r"\s*kg/m3")
_LOAD_RE = re.compile(_NUM + r"\s*kN/m")
_PERCENT_RE = re.compile(_NUM + r"\s*%?")


# ---------------------------------------------------------------- parsing

def _length(text):
    m = _LENGTH_RE.fullmatch(text.strip())
    if not m:
        raise ValueError(f"expected a length such as 2.4 m (mm, cm, m, in or ft), got {text!r}")
    return Fraction(m.group(1)) * LENGTH_UNITS[m.group(2)]


def _arch_type(text):
    value = text.strip().lower()
    if value not in ARCH_TYPES:
        raise ValueError(f"expected one of {', '.join(ARCH_TYPES)}, got {text!r}")
    return value


def _count(text):
    value = text.strip()
    if not value.isdigit() or int(value) < 3:
        raise ValueError(f"expected a whole number of 3 or more, got {text!r}")
    return int(value)


def _density(text):
    m = _DENSITY_RE.fullmatch(text.strip())
    if not m:
        raise ValueError(f"expected a density such as 2300 kg/m3, got {text!r}")
    return float(m.group(1))


def _waste(text):
    m = _PERCENT_RE.fullmatch(text.strip())
    if not m:
        raise ValueError(f"expected a percentage such as 5 %, got {text!r}")
    value = Fraction(m.group(1)) / 100
    if value >= 1:
        raise ValueError("waste must be less than 100 %")
    return float(value)


def _load(text):
    m = _LOAD_RE.fullmatch(text.strip())
    if not m:
        raise ValueError(f"expected a line load such as 12 kN/m, got {text!r}")
    return float(m.group(1))


def _name(text):
    value = text.strip()
    if not value:
        raise ValueError("name cannot be empty")
    return value


CONVERTERS = {
    "name": _name,
    "type": _arch_type,
    "span": _length,
    "rise": _length,
    "thickness": _length,
    "voussoirs": _count,
    "depth": _length,
    "density": _density,
    "waste": _waste,
    "load": _load,
    "max_stone": _length,
}


def parse_spec(text):
    """Split spec text into {key: (line, raw value)} plus syntax errors."""
    values, errors = {}, []
    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if "=" not in line:
            errors.append((lineno, "expected 'key = value'"))
            continue
        key, value = (part.strip() for part in line.split("=", 1))
        key = key.lower()
        if key not in CONVERTERS:
            errors.append((lineno, f"unknown key {key!r}"))
        elif key in values:
            errors.append((lineno, f"duplicate key {key!r} (first set on line {values[key][0]})"))
        else:
            values[key] = (lineno, value)
    return values, errors


@dataclass
class Arch:
    name: str
    kind: str
    span: float  # m
    rise: float  # m, derived for semicircle and pointed arches
    thickness: float  # m, radial depth of the ring
    voussoirs: int
    depth: float  # m, stone depth along the wall
    density: float  # kg/m3
    waste: float  # fraction
    load: float | None  # kN per metre run, optional
    max_stone: float  # m


def build_arch(text):
    """Parse and validate spec text. Returns (Arch or None, sorted [(line, message)])."""
    values, errors = parse_spec(text)
    parsed = {}
    for key, (lineno, raw) in values.items():
        try:
            parsed[key] = CONVERTERS[key](raw)
        except ValueError as exc:
            errors.append((lineno, f"{key}: {exc}"))
    for key in REQUIRED_KEYS:
        if key not in values:
            errors.append((0, f"missing required key {key!r}"))
    if errors:
        return None, sorted(errors)
    arch, more = _validate(parsed, values)
    return arch, sorted(errors + more)


def _validate(p, values):
    errors = []

    def fail(key, message):
        line = values[key][0] if key in values else 0
        errors.append((line, f"{key}: {message}"))

    if p["span"] <= 0:
        fail("span", "must be positive")
    if p["thickness"] <= 0:
        fail("thickness", "must be positive")
    if p["depth"] <= 0:
        fail("depth", "must be positive")
    span = float(p["span"])
    kind = p["type"]
    if kind == "segmental":
        if "rise" not in p:
            fail("type", "segmental arches need a rise = ... line")
            rise = None
        else:
            rise = float(p["rise"])
            if not 0 < rise < span / 2:
                fail("rise", "must be more than 0 and less than half the span")
                rise = None
    else:
        derived = span / 2 if kind == "semicircle" else span * math.sqrt(3) / 2
        if "rise" in p and abs(float(p["rise"]) - derived) > 0.0005:
            fail("rise", f"a {kind} arch has rise {derived:.4f} m; remove the line or match it")
        rise = derived
    if errors or rise is None:
        return None, errors

    arch = Arch(
        name=p.get("name", "Untitled arch"),
        kind=kind,
        span=span,
        rise=rise,
        thickness=float(p["thickness"]),
        voussoirs=p["voussoirs"],
        depth=float(p["depth"]),
        density=p.get("density", DEFAULT_DENSITY),
        waste=p.get("waste", 0.0),
        load=p.get("load"),
        max_stone=float(p["max_stone"]) if "max_stone" in p else DEFAULT_MAX_STONE,
    )
    intrados = geometry(arch).radius
    if arch.thickness >= intrados:
        fail("thickness", f"must be less than the intrados radius ({intrados:.3f} m)")
        return None, errors
    return arch, errors


# --------------------------------------------------------------- geometry

@dataclass
class Arc:
    cx: float  # centre of the right-hand intrados arc, m
    cy: float
    radius: float  # intrados radius, m
    a0: float  # springing angle, radians from +x
    a1: float  # crown angle, radians from +x


def geometry(arch):
    """Intrados arc of the right half. The left half is its mirror image."""
    half = arch.span / 2
    h = arch.rise
    if arch.kind == "segmental":
        radius = (half * half + h * h) / (2 * h)
        cx, cy = 0.0, h - radius
    elif arch.kind == "semicircle":
        radius, cx, cy = half, 0.0, 0.0
    else:  # pointed: each half is an arc struck from the opposite springing
        radius, cx, cy = arch.span, -half, 0.0
    a0 = math.atan2(-cy, half - cx)
    a1 = math.atan2(h - cy, -cx)
    return Arc(cx, cy, radius, a0, a1)


@dataclass
class Stone:
    label: str
    mark: str  # single character used by the ASCII drawing
    pieces: list  # (cx, cy, lo, hi) arc pieces, angles in radians
    key: bool = False

    @property
    def angle(self):
        return sum(hi - lo for _, _, lo, hi in self.pieces)


def layout(arch, arc):
    """Equal-angle voussoirs from the left springing to the right springing.

    An odd count puts a keystone on the crown, split across both halves. An
    even count puts a joint on the crown instead.
    """
    n = arch.voussoirs
    m = n // 2
    keystone = n % 2 == 1
    theta = (arc.a1 - arc.a0) / (m + 0.5 if keystone else m)
    cx, cy = arc.cx, arc.cy

    def right(lo, hi):
        return (cx, cy, lo, hi)

    def left(lo, hi):
        return (-cx, cy, math.pi - hi, math.pi - lo)

    stones, number = [], 0

    def numbered(piece):
        nonlocal number
        number += 1
        return Stone(str(number), MARKS[(number - 1) % len(MARKS)], [piece])

    for k in range(m):
        lo = arc.a0 + k * theta
        stones.append(numbered(left(lo, lo + theta)))
    if keystone:
        crown_lo = arc.a1 - theta / 2
        stones.append(Stone("K", "K", [right(crown_lo, arc.a1), left(crown_lo, arc.a1)], key=True))
    for k in reversed(range(m)):
        lo = arc.a0 + k * theta
        stones.append(numbered(right(lo, lo + theta)))
    return stones


def analyse(arch):
    """Every number the report, JSON and CI gates need, as plain data."""
    arc = geometry(arch)
    r_in = arc.radius
    r_out = r_in + arch.thickness
    rows = []
    for stone in layout(arch, arc):
        angle = stone.angle
        volume = arch.depth * (r_out**2 - r_in**2) / 2 * angle
        rows.append({
            "label": stone.label,
            "key": stone.key,
            "angle_deg": math.degrees(angle),
            "intrados_m": r_in * angle,
            "extrados_m": r_out * angle,
            "volume_m3": volume,
            "mass_kg": volume * arch.density,
        })
    total_volume = sum(r["volume_m3"] for r in rows)
    total_mass = sum(r["mass_kg"] for r in rows)
    thrust = arch.load * arch.span**2 / (8 * arch.rise) if arch.load is not None else None

    warnings = []
    ratio = arch.rise / arch.span
    if ratio < 0.2:
        warnings.append(f"flat arch: rise is {ratio:.2f} of the span (under 0.20); thrust climbs quickly")
    if arch.thickness < arch.span / 20:
        warnings.append("thin ring: thickness is under 1/20 of the span (rule of thumb)")
    for r in rows:
        if r["extrados_m"] > arch.max_stone:
            warnings.append(
                f"stone {r['label']}: extrados face {r['extrados_m']:.3f} m exceeds "
                f"max_stone {arch.max_stone:.3f} m"
            )

    return {
        "name": arch.name,
        "type": arch.kind,
        "span_m": arch.span,
        "rise_m": arch.rise,
        "rise_ratio": ratio,
        "thickness_m": arch.thickness,
        "depth_m": arch.depth,
        "density_kg_m3": arch.density,
        "waste_fraction": arch.waste,
        "voussoirs": arch.voussoirs,
        "intrados_radius_m": r_in,
        "extrados_radius_m": r_out,
        "springing_deg": math.degrees(arc.a0),
        "sweep_deg": math.degrees(2 * (arc.a1 - arc.a0)),
        "stones": rows,
        "total_volume_m3": total_volume,
        "total_mass_kg": total_mass,
        "order_volume_m3": total_volume * (1 + arch.waste),
        "heaviest_kg": max(r["mass_kg"] for r in rows),
        "load_kn_m": arch.load,
        "thrust_kn": thrust,
        "warnings": warnings,
    }


def min_rise_for_thrust(load, span, max_thrust):
    """Smallest rise that keeps the parabolic thrust estimate at or below max_thrust."""
    return load * span**2 / (8 * max_thrust)


# ---------------------------------------------------------------- drawing

def _arc_points(cx, cy, radius, lo, hi, steps=16):
    return [
        (cx + radius * math.cos(lo + (hi - lo) * i / steps), cy + radius * math.sin(lo + (hi - lo) * i / steps))
        for i in range(steps + 1)
    ]


def _piece_outline(piece, r_in, r_out):
    cx, cy, lo, hi = piece
    inner = _arc_points(cx, cy, r_in, lo, hi)
    outer = _arc_points(cx, cy, r_out, lo, hi)
    return inner + outer[::-1]


def render_svg(arch, width=640):
    arc = geometry(arch)
    r_in = arc.radius
    r_out = r_in + arch.thickness
    stones = layout(arch, arc)
    polygons = [(stone, [_piece_outline(p, r_in, r_out) for p in stone.pieces]) for stone in stones]
    xs = [x for _, outlines in polygons for outline in outlines for x, _ in outline]
    ys = [y for _, outlines in polygons for outline in outlines for _, y in outline]
    xs.append(-arch.span / 2)
    xs.append(arch.span / 2)
    ys.append(0.0)
    margin = 24
    xmin, xmax, ymin, ymax = min(xs), max(xs), min(ys), max(ys)
    scale = (width - 2 * margin) / (xmax - xmin)
    height = round((ymax - ymin) * scale + 2 * margin)

    def px(x, y):
        return margin + (x - xmin) * scale, margin + (ymax - y) * scale

    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        f"<title>{html.escape(arch.name)}</title>",
        f'<rect width="{width}" height="{height}" fill="#fbfaf7"/>',
    ]
    x0, y0 = px(xmin, 0)
    x1, _ = px(xmax, 0)
    out.append(f'<line x1="{x0:.1f}" y1="{y0:.1f}" x2="{x1:.1f}" y2="{y0:.1f}" stroke="#999" stroke-dasharray="4 3"/>')
    for stone, outlines in polygons:
        fill = "#b5651d" if stone.key else "#d8c3a0"
        for outline in outlines:
            points = " ".join(f"{X:.1f},{Y:.1f}" for X, Y in (px(x, y) for x, y in outline))
            out.append(f'<polygon points="{points}" fill="{fill}" stroke="#3b2f25" stroke-width="1"/>')
        cx, cy, lo, hi = stone.pieces[0]
        mid = (lo + hi) / 2
        radius = (r_in + r_out) / 2
        lx, ly = px(cx + radius * math.cos(mid), cy + radius * math.sin(mid))
        out.append(
            f'<text x="{lx:.1f}" y="{ly + 4:.1f}" font-size="12" text-anchor="middle" fill="#222">'
            f"{html.escape(stone.label)}</text>"
        )
    out.append("</svg>")
    return "\n".join(out) + "\n"


def render_ascii(arch, cols=60):
    arc = geometry(arch)
    r_in = arc.radius
    r_out = r_in + arch.thickness
    stones = layout(arch, arc)
    top = arch.rise + arch.thickness
    half_width = arch.span / 2 + arch.thickness
    rows = max(4, round(cols * top / (2 * half_width) * 0.5))

    def inside(stone, x, y):
        for cx, cy, lo, hi in stone.pieces:
            d = math.hypot(x - cx, y - cy)
            ang = math.atan2(y - cy, x - cx)
            if r_in <= d <= r_out and lo <= ang <= hi:
                return True
        return False

    lines = []
    for r in range(rows):
        y = top * (1 - (r + 0.5) / rows)
        row = []
        for c in range(cols):
            x = -half_width + 2 * half_width * (c + 0.5) / cols
            mark = "."
            for stone in stones:
                if inside(stone, x, y):
                    mark = stone.mark
                    break
            row.append(mark)
        lines.append("".join(row).rstrip())
    lines.append("")
    lines.append("stones numbered from the left springing; K is the keystone; . is void")
    return "\n".join(lines) + "\n"


# -------------------------------------------------------------- reporting

def format_report(a):
    out = [f"Keystone report: {a['name']} ({a['type']})", ""]
    out.append(
        f"  span {a['span_m']:.3f} m   rise {a['rise_m']:.3f} m   "
        f"rise/span {a['rise_ratio']:.3f}   thickness {a['thickness_m']:.3f} m   depth {a['depth_m']:.3f} m"
    )
    out.append(
        f"  intrados radius {a['intrados_radius_m']:.3f} m   extrados radius {a['extrados_radius_m']:.3f} m"
        f"   springing {a['springing_deg']:.2f}°   total sweep {a['sweep_deg']:.2f}°"
    )
    out.append(f"  voussoirs {a['voussoirs']}   density {a['density_kg_m3']:.0f} kg/m³   waste {a['waste_fraction'] * 100:.1f} %")
    out.append("")
    out.append(f"  {'stone':>5}  {'angle°':>7}  {'intrados mm':>11}  {'extrados mm':>11}  {'volume m³':>9}  {'mass kg':>8}")
    for r in a["stones"]:
        out.append(
            f"  {r['label']:>5}  {r['angle_deg']:7.2f}  {r['intrados_m'] * 1000:11.0f}  "
            f"{r['extrados_m'] * 1000:11.0f}  {r['volume_m3']:9.4f}  {r['mass_kg']:8.1f}"
        )
    out.append("")
    out.append(f"  masonry volume {a['total_volume_m3']:.4f} m³   mass {a['total_mass_kg']:.1f} kg")
    out.append(f"  order volume with waste {a['order_volume_m3']:.4f} m³   heaviest stone {a['heaviest_kg']:.1f} kg")
    if a["thrust_kn"] is None:
        out.append("  thrust: no load given (add load = ... kN/m to estimate)")
    else:
        out.append(
            f"  thrust (parabolic estimate) {a['thrust_kn']:.2f} kN per metre of wall "
            f"from load {a['load_kn_m']:.2f} kN/m"
        )
    if a["warnings"]:
        out.append("")
        out.extend(f"  warning: {w}" for w in a["warnings"])
    return "\n".join(out) + "\n"


def _error_line(path, lineno, message):
    return f"{path}:{lineno}: {message}" if lineno else f"{path}: {message}"


def _read(path):
    with open(path, encoding="utf-8") as fh:
        return build_arch(fh.read())


def _report_errors(path, errors):
    for lineno, message in errors:
        print(_error_line(path, lineno, message))
    print(f"{len(errors)} error(s); no geometry computed")
    return 1


# --------------------------------------------------------------- commands

def cmd_check(args):
    arch, errors = _read(args.file)
    if errors:
        return _report_errors(args.file, errors)
    a = analyse(arch)
    for w in a["warnings"]:
        print(f"{args.file}: warning: {w}")
    failures = []
    if args.max_thrust is not None:
        if a["thrust_kn"] is None:
            failures.append("--max-thrust needs a load = ... kN/m line in the spec")
        elif a["thrust_kn"] > args.max_thrust:
            failures.append(f"thrust {a['thrust_kn']:.2f} kN exceeds limit {args.max_thrust:.2f} kN")
    if args.max_stone_mass is not None and a["heaviest_kg"] > args.max_stone_mass:
        failures.append(f"heaviest stone {a['heaviest_kg']:.1f} kg exceeds limit {args.max_stone_mass:.1f} kg")
    if args.strict and a["warnings"]:
        failures.append(f"{len(a['warnings'])} warning(s) with --strict")
    for f in failures:
        print(f"FAIL: {f}")
    if failures:
        return 2
    thrust = "no thrust (no load)" if a["thrust_kn"] is None else f"thrust {a['thrust_kn']:.2f} kN/m"
    print(f"OK: {a['name']}: {a['voussoirs']} voussoirs, {thrust}, {len(a['warnings'])} warning(s)")
    return 0


def cmd_report(args):
    arch, errors = _read(args.file)
    if errors:
        return _report_errors(args.file, errors)
    a = analyse(arch)
    if args.json:
        print(json.dumps(a, indent=2))
    else:
        print(format_report(a), end="")
    return 0


def cmd_draw(args):
    arch, errors = _read(args.file)
    if errors:
        return _report_errors(args.file, errors)
    if args.svg:
        svg = render_svg(arch)
        if args.svg == "-":
            print(svg, end="")
        else:
            with open(args.svg, "w", encoding="utf-8") as fh:
                fh.write(svg)
            print(f"wrote {args.svg}")
    if args.ascii or not args.svg:
        print(render_ascii(arch), end="")
    return 0


def cmd_solve(args):
    arch, errors = _read(args.file)
    if errors:
        return _report_errors(args.file, errors)
    if arch.load is None:
        print(f"{args.file}: solve needs a load = ... kN/m line in the spec")
        return 1
    needed = min_rise_for_thrust(arch.load, arch.span, args.max_thrust)
    ceiling = arch.span * math.sqrt(3) / 2
    print(f"thrust limit {args.max_thrust:.2f} kN/m at load {arch.load:.2f} kN/m, span {arch.span:.3f} m")
    print(f"minimum rise {needed:.4f} m ({needed / arch.span:.3f} of span)")
    if needed > ceiling:
        print(f"unreachable: the highest pointed arch on this span rises {ceiling:.4f} m")
        return 2
    if arch.rise >= needed:
        print(f"the current rise {arch.rise:.4f} m already meets the limit")
    else:
        print(f"current rise {arch.rise:.4f} m is too low by {needed - arch.rise:.4f} m")
    return 0


def build_parser():
    parser = argparse.ArgumentParser(prog="keystone", description="Offline voussoir arch planner.")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("check", help="lint a spec and gate on thrust or stone mass")
    p.add_argument("file")
    p.add_argument("--max-thrust", type=float, metavar="KN", help="fail (exit 2) above this thrust per metre")
    p.add_argument("--max-stone-mass", type=float, metavar="KG", help="fail (exit 2) above this heaviest stone")
    p.add_argument("--strict", action="store_true", help="treat warnings as failures (exit 2)")
    p.set_defaults(func=cmd_check)

    p = sub.add_parser("report", help="print geometry, cut table and totals")
    p.add_argument("file")
    p.add_argument("--json", action="store_true", help="print the report as JSON")
    p.set_defaults(func=cmd_report)

    p = sub.add_parser("draw", help="draw the arch as ASCII and/or SVG")
    p.add_argument("file")
    p.add_argument("--svg", metavar="PATH", help="write an SVG drawing to PATH ('-' for stdout)")
    p.add_argument("--ascii", action="store_true", help="also print the ASCII drawing")
    p.set_defaults(func=cmd_draw)

    p = sub.add_parser("solve", help="find the minimum rise that meets a thrust limit")
    p.add_argument("file")
    p.add_argument("--max-thrust", type=float, required=True, metavar="KN")
    p.set_defaults(func=cmd_solve)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except OSError as exc:
        print(f"keystone: cannot read {args.file}: {exc.strerror}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
