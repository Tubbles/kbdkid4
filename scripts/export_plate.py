"""Export the 3D-printable switch plate (STL) with mounting screw holes.

The plate model is reused from kbdkid3: a parametric switch cell
replicated by a point array into the left plate, with a mirrored right
plate alongside in the same document. Only the left plate is exported;
the right half is mirrored in the slicer, like the tray.

Plain through holes for the mounting screws are drilled where the
board has its mounting drills, detected in the kbdkid4 STEP exactly
like the tray places its standoffs, so the plate holes always track
the PCB. The printout reports how much plate material surrounds each
hole; one position sits at a switch cutout edge of the reused plate,
so partial support there is expected, not an error.

Runs headless under FreeCAD's console interpreter (see board_step.py
for the freecadcmd quirks that shape the invocation):

    freecadcmd scripts/export_plate.py --pass <pcb.step> <plate.fcstd> <plate.stl> \
        [key=value ...]
"""

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import FreeCAD as App
import Part

from board_step import (
    MOUNTING_HOLE_DIAMETER_MM,
    export_stl,
    find_board,
    import_assembly,
    mounting_hole_centers,
    pick_resting_face,
    run_and_exit,
    script_arguments,
)

# The left plate object inside the FCStd document (the right plate is
# its mirror and is not exported).
PLATE_OBJECT_NAME = "PointArray"

# For the variant where the screws clamp the PCB and the plate goes on
# top of them, the holes must swallow the screw heads instead.
SCREW_HEAD_DIAMETER_MM = 3.77  # measured
SCREW_HEAD_CLEARANCE_MM = 0.4  # extra so a printed hole clears the head

# A hole whose rim has less than this much plate material around it
# indicates the plate and board frames do not line up.
MINIMUM_HOLE_SUPPORT = 0.5

USAGE = f"""\
usage: freecadcmd scripts/export_plate.py --pass <pcb.step> <plate.fcstd>
           <plate.stl> [heads] [hole_diameter={MOUNTING_HOLE_DIAMETER_MM}]

  heads          drill for the screw heads instead of the threads, for
                 the stack where the screws clamp the PCB and the plate
                 sits above them ({SCREW_HEAD_DIAMETER_MM} + \
{SCREW_HEAD_CLEARANCE_MM} mm)
  hole_diameter  drill for the mounting screws, mm\
"""


class Arguments:
    def __init__(self):
        self.step_file = None
        self.fcstd_file = None
        self.stl_file = None
        self.hole_diameter = MOUNTING_HOLE_DIAMETER_MM


def parse_arguments(argument_list):
    arguments = Arguments()
    positionals = []
    for argument in argument_list:
        if argument == "heads":
            arguments.hole_diameter = (
                SCREW_HEAD_DIAMETER_MM + SCREW_HEAD_CLEARANCE_MM
            )
        elif "=" in argument:
            key, _, value = argument.partition("=")
            if key != "hole_diameter":
                raise SystemExit(f"error: unknown option '{key}'\n{USAGE}")
            try:
                arguments.hole_diameter = float(value)
            except ValueError:
                raise SystemExit(f"error: '{key}' needs a number, got '{value}'")
        else:
            positionals.append(argument)
    if len(positionals) != 3:
        raise SystemExit(USAGE)
    arguments.step_file, arguments.fcstd_file, arguments.stl_file = positionals
    return arguments


def load_plate(fcstd_file):
    document = App.openDocument(fcstd_file)
    plate_object = document.getObject(PLATE_OBJECT_NAME)
    if plate_object is None:
        raise SystemExit(
            f"error: no '{PLATE_OBJECT_NAME}' object in {fcstd_file}"
        )
    shape = Part.getShape(plate_object)
    if shape.isNull() or not shape.Solids:
        raise SystemExit(f"error: '{PLATE_OBJECT_NAME}' has no solid geometry")
    return shape


def drill_holes(plate, hole_centers, hole_diameter):
    """Cut a plain through hole at each center and return the drilled
    plate along with each hole's material support fraction.

    The board frame and the plate frame share the XY plane, so only the
    centers' x and y matter; the drills span the plate's own z range.
    """
    box = plate.BoundBox
    drills = []
    supports = []
    full_volume = math.pi / 4.0 * hole_diameter**2 * box.ZLength
    for center in hole_centers:
        drill = Part.makeCylinder(
            hole_diameter / 2.0,
            box.ZLength + 2.0,
            App.Vector(center.x, center.y, box.ZMin - 1.0),
            App.Vector(0, 0, 1),
        )
        support = plate.common(drill).Volume / full_volume
        if support < MINIMUM_HOLE_SUPPORT:
            raise SystemExit(
                f"error: hole at ({center.x:.3f}, {center.y:.3f}) has only "
                f"{support * 100.0:.0f} % plate material around it; the "
                "plate and board frames probably do not line up"
            )
        drills.append(drill)
        supports.append(support)
    volume_before = plate.Volume
    removed_volume = plate.common(Part.makeCompound(drills)).Volume
    drilled = plate.cut(Part.makeCompound(drills))
    if abs(volume_before - drilled.Volume - removed_volume) > 0.001 * volume_before:
        raise SystemExit("error: drilling did not remove the expected volume")
    # The plate is a compound of touching cell solids and a drill can
    # sever a narrow web (splitting a cell in two is fine); what must
    # never happen is a piece losing contact with the rest.
    fused = drilled.Solids[0].multiFuse(drilled.Solids[1:])
    if len(fused.Solids) != 1:
        raise SystemExit(
            f"error: drilling left {len(fused.Solids)} disconnected plate "
            "pieces"
        )
    return drilled, supports


def main():
    arguments = parse_arguments(script_arguments(sys.argv))

    board_document = import_assembly(arguments.step_file)
    board_description, board_shape, outline_face_pair = find_board(board_document)
    resting_face, up = pick_resting_face(outline_face_pair, True)
    hole_centers = mounting_hole_centers(
        board_shape, up, resting_face.Surface.Position
    )

    plate = load_plate(arguments.fcstd_file)
    box = plate.BoundBox
    plate, supports = drill_holes(plate, hole_centers, arguments.hole_diameter)
    mesh = export_stl(plate, arguments.stl_file)

    print(f"board:      {board_description}, {len(hole_centers)} mounting drills")
    print(f"plate:      '{PLATE_OBJECT_NAME}' from {arguments.fcstd_file}, "
          f"{box.XLength:.2f} x {box.YLength:.2f} x {box.ZLength:.2f} mm, "
          f"{len(plate.Solids)} solids")
    for center, support in zip(hole_centers, supports):
        print(f"hole:       ({center.x:9.4f}, {center.y:8.4f}) "
              f"{arguments.hole_diameter} mm, {support * 100.0:5.1f} % supported")
    print(f"wrote:      {arguments.stl_file} ({mesh.CountFacets} facets)")


run_and_exit(main)
