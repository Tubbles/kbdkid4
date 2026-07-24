"""Export the 3D-printable switch plate (STL) with mounting screw holes.

The plate model is reused from kbdkid3: a parametric switch cell
replicated by a point array into the left plate, with a mirrored right
plate alongside in the same document. Only the left plate is exported;
the right half is mirrored in the slicer, like the tray.

The kbdkid3 plate does not share the kbdkid4 board's origin. The
script aligns it by matching the plate's switch cutout centers to the
board's key switch positions (parsed from the board sources), refusing
anything but a pure translation, and then trims the plate's outer
edges so it fits the tray. Below the microcontroller, next to the
thumb key column, the plate extends sideways to the tray wall.

Plain through holes for the mounting screws are drilled where the
board has its mounting drills, detected in the kbdkid4 STEP exactly
like the tray places its standoffs, so the plate holes always track
the PCB. Every position is cut, even where it sits mostly in open
plate area (one lands at a four-cell junction cutout): whatever
sliver of material protrudes into the screw's path must go. The
printout reports how much plate material surrounds each hole.

Runs headless under FreeCAD's console interpreter (see board_step.py
for the freecadcmd quirks that shape the invocation):

    freecadcmd scripts/export_plate.py --pass <pcb.step> <plate.fcstd> <plate.stl> \
        [key=value ...]
"""

import math
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import FreeCAD as App
import Part

from board_step import (
    MOUNTING_HOLE_DIAMETER_MM,
    component_positions,
    export_stl,
    find_board,
    import_assembly,
    mounting_hole_centers,
    offset_outline,
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

# The kbdkid3 plate does not share the kbdkid4 board's origin, so the
# script aligns it by matching the plate's switch cutout centers to the
# board's key switch positions (a pure translation; anything else is
# rejected). The switch positions come from the board sources, since
# the STEP carries no switch bodies.
SWITCH_NAME_PATTERN = re.compile(r"S[0-9]{3}")  # this project's key switches
ALIGNMENT_RESIDUAL_LIMIT_MM = 0.05

# The reused plate overhangs the tray; trim its outer edges to fit.
PLATE_EDGE_TRIM_MM = 0.4

# Below the microcontroller the plate extends sideways to the tray
# wall, next to the thumb key column: a tab on the rightmost silhouette
# edge that lies below the MCU.
MCU_NAME = "U1"
MCU_TAB_EXTENSION_MM = 2.5

# Below this much surrounding plate material a cut is a clearance
# cutout in mostly open plate area rather than a supported screw hole
# (one mounting position lands at a four-cell junction cutout). Only
# affects reporting: every position is cut either way, since whatever
# sliver protrudes into the screw's path must go.
SUPPORTED_HOLE_THRESHOLD = 0.5

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


def key_switch_positions():
    """The board's key switch positions, from the board sources."""
    found = list(component_positions(SWITCH_NAME_PATTERN).values())
    if not found:
        raise SystemExit(
            f"error: no placed switches matching "
            f"'{SWITCH_NAME_PATTERN.pattern}' found in the board sources"
        )
    return found


def cutout_centers(plate):
    """Center of each cell's switch cutout: the inner boundary of the
    cell's top face."""
    centers = []
    for solid in plate.Solids:
        for face in solid.Faces:
            surface = face.Surface
            if not isinstance(surface, Part.Plane):
                continue
            normal = face.normalAt(*surface.parameter(face.CenterOfMass))
            if normal.z < 0.999:
                continue
            inner_wires = [
                wire for wire in face.Wires if not wire.isSame(face.OuterWire)
            ]
            if not inner_wires:
                continue
            xs = []
            ys = []
            for wire in inner_wires:
                box = wire.BoundBox
                xs.extend([box.XMin, box.XMax])
                ys.extend([box.YMin, box.YMax])
            centers.append(
                App.Vector((min(xs) + max(xs)) / 2.0, (min(ys) + max(ys)) / 2.0, 0.0)
            )
            break
    if not centers:
        raise SystemExit("error: no switch cutouts found in the plate")
    return centers


def board_alignment_offset(plate, switches):
    """The translation that puts the plate in the board's frame, found
    by matching every switch cutout to its nearest switch position.

    The match must be a pure translation: all cutouts have to agree on
    the offset within ALIGNMENT_RESIDUAL_LIMIT_MM.
    """
    deltas = []
    for center in cutout_centers(plate):
        nearest = min(switches, key=lambda position: position.sub(center).Length)
        deltas.append(nearest.sub(center))
    mean = App.Vector(
        sum(delta.x for delta in deltas) / len(deltas),
        sum(delta.y for delta in deltas) / len(deltas),
        0.0,
    )
    worst = max(delta.sub(mean).Length for delta in deltas)
    if worst > ALIGNMENT_RESIDUAL_LIMIT_MM:
        raise SystemExit(
            f"error: plate cutouts do not match the board's switch grid by "
            f"a pure translation (worst residual {worst:.3f} mm)"
        )
    return mean


def plate_silhouette_bottom_face(plate):
    """The bottom face of the fused plate, whose outer wire is the
    plate's silhouette."""
    silhouette = plate.Solids[0].multiFuse(plate.Solids[1:]).removeSplitter()
    bottom = silhouette.BoundBox.ZMin
    bottom_faces = [
        face
        for face in silhouette.Faces
        if isinstance(face.Surface, Part.Plane)
        and abs(face.BoundBox.ZMin - bottom) < 0.001
        and abs(face.BoundBox.ZMax - bottom) < 0.001
    ]
    if len(bottom_faces) != 1:
        raise SystemExit(
            f"error: expected one plate bottom face, found {len(bottom_faces)}"
        )
    return bottom_faces[0]


def trim_outer_edges(plate, trim):
    """Shrink the plate's outer silhouette by `trim` on all outer
    edges, leaving the cutouts untouched."""
    outline = offset_outline(plate_silhouette_bottom_face(plate).OuterWire, -trim)
    keep_prism = Part.Face(outline).extrude(
        App.Vector(0, 0, plate.BoundBox.ZLength + 2.0)
    )
    keep_prism.translate(App.Vector(0, 0, -1.0))
    trimmed = plate.common(keep_prism)
    old_box = plate.BoundBox
    new_box = trimmed.BoundBox
    for old_length, new_length in (
        (old_box.XLength, new_box.XLength),
        (old_box.YLength, new_box.YLength),
    ):
        if abs(old_length - new_length - 2.0 * trim) > 0.01:
            raise SystemExit(
                f"error: edge trim changed a plate side from {old_length:.2f} "
                f"to {new_length:.2f} mm, expected minus {2.0 * trim:.2f} mm"
            )
    return trimmed


def extend_mcu_tab(plate):
    """Widen the plate out to the tray wall below the microcontroller,
    next to the thumb key column.

    The tab sits on the plate silhouette's rightmost vertical edge
    below the MCU (in this plate, the thumb key cell's outer edge) and
    extends MCU_TAB_EXTENSION_MM outward, spanning that edge's full
    length. Returns (plate, tab_edge_x, tab_y_range).
    """
    mcu_by_name = component_positions(re.compile(re.escape(MCU_NAME)))
    if MCU_NAME not in mcu_by_name:
        raise SystemExit(
            f"error: microcontroller '{MCU_NAME}' not found in the board sources"
        )
    mcu = mcu_by_name[MCU_NAME]
    box = plate.BoundBox
    plate_center_x = (box.XMin + box.XMax) / 2.0
    candidates = []
    for edge in plate_silhouette_bottom_face(plate).OuterWire.Edges:
        start = edge.valueAt(edge.FirstParameter)
        end = edge.valueAt(edge.LastParameter)
        if abs(start.x - end.x) > 0.01:
            continue
        if max(start.y, end.y) > mcu.y:
            continue
        if start.x < plate_center_x:
            continue
        candidates.append((start.x, min(start.y, end.y), max(start.y, end.y)))
    if not candidates:
        raise SystemExit(
            "error: no vertical silhouette edge below the MCU to extend"
        )
    edge_x, y_low, y_high = max(candidates)
    tab = Part.makeBox(
        MCU_TAB_EXTENSION_MM,
        y_high - y_low,
        box.ZLength,
        App.Vector(edge_x, y_low, box.ZMin),
    )
    return (
        Part.makeCompound(list(plate.Solids) + [tab]),
        edge_x,
        (y_low, y_high),
    )


def drill_holes(plate, hole_centers, hole_diameter):
    """Cut a plain through hole at each center and return the drilled
    plate along with each hole's material support fraction.

    Every center is cut regardless of support: a position in mostly
    open plate area still needs whatever sliver protrudes into the
    screw's path removed. The plate is already in the board's frame
    here, so only the centers' x and y matter; the drills span the
    plate's own z range.
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
        supports.append(plate.common(drill).Volume / full_volume)
        drills.append(drill)
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
    switches = key_switch_positions()
    alignment = board_alignment_offset(plate, switches)
    plate.translate(alignment)
    plate = trim_outer_edges(plate, PLATE_EDGE_TRIM_MM)
    plate, tab_edge_x, tab_y_range = extend_mcu_tab(plate)
    box = plate.BoundBox
    plate, supports = drill_holes(plate, hole_centers, arguments.hole_diameter)
    mesh = export_stl(plate, arguments.stl_file)

    print(f"board:      {board_description}, {len(hole_centers)} mounting drills")
    print(f"plate:      '{PLATE_OBJECT_NAME}' from {arguments.fcstd_file}, "
          f"{box.XLength:.2f} x {box.YLength:.2f} x {box.ZLength:.2f} mm, "
          f"{len(plate.Solids)} solids")
    print(f"aligned:    moved ({alignment.x:+.3f}, {alignment.y:+.3f}) mm onto the "
          f"board's switch grid ({len(switches)} switches), outer edges "
          f"trimmed {PLATE_EDGE_TRIM_MM} mm")
    print(f"tab:        {MCU_TAB_EXTENSION_MM} mm extension below {MCU_NAME} to "
          f"the tray wall, x {tab_edge_x:.2f} -> {tab_edge_x + MCU_TAB_EXTENSION_MM:.2f}, "
          f"y {tab_y_range[0]:.2f}..{tab_y_range[1]:.2f}")
    for center, support in zip(hole_centers, supports):
        note = ""
        if support < SUPPORTED_HOLE_THRESHOLD:
            note = " (mostly open plate area, clearance cut only)"
        print(f"hole:       ({center.x:9.4f}, {center.y:8.4f}) "
              f"{arguments.hole_diameter} mm, {support * 100.0:5.1f} % "
              f"supported{note}")
    print(f"wrote:      {arguments.stl_file} ({mesh.CountFacets} facets)")


run_and_exit(main)
