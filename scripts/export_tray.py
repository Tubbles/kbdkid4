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

All vertical corners of the outer shell share one radius: gap + wall,
capped by what the shortest outline step can geometrically fit (the
chosen value is printed). To get that, the board outline (whose
corners come pre-rounded from
the PCB design) is rebuilt as a sharp-corner polygon, offset with
sharp joins, extruded, and the shell's vertical edges are filleted
before the cavity is cut. The cavity itself keeps the plain offset
geometry so the board clearance stays constant everywhere.
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
SHARPEN_MAX_CORNER_RADIUS_MM = 3.0


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


def grow(wire, distance, sharp=False):
    """Offset a closed wire outward by `distance`, regardless of the
    wire's orientation (makeOffset2D's sign follows orientation).

    With sharp=True convex corners are extended to their intersection
    (join type 2) instead of being arced over.
    """
    join_type = 2 if sharp else 0
    original_area = Part.Face(wire).Area
    grown = wire.makeOffset2D(distance, join_type)
    if Part.Face(grown).Area < original_area:
        grown = wire.makeOffset2D(-distance, join_type)
    if Part.Face(grown).Area <= original_area:
        raise SystemExit(f"error: offsetting the outline by {distance} mm failed")
    return grown


def outline_straight_segments(outline_wire):
    """The outline's straight segments in wire order, as (point,
    direction) pairs. The small corner arcs between them are dropped;
    a large arc means the outline has a curved edge this script's
    uniform-corner rebuild cannot represent, so that is an error."""
    segments = []
    for edge in outline_wire.OrderedEdges:
        curve = edge.Curve
        if isinstance(curve, Part.Line):
            start = edge.valueAt(edge.FirstParameter)
            end = edge.valueAt(edge.LastParameter)
            segments.append((start, end.sub(start)))
        elif isinstance(curve, Part.Circle):
            if curve.Radius > SHARPEN_MAX_CORNER_RADIUS_MM:
                raise SystemExit(
                    f"error: outline contains an arc of radius "
                    f"{curve.Radius:.2f} mm, too large to be treated as a "
                    "corner round"
                )
        else:
            raise SystemExit(
                f"error: unsupported outline edge type "
                f"{type(curve).__name__}"
            )
    if len(segments) < 3:
        raise SystemExit("error: outline has fewer than 3 straight segments")
    return segments


def intersect_in_plane(point_a, direction_a, point_b, direction_b, normal):
    """Intersection of two lines lying in the plane with the given
    normal, or None for (near) parallel lines."""
    denominator = direction_a.cross(direction_b).dot(normal)
    if abs(denominator) < 1e-9 * direction_a.Length * direction_b.Length:
        return None
    parameter = point_b.sub(point_a).cross(direction_b).dot(normal) / denominator
    return point_a.add(direction_a * parameter)


def sharpen_outline(outline_wire, normal):
    """Rebuild the outline as a sharp-corner polygon: keep the straight
    segments and extend neighbours to their intersections, dropping the
    corner rounds the board outline already carries. This is what makes
    a single uniform corner radius possible later on."""
    segments = outline_straight_segments(outline_wire)
    corner_points = []
    for index, (point_a, direction_a) in enumerate(segments):
        point_b, direction_b = segments[(index + 1) % len(segments)]
        corner = intersect_in_plane(
            point_a, direction_a, point_b, direction_b, normal
        )
        if corner is None:
            raise SystemExit(
                "error: successive parallel outline segments, cannot "
                "rebuild a sharp-corner outline"
            )
        corner_points.append(corner)
    return Part.makePolygon(corner_points + [corner_points[0]])


def max_uniform_corner_radius(polygon_wire):
    """Largest fillet radius all corners of a polygon can share.

    A fillet with radius R at a corner with turn angle t consumes
    R * tan(t / 2) of each adjacent edge, so every edge must be at
    least as long as the demands of the fillets at its two ends.
    """
    points = [vertex.Point for vertex in polygon_wire.OrderedVertexes]
    count = len(points)
    directions = []
    lengths = []
    for index in range(count):
        vector = points[(index + 1) % count].sub(points[index])
        lengths.append(vector.Length)
        directions.append(vector.normalize())
    demands = []
    for index in range(count):
        cosine = max(-1.0, min(1.0, directions[index - 1].dot(directions[index])))
        demands.append(math.tan(math.acos(cosine) / 2.0))
    radius_limit = None
    for index in range(count):
        demand_sum = demands[index] + demands[(index + 1) % count]
        if demand_sum < 1e-9:
            continue
        limit = lengths[index] / demand_sum
        if radius_limit is None or limit < radius_limit:
            radius_limit = limit
    if radius_limit is None:
        raise SystemExit("error: outline polygon has no corners to fillet")
    return radius_limit


def fillet_vertical_edges(solid, up, radius):
    """Fillet every straight vertical edge of a prism, giving all its
    corners the same radius."""
    vertical_edges = []
    for edge in solid.Edges:
        if not isinstance(edge.Curve, Part.Line):
            continue
        direction = edge.valueAt(edge.LastParameter).sub(
            edge.valueAt(edge.FirstParameter)
        )
        if direction.Length < 1e-9:
            continue
        if abs(direction.normalize().dot(up)) > 0.999:
            vertical_edges.append(edge)
    if not vertical_edges:
        raise SystemExit("error: no vertical corner edges found to fillet")
    return solid.makeFillet(radius, vertical_edges)


def build_tray(outline_wire, up, gap, wall, floor, height):
    # The cavity follows the board outline exactly (constant clearance,
    # corner rounds included). The outer shell is rebuilt sharp and then
    # filleted so every visible corner shares one radius: gap + wall,
    # which at a 90 degree corner passes through the same point a plain
    # offset arc would, capped by what the shortest outline step can
    # geometrically fit.
    cavity_wire = grow(outline_wire, gap)
    outer_wire = grow(sharpen_outline(outline_wire, up), gap + wall, sharp=True)
    corner_radius = min(
        gap + wall,
        math.floor(95.0 * max_uniform_corner_radius(outer_wire)) / 100.0,
    )

    outer_face = Part.Face(outer_wire)
    outer_face.translate(up * -floor)
    shell = fillet_vertical_edges(outer_face.extrude(up * height), up, corner_radius)

    cavity_face = Part.Face(cavity_wire)
    cavity = cavity_face.extrude(up * (height - floor + 1.0))

    tray = shell.cut(cavity)
    validate_tray(tray, shell, cavity_wire, floor, height)
    return tray, corner_radius


def validate_tray(tray, shell, cavity_wire, floor, height):
    if not tray.isValid() or len(tray.Solids) != 1:
        raise SystemExit("error: tray boolean cut produced an invalid solid")
    expected_volume = (
        shell.Volume - Part.Face(cavity_wire).Area * (height - floor)
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

    tray, corner_radius = build_tray(
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
    print(f"corners:    uniform {corner_radius:.2f} mm radius on the outer shell")
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
