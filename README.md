# Keystone

**Offline voussoir arch planner: plain-text arch specs in, exact geometry, cut angles, stone masses, thrust estimates, drawings and CI gates out.**

Keystone takes one short text file describing a masonry arch (semicircle, segmental or pointed), works out the intrados and extrados curves, splits the ring into equal-angle voussoirs with a keystone or crown joint, and tells you what each stone weighs, how much to order, roughly how hard the arch pushes on its abutments, and whether the spec is sound. It is a single Python file using only the standard library, with no network access, no accounts and no API keys.

## Features

- **Three arch forms**: semicircle, segmental (from span and rise) and pointed (equilateral, each half struck from the opposite springing).
- **Exact input units**: lengths in `mm`, `cm`, `m`, `in` or `ft` are read as exact fractions before any trigonometry, so `1 in` is exactly 0.0254 m.
- **Line-numbered spec errors**: unknown keys, duplicate keys, bad units and impossible geometry all point at `file:line`.
- **Derived geometry**: intrados and extrados radii, springing angle, total sweep, and a check that the ring is thinner than its intrados radius.
- **Voussoir layout**: equal-angle stones from the left springing to the right, with a centred keystone for odd counts or a crown joint for even counts.
- **Cut table**: per-stone subtended angle, intrados and extrados face widths, volume and mass.
- **Order quantities**: total masonry volume, a waste-adjusted order volume, and the heaviest stone for handling checks.
- **Thrust estimate**: parabolic approximation `H = q·s² / (8·h)` from a line load you give in kN/m.
- **Minimum-rise solver**: the lowest rise that keeps thrust under a limit, and a clear "unreachable" answer when no arch of that type can do it.
- **Lint warnings**: flat arches (rise under a fifth of the span), thin rings (under 1/20 of span), and stones wider than your `max_stone`.
- **CI gates**: `check` exits 2 when thrust, heaviest stone mass or (with `--strict`) any warning breaks your limit.
- **Reports in two shapes**: a readable text report, or `report --json` for other tools.
- **Drawings**: an ASCII plan with numbered stones in your terminal, and an SVG file with labelled voussoirs, keystone shaded differently.

## Quick start

Keystone needs Python 3.10 or newer. There is nothing to install.

Save this as `chapel-doorway.arch`, or use the copy in `examples/`:

```text
# Chapel doorway: segmental stone arch
name = Chapel doorway
type = segmental
span = 2.4 m
rise = 0.9 m
thickness = 0.30 m
voussoirs = 9
depth = 0.25 m
density = 2300 kg/m3
waste = 5 %
load = 12 kN/m
max_stone = 0.6 m
```

Then run:

```sh
python3 keystone.py report examples/chapel-doorway.arch
```

For this spec the intrados radius is 1.25 m, the springing sits at about 16.3° above horizontal, and the nine stones each subtend about 16.4°. Each stone has an intrados face near 357 mm and an extrados face near 443 mm, so all stones pass the 600 mm `max_stone` limit. Each stone is roughly 0.030 m³ and 69 kg, the masonry totals about 0.270 m³ (about 622 kg), and the thrust estimate is 9.60 kN per metre of wall.

Draw it in the terminal and as an SVG file:

```sh
python3 keystone.py draw examples/chapel-doorway.arch --ascii
python3 keystone.py draw examples/chapel-doorway.arch --svg chapel.svg
```

Gate it in CI, failing if thrust exceeds 8 kN per metre or any stone is heavier than 80 kg:

```sh
python3 keystone.py check examples/chapel-doorway.arch --max-thrust 8 --max-stone-mass 80
echo $?   # 2 means a gate failed; 1 means the spec has errors
```

Find the least rise that brings thrust under 8 kN per metre:

```sh
python3 keystone.py solve examples/chapel-doorway.arch --max-thrust 8
```

## Commands

| Command | What it does |
| --- | --- |
| `check FILE [--max-thrust KN] [--max-stone-mass KG] [--strict]` | Lint and gate. Exit 0 pass, 1 spec errors, 2 gate failed. |
| `report FILE [--json]` | Print the geometry, cut table, totals, thrust and warnings. |
| `draw FILE [--svg PATH] [--ascii]` | ASCII plan by default. `--svg -` writes SVG to stdout. |
| `solve FILE --max-thrust KN` | Minimum rise for the thrust limit. Exit 2 if no arch of this kind can reach it. |

Errors from any command look like this:

```text
arch.arch:4: rise: a pointed arch has rise 1.7321 m; remove the line or match it
```

## Spec format

One `key = value` pair per line. Blank lines are ignored, and `#` starts a comment.

| Key | Required | Form | Notes |
| --- | --- | --- | --- |
| `name` | no | text | Shown in reports. |
| `type` | yes | `semicircle`, `segmental`, `pointed` | |
| `span` | yes | `2.4 m`, `300 mm`, `12 in`, `8 ft` | Clear span between springings. |
| `rise` | segmental only | length | Must be above 0 and below span/2. For other types it is derived; give it only if it matches. |
| `thickness` | yes | length | Radial depth of the ring. Must be less than the intrados radius. |
| `voussoirs` | yes | whole number ≥ 3 | Odd gives a keystone, even gives a crown joint. |
| `depth` | yes | length | Stone depth along the wall. |
| `density` | no | `2300 kg/m3` | Default 2300. |
| `waste` | no | `5 %` | Cutting allowance applied to the order volume. Default 0. |
| `load` | no | `12 kN/m` | Needed for thrust, `check --max-thrust` and `solve`. |
| `max_stone` | no | length | Widest allowed extrados face. Default 0.6 m. |

## Method and limits

- Stones are equal-angle voussoirs with radial joints, the usual layout for a first design. Joints are not optimised to a thrust line.
- Volumes are exact annular-sector volumes, `depth × (R_out² − R_in²) / 2 × angle`.
- Angles come from floating-point trigonometry. Expect results accurate to well under a millimetre at building scale.
- Thrust uses the parabolic approximation `H = q·s² / (8·h)`. It is a quick estimate for planning and is not a substitute for a thrust-line analysis. Flat and pointed arches can differ noticeably from it.
- The thin-ring and flat-arch rules are rules of thumb for early checks, not code requirements.
- Pointed arches have a cusp where the two extrados arcs meet above the crown. The keystone is cut on the intrados crown ray, so the SVG drawing and keystone volume leave that small cusp out.
- Keystone does not check bearing, abutment mass, mortar, or local building codes.

## Testing

```sh
python3 -m pip install pytest
python3 -m pytest tests/
```

The tests cover unit parsing, exact length conversion, line-numbered errors, the geometry of all three arch forms, the keystone and crown-joint layouts, stone angle totals, the annular volume identity, waste, thrust and the minimum-rise solver, lint warnings, SVG well-formedness, ASCII output, and the CLI exit codes and JSON output.

## Project layout

```text
keystone.py                  the whole tool: parser, geometry, layout, reports, drawings, CLI
examples/chapel-doorway.arch an example spec
tests/test_keystone.py       pytest suite
```

## Licence

Choose a licence before publishing. This repository does not yet include one.
