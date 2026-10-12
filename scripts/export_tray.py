"""Export a 3D-printable PCB tray (STL) from the board's STEP model.

Runs headless under FreeCAD's console interpreter. The leading "--pass"
makes freecadcmd forward the remaining arguments to this script; the
options are key=value words (not --flags) because freecadcmd's own
option parser intercepts dash-prefixed arguments even after "--pass"
(observed on FreeCAD 1.0.0):

    freecadcmd scripts/export_tray.py --pass <pcb.step> <tray.stl> \
        [key=value ...] [flip] [right]

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
protrude the furthest, so the bare(r) side rests on the tray floor; a
bare-board STEP (no component bodies) opens toward the board's top
side. Pass the word "flip" to override. The tray is positioned in
board coordinates: the cavity floor touches the board's resting face.

The right half uses the same board turned over, so its tray is the
same build with the board's other side up (the word "right"), where
that half's switches and hotswap sockets sit; afterwards the tray is
turned through 180 degrees about the X axis so it prints opening-up
like the left one. That is not a mirror of the left tray: the sockets
that reach the ledge on the left half do not on the right, so the
right tray has no ledge notches, and its ledge reliefs follow that
half's sockets and the height of its nano's sockets.

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

The battery switch (POWER_SWITCH_NAME) and the microcontroller with
its USB connector (MCU_NAME) are mounted on the board's underside, the
switch lever reaching through the wall and the connector opening onto
it, so the wall gets a window cut through it below the board over the
outline segment nearest each of them: one sized for the switch lever's
travel, one for a USB-C plug. The plug's window hugs the connector,
with rounded corners and both faces of the wall chamfered around it:
measured on the soldered left half, and lowered on the right half by
how much taller its nano's sockets are. The ledge behind the wall is
cut away over the same stretch. The switch and the microcontroller are
located via the board sources, since the STEP carries no component
bodies. The switch's reach below the board comes from its package 3D
model, the nano's from measurements (see the constants). The switch
body is wider than its window and comes close to the wall, so around
that window the wall's inner face gets a pocket over the body's width,
leaving a thin outer skin. The nano behind the USB window gets ledge
reliefs (below).

The hotswap sockets hang under the board too, and in the switch
column along the west edge each socket ends in a narrow tab that
reaches the board outline, where the ledge would sit. Every socket
whose tab reaches into the ledge gets a notch cut into the ledge,
through its full width, LEDGE_NOTCH_WIDTH_MM along the wall and
LEDGE_NOTCH_DEPTH_MM down from the ledge top. The tab's tip ends past
the board edge, so the wall's inner face gets a pocket there (behind
the notch, or on its own without a ledge) over the same width and
height, continued up past the ledge top, deep and tall enough to
leave the tip LEDGE_NOTCH_CLEARANCE_MM from the wall. Which sockets
qualify follows from the switch placements in the board sources, so
the notches track the layout.

Beyond that, the ledge is relieved wherever an underside body (the
nice!nano at its measured depth, the sockets and the battery
connector, as convex polygons measured on the populated STEP export)
comes within LEDGE_RELIEF_CLEARANCE_MM of its inner face along a
straight wall segment: through its full width over the body's extent
plus the clearance, down to the body's reach plus a margin, leaving
the wall and the rest of the ledge. The first printed left half bound
on the nano, 0.03 mm from the ledge.

The same bodies are kept clear of the standoffs: wherever one comes
within STANDOFF_RELIEF_CLEARANCE_MM of a standoff in plan view, the
standoff gets a vertical flat on the side facing it, from its top
down to the body's reach plus that clearance. A flat that would
leave less than STANDOFF_RELIEF_MINIMUM_WALL_MM of plastic around the
insert bore is refused.

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
    component_placements,
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

# The battery switch sits on the board's underside with its lever
# reaching through the wall, so the wall gets a window over the
# outline segment nearest the switch, from just below the switch body
# to just above the board's underside. The switch position comes from
# the board sources (the STEP carries no component bodies); its shape
# was measured on the package's 3D model as LibrePCB places it: body
# 7.7 mm wide, hanging 1.4 mm below the board and reaching to 0.09 mm
# inside the outline, lever 1.3 mm wide reaching 1.3 mm past the
# outline. On the assembled first print the body's outer face measured
# 1.13 mm from the tray's outer face, so 0.07 mm past the board edge
# and 0.33 mm from the wall's inner face. Only the lever passes through
# the wall, so the window is sized for its travel: the model shows it
# 0.1 to 1.4 mm off center at one end, so a sweep of 1.4 mm either
# side, which a 5.3 mm window clears by 1.25 mm per side. The body
# gets a pocket in the wall's inner face instead, over its width plus
# WINDOW_MARGIN_MM per side and the window's height band, leaving
# POWER_SWITCH_POCKET_SKIN_MM of the wall outside it (one nozzle
# width); the pocket also clears the ledge behind it.
POWER_SWITCH_NAME = "S1"
POWER_SWITCH_WINDOW_WIDTH_MM = 5.3  # through the wall, clears the lever's travel
POWER_SWITCH_BODY_WIDTH_MM = 7.7
POWER_SWITCH_BODY_BELOW_BOARD_MM = 1.4
POWER_SWITCH_POCKET_SKIN_MM = 0.4
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
# right, where the model assumes 2.75 mm). Its PCB is 1.6 mm thick
# (the model has 1.4 mm), and the receptacle's shell sits flush with
# the nano's underside (the model has it straddling the nano board,
# 0.78 mm past its underside). So the nano and its connector reach
# down to the socket height plus 1.6 mm below the board. The shell's
# 3.16 mm height comes from the model.
MCU_NAME = "U1"
MCU_USB_END_OFFSET_MM = 18.7
LEFT_NANO_SOCKET_HEIGHT_MM = 2.56
RIGHT_NANO_SOCKET_HEIGHT_MM = 4.30
NANO_PCB_THICKNESS_MM = 1.6

# On the soldered left half the receptacle's mouth sits only 0.56 mm
# behind the wall's outer face, so the wall hugs the connector. The
# window was measured on that half as the earlier one (14 x 8 mm, sized
# for a plug's overmold, centered 3.35 mm below the board where the
# package model puts the receptacle, along the wall at the outline
# point nearest the connector end) with its top edge pulled in 1.0 mm,
# its bottom edge 2.5 mm, its end nearer the power switch 2.0 mm and
# its other end 1.5 mm. Its corners are rounded like the connector's
# and both faces of the wall are chamfered around it. The right half
# gets the same window, lowered by how much taller its nano's sockets
# are (1.74 mm), since its nano is the same part mounted the same way.
# Its shift away from the switch stays in board coordinates, which
# assumes the shift's unknown cause follows the board. If it follows
# the nano instead, it belongs on the other side there (the shell then
# still clears the window by 0.28 mm).
USB_WINDOW_WIDTH_MM = 10.5
USB_WINDOW_HEIGHT_MM = 4.5
LEFT_USB_WINDOW_CENTER_BELOW_BOARD_MM = 2.60
USB_WINDOW_SHIFT_AWAY_FROM_SWITCH_MM = 0.25
# The nano's package model has the receptacle shell ("usb4520-03-0-a
# v1") 8.94 x 3.16 mm at its mouth with a 1.28 mm outer corner radius.
# The measured chain above puts the left shell 1.00 to 4.16 mm below
# the board (the right one 2.74 to 5.90 mm), its center 0.02 mm above
# the window's, so the window clears it by about 0.67 mm above and
# below. Across, the pull-ins center it with 0.78 mm to spare on each
# side. A 1.28 + 0.67 = 1.95 mm radius makes the corners concentric
# with the shell's vertically.
USB_WINDOW_CORNER_RADIUS_MM = 1.95
USB_WINDOW_CHAMFER_MM = 0.2  # 45 degrees, on the wall's outer and inner faces

# The key switches' hotswap sockets (Kailh Choc PG1350 with the
# CPG135001S001 socket) hang 2.0 mm under the board, and each ends in
# a 1.7 mm wide tab whose tip lies at the given footprint coordinates,
# measured on LibrePCB's populated STEP export. In the column along
# the west edge that tip reaches 0.2 mm past the board outline, into
# the ledge, so the ledge gets a notch there: LEDGE_NOTCH_WIDTH_MM
# along the wall centered on the tip, LEDGE_NOTCH_DEPTH_MM down from
# the ledge top (the socket plus solder needs 2 mm of each), through
# the ledge's full width. A socket qualifies when its tip comes within
# LEDGE_NOTCH_CLEARANCE_MM of the ledge's inner face. Only switches
# whose sockets face the cavity count: those on the side away from the
# opening. With the default gap the tip then ends 0.17 mm from the
# wall, less than a print's swelling, so the wall's inner face there
# gets a pocket over the notch's width, deep enough to leave the tip
# LEDGE_NOTCH_CLEARANCE_MM from the wall (0.33 mm deep, leaving
# 0.47 mm of wall), also without a ledge, since the tip's distance to
# the wall does not depend on it. It reaches from the notch's bottom to
# LEDGE_NOTCH_CLEARANCE_MM above the ledge top, since the tab's top
# sits only 0.17 mm under the board and a pocket ending at the ledge
# top left it 0.24 mm from the wall's edge there.
KEY_SWITCH_NAME_PATTERN = re.compile(r"S[0-9]{3}")
HOTSWAP_SOCKET_TAB_TIP_MM = (-3.70, 9.28)
LEDGE_NOTCH_WIDTH_MM = 3.0
LEDGE_NOTCH_DEPTH_MM = 3.0
LEDGE_NOTCH_CLEARANCE_MM = 0.5

# Other underside bodies come closer to the ledge than a print's
# swelling allows, so the ledge is relieved for them: wherever a body
# comes within LEDGE_RELIEF_CLEARANCE_MM of the ledge's inner face
# along a straight wall segment, the ledge is cut through its full
# width over the body's extent along that segment plus the clearance
# at both ends, from the ledge top down to the body's reach below the
# board plus LEDGE_RELIEF_MARGIN_BELOW_MM. The wall stays. Bodies are
# convex polygons in footprint coordinates with a reach below the
# board, measured on the populated STEP export like the tab tip: the
# nice!nano's PCB and its USB-C receptacle (which reaches past the
# PCB's end) as rectangles, both reaching down to the nano's underside
# on that half (see the nano constants above), the battery connector
# (below) as a rectangle, and the hotswap socket as its two offset
# lobes and its two 1.7 mm end tabs, corners in order around each. The
# lobe nearer the tab tip has its corner beside the tab rounded with
# 0.8 mm, so its polygon replaces that corner with a 45 degree chamfer
# just outside the round: as a rectangle corner it stood 0.39 mm proud
# of the body right where the standoffs beside S150 and S141 face it.
# Inside the west column's notches a tab's relief finds nothing left
# to cut; at the step corners of the south edge, where the notch logic
# passes (the tab tip is nearest a corner, not a straight stretch), it
# is what clears the tab. The first printed left half bound on the
# nano's north edge, 0.03 mm from the ledge.
MCU_BODY_RECTANGLES_MM = (  # (part, x range, y range), reach per half
    ("PCB", (-8.90, 8.90), (-15.45, 17.75)),
    ("USB-C receptacle", (-5.85, 5.85), (11.51, 18.71)),
)
HOTSWAP_SOCKET_POLYGONS_MM = (  # (corners, reach below the board)
    (  # lobe
        ((-8.22, -2.25), (-3.57, -2.25), (-3.57, 2.25), (-8.22, 2.25)),
        2.02,
    ),
    (  # lobe, its corner beside the tab chamfered
        ((-6.02, 2.25), (-1.37, 2.25), (-1.37, 7.60), (-5.47, 7.60), (-6.02, 7.05)),
        2.02,
    ),
    (  # tab, tip at HOTSWAP_SOCKET_TAB_TIP_MM
        ((-4.54, 7.60), (-2.86, 7.60), (-2.86, 9.28), (-4.54, 9.28)),
        2.02,
    ),
    (  # tab at the other end
        ((-6.74, -3.87), (-5.06, -3.87), (-5.06, -2.25), (-6.74, -2.25)),
        2.02,
    ),
)
LEDGE_RELIEF_CLEARANCE_MM = 0.5
LEDGE_RELIEF_MARGIN_BELOW_MM = 0.5

# The battery connector (a JST PH S2B-PH-K lying on the board's
# underside) measured on the populated STEP export like the sockets:
# a 5.9 x 7.6 mm body reaching 4.85 mm below the board. It is J1 on
# the left half and J2 on the right, the same part turned over at the
# same position.
LEFT_BATTERY_CONNECTOR_NAME = "J1"
RIGHT_BATTERY_CONNECTOR_NAME = "J2"
BATTERY_CONNECTOR_RECTANGLE_MM = ((-2.95, 2.95), (-3.75, 3.85))  # x range, y range
BATTERY_CONNECTOR_BELOW_BOARD_MM = 4.85

# Wherever an underside body (the ones above) comes within
# STANDOFF_RELIEF_CLEARANCE_MM of a standoff in plan view, the
# standoff gets a vertical flat on the side facing it: a plane
# perpendicular to the direction from the standoff's center to the
# body's nearest point, the clearance short of that point. The body is
# convex, so all of it then lies at least the clearance beyond the
# flat. The flat runs from the standoff top down to the body's reach
# below the board plus the clearance, never below the floor, so the
# full standoff below it keeps the clearance from the body's bottom
# edge too (with the ledge reliefs' 0.5 mm margin there, S150 ended
# up 0.70 mm from it). The clearance is twice the ledge reliefs'
# because at 0.5 mm the close spots would barely change (by their
# footprints, socket S150 0.49 mm from a standoff would get a 0.01 mm
# flat, socket S141 at 0.63 mm and the battery connector at 0.76 mm
# none), the standoffs have 1.3 mm of plastic around the bore to
# spare, and the board can shift about 0.2 mm in the cavity before the
# screws pull it into place. A flat that would leave less than
# STANDOFF_RELIEF_MINIMUM_WALL_MM of plastic between it and the insert
# bore is refused (the closest, S150's, leaves 0.79 mm).
STANDOFF_RELIEF_CLEARANCE_MM = 1.0
STANDOFF_RELIEF_MINIMUM_WALL_MM = 0.6

# Implementation tuning, rarely worth touching.
CORNER_FIT_SAFETY = 0.95  # margin on the largest corner radius that fits
MINIMUM_FILLET_RADIUS_MM = 0.01  # below this a fillet is skipped as moot
CAVITY_CUT_EXTRA_MM = 1.0  # cavity overshoot above the rim for a clean cut
SHARPEN_MAX_CORNER_RADIUS_MM = 3.0  # outline arcs above this are not corners


USAGE = f"""\
usage: freecadcmd scripts/export_tray.py --pass <pcb.step> <tray.stl>
           [gap={DEFAULT_GAP_MM}] [wall={DEFAULT_WALL_MM}] \
[floor={DEFAULT_FLOOR_MM}] [depth={DEFAULT_DEPTH_MM}] [flip] [right]
           [standoff_height={DEFAULT_STANDOFF_HEIGHT_MM}] \
[standoff_diameter={DEFAULT_STANDOFF_DIAMETER_MM}] \
[standoff_hole_diameter={DEFAULT_STANDOFF_HOLE_DIAMETER_MM}] \
[ledge_width={DEFAULT_LEDGE_WIDTH_MM}] [relief_clearance={LEDGE_RELIEF_CLEARANCE_MM}]

  gap     clearance between PCB edge and cavity wall, mm
  wall    tray wall thickness, mm
  floor   tray floor thickness, mm
  depth   cavity depth from the floor's top to the rim, mm
  flip    open the cavity toward the opposite side of the automatic choice
  right   build the right half's tray: the board's other side up (that
          half's switches and sockets), turned opening-up for printing
  standoff_height         insert standoff height above the floor, mm
  standoff_diameter       insert standoff outer diameter, mm
  standoff_hole_diameter  bore for the heat-set insert, mm
  ledge_width             PCB support ledge width from the cavity wall, mm;
                          the ledge is standoff_height tall, 0 disables it
  relief_clearance        an underside body closer than this to the ledge
                          gets the ledge cut away beside it, mm\
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
        self.relief_clearance = LEDGE_RELIEF_CLEARANCE_MM
        self.flip = False
        self.right = False


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
        "relief_clearance",
    )
    positionals = []
    for argument in argument_list:
        if argument == "flip":
            arguments.flip = True
        elif argument == "right":
            arguments.right = True
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


def cut_wall_window(
    tray, outline_wire, up, center_on_edge, direction, width, bottom, top,
    gap, wall, ledge_width, label,
):
    """Open a window through the wall and the ledge behind it: `width`
    along the wall centered on `center_on_edge`, from `bottom` to `top`
    above the floor, spanning the full wall thickness."""
    if top <= bottom:
        raise SystemExit(f"error: the {label} window has no height")
    outward = wall_outward(outline_wire, center_on_edge, direction, up)
    half_width = width / 2.0
    height = top - bottom
    ledge_reach = max(ledge_width - gap, 0.0)  # how far the ledge reaches under the board
    inner = -(ledge_reach + 0.5)  # start inside the cavity, past the ledge
    outer = gap + wall + 0.5
    base = center_on_edge.add(up * bottom)
    corners = [
        base.add(direction * -half_width).add(outward * inner),
        base.add(direction * half_width).add(outward * inner),
        base.add(direction * half_width).add(outward * outer),
        base.add(direction * -half_width).add(outward * outer),
    ]
    cutter = Part.Face(Part.makePolygon(corners + [corners[0]])).extrude(
        up * height
    )
    volume_before = tray.Volume
    result = tray.cut(cutter)
    if not result.isValid() or len(result.Solids) != 1:
        raise SystemExit(f"error: cutting the {label} window broke the solid")
    removed_volume = volume_before - result.Volume
    wall_volume = wall * width * height
    if not 0.99 * wall_volume <= removed_volume <= (outer - inner) * width * height:
        raise SystemExit(
            f"error: the {label} window removed {removed_volume:.1f} mm3, "
            f"expected at least the wall's {wall_volume:.1f} mm3; geometry is off"
        )
    solid = result.Solids[0]
    wall_center = center_on_edge.add(outward * (gap + wall / 2.0))
    middle = (bottom + top) / 2.0
    if solid.isInside(wall_center.add(up * middle), 1e-6, True):
        raise SystemExit(f"error: the {label} window did not open the wall")
    for z, where in ((bottom - 0.3, "below"), (top + 0.3, "above")):
        if not solid.isInside(wall_center.add(up * z), 1e-6, True):
            raise SystemExit(f"error: the wall {where} the {label} window is missing")
    if ledge_reach > 0:
        ledge_probe = center_on_edge.sub(outward * (ledge_reach / 2.0)).add(up * middle)
        if solid.isInside(ledge_probe, 1e-6, True):
            raise SystemExit(f"error: the {label} window left the ledge in place")
    return result


def rounded_rectangle_wire(center, along_axis, up_axis, half_width, half_height, radius):
    """A rectangle with rounded corners in the plane spanned by two unit
    vectors, centered on `center`: `half_width` along `along_axis`,
    `half_height` along `up_axis`. Its edges always run arc, line, arc,
    line, ... from the same corner, so two such wires loft edge to
    edge."""

    def point(along, height):
        return center.add(along_axis * along).add(up_axis * height)

    inner_along = half_width - radius
    inner_height = half_height - radius
    corner_centers = (  # counterclockwise from the bottom one along +along_axis
        (inner_along, -inner_height),
        (inner_along, inner_height),
        (-inner_along, inner_height),
        (-inner_along, -inner_height),
    )
    arcs = []
    for index, (corner_along, corner_height) in enumerate(corner_centers):
        start = -90.0 + 90.0 * index
        arcs.append([
            point(
                corner_along + radius * math.cos(math.radians(start + step)),
                corner_height + radius * math.sin(math.radians(start + step)),
            )
            for step in (0.0, 45.0, 90.0)
        ])
    edges = []
    for index, arc in enumerate(arcs):
        edges.append(Part.Arc(*arc).toShape())
        edges.append(Part.LineSegment(arc[2], arcs[(index + 1) % 4][0]).toShape())
    return Part.Wire(edges)


def rounded_rectangle_area(half_width, half_height, radius):
    return 4.0 * half_width * half_height - (4.0 - math.pi) * radius**2


def rounded_rectangle_perimeter(half_width, half_height, radius):
    return 4.0 * (half_width + half_height) - 2.0 * (4.0 - math.pi) * radius


def chamfer_volume(perimeter, size):
    """The volume a 45 degree chamfer of `size` takes out of a face
    around a rounded rectangle opening of the given perimeter: the
    opening grows by `size` minus the depth into the face."""
    return perimeter * size**2 / 2.0 + math.pi * size**3 / 3.0


def cut_rounded_wall_window(
    tray, outline_wire, up, center_on_edge, direction, width, bottom, top,
    corner_radius, chamfer, gap, wall, ledge_width, label,
):
    """Open a window with rounded corners through the wall and the
    ledge behind it: `width` along the wall centered on
    `center_on_edge`, from `bottom` to `top` above the floor, its
    corners rounded with `corner_radius`, and both faces of the wall
    chamfered by `chamfer` at 45 degrees around it. The profile lies in
    the wall's plane and is extruded across the wall. Each chamfer is a
    ruled loft from the profile grown by the chamfer at the face (and
    on past it a little, so no cutter face lies in the wall's) to the
    profile itself at the chamfer's depth."""
    half_width = width / 2.0
    half_height = (top - bottom) / 2.0
    if not 0.0 < corner_radius < min(half_width, half_height):
        raise SystemExit(
            f"error: the {label} window's corner radius {corner_radius} mm "
            f"does not fit its {width:.2f} x {top - bottom:.2f} mm"
        )
    if not 0.0 < chamfer < wall / 2.0:
        raise SystemExit(
            f"error: the {label} window's chamfer {chamfer} mm must be under "
            f"half the {wall} mm wall"
        )
    outward = wall_outward(outline_wire, center_on_edge, direction, up)
    middle = center_on_edge.add(up * ((bottom + top) / 2.0))
    ledge_reach = max(ledge_width - gap, 0.0)  # how far the ledge reaches under the board
    overshoot = 0.05  # the chamfer cutters run on past the wall's faces

    def profile(across, grow):
        return rounded_rectangle_wire(
            middle.add(outward * across), direction, up,
            half_width + grow, half_height + grow, corner_radius + grow,
        )

    inner = -(ledge_reach + 0.5)  # start inside the cavity, past the ledge
    outer = gap + wall + 0.5
    through = Part.Face(profile(inner, 0.0)).extrude(outward * (outer - inner))
    chamfers = [
        Part.makeLoft(
            [profile(face + outward_sign * overshoot, chamfer + overshoot),
             profile(face - outward_sign * chamfer, 0.0)],
            True,
            True,
        )
        for face, outward_sign in ((gap + wall, 1.0), (gap, -1.0))
    ]
    cutter = through.multiFuse(chamfers)
    if not cutter.isValid() or len(cutter.Solids) != 1:
        raise SystemExit(f"error: the {label} window's cutter is not one solid")
    volume_before = tray.Volume
    result = tray.cut(cutter)
    if not result.isValid() or len(result.Solids) != 1:
        raise SystemExit(f"error: cutting the {label} window broke the solid")
    removed_volume = volume_before - result.Volume
    area = rounded_rectangle_area(half_width, half_height, corner_radius)
    perimeter = rounded_rectangle_perimeter(half_width, half_height, corner_radius)
    expected_volume = area * wall + 2.0 * chamfer_volume(perimeter, chamfer)
    if ledge_width > 0:
        # The ledge in front of the wall goes too, as far as the window
        # and the inner chamfer's overshoot reach into it.
        expected_volume += (
            area * ledge_width
            + chamfer_volume(perimeter, chamfer + overshoot)
            - chamfer_volume(perimeter, chamfer)
        )
    if abs(removed_volume - expected_volume) > 0.002 * expected_volume + 0.01:
        raise SystemExit(
            f"error: the {label} window removed {removed_volume:.2f} mm3, "
            f"expected {expected_volume:.2f} mm3; geometry is off"
        )
    validate_rounded_window(
        result.Solids[0], middle, direction, outward, up, half_width,
        half_height, corner_radius, chamfer, gap, wall, ledge_reach, label,
    )
    return result


def validate_rounded_window(
    solid, middle, direction, outward, up, half_width, half_height,
    corner_radius, chamfer, gap, wall, ledge_reach, label,
):
    """Probe a window cut by cut_rounded_wall_window around its center
    `middle`: open inside its edges and solid just outside them at mid
    wall, the chamfers open just outside the straight edges near both
    faces but no wider than the chamfer, and the corners rounded."""

    def is_solid(along, across, height):
        point = middle.add(direction * along).add(outward * across).add(up * height)
        return solid.isInside(point, 1e-6, True)

    mid_wall = gap + wall / 2.0
    near_faces = (gap + chamfer / 4.0, gap + wall - chamfer / 4.0)
    if is_solid(0.0, mid_wall, 0.0):
        raise SystemExit(f"error: the {label} window did not open the wall")
    if ledge_reach > 0 and is_solid(0.0, -ledge_reach / 2.0, 0.0):
        raise SystemExit(f"error: the {label} window left the ledge in place")
    for along_sign, height_sign in ((1, 0), (-1, 0), (0, 1), (0, -1)):

        def beyond_edge(distance):
            return (
                along_sign * (half_width + distance),
                height_sign * (half_height + distance),
            )

        along, height = beyond_edge(-0.05)
        if is_solid(along, mid_wall, height):
            raise SystemExit(f"error: the {label} window is smaller than intended")
        along, height = beyond_edge(0.05)
        if not is_solid(along, mid_wall, height):
            raise SystemExit(f"error: the {label} window is larger than intended")
        if any(is_solid(along, across, height) for across in near_faces):
            raise SystemExit(f"error: the {label} window's chamfer is missing")
        along, height = beyond_edge(chamfer + 0.1)
        if not all(is_solid(along, across, height) for across in near_faces):
            raise SystemExit(f"error: the {label} window's chamfer is too wide")
    for along_sign in (1, -1):
        for height_sign in (1, -1):
            corner_along = along_sign * (half_width - corner_radius)
            corner_height = height_sign * (half_height - corner_radius)
            for fraction, want_solid in ((0.6, False), (0.9, True)):
                # Along the corner's diagonal: 0.85 radii out is inside
                # the rounded corner, 1.27 is outside it but still
                # inside the bounding rectangle.
                offset = fraction * corner_radius
                if is_solid(
                    corner_along + along_sign * offset,
                    mid_wall,
                    corner_height + height_sign * offset,
                ) != want_solid:
                    raise SystemExit(
                        f"error: the {label} window's corners are not rounded "
                        f"with {corner_radius} mm"
                    )


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


def cut_ledge_notch(
    tray, outline_wire, up, center_on_edge, direction, width, depth, ledge_top,
    gap, wall, ledge_width, label,
):
    """Cut a notch into the ledge, leaving the wall alone: `width`
    along the wall centered on `center_on_edge`, `depth` down from the
    ledge top, through the ledge's full width up to the wall's inner
    face."""
    outward = wall_outward(outline_wire, center_on_edge, direction, up)
    ledge_reach = ledge_width - gap  # how far the ledge reaches under the board
    half_width = width / 2.0
    inner = -(ledge_reach + 0.5)  # start inside the cavity, past the ledge
    outer = gap  # the wall's inner face
    base = center_on_edge.add(up * (ledge_top - depth))
    corners = [
        base.add(direction * -half_width).add(outward * inner),
        base.add(direction * half_width).add(outward * inner),
        base.add(direction * half_width).add(outward * outer),
        base.add(direction * -half_width).add(outward * outer),
    ]
    cutter = Part.Face(Part.makePolygon(corners + [corners[0]])).extrude(
        up * (depth + CAVITY_CUT_EXTRA_MM)
    )
    volume_before = tray.Volume
    result = tray.cut(cutter)
    if not result.isValid() or len(result.Solids) != 1:
        raise SystemExit(f"error: cutting the {label} ledge notch broke the solid")
    removed_volume = volume_before - result.Volume
    expected_volume = ledge_width * width * depth
    if abs(removed_volume - expected_volume) > 0.02 * expected_volume:
        raise SystemExit(
            f"error: the {label} ledge notch removed {removed_volume:.2f} mm3, "
            f"expected {expected_volume:.2f} mm3; geometry is off"
        )
    solid = result.Solids[0]
    ledge_middle = outward * ((gap - ledge_reach) / 2.0)
    middle_z = ledge_top - depth / 2.0

    def ledge_probe(along, z):
        return center_on_edge.add(direction * along).add(ledge_middle).add(up * z)

    if solid.isInside(ledge_probe(0.0, middle_z), 1e-6, True):
        raise SystemExit(f"error: the {label} ledge notch did not open the ledge")
    wall_probe = center_on_edge.add(outward * (gap + wall / 2.0)).add(up * middle_z)
    if not solid.isInside(wall_probe, 1e-6, True):
        raise SystemExit(f"error: the {label} ledge notch cut into the wall")
    for along, z, where in (
        (-(half_width + 0.3), middle_z, "beside"),
        (half_width + 0.3, middle_z, "beside"),
        (0.0, ledge_top - depth - 0.3, "below"),
    ):
        if not solid.isInside(ledge_probe(along, z), 1e-6, True):
            raise SystemExit(f"error: the ledge {where} the {label} notch is missing")
    return result


def cut_wall_pocket(
    tray, outline_wire, up, center_on_edge, direction, width, bottom, top,
    gap, wall, ledge_width, skin, label,
):
    """Cut a pocket into the wall's inner face and through the ledge
    behind it: `width` along the wall centered on `center_on_edge`, from
    `bottom` to `top` above the floor, leaving `skin` of the wall on the
    outside."""
    if top <= bottom:
        raise SystemExit(f"error: the {label} pocket has no height")
    if not 0.0 < skin < wall:
        raise SystemExit(
            f"error: the {label} pocket skin {skin} mm must be thinner than "
            f"the {wall} mm wall"
        )
    outward = wall_outward(outline_wire, center_on_edge, direction, up)
    half_width = width / 2.0
    height = top - bottom
    ledge_reach = max(ledge_width - gap, 0.0)  # how far the ledge reaches under the board
    inner = -(ledge_reach + 0.5)  # start inside the cavity, past the ledge
    outer = gap + wall - skin
    base = center_on_edge.add(up * bottom)
    corners = [
        base.add(direction * -half_width).add(outward * inner),
        base.add(direction * half_width).add(outward * inner),
        base.add(direction * half_width).add(outward * outer),
        base.add(direction * -half_width).add(outward * outer),
    ]
    cutter = Part.Face(Part.makePolygon(corners + [corners[0]])).extrude(
        up * height
    )
    removable = tray.common(cutter).Volume
    result = tray.cut(cutter)
    if not result.isValid() or len(result.Solids) != 1:
        raise SystemExit(f"error: cutting the {label} pocket broke the solid")
    removed_volume = tray.Volume - result.Volume
    if abs(removed_volume - removable) > 0.02 * removable + 1e-3:
        raise SystemExit(
            f"error: the {label} pocket removed {removed_volume:.2f} mm3, "
            f"expected {removable:.2f} mm3; geometry is off"
        )
    solid = result.Solids[0]
    middle = (bottom + top) / 2.0

    def probe(along, across, z):
        return center_on_edge.add(direction * along).add(outward * across).add(up * z)

    pocket_middle = gap + (wall - skin) / 2.0
    skin_middle = gap + wall - skin / 2.0
    for along in (-(half_width - 0.3), half_width - 0.3):
        if solid.isInside(probe(along, pocket_middle, middle), 1e-6, True):
            raise SystemExit(f"error: the {label} pocket did not open the wall's inner face")
        if not solid.isInside(probe(along, skin_middle, middle), 1e-6, True):
            raise SystemExit(f"error: the {label} pocket cut through the wall's skin")
        if ledge_reach > 0 and solid.isInside(
            probe(along, -ledge_reach / 2.0, middle), 1e-6, True
        ):
            raise SystemExit(f"error: the {label} pocket left the ledge in place")
    for along in (-(half_width + 0.3), half_width + 0.3):
        if not solid.isInside(probe(along, pocket_middle, middle), 1e-6, True):
            raise SystemExit(f"error: the wall beside the {label} pocket is missing")
    return result, removed_volume


def turn_for_printing(tray, up, floor, depth):
    """Turn a tray built opening-down through 180 degrees about the X
    axis so it prints opening-up, and put its floor's underside at
    -floor like a tray built opening-up."""
    if up.z > 0:
        return tray
    tray.rotate(tray.BoundBox.Center, App.Vector(1, 0, 0), 180)
    tray.translate(App.Vector(0, 0, -floor - tray.BoundBox.ZMin))
    box = tray.BoundBox
    if abs(box.ZMin + floor) > 0.01 or abs(box.ZMax - depth) > 0.01:
        raise SystemExit(
            f"error: the turned tray spans z {box.ZMin:.2f}..{box.ZMax:.2f}, "
            f"expected {-floor:.2f}..{depth:.2f}"
        )
    return tray


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


def relieve_ledge(
    tray, cavity_prism, segments, outline_wire, up, corners, reach, label,
    ledge_top, gap, wall, ledge_width, clearance, margin,
):
    """Cut the ledge away wherever a body comes within `clearance` of
    its inner face: for every straight wall segment the body lies
    alongside, through the ledge's full width over the body's extent
    along the segment plus the clearance at both ends, from the ledge
    top down to `reach` plus `margin` below the board. The cutter is
    clipped to the cavity, so it may run past the segment's end around
    a corner (the straight segments stop where the corner arcs begin,
    and a body beside a corner needs the corner's ledge gone too) and
    never touches a wall; a stub shorter than 1 mm left at a segment
    end goes too. `corners` are the corners of the body's convex
    footprint polygon in board coordinates. Returns (tray, reliefs),
    one (center, length, depth, removed volume) per segment that was
    cut."""
    ledge_reach = ledge_width - gap
    depth = reach + margin
    reliefs = []
    for start, vector in segments:
        length = vector.Length
        direction = App.Vector(vector).normalize()
        outward = wall_outward(
            outline_wire, start.add(direction * (length / 2.0)), direction, up
        )
        across = [outward.dot(corner.sub(start)) for corner in corners]
        along = [direction.dot(corner.sub(start)) for corner in corners]
        if max(across) < -(ledge_reach + clearance):
            continue  # clear of this segment's ledge
        if min(across) > gap:
            continue  # wholly outside this segment's wall: not alongside it
        low = min(along) - clearance
        high = max(along) + clearance
        if high < 0.0 or low > length:
            continue  # not alongside this segment
        if low < 1.0:
            low = -(ledge_width + gap)  # take the corner block too
        if length - high < 1.0:
            high = length + ledge_width + gap
        base = start.add(direction * low).add(up * (ledge_top - depth))
        inner = -(ledge_reach + 0.5)  # start inside the cavity, past the ledge
        outer = gap  # the wall's inner face
        polygon = [
            base.add(outward * inner),
            base.add(direction * (high - low)).add(outward * inner),
            base.add(direction * (high - low)).add(outward * outer),
            base.add(outward * outer),
        ]
        cutter = Part.Face(Part.makePolygon(polygon + [polygon[0]])).extrude(
            up * (depth + CAVITY_CUT_EXTRA_MM)
        ).common(cavity_prism)
        removable = tray.common(cutter).Volume if cutter.Solids else 0.0
        if removable < 1e-3:
            continue  # a window or notch already opened this stretch
        volume_before = tray.Volume
        result = tray.cut(cutter)
        if not result.isValid() or len(result.Solids) != 1:
            raise SystemExit(f"error: the {label} ledge relief broke the solid")
        removed = volume_before - result.Volume
        if abs(removed - removable) > 0.02 * removable + 1e-3:
            raise SystemExit(
                f"error: the {label} ledge relief removed {removed:.2f} mm3, "
                f"expected {removable:.2f} mm3; geometry is off"
            )
        center = start.add(direction * ((low + high) / 2.0))
        # The cutter ends at the wall's inner face; make sure no wall that
        # was there is gone (a window may already have opened the wall).
        for along in (low + 0.2, (low + high) / 2.0, high - 0.2):
            wall_probe = start.add(direction * along).add(
                outward * (gap + wall / 2.0)
            ).add(up * (ledge_top - depth / 2.0))
            was_wall = tray.isInside(wall_probe, 1e-6, True)
            if was_wall and not result.Solids[0].isInside(wall_probe, 1e-6, True):
                raise SystemExit(f"error: the {label} ledge relief cut into the wall")
        tray = result
        reliefs.append((center, high - low, depth, removed))
    return tray, reliefs


def rectangle_polygon(x_range, y_range):
    """A footprint rectangle's corners in order around it."""
    (x_low, x_high), (y_low, y_high) = x_range, y_range
    return ((x_low, y_low), (x_high, y_low), (x_high, y_high), (x_low, y_high))


def nearest_footprint_point(corners, center, up):
    """(distance, point) from `center` to the nearest point of a body's
    footprint polygon, in the plane through `center` perpendicular to
    `up`. The distance is zero when `center` lies inside it."""
    flat = [corner.sub(up * up.dot(corner.sub(center))) for corner in corners]
    face = Part.Face(Part.makePolygon(flat + [flat[0]]))
    distance, pairs, _info = face.distToShape(Part.Vertex(center))
    return distance, pairs[0][0]


def circular_segment_area(radius, chord_distance):
    """Area of the part of a circle beyond a chord at `chord_distance`
    from its center."""
    half_chord = math.sqrt(radius**2 - chord_distance**2)
    return radius**2 * math.acos(chord_distance / radius) - chord_distance * half_chord


def relieve_standoffs(
    tray, hole_centers, up, corners, reach, label, standoff_top,
    standoff_radius, bore_radius, clearance, minimum_wall,
):
    """Cut a vertical flat into every standoff the body comes within
    `clearance` of in plan view, on the side facing it: a plane
    perpendicular to the direction from the standoff's center to the
    body's nearest point, `clearance` short of that point. The body is
    convex, so all of it then lies at least `clearance` beyond the
    plane. The flat runs from the standoff top down to `reach` plus
    `clearance` below the board, so the full standoff below it keeps
    that clearance from the body's bottom too, but never below the
    floor's top. `corners` are the corners of the body's footprint
    polygon in board coordinates. Returns (tray, reliefs), one (center,
    flat depth, plastic left around the bore, body distance, flat
    bottom, removed volume) per flat."""
    reliefs = []
    for center in hole_centers:
        distance, nearest = nearest_footprint_point(corners, center, up)
        plane_distance = distance - clearance
        if plane_distance >= standoff_radius:
            continue  # the body clears this standoff
        plastic = plane_distance - bore_radius
        if plastic < minimum_wall:
            raise SystemExit(
                f"error: the {label} standoff relief at ({center.x:.2f}, "
                f"{center.y:.2f}) would leave {plastic:.2f} mm around the insert "
                f"bore, less than {minimum_wall} mm"
            )
        toward_body = nearest.sub(center).normalize()
        along_flat = toward_body.cross(up)
        bottom = max(standoff_top - reach - clearance, 0.0)
        height = standoff_top - bottom
        reach_out = standoff_radius + 0.5  # past the standoff's side
        base = center.add(up * bottom)
        polygon = [
            base.add(toward_body * plane_distance).add(along_flat * -reach_out),
            base.add(toward_body * plane_distance).add(along_flat * reach_out),
            base.add(toward_body * reach_out).add(along_flat * reach_out),
            base.add(toward_body * reach_out).add(along_flat * -reach_out),
        ]
        cutter = Part.Face(Part.makePolygon(polygon + [polygon[0]])).extrude(
            up * (height + CAVITY_CUT_EXTRA_MM)
        )
        removable = tray.common(cutter).Volume
        if removable < 1e-3:
            continue  # an earlier flat on this standoff already opened it
        segment_volume = circular_segment_area(standoff_radius, plane_distance) * height
        if removable > 1.002 * segment_volume + 1e-3:
            raise SystemExit(
                f"error: the {label} standoff relief would remove {removable:.2f} "
                f"mm3, more than the standoff's {segment_volume:.2f} mm3 beyond "
                "the flat; it reaches something else"
            )
        result = tray.cut(cutter)
        if not result.isValid() or len(result.Solids) != 1:
            raise SystemExit(f"error: the {label} standoff relief broke the solid")
        removed = tray.Volume - result.Volume
        if abs(removed - removable) > 0.02 * removable + 1e-3:
            raise SystemExit(
                f"error: the {label} standoff relief removed {removed:.2f} mm3, "
                f"expected {removable:.2f} mm3; geometry is off"
            )
        solid = result.Solids[0]

        def probe(radial, z):
            return center.add(toward_body * radial).add(up * z)

        middle = bottom + height / 2.0
        beyond_flat = (plane_distance + standoff_radius) / 2.0
        if solid.isInside(probe(beyond_flat, middle), 1e-6, True):
            raise SystemExit(f"error: the {label} standoff relief did not open the flat")
        if not solid.isInside(probe((bore_radius + plane_distance) / 2.0, middle), 1e-6, True):
            raise SystemExit(f"error: the {label} standoff relief cut into the bore's wall")
        below = probe(beyond_flat, bottom - 0.3)
        if tray.isInside(below, 1e-6, True) and not solid.isInside(below, 1e-6, True):
            raise SystemExit(f"error: the {label} standoff relief reaches too low")
        tray = result
        reliefs.append(
            (center, standoff_radius - plane_distance, plastic,
             distance - standoff_radius, bottom, removed)
        )
    return tray, reliefs


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

    return tray, corner_radius, cavity_prism


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
    if arguments.right:
        open_toward_positive_axis = not open_toward_positive_axis
    resting_face, up = pick_resting_face(
        outline_face_pair, open_toward_positive_axis
    )

    tray, corner_radius, cavity_prism = build_tray(
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
    _switch_index, switch_window_center, switch_direction = nearest_outline_segment(
        segments, switch_by_name[POWER_SWITCH_NAME]
    )
    board_underside = arguments.standoff_height  # the board rests on the standoffs
    switch_window_bottom = (
        board_underside - POWER_SWITCH_BODY_BELOW_BOARD_MM - WINDOW_MARGIN_MM
    )
    switch_window_top = board_underside + WINDOW_MARGIN_MM
    tray = cut_wall_window(
        tray,
        resting_face.OuterWire,
        up,
        switch_window_center,
        switch_direction,
        POWER_SWITCH_WINDOW_WIDTH_MM,
        switch_window_bottom,
        switch_window_top,
        arguments.gap,
        arguments.wall,
        arguments.ledge_width,
        "switch",
    )
    switch_pocket_width = POWER_SWITCH_BODY_WIDTH_MM + 2.0 * WINDOW_MARGIN_MM
    tray, switch_pocket_volume = cut_wall_pocket(
        tray,
        resting_face.OuterWire,
        up,
        switch_window_center,
        switch_direction,
        switch_pocket_width,
        switch_window_bottom,
        switch_window_top,
        arguments.gap,
        arguments.wall,
        arguments.ledge_width,
        POWER_SWITCH_POCKET_SKIN_MM,
        "switch body",
    )
    mcu_by_name = component_placements(re.compile(re.escape(MCU_NAME)))
    if MCU_NAME not in mcu_by_name:
        raise SystemExit(
            f"error: microcontroller '{MCU_NAME}' not found in the board sources"
        )
    usb_end = mcu_by_name[MCU_NAME].map_point(
        App.Vector(0.0, MCU_USB_END_OFFSET_MM, 0.0)
    )
    _usb_index, usb_outline_point, usb_direction = nearest_outline_segment(
        segments, usb_end
    )
    usb_window_center = usb_window_center_away_from_switch(
        usb_outline_point, usb_direction, switch_window_center
    )
    nano_socket_height = (
        RIGHT_NANO_SOCKET_HEIGHT_MM if arguments.right else LEFT_NANO_SOCKET_HEIGHT_MM
    )
    usb_window_middle = board_underside - (
        LEFT_USB_WINDOW_CENTER_BELOW_BOARD_MM
        + nano_socket_height
        - LEFT_NANO_SOCKET_HEIGHT_MM
    )
    usb_window_bottom = usb_window_middle - USB_WINDOW_HEIGHT_MM / 2.0
    usb_window_top = usb_window_middle + USB_WINDOW_HEIGHT_MM / 2.0
    tray = cut_rounded_wall_window(
        tray,
        resting_face.OuterWire,
        up,
        usb_window_center,
        usb_direction,
        USB_WINDOW_WIDTH_MM,
        usb_window_bottom,
        usb_window_top,
        USB_WINDOW_CORNER_RADIUS_MM,
        USB_WINDOW_CHAMFER_MM,
        arguments.gap,
        arguments.wall,
        arguments.ledge_width,
        "usb",
    )
    switches = component_placements(KEY_SWITCH_NAME_PATTERN)
    battery_connector_name = (
        RIGHT_BATTERY_CONNECTOR_NAME if arguments.right else LEFT_BATTERY_CONNECTOR_NAME
    )
    battery_connector_by_name = component_placements(
        re.compile(re.escape(battery_connector_name))
    )
    if battery_connector_name not in battery_connector_by_name:
        raise SystemExit(
            f"error: battery connector '{battery_connector_name}' not found in the "
            "board sources"
        )
    nano_reach = nano_socket_height + NANO_PCB_THICKNESS_MM
    bodies = [
        (f"{MCU_NAME} {part}", mcu_by_name[MCU_NAME],
         rectangle_polygon(x_range, y_range), nano_reach)
        for part, x_range, y_range in MCU_BODY_RECTANGLES_MM
    ]
    bodies.append((
        f"{battery_connector_name} battery connector",
        battery_connector_by_name[battery_connector_name],
        rectangle_polygon(*BATTERY_CONNECTOR_RECTANGLE_MM),
        BATTERY_CONNECTOR_BELOW_BOARD_MM,
    ))
    for name in sorted(switches):
        if switches[name].flipped == open_toward_positive_axis:
            continue  # its socket faces the opening, not the cavity
        for polygon, reach in HOTSWAP_SOCKET_POLYGONS_MM:
            bodies.append((f"{name} socket", switches[name], polygon, reach))
    body_footprints = [
        (label, [placement.map_point(App.Vector(x, y, 0.0)) for x, y in polygon], reach)
        for label, placement, polygon, reach in bodies
    ]
    ledge_notches = []
    tab_pockets = []
    ledge_reliefs = []
    has_ledge = arguments.ledge_width > arguments.gap
    ledge_reach = arguments.ledge_width - arguments.gap
    for name in sorted(switches):
        placement = switches[name]
        if placement.flipped == open_toward_positive_axis:
            continue  # its socket faces the opening, not the cavity
        tip = placement.map_point(App.Vector(*HOTSWAP_SOCKET_TAB_TIP_MM, 0.0))
        _index, closest, direction = nearest_outline_segment(segments, tip)
        if abs(direction.dot(tip.sub(closest))) > 1e-6:
            continue  # nearest to a corner, not alongside a straight wall
        outward = wall_outward(resting_face.OuterWire, closest, direction, up)
        past_edge = outward.dot(tip.sub(closest))
        if has_ledge and past_edge >= -(ledge_reach + LEDGE_NOTCH_CLEARANCE_MM):
            tray = cut_ledge_notch(
                tray,
                resting_face.OuterWire,
                up,
                closest,
                direction,
                LEDGE_NOTCH_WIDTH_MM,
                LEDGE_NOTCH_DEPTH_MM,
                board_underside,
                arguments.gap,
                arguments.wall,
                arguments.ledge_width,
                f"{name} socket",
            )
            ledge_notches.append((name, closest, past_edge))
        # The tip's distance to the wall does not depend on the ledge.
        pocket_depth = LEDGE_NOTCH_CLEARANCE_MM - (arguments.gap - past_edge)
        if pocket_depth > 0:
            tray, pocket_volume = cut_wall_pocket(
                tray,
                resting_face.OuterWire,
                up,
                closest,
                direction,
                LEDGE_NOTCH_WIDTH_MM,
                board_underside - LEDGE_NOTCH_DEPTH_MM,
                board_underside + LEDGE_NOTCH_CLEARANCE_MM,
                arguments.gap,
                arguments.wall,
                arguments.ledge_width,
                arguments.wall - pocket_depth,
                f"{name} socket tab",
            )
            tab_pockets.append((name, closest, pocket_depth, pocket_volume))
    if has_ledge:
        for label, corners, reach in body_footprints:
            tray, reliefs = relieve_ledge(
                tray, cavity_prism, segments, resting_face.OuterWire, up, corners,
                reach, label, board_underside, arguments.gap, arguments.wall,
                arguments.ledge_width, arguments.relief_clearance,
                LEDGE_RELIEF_MARGIN_BELOW_MM,
            )
            ledge_reliefs.extend((label,) + relief for relief in reliefs)
    standoff_reliefs = []
    for label, corners, reach in body_footprints:
        tray, reliefs = relieve_standoffs(
            tray, hole_centers, up, corners, reach, label, board_underside,
            arguments.standoff_diameter / 2.0, arguments.standoff_hole_diameter / 2.0,
            STANDOFF_RELIEF_CLEARANCE_MM, STANDOFF_RELIEF_MINIMUM_WALL_MM,
        )
        standoff_reliefs.extend((label,) + relief for relief in reliefs)
    if arguments.right:
        tray = turn_for_printing(tray, up, arguments.floor, arguments.depth)
    mesh = export_stl(tray, arguments.stl_file)

    board_box = board_shape.BoundBox
    print(f"board:      {board_description}, {board_box.XLength:.2f} x {board_box.YLength:.2f} mm, "
          f"{thickness:.2f} mm thick, outline face {outline_face_pair[0].Area:.1f} mm2")
    print(f"components: protrude {above:.2f} mm above / {below:.2f} mm below the board")
    print(f"opening:    toward {'+' if up.dot(axis) > 0 else '-'}{axis_name(axis)}"
          f"{' (flipped)' if arguments.flip else ''}"
          f"{' (right half: built with the board turned over, then turned opening-up for printing)' if arguments.right else ''}")
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
    print(f"window:     {POWER_SWITCH_WINDOW_WIDTH_MM} x "
          f"{switch_window_top - switch_window_bottom:.1f} mm through the wall "
          f"for {POWER_SWITCH_NAME}'s lever at the wall segment near "
          f"({switch_window_center.x:.2f}, {switch_window_center.y:.2f}), "
          f"{switch_window_bottom:.2f} to {switch_window_top:.2f} mm above the "
          f"floor (board underside at {board_underside:.2f} mm)")
    print(f"pocket:     {switch_pocket_width:.1f} x "
          f"{switch_window_top - switch_window_bottom:.1f} mm into the wall's inner "
          f"face around that window for {POWER_SWITCH_NAME}'s body, "
          f"{POWER_SWITCH_POCKET_SKIN_MM} mm of wall left outside it, "
          f"{switch_pocket_volume:.1f} mm3")
    print(f"window:     {USB_WINDOW_WIDTH_MM:.1f} x {usb_window_top - usb_window_bottom:.1f} "
          f"mm through the wall for the USB-C plug, corners rounded "
          f"{USB_WINDOW_CORNER_RADIUS_MM} mm, a {USB_WINDOW_CHAMFER_MM} mm x 45 "
          f"degree chamfer on both faces of the wall, at the wall "
          f"segment nearest "
          f"{MCU_NAME}'s connector end ({usb_end.x:.2f}, {usb_end.y:.2f}), "
          f"centered near ({usb_window_center.x:.2f}, {usb_window_center.y:.2f}), "
          f"{usb_window_bottom:.2f} to {usb_window_top:.2f} mm above the floor")
    if not ledge_notches:
        print("ledge notch: none, no socket tab reaches the ledge on this half")
    for name, closest, past_edge in ledge_notches:
        print(f"ledge notch: {LEDGE_NOTCH_WIDTH_MM} x {LEDGE_NOTCH_DEPTH_MM} mm for "
              f"{name}'s socket at ({closest.x:.2f}, {closest.y:.2f}); the socket "
              f"tab ends {past_edge:+.2f} mm past the board edge, "
              f"{arguments.gap - past_edge:.2f} mm from the wall")
    for name, closest, pocket_depth, pocket_volume in tab_pockets:
        print(f"tab pocket: {LEDGE_NOTCH_WIDTH_MM} x "
              f"{LEDGE_NOTCH_DEPTH_MM + LEDGE_NOTCH_CLEARANCE_MM} mm, "
              f"{pocket_depth:.2f} mm into the wall's inner face for {name}'s socket "
              f"tab at ({closest.x:.2f}, {closest.y:.2f}), "
              f"{arguments.wall - pocket_depth:.2f} mm of wall left, the tab tip "
              f"{LEDGE_NOTCH_CLEARANCE_MM} mm from it, {pocket_volume:.1f} mm3")
    if arguments.ledge_width > arguments.gap and not ledge_reliefs:
        print(f"ledge relief: none, every underside body clears the ledge by "
              f"{arguments.relief_clearance} mm")
    for label, center, length, depth, removed in ledge_reliefs:
        print(f"ledge relief: {length:.1f} mm along the wall, {depth:.2f} mm deep, "
              f"for {label} at ({center.x:.2f}, {center.y:.2f}), {removed:.1f} mm3")
    if not standoff_reliefs:
        print(f"standoff relief: none, every underside body clears the standoffs by "
              f"{STANDOFF_RELIEF_CLEARANCE_MM} mm")
    for label, center, flat_depth, plastic, body_distance, bottom, removed in standoff_reliefs:
        print(f"standoff relief: {flat_depth:.2f} mm deep flat, {bottom:.2f} to "
              f"{board_underside:.2f} mm above the floor, on the standoff at "
              f"({center.x:.2f}, {center.y:.2f}) for {label} ({body_distance:.2f} mm "
              f"from it), {plastic:.2f} mm left around the bore, {removed:.1f} mm3")
    print(f"wrote:      {arguments.stl_file} ({mesh.CountFacets} facets)")


def axis_name(axis):
    for name, direction in (("Z", App.Vector(0, 0, 1)),
                            ("Y", App.Vector(0, 1, 0)),
                            ("X", App.Vector(1, 0, 0))):
        if abs(axis.dot(direction)) > 0.999:
            return name
    return f"({axis.x:.2f},{axis.y:.2f},{axis.z:.2f})"


run_and_exit(main)
