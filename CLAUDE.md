# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

LibrePCB project for kbdkid4, a split wireless keyboard. The `.lp` S-expression files (`circuit/`, `schematics/`, `boards/`, `library/`, `project/`) are written by the LibrePCB application; design changes happen through the LibrePCB GUI, not by hand-editing those files. The only hand-written code lives in `scripts/`.

`output/v1/` contains committed generated outputs (gerbers, BOM, PDFs, STEP model of the assembled board). They are produced by the output jobs defined in `project/jobs.lp`, run from the LibrePCB GUI or by librepcb-cli.

## Tray export

`scripts/export_tray.py` builds a 3D-printable tray STL from the board's STEP model, running FreeCAD headless in a container (`scripts/freecad.Dockerfile`, Debian trixie's FreeCAD 1.0). Locally this machine has podman, not docker:

    podman build -t freecad-headless -f scripts/freecad.Dockerfile scripts
    podman run --rm -v "$PWD":/work -w /work freecad-headless \
        freecadcmd scripts/export_tray.py --pass output/v1/kbdkid4_v1.step tmp/tray.stl [key=value ...] [flip]

Parameters and their defaults live in the constants block at the top of the script; the usage header lists the key=value override names.

The script locates the board without hardcoded face indices: by the `PCB` assembly label (a constant in LibrePCB's `stepexport.cpp`), validated geometrically, with a geometry-only fallback. Its module docstring documents the freecadcmd quirks that shaped it (exit codes swallowed, `__name__` set to the file stem, scripts run twice, dash-arguments intercepted even after `--pass`, hence the `key=value` argument style and `os._exit`). Read that docstring before writing any new FreeCAD script here.

The STL's Z orientation is not critical: the tray is mirrored in the slicer anyway, since the split keyboard needs both mirrored halves.

## CI

`.github/workflows/ci.yml` has two jobs: `outputs` runs the `Tubbles/librepcb-ci@v1` action (regenerates all output jobs with librepcb-cli, uploads them as the `librepcb-ci-outputs` artifact, publishes browsable outputs to GitHub Pages; ERC/DRC checks are non-fatal), and `tray` downloads that artifact, builds the FreeCAD image, runs the tray export on every generated `.step`, and uploads the result as the `tray-stl` artifact.

## Conventions

- `tmp/` is untracked scratch space; `work/` holds design notes and is not committed.
- Test any change to `scripts/export_tray.py` by running it in the container against `output/v1/kbdkid4_v1.step` and checking the exit code; freecadcmd hides Python failures unless the script exits via `os._exit`.
