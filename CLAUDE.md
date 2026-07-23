# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

LibrePCB project for kbdkid4, a split wireless keyboard. The `.lp` S-expression files (`circuit/`, `schematics/`, `boards/`, `library/`, `project/`) are written by the LibrePCB application; design changes happen through the LibrePCB GUI, not by hand-editing those files. The only hand-written code lives in `scripts/`.

`output/v1/` contains committed generated outputs (gerbers, BOM, PDFs, STEP model of the assembled board). They are produced by the output jobs defined in `project/jobs.lp`, run from the LibrePCB GUI or by librepcb-cli.

## Tray export

`scripts/export_tray.py` builds a 3D-printable tray STL from the board's STEP model, with bored standoffs for M2 heat-set inserts at the board's mounting drills, running FreeCAD headless in a container (`scripts/freecad.Dockerfile`, Debian trixie's FreeCAD 1.0). Locally this machine has podman, not docker:

    podman build -t freecad-headless -f scripts/freecad.Dockerfile scripts
    podman run --rm -v "$PWD":/work -w /work freecad-headless \
        freecadcmd scripts/export_tray.py --pass output/v1/kbdkid4_v1.step tmp/tray.stl [key=value ...] [flip]

Parameters and their defaults live in the constants block at the top of the script; the usage header lists the key=value override names.

`scripts/export_plate.py` exports the switch plate the same way: the kbdkid3 plate model (`resources/kbdkid3-plate-left.FCStd`, a parametric switch cell replicated by a point array, with a mirrored right plate that is not exported) drilled with through holes at the board's mounting drills.

Shared machinery lives in `scripts/board_step.py`: locating the board without hardcoded face indices (by the `PCB` assembly label, a constant in LibrePCB's `stepexport.cpp`, validated geometrically, with a geometry-only fallback), mounting drill detection, and the freecadcmd scaffolding. Its module docstring documents the freecadcmd quirks (exit codes swallowed, `__name__` set to the file stem, scripts run twice, dash-arguments intercepted even after `--pass`, hence the `key=value` argument style and `os._exit`). Read that docstring before writing any new FreeCAD script here.

The STL's Z orientation is not critical: the tray is mirrored in the slicer anyway, since the split keyboard needs both mirrored halves.

## CI

`.github/workflows/ci.yml` has two jobs: `outputs` runs the `Tubbles/librepcb-ci@v1` action (regenerates all output jobs with librepcb-cli, uploads them as the `librepcb-ci-outputs` artifact, publishes browsable outputs to GitHub Pages; ERC/DRC checks are non-fatal), and `tray` downloads that artifact, builds the FreeCAD image, runs the tray and plate exports on every generated `.step`, and uploads the results as the `tray-stl` and `plate-stl` artifacts.

## Conventions

- Commit and push completed changes without asking. Keep commits small and focused.
- `tmp/` is untracked scratch space; `work/` holds design notes and is not committed.
- Test any change to the export scripts by running them in the container against `output/v1/kbdkid4_v1.step` and checking the exit code; freecadcmd hides Python failures unless the script exits via `os._exit`.
- `boards/default/board.lp` is the design ground truth (outline polygon vertices, board-level mounting drills). Cross-check what the script detects from the STEP against it rather than trusting either alone.
- To inspect geometry beyond the exit code: `board_step.py` can be imported normally (put `scripts/` on `sys.path`), but the export scripts must be exec'd with their trailing `run_and_exit(main)` line stripped and `__file__` predefined (a plain import would run main and `os._exit` the interpreter). Then drive their functions directly: census cylinder-face radii, sample wall thickness with `distToShape`, compare volumes against analytic values.
