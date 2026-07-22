# kbdkid4

## Description

This is a [LibrePCB](https://librepcb.org) project!
Just edit this file to add a description about it.

## 3D printed tray

`scripts/export_tray.py` builds a 3D-printable tray for the board from the exported STEP model, running FreeCAD headless. The board outline is located automatically (no hardcoded face indices); see the script's docstring for how and for the tray parameters.

    docker build -t freecad-headless -f scripts/freecad.Dockerfile scripts
    docker run --rm -v "$PWD":/work -w /work freecad-headless \
        freecadcmd scripts/export_tray.py --pass output/v1/kbdkid4_v1.step tray.stl [gap=0.8] [wall=0.4] [floor=0.6] [height=10.0] [flip]

CI runs this against the freshly generated STEP and uploads the result as the `tray-stl` workflow artifact.

The STL's orientation is not critical: the tray gets mirrored in the slicer anyway, since the split keyboard needs both mirrored halves.

## License

See [LICENSE.txt](LICENSE.txt).
