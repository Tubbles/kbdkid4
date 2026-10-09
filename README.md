# kbdkid4

## Description

kbdkid4 is a split wireless keyboard, designed in [LibrePCB](https://librepcb.org).

Generated outputs (gerbers, BOM, schematic and assembly PDFs, STEP model) live in `output/v1/` and are also rebuilt by CI on every push, which publishes them as workflow artifacts and to [GitHub Pages](https://tubbles.github.io/kbdkid4/).

## 3D printed tray

`scripts/export_tray.py` builds a 3D-printable tray for the board from the exported STEP model, running FreeCAD headless. The board outline is located automatically (no hardcoded face indices); see the script's docstring for how and for the tray parameters.

    docker build -t freecad-headless -f scripts/freecad.Dockerfile scripts
    docker run --rm -v "$PWD":/work -w /work freecad-headless \
        freecadcmd scripts/export_tray.py --pass output/v1/kbdkid4_v1.step tray.stl [key=value ...] [flip]

The parameters (gap, wall, floor, depth, standoff and ledge dimensions) and their defaults are listed in the script's usage header and constants block.

`scripts/export_plate.py` likewise exports the switch plate: the kbdkid3 plate model (`resources/kbdkid3-plate-left.FCStd`), aligned onto the board by matching its switch cutouts to the board's switch grid, trimmed at the outer edges to fit the tray, extended over the microcontroller corner so it covers the whole board (with a conical recess on the underside at every soldered lead, 0.2 mm short of the top face, and a hole for the reset button), and cut with head-sized clearance holes at the board's mounting drills: the screws clamp the PCB onto the standoffs, the plate sits over their heads and is held down by the switches. The plate STL is written upside down (top face on the bed, lead recesses opening upward) so it prints as is without supports. CI exports both halves as the `plate-stl` artifact: `_Plate_Left.stl`, and `_Plate_Right.stl` mirrored across the board's center line (the word `right`).

CI runs this against the freshly generated STEP and uploads the result as the `tray-stl` workflow artifact.

CI exports both halves as the `tray-stl` artifact: `_Tray_Left.stl` as described, and `_Tray_Right.stl` built with the board's other side up (the word `right`), where the right half's switches and hotswap sockets sit, then turned over so it prints opening-up. That is not a mirror of the left tray: the right half's sockets do not reach the board edge, so that tray has no ledge notches.

## 3D printed PCB replica

`scripts/export_pcb.py` exports a printable stand-in for the bare board, for test-fitting the tray, plate, switches and screws before the fabricated boards arrive: the outline extruded to the board thickness with every drill hole, no components. Printed parts come out slightly larger than modelled, so the replica is pulled in by `pull_in` (default 0.2 mm) per side: the outline moves inward and every hole grows outward by that much. The thickness stays as modelled unless overridden with `thickness=`.

    docker run --rm -v "$PWD":/work -w /work freecad-headless \
        freecadcmd scripts/export_pcb.py --pass output/v1/kbdkid4_v1.step pcb.stl [pull_in=0.2] [thickness=1.6]

CI uploads it as the `pcb-stl` artifact. One file serves both halves: the bare board's mirror image is the board itself turned over.

## License

See [LICENSE.txt](LICENSE.txt).
