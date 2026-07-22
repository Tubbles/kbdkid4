"""Export a 3D-printable PCB tray (STL) from the board's STEP model.

Runs headless under FreeCAD's console interpreter. The leading "--pass"
makes freecadcmd forward the remaining arguments to this script; the
options are key=value words (not --flags) because freecadcmd's own
option parser intercepts dash-prefixed arguments even after "--pass"
(observed on FreeCAD 1.0.0):

    freecadcmd scripts/export_tray.py --pass <pcb.step> <tray.stl> \
        [gap=0.8] [wall=0.4] [floor=0.6] [height=10.0] [flip]

The board is located inside the STEP assembly without any hardcoded face
indices, in two stages:

1. By label: LibrePCB names the board body "PCB" in the exported assembly
   (or "PCB1", "PCB2", ... for boards with multiple outline polygons; see
   stepexport.cpp in the LibrePCB sources). Components are labeled by
   their designator (D100, ...), so the label is unambiguous.
2. By geometry, as fallback and as validation of stage 1: the board is
   the solid owning the largest planar face in the assembly, and that
   face must have an equal-area parallel partner face at a plausible
   board thickness away (the board's other side). Anything that fails
   this check is rejected loudly rather than guessed at.

The tray's cavity opens toward the side of the board where components
protrude the furthest, so the bare(r) side rests on the tray floor.
Pass the word "flip" to override. The tray is positioned in board
coordinates: the cavity floor touches the board's resting face.
"""

import math
import os
import re
import sys
import traceback

import FreeCAD as App
import Import
import MeshPart
import Part

# LibrePCB names the board body "PCB" ("PCB1", "PCB2", ... for multiple
# outlines); depending on the FreeCAD version the imported object carries
# the product label ("PCB") or the instance label ("PCB:1").
BOARD_LABEL_PATTERN = re.compile(r"^PCB\d*(:\d+)?$")
BOARD_THICKNESS_RANGE_MM = (0.2, 5.0)
PARTNER_FACE_AREA_TOLERANCE = 0.05
MESH_LINEAR_DEFLECTION_MM = 0.05


def script_arguments(argv):
    """Return the arguments meant for this script.

    Under freecadcmd, sys.argv contains freecadcmd's own arguments too;
    everything after "--pass" is ours. Under a plain python interpreter
    the usual convention applies.
    """
    if "--pass" in argv:
        return argv[argv.index("--pass") + 1 :]
    return argv[1:]


USAGE = """\
usage: freecadcmd scripts/export_tray.py --pass <pcb.step> <tray.stl>
           [gap=0.8] [wall=0.4] [floor=0.6] [height=10.0] [flip]

  gap     clearance between PCB edge and cavity wall, mm
  wall    tray wall thickness, mm
  floor   tray floor thickness, mm
  height  total tray height including the floor, mm
  flip    open the cavity toward the opposite side of the automatic choice\
"""


class Arguments:
    def __init__(self):
        self.step_file = None
        self.stl_file = None
        self.gap = 0.8
        self.wall = 0.4
        self.floor = 0.6
        self.height = 10.0
        self.flip = False


def parse_arguments(argument_list):
    arguments = Arguments()
    numeric_keys = ("gap", "wall", "floor", "height")
    positionals = []
    for argument in argument_list:
        if argument == "flip":
            arguments.flip = True
        elif "=" in argument:
            key, _, value = argument.partition("=")
            if key not in numeric_keys:
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


def import_assembly(step_file):
    document = App.newDocument("tray_export")
    Import.insert(step_file, document.Name)
    return document


def shapes_with_solids(document):
    """All (label, shape) pairs in the document that contain solids."""
    pairs = []
    for obj in document.Objects:
        shape = Part.getShape(obj)
        if not shape.isNull() and shape.Solids:
            pairs.append((obj.Label, shape))
    return pairs


def deduplicate_shapes(pairs):
    """Drop shapes that are geometrically the same body as an earlier one.

    STEP imports can expose the same body twice (e.g. a group and the
    feature inside it); volume plus bounding box identifies duplicates
    well enough for that purpose.
    """
    unique_pairs = []
    seen_keys = set()
    for label, shape in pairs:
        box = shape.BoundBox
        key = (
            round(shape.Volume, 3),
            round(box.XMin, 3),
            round(box.YMin, 3),
            round(box.ZMin, 3),
            round(box.DiagonalLength, 3),
        )
        if key not in seen_keys:
            seen_keys.add(key)
            unique_pairs.append((label, shape))
    return unique_pairs


def planar_faces(shape):
    return [face for face in shape.Faces if isinstance(face.Surface, Part.Plane)]


def plane_distance_along_axis(face_a, face_b):
    axis = face_a.Surface.Axis
    offset = face_b.Surface.Position.sub(face_a.Surface.Position)
    return axis.dot(offset)


def find_outline_face_pair(shape):
    """Return (face, partner, thickness) for a board-like shape, else None.

    The board outline face is the largest planar face; the partner is the
    board's other side: parallel, nearly equal area, and a plausible board
    thickness away.
    """
    faces = planar_faces(shape)
    if not faces:
        return None
    largest = max(faces, key=lambda face: face.Area)
    candidates = []
    for face in faces:
        if face is largest:
            continue
        if abs(face.Surface.Axis.dot(largest.Surface.Axis)) < 0.999:
            continue
        if abs(face.Area - largest.Area) > PARTNER_FACE_AREA_TOLERANCE * largest.Area:
            continue
        thickness = abs(plane_distance_along_axis(largest, face))
        if BOARD_THICKNESS_RANGE_MM[0] <= thickness <= BOARD_THICKNESS_RANGE_MM[1]:
            candidates.append((face, thickness))
    if not candidates:
        return None
    partner, thickness = min(candidates, key=lambda candidate: candidate[1])
    return largest, partner, thickness


def find_board(document):
    """Locate the board body: by LibrePCB's label, else by geometry.

    Returns (description, shape, outline_face_pair). Both routes must
    pass the geometric outline-face-pair validation.
    """
    all_pairs = shapes_with_solids(document)
    candidates = deduplicate_shapes(all_pairs)

    labeled = deduplicate_shapes(
        [
            (label, shape)
            for label, shape in all_pairs
            if BOARD_LABEL_PATTERN.match(label)
        ]
    )
    if len(labeled) > 1:
        labels = ", ".join(label for label, _ in labeled)
        raise SystemExit(
            f"error: multiple board bodies found ({labels}); a board with "
            "several outline polygons is not supported by this script"
        )
    if labeled:
        label, shape = labeled[0]
        pair = find_outline_face_pair(shape)
        if pair is None:
            raise SystemExit(
                f"error: body labeled '{label}' does not look like a board "
                "(no parallel equal-area face pair at a plausible thickness)"
            )
        return f"'{label}' (by label)", shape, pair

    # Fallback for STEP files without LibrePCB's labels: the board is the
    # solid owning the largest planar face in the whole assembly.
    best = None
    for label, shape in candidates:
        pair = find_outline_face_pair(shape)
        if pair is None:
            continue
        if best is None or pair[0].Area > best[2][0].Area:
            best = (f"'{label}' (by geometry)", shape, pair)
    if best is None:
        raise SystemExit(
            "error: no board-like solid found in the STEP file "
            "(nothing has a parallel equal-area planar face pair)"
        )
    return best


def component_protrusions(document, board_shape, axis):
    """How far bodies other than the board stick out past the board,
    along +axis and -axis, in mm."""
    board_box = board_shape.BoundBox
    board_low, board_high = projected_interval(board_box, axis)
    above = 0.0
    below = 0.0
    for _label, shape in deduplicate_shapes(shapes_with_solids(document)):
        low, high = projected_interval(shape.BoundBox, axis)
        above = max(above, high - board_high)
        below = max(below, board_low - low)
    return above, below


def projected_interval(bound_box, axis):
    """The [min, max] interval covered by a bounding box when projected
    onto an axis."""
    values = [
        axis.dot(App.Vector(x, y, z))
        for x in (bound_box.XMin, bound_box.XMax)
        for y in (bound_box.YMin, bound_box.YMax)
        for z in (bound_box.ZMin, bound_box.ZMax)
    ]
    return min(values), max(values)


def pick_resting_face(outline_face_pair, open_toward_positive_axis):
    """Return (resting_face, up) where the tray floor sits under
    resting_face and `up` points from the floor toward the opening."""
    face_a, face_b, _thickness = outline_face_pair
    axis = face_a.Surface.Axis
    if plane_distance_along_axis(face_a, face_b) > 0:
        low_face, high_face = face_a, face_b
    else:
        low_face, high_face = face_b, face_a
    if open_toward_positive_axis:
        return low_face, axis
    return high_face, axis.negative()


def grow(wire, distance):
    """Offset a closed wire outward by `distance`, regardless of the
    wire's orientation (makeOffset2D's sign follows orientation)."""
    original_area = Part.Face(wire).Area
    grown = wire.makeOffset2D(distance)
    if Part.Face(grown).Area < original_area:
        grown = wire.makeOffset2D(-distance)
    if Part.Face(grown).Area <= original_area:
        raise SystemExit(f"error: offsetting the outline by {distance} mm failed")
    return grown


def build_tray(outline_wire, up, gap, wall, floor, height):
    cavity_wire = grow(outline_wire, gap)
    outer_wire = grow(cavity_wire, wall)

    outer_face = Part.Face(outer_wire)
    outer_face.translate(up * -floor)
    shell = outer_face.extrude(up * height)

    cavity_face = Part.Face(cavity_wire)
    cavity = cavity_face.extrude(up * (height - floor + 1.0))

    tray = shell.cut(cavity)
    validate_tray(tray, outer_wire, cavity_wire, floor, height)
    return tray


def validate_tray(tray, outer_wire, cavity_wire, floor, height):
    if not tray.isValid() or len(tray.Solids) != 1:
        raise SystemExit("error: tray boolean cut produced an invalid solid")
    expected_volume = (
        Part.Face(outer_wire).Area * height
        - Part.Face(cavity_wire).Area * (height - floor)
    )
    if abs(tray.Volume - expected_volume) > 0.001 * expected_volume:
        raise SystemExit(
            f"error: tray volume {tray.Volume:.1f} mm3 deviates from the "
            f"expected {expected_volume:.1f} mm3; geometry is off"
        )


def export_stl(tray, stl_file):
    mesh = MeshPart.meshFromShape(
        Shape=tray,
        LinearDeflection=MESH_LINEAR_DEFLECTION_MM,
        AngularDeflection=math.radians(15),
        Relative=False,
    )
    mesh.write(stl_file)
    return mesh


def main():
    arguments = parse_arguments(script_arguments(sys.argv))

    document = import_assembly(arguments.step_file)
    board_description, board_shape, outline_face_pair = find_board(document)
    thickness = outline_face_pair[2]

    axis = outline_face_pair[0].Surface.Axis
    above, below = component_protrusions(document, board_shape, axis)
    if abs(above - below) < 0.01:
        # Symmetric protrusion (e.g. THT bodies vs. lead stubs): fall back
        # to the convention that the cavity opens upward.
        open_toward_positive_axis = axis.z >= 0
    else:
        open_toward_positive_axis = above > below
    if arguments.flip:
        open_toward_positive_axis = not open_toward_positive_axis
    resting_face, up = pick_resting_face(
        outline_face_pair, open_toward_positive_axis
    )

    tray = build_tray(
        resting_face.OuterWire,
        up,
        arguments.gap,
        arguments.wall,
        arguments.floor,
        arguments.height,
    )
    mesh = export_stl(tray, arguments.stl_file)

    board_box = board_shape.BoundBox
    print(f"board:      {board_description}, {board_box.XLength:.2f} x {board_box.YLength:.2f} mm, "
          f"{thickness:.2f} mm thick, outline face {outline_face_pair[0].Area:.1f} mm2")
    print(f"components: protrude {above:.2f} mm above / {below:.2f} mm below the board")
    print(f"opening:    toward {'+' if up.dot(axis) > 0 else '-'}{axis_name(axis)}"
          f"{' (flipped)' if arguments.flip else ''}")
    print(f"tray:       gap {arguments.gap} mm, wall {arguments.wall} mm, "
          f"floor {arguments.floor} mm, height {arguments.height} mm, "
          f"volume {tray.Volume / 1000.0:.2f} cm3")
    print(f"wrote:      {arguments.stl_file} ({mesh.CountFacets} facets)")


def axis_name(axis):
    for name, direction in (("Z", App.Vector(0, 0, 1)),
                            ("Y", App.Vector(0, 1, 0)),
                            ("X", App.Vector(1, 0, 0))):
        if abs(axis.dot(direction)) > 0.999:
            return name
    return f"({axis.x:.2f},{axis.y:.2f},{axis.z:.2f})"


def run_and_exit():
    """Run main() and leave through os._exit().

    freecadcmd executes command line scripts with __name__ set to the
    file's stem, runs them twice, and always exits 0 even when the script
    raised. Exiting the process directly (after flushing) gives CI a real
    exit code and stops the second run.
    """
    exit_code = 0
    try:
        main()
    except SystemExit as stop:
        if isinstance(stop.code, str):
            print(stop.code, file=sys.stderr)
            exit_code = 1
        else:
            exit_code = stop.code or 0
    except Exception:
        traceback.print_exc()
        exit_code = 1
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(exit_code)


run_and_exit()
