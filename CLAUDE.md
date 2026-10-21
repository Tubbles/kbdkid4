# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository. README.md has what is of interest to humans as well, and this file does not repeat it.

## What this is

LibrePCB project for kbdkid4, a split wireless keyboard. The `.lp` S-expression files (`circuit/`, `schematics/`, `boards/`, `library/`, `project/`) are written by the LibrePCB application. The GUI is still the natural way to do interactive design work, but these files can also be edited directly (see below).

The outputs in `output/v1/` (README.md) are produced by the output jobs defined in `project/jobs.lp`, run from the LibrePCB GUI or by librepcb-cli.

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

## CI

`.github/workflows/ci.yml` has one job, `outputs`, which runs the `Tubbles/librepcb-ci@v1` action. It regenerates all output jobs with librepcb-cli and uploads them as the `librepcb-ci-outputs` artifact. Its ERC and DRC checks are non-fatal.

## What model-workshop reads from here

Model work for this keyboard goes to model-workshop (README.md), never here. Its kbdkid4 jobs look up this repository's latest successful run of `ci.yml` on main, take the STEP from that run's `librepcb-ci-outputs` artifact (`kbdkid4/kbdkid4_v1.step` inside it), and read `boards/boards.lp`, the default board it lists and `circuit/circuit.lp` from a checkout of that run's commit. The STEP's name comes from the STEP Model job's output in `project/jobs.lp` (`{{PROJECT}}_{{VERSION}}.step`) with the name and version in `project/metadata.lp`, so a new version renames it. Renaming `ci.yml` or the `librepcb-ci-outputs` artifact (named by the `Tubbles/librepcb-ci` action), changing the STEP's name, or moving `boards/boards.lp` or `circuit/circuit.lp` means updating model-workshop too. A board directory can be renamed freely, since the default board is found through `boards/boards.lp`. A push here does not run model-workshop's CI: run its workflow by hand once this repository's run has passed. GitHub deletes artifacts after its retention period, so after a long quiet spell rerun this repository's CI first.

## Conventions

- Commit and push completed changes without asking. Keep commits small and focused.
- After `fmt -w 72` on a commit message, put the `Assisted-by:` and `Claude-Session:` trailers back on lines of their own: fmt joins them into one paragraph, which breaks git's trailer parsing. Leave the `Claude-Session:` line out of the width check, since its URL alone is over 72 columns.
- Tools come through a container image (librepcb-cli above), never a downloaded AppImage. The user, 2026-07-22: "why did you download an app image? just do a dockerfile directly or something".
- Never quote a PDF from a WebFetch summary. On 2026-07-26 WebFetch returned a sentence that does not exist in the PDF it summarized. Download with `curl -L -o` and quote from `pdftotext -layout` output, or read the pages as images for drawings.
- What an agent learns here goes into this repository's docs (this file for agents, README.md for humans), not into an agent's local memory. The user, 2026-10-21: "Make sure that stuff you put in "local memories" that are of any importance are put into the repos CLAUDE.md, as appropriate."
- `tmp/` is untracked scratch space; `work/` holds design notes and is not committed.
- The default board file (the first entry in `boards/boards.lp`, currently `boards/board_1.1/board.lp`) is the design ground truth (outline polygon vertices, mounting drills). The STEP Model job in `project/jobs.lp` exports that board (`(board default)`).
