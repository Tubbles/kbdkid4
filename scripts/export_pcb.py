"""Export a 3D-printable replica of the bare PCB (STL) from the board's
STEP model.

For test-fitting the tray, the plate, switches and screws before the
fabricated boards arrive: the board outline extruded to the board
thickness, with every drill hole and cutout, and nothing else. FDM
prints come out slightly larger than modelled (the extruded bead
spreads, and the first layer squashes wider still), so the replica is
pulled in from all sides: the outline moves inward by pull_in and
every hole and cutout grows outward by pull_in, so the printed part
measures like the real board instead of binding in the tray or
refusing the switches. The thickness stays as modelled, since a
print's height follows its layer count and does not swell the same
way; thickness= overrides it.

Runs headless under FreeCAD's console interpreter (see board_step.py
for the freecadcmd quirks that shape the invocation):

    freecadcmd scripts/export_pcb.py --pass <pcb.step> <replica.stl> \
        [pull_in=0.2] [thickness=<from the STEP>]

The replica sits in board coordinates like the tray, its resting face
on the board's resting face.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import Part

from board_step import (
    export_stl,
    find_board,
    import_assembly,
    offset_outline,
    pick_resting_face,
    run_and_exit,
    script_arguments,
)

# How far the printed part is expected to swell per side, in mm: the
# outline moves inward and every opening grows outward by this much.
DEFAULT_PULL_IN_MM = 0.2

# Implementation tuning, rarely worth touching.
CUT_EXTRA_MM = 1.0  # opening cutters overshoot both faces for a clean cut

USAGE = f"""\
usage: freecadcmd scripts/export_pcb.py --pass <pcb.step> <replica.stl>
           [pull_in={DEFAULT_PULL_IN_MM}] [thickness=<from the STEP>]

  pull_in    swelling allowance per side, mm: the outline moves inward and
             every hole or cutout grows outward by this much
  thickness  replica thickness, mm (default: the board's, from the STEP)\
"""


class Arguments:
    def __init__(self):
        self.step_file = None
        self.stl_file = None
        self.pull_in = DEFAULT_PULL_IN_MM
        self.thickness = None


def parse_arguments(argument_list):
    arguments = Arguments()
    positionals = []
    for argument in argument_list:
        if "=" in argument:
            key, _, value = argument.partition("=")
            if key not in ("pull_in", "thickness"):
                raise SystemExit(f"error: unknown option '{key}'\n{USAGE}")
            try:
                setattr(arguments, key, float(value))
            except ValueError:
                raise SystemExit(f"error: '{key}' needs a number, got '{value}'")
        else:
            positionals.append(argument)
    if len(positionals) != 2:
        raise SystemExit(USAGE)
    arguments.step_file, arguments.stl_file = positionals
    return arguments


def opening_wires(board_face):
    """The board face's inner wires: drill holes and cutouts."""
    return [
        wire for wire in board_face.Wires if not wire.isSame(board_face.OuterWire)
    ]


def replica_wires(board_face, pull_in):
    """(outline, openings) of the replica: the board's outline moved
    inward and each opening moved outward by pull_in."""
    openings = opening_wires(board_face)
    if pull_in == 0:
        return board_face.OuterWire, openings
    return (
        offset_outline(board_face.OuterWire, -pull_in),
        [offset_outline(wire, pull_in) for wire in openings],
    )


def build_replica(outline, openings, up, thickness):
    body = Part.Face(outline).extrude(up * thickness)
    cutters = []
    for wire in openings:
        cutter = Part.Face(wire).extrude(up * (thickness + 2.0 * CUT_EXTRA_MM))
        cutter.translate(up * -CUT_EXTRA_MM)
        cutters.append(cutter)
    replica = body.cut(Part.makeCompound(cutters)) if cutters else body
    validate_replica(replica, outline, openings, thickness)
    return replica


def validate_replica(replica, outline, openings, thickness):
    if not replica.isValid() or len(replica.Solids) != 1:
        raise SystemExit("error: cutting the openings broke the replica solid")
    expected_volume = (
        Part.Face(outline).Area - sum(Part.Face(wire).Area for wire in openings)
    ) * thickness
    if abs(replica.Volume - expected_volume) > 0.001 * expected_volume:
        raise SystemExit(
            f"error: replica volume {replica.Volume:.1f} mm3 deviates from the "
            f"expected {expected_volume:.1f} mm3; geometry is off"
        )


def circle_diameter(wire):
    """The diameter of a wire that is one full circle, else None."""
    radii = set()
    for edge in wire.Edges:
        if not isinstance(edge.Curve, Part.Circle):
            return None
        radii.add(round(edge.Curve.Radius, 3))
    if len(radii) != 1:
        return None
    return 2.0 * radii.pop()


def opening_census(openings):
    """(drill diameter counts as {diameter: count}, number of other
    openings)."""
    drills = {}
    cutouts = 0
    for wire in openings:
        diameter = circle_diameter(wire)
        if diameter is None:
            cutouts += 1
        else:
            drills[diameter] = drills.get(diameter, 0) + 1
    return drills, cutouts


def main():
    arguments = parse_arguments(script_arguments(sys.argv))

    document = import_assembly(arguments.step_file)
    board_description, _board_shape, outline_face_pair = find_board(document)
    board_thickness = outline_face_pair[2]
    thickness = (
        board_thickness if arguments.thickness is None else arguments.thickness
    )
    resting_face, up = pick_resting_face(outline_face_pair, True)

    outline, openings = replica_wires(resting_face, arguments.pull_in)
    replica = build_replica(outline, openings, up, thickness)
    mesh = export_stl(replica, arguments.stl_file)

    board_box = resting_face.OuterWire.BoundBox
    replica_box = replica.BoundBox
    drills, cutouts = opening_census(opening_wires(resting_face))
    print(f"board:      {board_description}, {board_box.XLength:.2f} x "
          f"{board_box.YLength:.2f} mm, {board_thickness:.2f} mm thick")
    print(f"replica:    {replica_box.XLength:.2f} x {replica_box.YLength:.2f} x "
          f"{replica_box.ZLength:.2f} mm, pulled in {arguments.pull_in} mm per "
          f"side, volume {replica.Volume / 1000.0:.2f} cm3")
    for diameter, count in sorted(drills.items()):
        print(f"drills:     {count:3d} x {diameter:.2f} mm -> "
              f"{diameter + 2.0 * arguments.pull_in:.2f} mm")
    if cutouts:
        print(f"cutouts:    {cutouts} grown {arguments.pull_in} mm outward")
    print(f"wrote:      {arguments.stl_file} ({mesh.CountFacets} facets)")


run_and_exit(main)
