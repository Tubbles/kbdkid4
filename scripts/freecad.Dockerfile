# Headless FreeCAD for scripts/export_tray.py, used both locally and in CI:
#
#     docker build -t freecad-headless -f scripts/freecad.Dockerfile scripts
#     docker run --rm -v "$PWD":/work -w /work freecad-headless \
#         freecadcmd scripts/export_tray.py --pass <pcb.step> <tray.stl>
#
# Debian trixie ships FreeCAD 1.x; freecad-python3 is the GUI-less subset
# that provides /usr/bin/freecadcmd.
FROM debian:trixie-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends freecad-python3 \
    && rm -rf /var/lib/apt/lists/*
