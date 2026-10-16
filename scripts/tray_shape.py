"""The tray's shape, as far as parts built around it need to know it.

Which way the tray opens, the outline helpers its walls are built
from (sharp-corner rebuild, uniform corner fillets), the corner
radius those walls get, the tray's dimension defaults, and where the
power switch and USB
windows open in its wall: the point on the outline, the directions
along the wall and out of it, and the height band above the floor.
export_tray.py builds the tray from these, and export_case.py shares
them so the case's shells follow the tray's outside and line up with
its windows.
Like board_step.py this module has no entry point, so it is safe to
import from the export scripts and probes.
"""

import math

import FreeCAD as App
import Part

from board_step import deduplicate_shapes, shapes_with_solids

# The tray's dimensions, all in mm: export_tray.py's defaults, which
# it overrides per run with key=value command line words. The corner
# radii derive from gap and wall.
DEFAULT_GAP_MM = 0.4  # clearance between PCB edge and cavity wall
DEFAULT_WALL_MM = 0.8  # wall thickness (two nozzle widths)
DEFAULT_FLOOR_MM = 1.2  # floor thickness
DEFAULT_DEPTH_MM = 11.9  # cavity depth, floor top to rim (overall height = depth + floor)
DEFAULT_STANDOFF_HEIGHT_MM = 8.0  # insert standoff height above the floor

# The battery switch sits on the board's underside with its lever
# reaching through the wall, so the wall gets a window over the
# outline segment nearest the switch, from just below the switch body
# to just above the board's underside. The switch position comes from
# the board sources (the STEP carries no component bodies); the body's
# 1.4 mm hang below the board was measured on the package's 3D model
# as LibrePCB places it. The rest of the switch's measurements, the
# window's width and the pocket around it for the body are
# export_tray.py's.
POWER_SWITCH_NAME = "S1"
POWER_SWITCH_BODY_BELOW_BOARD_MM = 1.4
WINDOW_MARGIN_MM = 0.5  # switch window and pocket edges beyond the body: below, above and per side

# The nice!nano hangs under the board with its USB-C receptacle
# opening onto the board outline, so the wall gets a second window
# over the outline segment nearest the connector. The connector end is
# the far end of the nice!nano package along the footprint's +Y axis,
# 18.7 mm from the footprint origin (the center of the pin rows).
# How deep the nano hangs was measured on the real parts (user,
# 2026-10-12), since the package model gets it wrong: the nano is
# soldered to pins and sits flush on Mill-Max sockets with its
# component side facing the board, so its PCB starts the sockets'
# height below the board (2.56 mm on the left half, 4.3 mm on the
# right, where the model assumes 2.75 mm). export_tray.py has the rest
# of those measurements (the nano's PCB and its connector's shell).
MCU_NAME = "U1"
MCU_USB_END_OFFSET_MM = 18.7
LEFT_NANO_SOCKET_HEIGHT_MM = 2.56
RIGHT_NANO_SOCKET_HEIGHT_MM = 4.30

# On the soldered left half the receptacle's mouth sits only 0.56 mm
# behind the wall's outer face, so the wall hugs the connector. The
# window was measured on that half as the earlier one (14 x 8 mm, sized
# for a plug's overmold, centered 3.35 mm below the board where the
# package model puts the receptacle, along the wall at the outline
# point nearest the connector end) with its top edge pulled in 1.0 mm,
# its bottom edge 2.5 mm, its end nearer the power switch 2.0 mm and
# its other end 1.5 mm (its width, USB_WINDOW_WIDTH_MM, is
# export_tray.py's). The right half gets the same window, lowered by
# how much taller its nano's sockets are (1.74 mm), since its nano is
# the same part mounted the same way. Its shift away from the switch
# stays in board coordinates, which assumes the shift's unknown cause
# follows the board. If it follows the nano instead, it belongs on the
# other side there (the shell then still clears the window by
# 0.28 mm).
USB_WINDOW_HEIGHT_MM = 4.5
LEFT_USB_WINDOW_CENTER_BELOW_BOARD_MM = 2.60
USB_WINDOW_SHIFT_AWAY_FROM_SWITCH_MM = 0.25

# Implementation tuning, rarely worth touching.
CORNER_FIT_SAFETY = 0.95  # margin on the largest corner radius that fits
MINIMUM_FILLET_RADIUS_MM = 0.01  # below this a fillet is skipped as moot
SHARPEN_MAX_CORNER_RADIUS_MM = 3.0  # outline arcs above this are not corners


def tray_opens_toward_positive_axis(above, below, axis, right):
    """Whether a half's tray opens toward +axis, the board outline
    face's normal, given how far components protrude past the board
    along +axis (`above`) and -axis (`below`): toward the side where
    they protrude the furthest, so the bare(r) side rests on the floor.
    With symmetric protrusion (THT bodies against lead stubs, or a
    bare-board STEP) it falls back to the convention that the cavity
    opens upward. The right half (`right` true) is built with the
    board's other side up, so its tray opens the other way."""
    if abs(above - below) < 0.01:
        toward_positive = axis.z >= 0
    else:
        toward_positive = above > below
    return toward_positive != right


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
    a large arc means the outline has a curved edge the tray's
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


def tray_corner_radius(outer_wire, gap, wall):
    """The corner radius on the outside of every bend of the tray's
    wall: gap + wall, capped by what the outer wall's sharp-corner
    polygon (`outer_wire`, the sharpened outline offset by gap + wall)
    can fit at all of its corners, less the CORNER_FIT_SAFETY margin
    and rounded down to 0.01 mm."""
    return min(
        gap + wall,
        math.floor(100.0 * CORNER_FIT_SAFETY * max_uniform_corner_radius(outer_wire))
        / 100.0,
    )


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


def wall_outward(outline_wire, center_on_edge, direction, up):
    """The horizontal direction pointing out of the board at a point on
    the outline, perpendicular to the wall direction there: the side of
    the segment on which a point just off the outline lies outside the
    board (the bounding box center would mislead on the short risers of
    a stepped edge)."""
    outward = direction.cross(up)
    probe = center_on_edge.add(outward * 0.05)
    if Part.Face(outline_wire).isInside(probe, 1e-6, True):
        outward = outward.negative()
    return outward


def switch_window_center_and_direction(segments, switch_position):
    """(center on the outline, direction along the wall) of the power
    switch window: the closest point of the outline segment nearest
    the switch."""
    _index, center, direction = nearest_outline_segment(segments, switch_position)
    return center, direction


def switch_window_height_band(board_underside):
    """(bottom, top) of the power switch window above the floor, with
    the board's underside `board_underside` above it: from
    WINDOW_MARGIN_MM below the switch body to WINDOW_MARGIN_MM above
    the board's underside."""
    bottom = board_underside - POWER_SWITCH_BODY_BELOW_BOARD_MM - WINDOW_MARGIN_MM
    top = board_underside + WINDOW_MARGIN_MM
    return bottom, top


def usb_connector_end(mcu_placement):
    """The nice!nano's USB connector end in board coordinates, given
    the microcontroller's placement from the board sources."""
    return mcu_placement.map_point(App.Vector(0.0, MCU_USB_END_OFFSET_MM, 0.0))


def usb_window_center_away_from_switch(
    usb_outline_point, usb_direction, switch_window_center
):
    """The USB window center on the outline: the outline point nearest
    the connector end moved USB_WINDOW_SHIFT_AWAY_FROM_SWITCH_MM along
    the wall, away from the power switch window."""
    toward_switch = usb_direction.dot(switch_window_center.sub(usb_outline_point))
    if abs(toward_switch) < 1.0:
        raise SystemExit(
            "error: the power switch window is not off to either side of the "
            "USB window, cannot tell which way is away from it"
        )
    switch_side = 1.0 if toward_switch > 0 else -1.0
    return usb_outline_point.add(
        usb_direction * (-switch_side * USB_WINDOW_SHIFT_AWAY_FROM_SWITCH_MM)
    )


def usb_window_center_and_direction(segments, usb_end, switch_window_center):
    """(center on the outline, direction along the wall) of the USB
    window: the closest point of the outline segment nearest the
    connector end, moved away from the power switch window by
    usb_window_center_away_from_switch()."""
    _index, usb_outline_point, usb_direction = nearest_outline_segment(
        segments, usb_end
    )
    center = usb_window_center_away_from_switch(
        usb_outline_point, usb_direction, switch_window_center
    )
    return center, usb_direction


def nano_socket_height_for_half(right):
    """The height of the nice!nano's sockets on the right half (`right`
    true) or the left one: how far below the board its PCB starts."""
    return RIGHT_NANO_SOCKET_HEIGHT_MM if right else LEFT_NANO_SOCKET_HEIGHT_MM


def usb_window_height_band(board_underside, right):
    """(bottom, top) of the USB window above the floor on the right half
    (`right` true) or the left one, with the board's underside
    `board_underside` above the floor: USB_WINDOW_HEIGHT_MM tall,
    centered where it was measured on the left half, lowered on the
    right half by how much taller its nano's sockets are."""
    middle = board_underside - (
        LEFT_USB_WINDOW_CENTER_BELOW_BOARD_MM
        + nano_socket_height_for_half(right)
        - LEFT_NANO_SOCKET_HEIGHT_MM
    )
    bottom = middle - USB_WINDOW_HEIGHT_MM / 2.0
    top = middle + USB_WINDOW_HEIGHT_MM / 2.0
    return bottom, top
