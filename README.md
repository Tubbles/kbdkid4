# kbdkid4

## Description

kbdkid4 is a split wireless keyboard, designed in [LibrePCB](https://librepcb.org).

Generated outputs (gerbers, BOM, schematic and assembly PDFs, STEP model) live in `output/v1/` and are also rebuilt by CI on every push, which publishes them as workflow artifacts and to GitHub Pages.

## 3D printed tray

`scripts/export_tray.py` builds a 3D-printable tray for the board from the exported STEP model, running FreeCAD headless. The board outline is located automatically (no hardcoded face indices); see the script's docstring for how and for the tray parameters.

    docker build -t freecad-headless -f scripts/freecad.Dockerfile scripts
    docker run --rm -v "$PWD":/work -w /work freecad-headless \
        freecadcmd scripts/export_tray.py --pass output/v1/kbdkid4_v1.step tray.stl [key=value ...] [flip]

The parameters (gap, wall, floor, depth, standoff and ledge dimensions) and their defaults are listed in the script's usage header and constants block.

`scripts/export_plate.py` likewise exports the switch plate: the kbdkid3 plate model (`resources/kbdkid3-plate-left.FCStd`) drilled with through holes at the board's mounting drills. Only the left plate is exported; both it and the tray get mirrored in the slicer for the other keyboard half. CI uploads it as the `plate-stl` artifact.

CI runs this against the freshly generated STEP and uploads the result as the `tray-stl` workflow artifact.

The STL's orientation is not critical: the tray gets mirrored in the slicer anyway, since the split keyboard needs both mirrored halves.

## License

See [LICENSE.txt](LICENSE.txt).
