# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

LibrePCB project for kbdkid4, a split wireless keyboard. The `.lp` S-expression files (`circuit/`, `schematics/`, `boards/`, `library/`, `project/`) are written by the LibrePCB application. The GUI is still the natural way to do interactive design work, but these files can also be edited directly (see below). The only hand-written code lives in `scripts/`.

`output/v1/` contains committed generated outputs (gerbers, BOM, PDFs, STEP model of the assembled board). They are produced by the output jobs defined in `project/jobs.lp`, run from the LibrePCB GUI or by librepcb-cli.

## Editing the `.lp` files directly

The `librepcb` skill (`~/.claude/skills/librepcb/`) carries the file format reference and a toolkit whose serializer is a port of LibrePCB's own, verified byte-exact against LibrePCB's test data. Use it rather than editing `.lp` files with a text editor or a generic S-expression library: line breaks are nodes in the tree, indentation is significant, and project-level collections are written sorted by UUID, so a naive edit reflows the file or lands a node in the wrong place.

The workflow, on a clean git tree:

    LP=~/.claude/skills/librepcb/tools/lp.py
    python3 $LP get boards/board_1.1/board.lp 'device[@0=<uuid>]/position'
    python3 $LP set boards/board_1.1/board.lp 'device[@0=<uuid>]/position/@1' 41.0
    podman run --rm -v "$PWD":/work -w /work docker.io/librepcb/librepcb-cli:2.1.1 \
        open-project --strict --erc --drc kbdkid4.lpp

`--strict` fails unless the files are exactly what LibrePCB itself would write, so it is the authority on whether an edit is correct. Treat a failure as a wrong edit, not a LibrePCB quirk. `lp.py diff` gives a structural diff keyed by UUID, which is far more readable than `git diff` on `board.lp`.

Changes that span several files (adding or removing a component instance, placing it on the board, creating or deleting a net) go through `tools/lpedit.py` in that skill, which does the whole operation and writes nothing if any part of it fails. `tools/lpsch.py` draws schematic wires and `tools/lpbrd.py` routes copper, both addressing terminals by name (`D110.A`, `JP12.2`). `lpedit.py check` verifies that every cross-file UUID reference still resolves, which is the layer below ERC and the thing a half-finished hand edit breaks.

`tools/lplib.py` authors library elements (symbols, packages, components, devices) in `library/`, including the pin and pad to signal maps, which it can fill in by matching names.

Those tools are exact about connectivity and geometry but know nothing about where copper should go: no autorouting, no collision avoidance. Plan the path, then let DRC judge it. When DRC does complain, `lpbrd.py clearance --net <name>` measures the geometry and gives coordinates, which the DRC output itself does not.

For layout decisions themselves (stackup, placement, trace widths, impedance, EMC), the `pcb-design` skill has the engineering reference and a calculator.

## Tray export

`scripts/export_tray.py` builds a 3D-printable tray STL from the board's STEP model, with bored standoffs for M2 heat-set inserts at the board's mounting drills, running FreeCAD headless in a container (`scripts/freecad.Dockerfile`, Debian trixie's FreeCAD 1.0). Locally this machine has podman, not docker:

    podman build -t freecad-headless -f scripts/freecad.Dockerfile scripts
    podman run --rm -v "$PWD":/work -w /work freecad-headless \
        freecadcmd scripts/export_tray.py --pass output/v1/kbdkid4_v1.step tmp/tray.stl [key=value ...] [flip]

Parameters and their defaults live in the constants block at the top of the script (gap, wall, floor, depth and standoff height in `scripts/tray_shape.py`); the usage header lists the key=value override names.

`scripts/export_plate.py` exports the switch plate the same way: the kbdkid3 plate model (`resources/kbdkid3-plate-left.FCStd`, a parametric switch cell replicated by a point array, with a mirrored right plate that is not exported) cut with clearance holes for the screw heads at the board's mounting drills (the screws clamp the PCB, the switches hold the plate). The kbdkid3 plate does not share the kbdkid4 board's origin; the script aligns it by matching the plate's cutout centers against the switch positions parsed from `board.lp` and `circuit.lp`, accepting only a pure translation. The plate then extends over the switch-less microcontroller corner, with frustum recesses on its underside at every lead drill found in the STEP but the nice!view header's five (DS1, not fitted for now), stopping 0.4 mm short of the top face (the through-hole parts sit on the board's underside, their leads stick up), and for the reset switch (pressed with a SIM ejector pin) a 3.0 mm pin hole with a 1.0 mm deep pocket in the underside over the switch body and pads, checked to stay clear of the lead recesses; the corner's inner boundaries and its north edge are read off the plate silhouette (it stays flush with the switch cells beside it), its east edge off the board outline. Last, the whole hole pattern is shifted `pattern_shift` mm along +X with the outline held in place (0.25 mm by default, an empirical correction for a drift seen on printed plates whose cause is not yet found; see SUGGESTIONS.md), by translating the plate, clipping it solid by solid back to the original silhouette and filling the strips that open on the trailing edges. A `common()` of the whole compound silently drops a cell on FreeCAD 1.0, hence solid by solid. Then `side_shave` mm (0.1 by default) is clipped off the plate's west and east extremes, nothing off north and south. The word `covered` makes the variant without the hard-to-reach key S123 (bottom row, third from the left): before the pattern shift, its cell solid is replaced by a full-thickness prism of the cell's outline, so the cutout is filled in solid while the outline and the contact with the neighbouring cells stay as they are, and a rectangular pit for its diode D123 (measured 1.14 mm tall) is cut 1.6 mm deep into the underside, leaving three print layers over it, since a single 0.2 mm print layer showed through, as it did over the lead recesses. The right half gets the cover through the mirror, after a check that flipped parts sit at exactly the same board positions there (S243, D243). Right before export the solids are fused into one, checked to be a single valid solid of unchanged volume, and the mesh is checked to be closed, manifold and free of self-intersections, so the STL has no internal walls.

`scripts/export_pcb.py` exports a printable replica of the bare board for test-fitting before the fabricated boards arrive: the board's outline face from the STEP, outline moved inward and every drill hole moved outward by `pull_in` (default 0.2 mm, the expected print swelling per side), extruded to the board thickness. FreeCAD's `makeOffset2D` on the whole face would shrink the holes along with the outline, which is why the script offsets the outer wire and each hole wire separately.

`scripts/export_spool_axle.py` has nothing to do with the keyboard: it exports the axle of a solder spool holder (a 19 x 39.5 mm body with a 7.9 x 2.6 mm stub on each end for the cradle), built from Part primitives with no STEP input. A groove in the body takes the rim inside the spool's bore at one face, so the spool lies flat. Its position assumes the rim flush with that face of a 27 mm spool centered on the body (`SPOOL_RIM_CENTER_FROM_FACE_MM`). The script checks the solid's volume against the analytic value, rounded edges included.

Shared machinery lives in `scripts/board_step.py`: locating the board without hardcoded face indices (by the `PCB` assembly label, a constant in LibrePCB's `stepexport.cpp`, validated geometrically, with a geometry-only fallback), mounting drill detection, STL export with a check that the written mesh is one closed, manifold shell, and the freecadcmd scaffolding. Its module docstring documents the freecadcmd quirks (exit codes swallowed, `__name__` set to the file stem, scripts run twice, dash-arguments intercepted even after `--pass`, hence the `key=value` argument style and `os._exit`). Read that docstring before writing any new FreeCAD script here. `scripts/tray_shape.py` holds what the tray export shares with the coming case export: the outline helpers the tray's walls are built from (sharp-corner rebuild, uniform corner fillets), the tray's corner radius, its dimension defaults (gap, wall, floor, depth, standoff height) and where the power switch and USB windows sit along the wall and above the floor.

Both halves are exported. The right tray is not a mirror of the left: it is built with the board's other side up (the `right` word), where the right half's switches and sockets are, and turned over afterwards for printing, so it carries no ledge notches (only the left half's sockets reach the ledge); its ledge reliefs (cut beside any underside body within `relief_clearance` of the ledge: the nano, at that half's measured socket height, the socket bodies and the battery connector) follow that half's parts. Behind the left tray's ledge notches the wall's inner face is pocketed so the socket tab tips keep `LEDGE_NOTCH_CLEARANCE_MM` from it, and on both trays a standoff gets a vertical flat facing any of those bodies that comes within `STANDOFF_RELIEF_CLEARANCE_MM` of it. Both USB windows are the 10.5 x 4.5 mm window measured on the soldered left half, with rounded corners and chamfered faces. The right one sits 1.74 mm lower, since that half's nano is on 4.3 mm sockets instead of the left's 2.56 mm. The right plate and the right PCB replica are the left ones mirrored (a printed replica is not its own mirror image the way a bare board is, since the bed side and the top side print differently).

## CI

`.github/workflows/ci.yml` has two jobs: `outputs` runs the `Tubbles/librepcb-ci@v1` action (regenerates all output jobs with librepcb-cli, uploads them as the `librepcb-ci-outputs` artifact, publishes browsable outputs to GitHub Pages; ERC/DRC checks are non-fatal), and `tray` downloads that artifact, builds the FreeCAD image, runs the tray, plate and PCB replica exports for both halves on every generated `.step` and the solder spool axle export (which needs no STEP), and uploads the results as the `tray-stl` (`_Tray_Left`, `_Tray_Right`), `plate-stl` (`_Plate_Left`, `_Plate_Right`, `_Plate_Left_Covered`, `_Plate_Right_Covered`), `pcb-stl` (`_Pcb_Left`, `_Pcb_Right`) and `spool-stl` (`Solder_Spool_Axle.stl`) artifacts.

## Conventions

- Commit and push completed changes without asking. Keep commits small and focused.
- `tmp/` is untracked scratch space; `work/` holds design notes and is not committed.
- Test any change to the export scripts by running them in the container against `output/v1/kbdkid4_v1.step` and checking the exit code; freecadcmd hides Python failures unless the script exits via `os._exit`.
- The default board file (the first entry in `boards/boards.lp`, currently `boards/board_1.1/board.lp`) is the design ground truth (outline polygon vertices, mounting drills). Cross-check what the script detects from the STEP against it rather than trusting either alone. The scripts resolve it through `boards/boards.lp`, so renaming a board directory needs no script change.
- To inspect geometry beyond the exit code: `board_step.py` and `tray_shape.py` can be imported normally (put `scripts/` on `sys.path`), but the export scripts must be exec'd with their trailing `run_and_exit(main)` line stripped and `__file__` predefined (a plain import would run main and `os._exit` the interpreter). Then drive their functions directly: census cylinder-face radii, sample wall thickness with `distToShape`, compare volumes against analytic values.
- LibrePCB's populated STEP export (a temporary jobs file with `(variant default)`, see `tmp/jobs_step_populated.lp`) imports as one `App::Part` per component, the switch package (two 3D models) with a second container nested inside. `Part.getShape` on a component's container returned those switch bodies unplaced in x and y while single-level components came out right; walking each container's tree and multiplying the ancestor placements onto every `Part::Feature` shape places everything correctly.
