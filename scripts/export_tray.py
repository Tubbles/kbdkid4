"""Export a 3D-printable PCB tray (STL) from the board's STEP model.

Runs headless under FreeCAD's console interpreter. The leading "--pass"
makes freecadcmd forward the remaining arguments to this script; the
options are key=value words (not --flags) because freecadcmd's own
option parser intercepts dash-prefixed arguments even after "--pass"
(observed on FreeCAD 1.0.0):

    freecadcmd scripts/export_tray.py --pass <pcb.step> <tray.stl> \
        [key=value ...] [flip]

The key=value parameter names and their defaults are listed in the
USAGE text and the constants block below.

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

Every corner, convex or concave, bends with the same pair of
concentric radii: the corner radius on the outside of the bend and
the corner radius minus the wall thickness on the inside. All corners
therefore look alike and the wall keeps its nominal width through
them. The corner radius is gap + wall, capped by what the shortest
outline step can geometrically fit (the chosen value is printed). To
make that possible, both walls are built from the outline rebuilt as
a sharp-corner polygon (the corner rounds the outline carries from
the PCB design are dropped), offset with sharp joins, extruded, and
filleted. The cavity therefore does not follow the board's own corner
rounds; its corner clearance only ever grows relative to the nominal
gap, never shrinks.

At each of the board's mounting drills (MOUNTING_HOLE_DIAMETER_MM,
found in the STEP geometry rather than assumed) a cylindrical standoff
rises from the tray floor, bored for an M2 heat-set insert. The bore's
floor is the tray floor's top surface, so the floor thickness of
material backs the insert.

A ledge along the cavity wall, ledge_width wide and as tall as the
standoffs, supports the board's perimeter: since the wall sits gap
away from the board edge, the shelf reaches ledge_width minus gap
under the board, and the board rests on ledge and standoffs together.
The well inside the ledge continues the concentric corner treatment
inward. Set ledge_width to 0 to build without a ledge.

The battery switch (POWER_SWITCH_NAME, located via the board sources
since it has no 3D model in the STEP) protrudes past the board
outline, so the wall gets a notch cut down from the rim over the
outline segment nearest the switch. The neighbouring segment on the
north side gets the same treatment over its whole length, letting the
USB cable come in from the top down to the microcontroller. At the
merged opening's two outer ends the neighbouring wall slopes down
into the notch and the crest where the full wall meets the slope is
rounded.

The design values live in the constants right below this docstring;
everything else derives from them.
"""

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import FreeCAD as App
import Part

import re

from board_step import (
    MOUNTING_HOLE_DIAMETER_MM,
    component_positions,
    deduplicate_shapes,
    export_stl,
    find_board,
    import_assembly,
    mounting_hole_centers,
    offset_outline,
    pick_resting_face,
    run_and_exit,
    script_arguments,
    shapes_with_solids,
)

# Tray design parameters, all in mm. Overridable per run with key=value
# command line words; the corner radii derive from gap and wall.
DEFAULT_GAP_MM = 0.4  # clearance between PCB edge and cavity wall
DEFAULT_WALL_MM = 0.8  # wall thickness (two nozzle widths)
DEFAULT_FLOOR_MM = 1.2  # floor thickness
DEFAULT_DEPTH_MM = 11.9  # cavity depth, floor top to rim (overall height = depth + floor)
DEFAULT_STANDOFF_HEIGHT_MM = 8.0  # insert standoff height above the floor
DEFAULT_STANDOFF_DIAMETER_MM = 5.8  # insert standoff outer diameter
DEFAULT_STANDOFF_HOLE_DIAMETER_MM = 3.2  # bore for an M2 heat-set insert
DEFAULT_LEDGE_WIDTH_MM = 1.0  # PCB support ledge from the cavity wall (0 disables)

# The battery switch protrudes past the board outline, so the wall gets
# a notch cut down from the rim over the outline segment nearest the
# switch. The switch position comes from the board sources (it has no
# 3D model in the STEP).
POWER_SWITCH_NAME = "S1"
POWER_SWITCH_NOTCH_DEPTH_MM = 3.2  # cut down from the rim
POWER_SWITCH_NOTCH_WIDTH_MM = 9.3  # along the wall, the whole segment

# The USB cable comes in over the outline segment north of the switch
# segment, down to the nice!nano below it, so that rim gets the same
# treatment over the whole neighbouring segment. The width derives from
# the segment; the notch reaches past the corner shared with the switch
# notch so the two openings merge instead of leaving a sliver: the two
# rectangular cutters' end faces meet at an angle, so the reach must
# cover the outer corner wedge between them, which extends about
# 1.3 mm past the corner. It also reaches just past the far corner
# round's sharpened end.
USB_NOTCH_DEPTH_MM = 3.2
USB_NOTCH_PAST_SHARED_CORNER_MM = 2.5
USB_NOTCH_PAST_FAR_CORNER_MM = 0.5

# At the merged opening's two outer ends the neighbouring wall slopes
# down into the notch (45 degrees when the ramp equals the notch
# depth), and the crest where the full wall meets the slope is rounded.
NOTCH_RAMP_MM = 3.2
NOTCH_CREST_RADIUS_MM = 1.0

# Implementation tuning, rarely worth touching.
CORNER_FIT_SAFETY = 0.95  # margin on the largest corner radius that fits
MINIMUM_FILLET_RADIUS_MM = 0.01  # below this a fillet is skipped as moot
CAVITY_CUT_EXTRA_MM = 1.0  # cavity overshoot above the rim for a clean cut
SHARPEN_MAX_CORNER_RADIUS_MM = 3.0  # outline arcs above this are not corners


USAGE = f"""\
usage: freecadcmd scripts/export_tray.py --pass <pcb.step> <tray.stl>
           [gap={DEFAULT_GAP_MM}] [wall={DEFAULT_WALL_MM}] \
[floor={DEFAULT_FLOOR_MM}] [depth={DEFAULT_DEPTH_MM}] [flip]
           [standoff_height={DEFAULT_STANDOFF_HEIGHT_MM}] \
[standoff_diameter={DEFAULT_STANDOFF_DIAMETER_MM}] \
[standoff_hole_diameter={DEFAULT_STANDOFF_HOLE_DIAMETER_MM}] \
[ledge_width={DEFAULT_LEDGE_WIDTH_MM}]

  gap     clearance between PCB edge and cavity wall, mm
  wall    tray wall thickness, mm
  floor   tray floor thickness, mm
  depth   cavity depth from the floor's top to the rim, mm
  flip    open the cavity toward the opposite side of the automatic choice
  standoff_height         insert standoff height above the floor, mm
  standoff_diameter       insert standoff outer diameter, mm
  standoff_hole_diameter  bore for the heat-set insert, mm
  ledge_width             PCB support ledge width from the cavity wall, mm;
                          the ledge is standoff_height tall, 0 disables it\
"""


class Arguments:
    def __init__(self):
        self.step_file = None
        self.stl_file = None
        self.gap = DEFAULT_GAP_MM
        self.wall = DEFAULT_WALL_MM
        self.floor = DEFAULT_FLOOR_MM
        self.depth = DEFAULT_DEPTH_MM
        self.standoff_height = DEFAULT_STANDOFF_HEIGHT_MM
        self.standoff_diameter = DEFAULT_STANDOFF_DIAMETER_MM
        self.standoff_hole_diameter = DEFAULT_STANDOFF_HOLE_DIAMETER_MM
        self.ledge_width = DEFAULT_LEDGE_WIDTH_MM
        self.flip = False


def parse_arguments(argument_list):
    arguments = Arguments()
    numeric_keys = (
        "gap",
        "wall",
        "floor",
        "depth",
        "standoff_height",
        "standoff_diameter",
        "standoff_hole_diameter",
        "ledge_width",
    )
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


def is_vertical_line_edge(edge, up):
    if not isinstance(edge.Curve, Part.Line):
        return False
    direction = edge.valueAt(edge.LastParameter).sub(
        edge.valueAt(edge.FirstParameter)
    )
    if direction.Length < 1e-9:
        return False
    return abs(direction.normalize().dot(up)) > 0.999


def vertex_key(point):
    return (round(point.x, 4), round(point.y, 4), round(point.z, 4))


def polygon_corner_convexity(polygon_wire, up):
    """Map each polygon vertex position to whether its corner is convex
    (material angle below 180 degrees), keyed by vertex_key()."""
    points = [vertex.Point for vertex in polygon_wire.OrderedVertexes]
    count = len(points)
    directions = [
        points[(index + 1) % count].sub(points[index]).normalize()
        for index in range(count)
    ]
    turns = []
    for index in range(count):
        cross = directions[index - 1].cross(directions[index]).dot(up)
        dot = directions[index - 1].dot(directions[index])
        turns.append(math.atan2(cross, dot))
    orientation = 1.0 if sum(turns) > 0 else -1.0
    return {
        vertex_key(points[index]): turns[index] * orientation > 0
        for index in range(count)
    }


def corner_edges(solid, up, convexity_by_vertex, want_convex):
    """The solid's vertical edges standing on polygon corners of the
    requested convexity. Seam edges from earlier fillets stand on no
    polygon corner and are skipped by the position match."""
    selected = []
    for edge in solid.Edges:
        if not is_vertical_line_edge(edge, up):
            continue
        for parameter in (edge.FirstParameter, edge.LastParameter):
            key = vertex_key(edge.valueAt(parameter))
            if key in convexity_by_vertex:
                if convexity_by_vertex[key] == want_convex:
                    selected.append(edge)
                break
    return selected


def fillet_prism_corners(prism, polygon, up, convex_radius, concave_radius):
    """Fillet a prism's vertical corner edges, with one radius for the
    polygon's convex corners and another for its concave ones."""
    convexity = polygon_corner_convexity(polygon, up)
    result = prism
    for want_convex, radius in ((True, convex_radius), (False, concave_radius)):
        if radius < MINIMUM_FILLET_RADIUS_MM:
            continue
        edges = corner_edges(result, up, convexity, want_convex)
        if edges:
            result = result.makeFillet(radius, edges)
    return result


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


def add_standoffs(
    tray, hole_centers, up, floor, standoff_height, standoff_diameter,
    standoff_hole_diameter,
):
    """Fuse an insert standoff onto the tray floor at each mounting hole
    center and bore it for a heat-set insert.

    The standoff body reaches down to the underside of the floor so the
    fuse never leaves a seam; the bore's floor is the tray floor's top
    surface, leaving the floor thickness of material under the insert.
    """
    if standoff_hole_diameter >= standoff_diameter:
        raise SystemExit(
            f"error: standoff hole {standoff_hole_diameter} mm must be "
            f"smaller than the standoff diameter {standoff_diameter} mm"
        )
    bodies = []
    bores = []
    for center in hole_centers:
        base = center.sub(up * floor)
        bodies.append(
            Part.makeCylinder(
                standoff_diameter / 2.0, floor + standoff_height, base, up
            )
        )
        bores.append(
            Part.makeCylinder(
                standoff_hole_diameter / 2.0,
                standoff_height + CAVITY_CUT_EXTRA_MM,
                center,
                up,
            )
        )
    volume_before = tray.Volume
    result = tray.fuse(Part.makeCompound(bodies))
    result = result.cut(Part.makeCompound(bores))
    result = result.removeSplitter()
    if not result.isValid() or len(result.Solids) != 1:
        raise SystemExit("error: adding the standoffs broke the solid")
    added_volume = result.Volume - volume_before
    expected_volume = (
        len(hole_centers)
        * math.pi
        / 4.0
        * (standoff_diameter**2 - standoff_hole_diameter**2)
        * standoff_height
    )
    if added_volume <= 0 or added_volume > 1.001 * expected_volume:
        raise SystemExit(
            f"error: standoffs added {added_volume:.1f} mm3, expected up to "
            f"{expected_volume:.1f} mm3; geometry is off"
        )
    return result


def nearest_outline_segment(segments, position):
    """(index, closest point on segment, direction) of the outline
    segment nearest a position."""
    best = None
    for index, (start, vector) in enumerate(segments):
        length = vector.Length
        direction = App.Vector(vector).normalize()
        along = max(0.0, min(length, direction.dot(position.sub(start))))
        closest = start.add(direction * along)
        distance = position.sub(closest).Length
        if best is None or distance < best[0]:
            best = (distance, index, closest, direction)
    return best[1], best[2], best[3]


def cut_rim_notch(
    tray, outline_wire, up, center_on_edge, direction, width, notch_depth,
    gap, wall, depth, label,
):
    """Open a notch in the wall's rim: `width` along the wall centered
    on `center_on_edge`, `notch_depth` down from the rim, spanning the
    full wall thickness."""
    outward = notch_outward(outline_wire, center_on_edge, direction, up)
    half_width = width / 2.0
    inner = -0.5  # start inside the cavity, across the gap
    outer = gap + wall + 0.5
    base = center_on_edge.add(up * (depth - notch_depth))
    corners = [
        base.add(direction * -half_width).add(outward * inner),
        base.add(direction * half_width).add(outward * inner),
        base.add(direction * half_width).add(outward * outer),
        base.add(direction * -half_width).add(outward * outer),
    ]
    cutter = Part.Face(Part.makePolygon(corners + [corners[0]])).extrude(
        up * (notch_depth + 1.0)
    )
    volume_before = tray.Volume
    result = tray.cut(cutter)
    if not result.isValid() or len(result.Solids) != 1:
        raise SystemExit(f"error: cutting the {label} notch broke the solid")
    if result.Volume >= volume_before:
        raise SystemExit(f"error: the {label} notch removed no material")
    wall_probe = center_on_edge.add(outward * (gap + wall / 2.0)).add(
        up * (depth - 0.1)
    )
    if result.Solids[0].isInside(wall_probe, 1e-6, True):
        raise SystemExit(f"error: the {label} notch did not open the wall rim")
    return result


def notch_outward(outline_wire, center_on_edge, direction, up):
    """The horizontal direction pointing out of the board at a point on
    the outline, perpendicular to the wall direction there."""
    outward = direction.cross(up)
    outline_box = outline_wire.BoundBox
    outline_center = App.Vector(
        (outline_box.XMin + outline_box.XMax) / 2.0,
        (outline_box.YMin + outline_box.YMax) / 2.0,
        center_on_edge.z,
    )
    if outward.dot(center_on_edge.sub(outline_center)) < 0:
        outward = outward.negative()
    return outward


def cut_notch_ramp(
    tray, outline_wire, up, end_on_outline, away, gap, wall, depth,
    notch_depth, label,
):
    """Slope the wall down into a notch end and round the crest.

    Cuts a wedge so the neighbouring wall descends from full height
    (NOTCH_RAMP_MM away from the notch end) to the notch floor, then
    fillets the crest edge where the full-height rim meets the slope
    with NOTCH_CREST_RADIUS_MM. Returns (tray, crest_rounded).
    """
    outward = notch_outward(outline_wire, end_on_outline, away, up)
    inner = -0.5
    outer = gap + wall + 2.0  # wide, the wall may bend within the ramp
    floor_z = depth - notch_depth
    profile = [
        end_on_outline.add(up * floor_z),
        end_on_outline.add(up * (depth + 1.0)),
        end_on_outline.add(away * NOTCH_RAMP_MM).add(up * (depth + 1.0)),
        end_on_outline.add(away * NOTCH_RAMP_MM).add(up * depth),
    ]
    face = Part.Face(Part.makePolygon(profile + [profile[0]]))
    face.translate(outward * inner)
    cutter = face.extrude(outward * (outer - inner))
    volume_before = tray.Volume
    result = tray.cut(cutter)
    if not result.isValid() or len(result.Solids) != 1:
        raise SystemExit(f"error: cutting the {label} ramp broke the solid")
    if result.Volume >= volume_before:
        raise SystemExit(f"error: the {label} ramp removed no material")

    crest = end_on_outline.add(away * NOTCH_RAMP_MM).add(up * depth)
    crest_edges = []
    for edge in result.Edges:
        midpoint = edge.valueAt((edge.FirstParameter + edge.LastParameter) / 2.0)
        offset = midpoint.sub(crest)
        if abs(offset.dot(away)) > 0.4 or abs(offset.dot(up)) > 0.4:
            continue
        if not -1.0 < offset.dot(outward) < outer:
            continue
        tangent = edge.valueAt(edge.LastParameter).sub(
            edge.valueAt(edge.FirstParameter)
        )
        if tangent.Length < 1e-9:
            continue
        tangent.normalize()
        if abs(tangent.dot(away)) > 0.5 or abs(tangent.dot(up)) > 0.5:
            continue
        crest_edges.append(edge)
    if crest_edges:
        try:
            rounded = result.makeFillet(NOTCH_CREST_RADIUS_MM, crest_edges)
            if rounded.isValid() and len(rounded.Solids) == 1:
                return rounded, True
        except Part.OCCError:
            pass
    return result, False


def build_tray(outline_wire, up, gap, wall, floor, depth, ledge_width, ledge_height):
    # Both walls are built from the sharpened outline so every corner
    # can carry a chosen radius. Each bend, convex or concave, gets the
    # corner radius on its outside and corner radius minus wall on its
    # inside; the two arcs are concentric for any corner angle, so all
    # corners look alike and the wall keeps its nominal width through
    # them. The cavity therefore does not follow the board's own corner
    # rounds; corner clearance only ever grows relative to the nominal
    # gap, never shrinks.
    sharp_outline = sharpen_outline(outline_wire, up)
    cavity_polygon = offset_outline(sharp_outline, gap)
    outer_wire = offset_outline(sharp_outline, gap + wall)
    corner_radius = min(
        gap + wall,
        math.floor(100.0 * CORNER_FIT_SAFETY * max_uniform_corner_radius(outer_wire))
        / 100.0,
    )

    outer_wire.translate(up * -floor)

    def outer_prism(height_above_floor):
        prism = Part.Face(outer_wire).extrude(up * (floor + height_above_floor))
        return fillet_prism_corners(
            prism,
            outer_wire,
            up,
            convex_radius=corner_radius,
            concave_radius=corner_radius - wall,
        )

    shell = outer_prism(depth)
    cavity_prism = fillet_prism_corners(
        Part.Face(cavity_polygon).extrude(up * (depth + CAVITY_CUT_EXTRA_MM)),
        cavity_polygon,
        up,
        convex_radius=corner_radius - wall,
        concave_radius=corner_radius,
    )

    tray = shell.cut(cavity_prism)
    validate_tray(tray, shell, cavity_prism, depth)

    if ledge_width > 0:
        # The ledge: a shelf along the cavity wall for the board's
        # perimeter to rest on, its top level with the standoff tops.
        # The well inside it continues the concentric corner treatment
        # inward: convex corners have run out of radius there (sharp),
        # concave ones grow by the ledge width.
        if ledge_width <= gap:
            raise SystemExit(
                f"error: ledge_width {ledge_width} mm must exceed the gap "
                f"{gap} mm for the board to rest on the ledge"
            )
        well_polygon = offset_outline(sharp_outline, gap - ledge_width)
        well_prism = fillet_prism_corners(
            Part.Face(well_polygon).extrude(
                up * (ledge_height + CAVITY_CUT_EXTRA_MM)
            ),
            well_polygon,
            up,
            convex_radius=corner_radius - wall - ledge_width,
            concave_radius=corner_radius + ledge_width,
        )
        ledge_ring = outer_prism(ledge_height).cut(well_prism)
        volume_before_ledge = tray.Volume
        tray = tray.fuse(ledge_ring)
        if not tray.isValid() or len(tray.Solids) != 1:
            raise SystemExit("error: fusing the ledge broke the solid")
        added_volume = tray.Volume - volume_before_ledge
        nominal_volume = (
            Part.Face(cavity_polygon).Area - Part.Face(well_polygon).Area
        ) * ledge_height
        if not 0.85 * nominal_volume < added_volume < 1.15 * nominal_volume:
            raise SystemExit(
                f"error: ledge added {added_volume:.1f} mm3, expected about "
                f"{nominal_volume:.1f} mm3; geometry is off"
            )

    return tray, corner_radius


def validate_tray(tray, shell, cavity_prism, depth):
    if not tray.isValid() or len(tray.Solids) != 1:
        raise SystemExit("error: tray boolean cut produced an invalid solid")
    # The cavity prism is a straight extrusion, so the part of it that
    # overlaps the shell scales linearly with height.
    cavity_height = depth + CAVITY_CUT_EXTRA_MM
    expected_volume = (
        shell.Volume - cavity_prism.Volume * depth / cavity_height
    )
    if abs(tray.Volume - expected_volume) > 0.001 * expected_volume:
        raise SystemExit(
            f"error: tray volume {tray.Volume:.1f} mm3 deviates from the "
            f"expected {expected_volume:.1f} mm3; geometry is off"
        )


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
        arguments.depth,
        arguments.ledge_width,
        arguments.standoff_height,
    )
    hole_centers = mounting_hole_centers(
        board_shape, up, resting_face.Surface.Position
    )
    tray = add_standoffs(
        tray,
        hole_centers,
        up,
        arguments.floor,
        arguments.standoff_height,
        arguments.standoff_diameter,
        arguments.standoff_hole_diameter,
    )
    switch_by_name = component_positions(re.compile(re.escape(POWER_SWITCH_NAME)))
    if POWER_SWITCH_NAME not in switch_by_name:
        raise SystemExit(
            f"error: power switch '{POWER_SWITCH_NAME}' not found in the "
            "board sources"
        )
    segments = outline_straight_segments(resting_face.OuterWire)
    switch_index, switch_notch_center, switch_direction = nearest_outline_segment(
        segments, switch_by_name[POWER_SWITCH_NAME]
    )
    tray = cut_rim_notch(
        tray,
        resting_face.OuterWire,
        up,
        switch_notch_center,
        switch_direction,
        POWER_SWITCH_NOTCH_WIDTH_MM,
        POWER_SWITCH_NOTCH_DEPTH_MM,
        arguments.gap,
        arguments.wall,
        arguments.depth,
        "switch",
    )

    def segment_midpoint(segment):
        start, vector = segment
        return start.add(vector * 0.5)

    neighbours = [
        segments[(switch_index - 1) % len(segments)],
        segments[(switch_index + 1) % len(segments)],
    ]
    usb_segment = max(neighbours, key=lambda segment: segment_midpoint(segment).y)
    usb_start, usb_vector = usb_segment
    usb_direction = App.Vector(usb_vector).normalize()
    usb_end = usb_start.add(usb_vector)
    if switch_notch_center.sub(usb_end).Length < switch_notch_center.sub(usb_start).Length:
        usb_start = usb_end
        usb_direction = usb_direction.negative()
    usb_width = (
        usb_vector.Length
        + USB_NOTCH_PAST_SHARED_CORNER_MM
        + USB_NOTCH_PAST_FAR_CORNER_MM
    )
    usb_notch_center = usb_start.add(
        usb_direction
        * (
            (
                usb_vector.Length
                + USB_NOTCH_PAST_FAR_CORNER_MM
                - USB_NOTCH_PAST_SHARED_CORNER_MM
            )
            / 2.0
        )
    )
    tray = cut_rim_notch(
        tray,
        resting_face.OuterWire,
        up,
        usb_notch_center,
        usb_direction,
        usb_width,
        USB_NOTCH_DEPTH_MM,
        arguments.gap,
        arguments.wall,
        arguments.depth,
        "usb",
    )
    ramp_ends = (
        (
            switch_notch_center.sub(
                switch_direction * (POWER_SWITCH_NOTCH_WIDTH_MM / 2.0)
            ),
            switch_direction.negative(),
            POWER_SWITCH_NOTCH_DEPTH_MM,
            "switch end",
        ),
        (
            usb_notch_center.add(usb_direction * (usb_width / 2.0)),
            usb_direction,
            USB_NOTCH_DEPTH_MM,
            "usb end",
        ),
    )
    crest_results = []
    for end_on_outline, away, notch_depth, label in ramp_ends:
        tray, crest_rounded = cut_notch_ramp(
            tray,
            resting_face.OuterWire,
            up,
            end_on_outline,
            away,
            arguments.gap,
            arguments.wall,
            arguments.depth,
            notch_depth,
            label,
        )
        crest_results.append((label, crest_rounded))
    mesh = export_stl(tray, arguments.stl_file)

    board_box = board_shape.BoundBox
    print(f"board:      {board_description}, {board_box.XLength:.2f} x {board_box.YLength:.2f} mm, "
          f"{thickness:.2f} mm thick, outline face {outline_face_pair[0].Area:.1f} mm2")
    print(f"components: protrude {above:.2f} mm above / {below:.2f} mm below the board")
    print(f"opening:    toward {'+' if up.dot(axis) > 0 else '-'}{axis_name(axis)}"
          f"{' (flipped)' if arguments.flip else ''}")
    print(f"tray:       gap {arguments.gap} mm, wall {arguments.wall} mm, "
          f"floor {arguments.floor} mm, depth {arguments.depth} mm "
          f"({arguments.floor + arguments.depth:.1f} mm overall), "
          f"volume {tray.Volume / 1000.0:.2f} cm3")
    print(f"corners:    every bend {max(corner_radius - arguments.wall, 0.0):.2f} mm "
          f"inside / {corner_radius:.2f} mm outside, concentric")
    print(f"standoffs:  {len(hole_centers)} posts at the board's "
          f"{MOUNTING_HOLE_DIAMETER_MM} mm drills, {arguments.standoff_diameter} mm "
          f"wide, {arguments.standoff_hole_diameter} mm bore, "
          f"{arguments.standoff_height} mm tall")
    if arguments.ledge_width > 0:
        print(f"ledge:      {arguments.ledge_width} mm wide along the cavity wall, "
              f"{arguments.standoff_height} mm tall, "
              f"{arguments.ledge_width - arguments.gap:.2f} mm under the board edge")
    print(f"notch:      {POWER_SWITCH_NOTCH_WIDTH_MM} x "
          f"{POWER_SWITCH_NOTCH_DEPTH_MM} mm rim cut for {POWER_SWITCH_NAME} "
          f"at the wall segment near ({switch_notch_center.x:.2f}, "
          f"{switch_notch_center.y:.2f})")
    print(f"notch:      {usb_width:.1f} x {USB_NOTCH_DEPTH_MM} mm rim cut "
          f"for the USB cable over the whole neighbouring segment near "
          f"({usb_notch_center.x:.2f}, {usb_notch_center.y:.2f}), merged with "
          f"the switch notch")
    for label, crest_rounded in crest_results:
        crest_note = (
            f"crest rounded r{NOTCH_CREST_RADIUS_MM}"
            if crest_rounded
            else "crest left sharp (fillet failed)"
        )
        print(f"ramp:       {NOTCH_RAMP_MM} mm slope into the notch at the "
              f"{label}, {crest_note}")
    print(f"wrote:      {arguments.stl_file} ({mesh.CountFacets} facets)")


def axis_name(axis):
    for name, direction in (("Z", App.Vector(0, 0, 1)),
                            ("Y", App.Vector(0, 1, 0)),
                            ("X", App.Vector(1, 0, 0))):
        if abs(axis.dot(direction)) > 0.999:
            return name
    return f"({axis.x:.2f},{axis.y:.2f},{axis.z:.2f})"


run_and_exit(main)
