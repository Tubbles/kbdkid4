"""Export the printable parts of a Raspberry Pi Camera Module 2 arm for
a stock Ender 3 V2 (STL files, each in its print orientation).

The arm stands on the top face of the printer base's right 4040 rail
(the one running front to back at bed level), behind the right
upright, clamped by one M3 bolt into a printed twist-in T-nut with a
captive M3 nut in the rail's outer top slot. Two ribs under its base
sit in both top slots' mouths, so the bolt alone holds it square. A
post rises to a bracket that carries the camera case at one fixed
angle, looking down at the bed from behind and to the right. The case
is two shells around the camera board, closed by four M2 screws
through the board's holes into heat-set inserts in the back shell,
and fixed to the arm by two M2 screws through ears on the back shell
into inserts in the arm. The 15 pin ribbon leaves the case's bottom
through a socket that takes the end of a cable sock.

Runs headless under FreeCAD's console interpreter (see board_step.py
for the freecadcmd quirks that shape the invocation):

    freecadcmd scripts/export_camera_arm.py --pass <output directory>

and writes Camera_Arm.stl, Camera_T_Nut.stl, Camera_Case_Back.stl and
Camera_Case_Front.stl there, each lying on z = 0 the way it prints,
without support. It also prints the fits, the clearances to the
printer and what part of the bed the camera sees over the Y travel.

Sources (downloads kept under work/research/camera/):

- Raspberry Pi Camera Module V2.1 mechanical drawing (RPI-CAM-V2_1,
  2015-11-12), https://datasheets.raspberrypi.com/camera/
  camera-module-2-mechanical-drawing.pdf: the board is 25 x 23.862 mm
  with 2.0 mm corner radii and four 2.2 mm holes, 2 mm in from the
  side edges, one row 2 mm and one 14.5 mm from the edge away from the
  connector (12.5 x 21 mm apart). The 8.5 x 8.5 mm lens block sits
  centered across the board on the 14.5 mm row, the 20.8 mm wide
  ribbon connector takes the 5.5 mm next to the other edge. The
  drawing also gives 9.462 mm from that row to the connector edge,
  which with 14.5 mm makes 23.962, not 23.862: the 0.1 mm goes into
  the case's gap. It gives no thicknesses and does not say which
  side its components are on.
- Raspberry Pi documentation, camera hardware specification
  (github.com/raspberrypi/documentation, documentation/asciidoc/
  accessories/camera/hardware_specification.adoc): Camera Module 2 is
  "around 25 x 24 x 9 mm", 62.2 degrees horizontal and 48.8 degrees
  vertical field of view, 3.04 mm focal length, focus from about 10
  cm.
- Creality's Ender-3 V2 firmware configuration (github.com/
  CrealityOfficial/Ender-3V2, Marlin/Configuration.h): X_BED_SIZE and
  Y_BED_SIZE 220, Y_MIN_POS 0, Y_MAX_POS 220, Z_MAX_POS 250.
- Creality's mechanical CAD of the Ender-3, the V2's predecessor
  (github.com/Creality3DPrinting/Ender-3, Ender-3 Mechanical/STP/
  Ender3.STEP and 4040 profile.step, PDF/4040 profile1-3.PDF). Creality
  publishes no V2 CAD there (CrealityOfficial/Ender-3V2 holds firmware
  only, the V2 download page firmware and the manual), so the printer
  numbers below are the Ender-3's, measured in FreeCAD. They agree with
  the user's description of the rail: 4040 profiles 290 mm long run
  front to back on both sides of the base. On that drawing the right
  upright (2040) stands centered on the rail, the bed plate (235 mm)
  sits 60.96 mm above the rail's top face with its right edge 7.3 mm
  short of the rail's inner side, the nozzle is 63.7 mm in front of
  the upright's back face, and the 4040 slot has a 6.0 mm neck (6.57
  mm on the faces modelled with 0.2 mm fillets), 1.8 mm lips, 10.42 mm
  inside down to 3.8 mm, then a 45 degree taper to 6.0 mm deep, slots
  20 mm apart. On the Ender-3 the power supply stands on the rail
  behind the right upright, which on the V2 moved into the base; that
  the rail is free there on the V2 is assumed, not drawn.

Assumed without a source, to be measured on the real parts: the board
1.0 mm thick, the case's room for components 3.0 mm in front of the
board (the lens block passes through a window) and 4.0 mm behind it;
the ribbon 16 mm wide (15 contacts at 1 mm pitch); the sock's end
about 8 to 10 mm across round, or flattened around the flat ribbon.

Frames: the printer frame has x to the right (seen from the front), y
toward the back and z up, its origin on the right rail's top face, on
the rail's center line, level with the right upright's back face. The
case frame has u along the board's 25 mm side, v along its 23.862 mm
side from the connector edge, w through the board toward the lens,
the board's back face at w = 0. The T-nut frame has x across the slot
and y along it, z up, the face that bears on the slot's lips at z = 0.
The arm is built in its print frame, which lies on the bed plane.
"""

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import FreeCAD as App
import Part

from board_step import check_closed_mesh, export_stl, run_and_exit, script_arguments

# Camera Module 2, from the mechanical drawing, in the case frame.
BOARD_WIDTH_MM = 25.0  # along u
BOARD_HEIGHT_MM = 23.862  # along v, connector edge at v = 0
BOARD_CORNER_RADIUS_MM = 2.0
BOARD_HOLE_DIAMETER_MM = 2.2
BOARD_HOLE_CENTERS_MM = ((2.0, 21.862), (23.0, 21.862), (2.0, 9.362), (23.0, 9.362))
LENS_CENTER_MM = (12.5, 9.362)
LENS_BLOCK_SIDE_MM = 8.5
CONNECTOR_WIDTH_MM = 20.8
CONNECTOR_DEPTH_MM = 5.5

# Assumed: not in the drawing. The lens block and connector heights only
# feed the fit check (a part model of the board inside the case).
BOARD_THICKNESS_MM = 1.0
LENS_BLOCK_HEIGHT_MM = 5.5  # above the board's front
CONNECTOR_HEIGHT_MM = 2.5  # below the board's back
RIBBON_WIDTH_MM = 16.0

HORIZONTAL_FIELD_OF_VIEW_DEGREES = 62.2  # along u
VERTICAL_FIELD_OF_VIEW_DEGREES = 48.8  # along v

# The printer, in the printer frame, from the Ender-3 CAD and the V2
# firmware (see the module docstring).
RAIL_HALF_WIDTH_MM = 20.0
RAIL_SLOT_CENTERS_X_MM = (-10.0, 10.0)
RAIL_BACK_END_Y_MM = 135.0
SLOT_NECK_WIDTH_MM = 6.0
SLOT_LIP_THICKNESS_MM = 1.8
SLOT_INNER_WIDTH_MM = 10.42
SLOT_TAPER_START_DEPTH_MM = 3.8  # below the rail's face, 45 degrees from there
SLOT_DEPTH_MM = 6.0
UPRIGHT_BOX_MM = ((-20.0, 20.0), (-20.0, 0.0), (0.0, 400.0))
# The X gantry's right end (wheel plate, wheels, belt tensioner) at its
# lowest, nozzle on the bed; it sweeps up from there.
GANTRY_RIGHT_END_BOX_MM = ((-63.4, 61.56), (-49.85, -4.9), (52.46, 147.56))
X_BEAM_BOX_MM = ((-308.09, 36.91), (-46.85, -26.85), (90.0, 110.0))  # at its lowest
BED_PLATE_X_MM = (-262.3, -27.3)
BED_PLATE_SIZE_MM = 235.0
BED_TOP_Z_MM = 60.96
BED_PLATE_THICKNESS_MM = 3.0
LEVELLING_KNOB_INSET_MM = 32.5  # knob centers from the plate's edges
LEVELLING_KNOB_RADIUS_MM = 30.0  # the CAD's bounding box, the knob is smaller
LEVELLING_KNOB_Z_MM = (27.5, 38.0)
NOZZLE_Y_MM = -63.7
PRINT_AREA_SIZE_MM = 220.0  # centered on the plate
Y_TRAVEL_MM = 220.0
MAXIMUM_PRINT_HEIGHT_MM = 250.0
BUILD_VOLUME_MM = (220.0, 220.0, 250.0)  # for the arm's own print

# Print fits, by kbdkid4's conventions: a printed part swells about 0.2
# mm per side (export_pcb.py's pull_in), so holes are drawn 0.4 mm over
# size, screw clearance holes another 0.2 mm for play, and the nut
# pocket without play, for a press fit; the M2 heat-set insert bore is
# the tray's (export_tray.py's DEFAULT_STANDOFF_HOLE_DIAMETER_MM,
# standoff 5.8 mm across).
PRINT_SWELLING_PER_SIDE_MM = 0.2
INSERT_BORE_DIAMETER_MM = 3.2
INSERT_STANDOFF_DIAMETER_MM = 5.8
M2_CLEARANCE_DIAMETER_MM = 2.6
M2_HEAD_COUNTERBORE_DIAMETER_MM = 4.6  # 3.8 mm socket head
M2_HEAD_COUNTERBORE_DEPTH_MM = 2.0
M3_CLEARANCE_DIAMETER_MM = 3.6
M3_HEAD_COUNTERBORE_DIAMETER_MM = 6.4  # 5.5 mm socket head
M3_NUT_ACROSS_FLATS_MM = 5.5
M3_NUT_THICKNESS_MM = 2.4
M3_BOLT_LENGTH_MM = 10.0

# The camera's fixed pose: its optical axis points 225 degrees from +x
# (forward and to the left, toward the bed) and 40 degrees down. The arm
# carries the case's back face on a bar whose back face center is at
# HEAD_BAR_BACK_CENTER_MM.
CAMERA_YAW_DEGREES = 225.0
CAMERA_PITCH_DEGREES = 40.0
HEAD_BAR_BACK_CENTER_MM = (3.0, 90.0, 198.0)

# The case. The board sits CASE_GAP_MM inside the walls on four
# standoffs bored for the inserts; bosses on the front shell press it
# down, reaching FRONT_BOSS_PRESS_MM past the assumed board thickness,
# so the shells close on the board, not on each other: the seam stays
# that far open on a 1.0 mm board.
CASE_GAP_MM = 0.4
CASE_WALL_MM = 1.6
FRONT_CAVITY_MM = 3.0  # above the board's front face
BACK_CAVITY_MM = 4.0  # below the board's back face
INSERT_BORE_DEPTH_MM = 5.0  # from the board's back face
FRONT_BOSS_DIAMETER_MM = 6.0
FRONT_BOSS_PRESS_MM = 0.2
LENS_WINDOW_SIDE_MM = LENS_BLOCK_SIDE_MM + 2.0 * (PRINT_SWELLING_PER_SIDE_MM + 0.3)
# The ribbon leaves through a slot in the bottom wall into a socket for
# the sock's end: an 18.4 x 8.8 mm stadium, SOCK_SOCKET_DEPTH_MM deep,
# which takes a round sock end up to about 8.4 mm squeezed to an oval
# (a 10 mm sock's 31 mm perimeter fits it easily) or a sock flattened
# around the flat ribbon. The narrower ribbon slot is the sock's stop.
RIBBON_SLOT_WIDTH_MM = RIBBON_WIDTH_MM + 1.4
RIBBON_SLOT_W_MM = (-BACK_CAVITY_MM, BOARD_THICKNESS_MM)
SOCK_SOCKET_WIDTH_MM = 18.4
SOCK_SOCKET_HEIGHT_MM = 8.8
SOCK_SOCKET_DEPTH_MM = 8.0
SOCK_SOCKET_WALL_MM = 1.2
# Ears on the back shell for the two screws into the arm, beyond the
# front shell's sides, so the screws go in from the front.
EAR_CENTERS_U_MM = (-4.8, BOARD_WIDTH_MM + 4.8)
EAR_RADIUS_MM = 3.6
EAR_THICKNESS_MM = 3.0
# The arm's bar under the ears: from 4 mm beyond each ear center, 8 mm
# tall, 7 mm thick, bored for the inserts 5.5 mm deep.
BAR_REACH_BEYOND_EARS_MM = 4.0
BAR_HALF_HEIGHT_MM = 4.0
BAR_THICKNESS_MM = 7.0
BAR_INSERT_DEPTH_MM = 5.5

# The arm. The base sits on the rail behind the upright with the bolt
# in the outer slot (printer frame). The post stands behind the case,
# given in the bracket's profile: POST_H_MM along the horizontal part of
# the viewing direction from the bar's back center, POST_WIDTH_MM of
# the case's u from the bar's end.
BASE_Y_MM = (62.0, 130.0)
BASE_THICKNESS_MM = 8.0
BOLT_POSITION_MM = (10.0, 70.0)
BOLT_HEAD_SEAT_HEIGHT_MM = 4.5  # above the rail's face: an M3 x 10 ends 5.5 mm below it
RIB_ROOT_WIDTH_MM = 5.0
RIB_DEPTH_MM = 1.2  # 45 degree sides
POST_H_MM = (-25.0, -9.0)
POST_WIDTH_MM = 16.0
BRACKET_DROP_MM = 14.0  # below the bar's back center
BRACKET_RISE_MM = 8.0  # above it, at the post
FRONT_GUSSET_MM = (15.0, 15.0)  # along h toward the camera, up the post

# The T-nut: a plate that bears on the lips, the nut below it in a
# pocket open at the bottom and through both long sides (the nut is as
# wide as the body may be to pass the slot's neck).
T_NUT_LENGTH_MM = 9.4  # across the slot, turned in
T_NUT_WIDTH_MM = SLOT_NECK_WIDTH_MM - 2.0 * (PRINT_SWELLING_PER_SIDE_MM + 0.1)
T_NUT_PLATE_MM = 1.4
T_NUT_POCKET_DEPTH_MM = M3_NUT_THICKNESS_MM + 0.1
T_NUT_POCKET_ACROSS_FLATS_MM = M3_NUT_ACROSS_FLATS_MM + 2.0 * PRINT_SWELLING_PER_SIDE_MM
T_NUT_CHAMFER_START_MM = SLOT_TAPER_START_DEPTH_MM - SLOT_LIP_THICKNESS_MM

# Checks.
OVERHANG_NORMAL_LIMIT = -0.7072  # a face pointing down more than 45 degrees
COVERAGE_GRID = 21  # bed samples per side
COVERAGE_TRAVEL_STEPS = 12
CUT_EXTRA_MM = 1.0
CONTACT_VOLUME_LIMIT_MM3 = 0.01

USAGE = """\
usage: freecadcmd scripts/export_camera_arm.py --pass <output directory>\
"""

PART_FILE_NAMES = {
    "arm": "Camera_Arm.stl",
    "t_nut": "Camera_T_Nut.stl",
    "case_back": "Camera_Case_Back.stl",
    "case_front": "Camera_Case_Front.stl",
}


# Vectors as plain tuples, for the pure geometry.

def add(a, b):
    return tuple(x + y for x, y in zip(a, b))


def scale(a, factor):
    return tuple(x * factor for x in a)


def dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def normalized(a):
    return scale(a, 1.0 / math.sqrt(dot(a, a)))


def camera_axes(yaw_degrees, pitch_degrees):
    """(forward, right, up) of a level camera with that yaw and pitch."""
    yaw = math.radians(yaw_degrees)
    pitch = math.radians(pitch_degrees)
    forward = (math.cos(pitch) * math.cos(yaw), math.cos(pitch) * math.sin(yaw), -math.sin(pitch))
    right = normalized((forward[1], -forward[0], 0.0))
    return forward, right, cross(right, forward)


def case_axes():
    """The case frame's u, v, w in the printer frame: u runs to the
    camera's left, which keeps the frame right handed."""
    forward, right, up = camera_axes(CAMERA_YAW_DEGREES, CAMERA_PITCH_DEGREES)
    return scale(right, -1.0), up, forward


def case_outline_center_v():
    return BOARD_HEIGHT_MM / 2.0


def bar_back_center_in_case():
    return (BOARD_WIDTH_MM / 2.0, case_outline_center_v(), case_back_w() - BAR_THICKNESS_MM)


def case_back_w():
    return -BACK_CAVITY_MM - CASE_WALL_MM


def case_front_w():
    return BOARD_THICKNESS_MM + FRONT_CAVITY_MM + CASE_WALL_MM


def case_to_printer(point):
    """A case frame point in the printer frame."""
    u_axis, v_axis, w_axis = case_axes()
    offset = tuple(p - q for p, q in zip(point, bar_back_center_in_case()))
    world = add(scale(u_axis, offset[0]), add(scale(v_axis, offset[1]), scale(w_axis, offset[2])))
    return add(HEAD_BAR_BACK_CENTER_MM, world)


def matrix_from_axes(x_axis, y_axis, z_axis, origin):
    """The matrix taking a frame with these axes and origin to its parent."""
    return App.Matrix(
        x_axis[0], y_axis[0], z_axis[0], origin[0],
        x_axis[1], y_axis[1], z_axis[1], origin[1],
        x_axis[2], y_axis[2], z_axis[2], origin[2],
        0.0, 0.0, 0.0, 1.0,
    )


def case_matrix(front_offset_w=0.0):
    u_axis, v_axis, w_axis = case_axes()
    return matrix_from_axes(u_axis, v_axis, w_axis, case_to_printer((0.0, 0.0, front_offset_w)))


def arm_frame_axes():
    """The arm's print frame: x back and to the right (against the
    camera's horizontal viewing direction), y up, z along the case's u.
    Its origin lies on the bed plane through the bar's -u end."""
    u_axis, _, w_axis = case_axes()
    horizontal = normalized((w_axis[0], w_axis[1], 0.0))
    return scale(horizontal, -1.0), (0.0, 0.0, 1.0), u_axis


def arm_frame_origin():
    _, _, z_axis = arm_frame_axes()
    bar_end_s = EAR_CENTERS_U_MM[0] - BAR_REACH_BEYOND_EARS_MM - BOARD_WIDTH_MM / 2.0
    center = (HEAD_BAR_BACK_CENTER_MM[0], HEAD_BAR_BACK_CENTER_MM[1], 0.0)
    return add(center, scale(z_axis, bar_end_s))


def arm_matrix():
    x_axis, y_axis, z_axis = arm_frame_axes()
    return matrix_from_axes(x_axis, y_axis, z_axis, arm_frame_origin())


def profile_up():
    """The camera's up in the bracket's (h, z) profile, h along the
    horizontal part of the viewing direction."""
    _, up, forward = case_axes()
    horizontal = normalized((forward[0], forward[1], 0.0))
    return dot(up, horizontal), up[2]


# Shape helpers.

def vector(point):
    return App.Vector(*point)


def box_between(x_range, y_range, z_range):
    return Part.makeBox(
        x_range[1] - x_range[0], y_range[1] - y_range[0], z_range[1] - z_range[0],
        App.Vector(x_range[0], y_range[0], z_range[0]),
    )


def edges_along_z(shape):
    edges = []
    for edge in shape.Edges:
        delta = edge.Vertexes[-1].Point.sub(edge.Vertexes[0].Point)
        if abs(delta.x) < 1e-7 and abs(delta.y) < 1e-7 and abs(delta.z) > 1e-7:
            edges.append(edge)
    return edges


def rounded_box(x_range, y_range, z_range, radius):
    """A box with its edges along z rounded."""
    solid = box_between(x_range, y_range, z_range)
    return solid.makeFillet(radius, edges_along_z(solid))


def cylinder_z(center, radius, z_range):
    return Part.makeCylinder(
        radius, z_range[1] - z_range[0], App.Vector(center[0], center[1], z_range[0])
    )


def prism_from_polygon(points, direction):
    """Points of a closed planar polygon, extruded along direction."""
    wire = Part.makePolygon([vector(point) for point in points] + [vector(points[0])])
    return Part.Face(wire).extrude(vector(direction))


def single_solid(shape):
    shape = shape.removeSplitter()
    if len(shape.Solids) != 1:
        raise SystemExit(f"error: expected one solid, got {len(shape.Solids)}")
    return shape.Solids[0]


# The T-nut, in the T-nut frame (the face against the lips at z = 0,
# the body below it).

def t_nut_height():
    return T_NUT_PLATE_MM + T_NUT_POCKET_DEPTH_MM


def t_nut_rotation_radius():
    """The leading corners' radius: the slot's half inner width less the
    swelling and a 0.3 mm clearance."""
    return SLOT_INNER_WIDTH_MM / 2.0 - PRINT_SWELLING_PER_SIDE_MM - 0.3


def t_nut_body():
    """The block, its lower ends chamfered at 45 degrees along the slot's taper."""
    half_length = T_NUT_LENGTH_MM / 2.0
    height = t_nut_height()
    chamfer = height - T_NUT_CHAMFER_START_MM
    profile = [
        (-half_length, 0.0, 0.0), (half_length, 0.0, 0.0),
        (half_length, 0.0, -T_NUT_CHAMFER_START_MM), (half_length - chamfer, 0.0, -height),
        (-half_length + chamfer, 0.0, -height), (-half_length, 0.0, -T_NUT_CHAMFER_START_MM),
    ]
    body = prism_from_polygon(profile, (0.0, T_NUT_WIDTH_MM, 0.0))
    body.translate(App.Vector(0.0, -T_NUT_WIDTH_MM / 2.0, 0.0))
    return body


def t_nut_rotation_envelope():
    """What may sweep the slot while the nut turns: a cylinder down to
    the taper, a cone along it."""
    radius = t_nut_rotation_radius()
    height = t_nut_height()
    cylinder = Part.makeCylinder(radius, T_NUT_CHAMFER_START_MM, App.Vector(0, 0, -T_NUT_CHAMFER_START_MM))
    cone_height = height - T_NUT_CHAMFER_START_MM
    cone = Part.makeCone(radius - cone_height, radius, cone_height, App.Vector(0, 0, -height))
    return cylinder.fuse(cone)


def hexagon_prism(across_flats, z_range):
    """A hexagonal prism around the z axis, corners along x."""
    radius = across_flats / math.sqrt(3.0)
    points = [
        (radius * math.cos(math.radians(60.0 * index)), radius * math.sin(math.radians(60.0 * index)), z_range[0])
        for index in range(6)
    ]
    return prism_from_polygon(points, (0.0, 0.0, z_range[1] - z_range[0]))


def build_t_nut():
    """Dropped in with its length along the slot and turned clockwise
    (seen from above) a quarter turn: the two corners that lead in that
    turn are rounded to the rotation envelope, the other two stay
    square and jam against the slot's sides a little past the quarter
    turn, which is also where the bolt's tightening drags it."""
    body = t_nut_body()
    big = 2.0 * T_NUT_LENGTH_MM
    height = t_nut_height()
    square_corners = box_between((0.0, big), (0.0, big), (-height - 1.0, 1.0)).fuse(
        box_between((-big, 0.0), (-big, 0.0), (-height - 1.0, 1.0))
    )
    kept = body.common(t_nut_rotation_envelope()).fuse(body.common(square_corners))
    bolt_hole = cylinder_z((0.0, 0.0), M3_CLEARANCE_DIAMETER_MM / 2.0, (-height - 1.0, 1.0))
    pocket = hexagon_prism(T_NUT_POCKET_ACROSS_FLATS_MM, (-height - 1.0, -T_NUT_PLATE_MM))
    return single_solid(kept.cut(bolt_hole).cut(pocket))


# The case, in the case frame.

def case_outline_prism(offset, w_range):
    return rounded_box(
        (-offset, BOARD_WIDTH_MM + offset), (-offset, BOARD_HEIGHT_MM + offset), w_range,
        BOARD_CORNER_RADIUS_MM + offset,
    )


def outer_offset():
    return CASE_GAP_MM + CASE_WALL_MM


def sock_socket_box(w_range):
    """The socket's outside below the case's bottom wall, for one shell."""
    half_width = SOCK_SOCKET_WIDTH_MM / 2.0 + SOCK_SOCKET_WALL_MM
    center_u = BOARD_WIDTH_MM / 2.0
    bottom = -outer_offset() - SOCK_SOCKET_DEPTH_MM
    return box_between((center_u - half_width, center_u + half_width), (bottom, -CASE_GAP_MM), w_range)


def sock_socket_bore():
    """The stadium the sock's end goes into, along v up to the wall."""
    radius = SOCK_SOCKET_HEIGHT_MM / 2.0
    straight = SOCK_SOCKET_WIDTH_MM / 2.0 - radius
    center_u = BOARD_WIDTH_MM / 2.0
    bottom = -outer_offset() - SOCK_SOCKET_DEPTH_MM - CUT_EXTRA_MM
    length = SOCK_SOCKET_DEPTH_MM + CUT_EXTRA_MM
    middle = box_between((center_u - straight, center_u + straight), (bottom, bottom + length), (-radius, radius))
    ends = [
        Part.makeCylinder(radius, length, App.Vector(center_u + side * straight, bottom, 0.0), App.Vector(0, 1, 0))
        for side in (-1.0, 1.0)
    ]
    return middle.fuse(ends)


def ribbon_slot():
    center_u = BOARD_WIDTH_MM / 2.0
    half_width = RIBBON_SLOT_WIDTH_MM / 2.0
    return box_between(
        (center_u - half_width, center_u + half_width),
        (-outer_offset() - CUT_EXTRA_MM, -CASE_GAP_MM + CUT_EXTRA_MM),
        RIBBON_SLOT_W_MM,
    )


def ears():
    """The two ears, from inside the back shell's side walls outward."""
    v = case_outline_center_v()
    w_range = (case_back_w(), case_back_w() + EAR_THICKNESS_MM)
    shapes = []
    for center_u in EAR_CENTERS_U_MM:
        wall_u = -CASE_GAP_MM if center_u < 0 else BOARD_WIDTH_MM + CASE_GAP_MM
        u_range = (min(center_u, wall_u), max(center_u, wall_u))
        tab = box_between(u_range, (v - EAR_RADIUS_MM, v + EAR_RADIUS_MM), w_range)
        shapes.append(tab.fuse(cylinder_z((center_u, v), EAR_RADIUS_MM, w_range)))
    return shapes


def ear_holes():
    v = case_outline_center_v()
    w_range = (case_back_w() - CUT_EXTRA_MM, case_back_w() + EAR_THICKNESS_MM + CUT_EXTRA_MM)
    return [cylinder_z((center_u, v), M2_CLEARANCE_DIAMETER_MM / 2.0, w_range) for center_u in EAR_CENTERS_U_MM]


def build_case_back():
    """Floor, walls up to the seam at w = 0 (the board's back face),
    four standoffs with insert bores, the ears and the socket's back half."""
    back = case_back_w()
    shell = case_outline_prism(outer_offset(), (back, 0.0))
    shell = shell.fuse([sock_socket_box((back, 0.0))] + ears())
    standoffs = [
        cylinder_z(center, INSERT_STANDOFF_DIAMETER_MM / 2.0, (-BACK_CAVITY_MM, 0.0))
        for center in BOARD_HOLE_CENTERS_MM
    ]
    cavity = case_outline_prism(CASE_GAP_MM, (-BACK_CAVITY_MM, CUT_EXTRA_MM)).cut(standoffs)
    bores = [
        cylinder_z(center, INSERT_BORE_DIAMETER_MM / 2.0, (-INSERT_BORE_DEPTH_MM, CUT_EXTRA_MM))
        for center in BOARD_HOLE_CENTERS_MM
    ]
    cutters = [cavity, ribbon_slot(), sock_socket_bore()] + bores + ear_holes()
    return single_solid(shell.cut(Part.makeCompound(cutters)))


def build_case_front():
    """Walls from the seam, the front plate with the lens window, the
    bosses that press the board, counterbored screw holes and the
    socket's front half."""
    front = case_front_w()
    ceiling = BOARD_THICKNESS_MM + FRONT_CAVITY_MM
    boss_bottom = BOARD_THICKNESS_MM - FRONT_BOSS_PRESS_MM
    shell = case_outline_prism(outer_offset(), (0.0, front)).fuse(sock_socket_box((0.0, front)))
    bosses = [
        cylinder_z(center, FRONT_BOSS_DIAMETER_MM / 2.0, (boss_bottom, ceiling + CUT_EXTRA_MM))
        for center in BOARD_HOLE_CENTERS_MM
    ]
    cavity = case_outline_prism(CASE_GAP_MM, (-CUT_EXTRA_MM, ceiling)).cut(bosses)
    holes = [
        cylinder_z(center, M2_CLEARANCE_DIAMETER_MM / 2.0, (boss_bottom - CUT_EXTRA_MM, front + CUT_EXTRA_MM))
        for center in BOARD_HOLE_CENTERS_MM
    ]
    counterbores = [
        cylinder_z(center, M2_HEAD_COUNTERBORE_DIAMETER_MM / 2.0,
                   (front - M2_HEAD_COUNTERBORE_DEPTH_MM, front + CUT_EXTRA_MM))
        for center in BOARD_HOLE_CENTERS_MM
    ]
    half_window = LENS_WINDOW_SIDE_MM / 2.0
    window = box_between(
        (LENS_CENTER_MM[0] - half_window, LENS_CENTER_MM[0] + half_window),
        (LENS_CENTER_MM[1] - half_window, LENS_CENTER_MM[1] + half_window),
        (ceiling - CUT_EXTRA_MM, front + CUT_EXTRA_MM),
    )
    cutters = [cavity, window, ribbon_slot(), sock_socket_bore()] + holes + counterbores
    return single_solid(shell.cut(Part.makeCompound(cutters)))


def board_model():
    """The camera board as drawn, with the assumed heights: the board,
    the lens block in front, the connector behind."""
    board = rounded_box((0.0, BOARD_WIDTH_MM), (0.0, BOARD_HEIGHT_MM), (0.0, BOARD_THICKNESS_MM),
                        BOARD_CORNER_RADIUS_MM)
    holes = [cylinder_z(center, BOARD_HOLE_DIAMETER_MM / 2.0, (-1.0, 2.0)) for center in BOARD_HOLE_CENTERS_MM]
    half_block = LENS_BLOCK_SIDE_MM / 2.0
    lens_block = box_between(
        (LENS_CENTER_MM[0] - half_block, LENS_CENTER_MM[0] + half_block),
        (LENS_CENTER_MM[1] - half_block, LENS_CENTER_MM[1] + half_block),
        (BOARD_THICKNESS_MM, BOARD_THICKNESS_MM + LENS_BLOCK_HEIGHT_MM),
    )
    half_connector = CONNECTOR_WIDTH_MM / 2.0
    connector = box_between(
        (BOARD_WIDTH_MM / 2.0 - half_connector, BOARD_WIDTH_MM / 2.0 + half_connector),
        (0.0, CONNECTOR_DEPTH_MM), (-CONNECTOR_HEIGHT_MM, 0.0),
    )
    return board.cut(holes).fuse([lens_block, connector])


def bar_in_case_frame():
    """The arm's bar behind the ears, and its insert bores."""
    v = case_outline_center_v()
    u_range = (EAR_CENTERS_U_MM[0] - BAR_REACH_BEYOND_EARS_MM, EAR_CENTERS_U_MM[1] + BAR_REACH_BEYOND_EARS_MM)
    w_range = (case_back_w() - BAR_THICKNESS_MM, case_back_w())
    bar = box_between(u_range, (v - BAR_HALF_HEIGHT_MM, v + BAR_HALF_HEIGHT_MM), w_range)
    bores = [
        cylinder_z((center_u, v), INSERT_BORE_DIAMETER_MM / 2.0,
                   (case_back_w() - BAR_INSERT_DEPTH_MM, case_back_w() + CUT_EXTRA_MM))
        for center_u in EAR_CENTERS_U_MM
    ]
    return bar, bores


# The arm, built in its print frame (see arm_frame_axes).

def bracket_profile_points():
    """The bracket in the (h, z) profile, relative to the bar's back
    center: from the post up and over to the bar's back face."""
    up = profile_up()
    top = (BAR_HALF_HEIGHT_MM * up[0], BAR_HALF_HEIGHT_MM * up[1])
    z = HEAD_BAR_BACK_CENTER_MM[2]
    return [
        (POST_H_MM[0], z - BRACKET_DROP_MM), (POST_H_MM[0], z + BRACKET_RISE_MM),
        (top[0], z + top[1]), (-top[0], z - top[1]), (POST_H_MM[1], z - BRACKET_DROP_MM),
    ]


def profile_prism(points, width):
    """An (h, z) polygon as a prism in the arm frame, from its bed plane."""
    return prism_from_polygon([(-h, z, 0.0) for h, z in points], (0.0, 0.0, width))


def to_arm_frame(shape):
    return shape.transformed(arm_matrix().inverse())


def bar_width():
    return EAR_CENTERS_U_MM[1] - EAR_CENTERS_U_MM[0] + 2.0 * BAR_REACH_BEYOND_EARS_MM


def rail_parts():
    """Base, ribs and the bolt's hole and counterbore, in the printer frame."""
    base = box_between((-RAIL_HALF_WIDTH_MM, RAIL_HALF_WIDTH_MM), BASE_Y_MM, (0.0, BASE_THICKNESS_MM))
    ribs = []
    for slot_x in RAIL_SLOT_CENTERS_X_MM:
        half_root = RIB_ROOT_WIDTH_MM / 2.0
        half_tip = half_root - RIB_DEPTH_MM
        profile = [
            (slot_x - half_root, BASE_Y_MM[0], 0.0), (slot_x + half_root, BASE_Y_MM[0], 0.0),
            (slot_x + half_tip, BASE_Y_MM[0], -RIB_DEPTH_MM), (slot_x - half_tip, BASE_Y_MM[0], -RIB_DEPTH_MM),
        ]
        ribs.append(prism_from_polygon(profile, (0.0, BASE_Y_MM[1] - BASE_Y_MM[0], 0.0)))
    bolt_hole = cylinder_z(BOLT_POSITION_MM, M3_CLEARANCE_DIAMETER_MM / 2.0,
                           (-RIB_DEPTH_MM - CUT_EXTRA_MM, BASE_THICKNESS_MM + CUT_EXTRA_MM))
    counterbore = cylinder_z(BOLT_POSITION_MM, M3_HEAD_COUNTERBORE_DIAMETER_MM / 2.0,
                             (BOLT_HEAD_SEAT_HEIGHT_MM, BASE_THICKNESS_MM + CUT_EXTRA_MM))
    return base.fuse(ribs), [bolt_hole, counterbore]


def build_arm():
    """Base, post, gusset, bracket and bar, clipped to the bed plane."""
    post_top = HEAD_BAR_BACK_CENTER_MM[2] - BRACKET_DROP_MM + 1.0
    post = profile_prism(
        [(POST_H_MM[0], BASE_THICKNESS_MM), (POST_H_MM[1], BASE_THICKNESS_MM),
         (POST_H_MM[1], post_top), (POST_H_MM[0], post_top)],
        POST_WIDTH_MM,
    )
    gusset = profile_prism(
        [(POST_H_MM[1], BASE_THICKNESS_MM), (POST_H_MM[1] + FRONT_GUSSET_MM[0], BASE_THICKNESS_MM),
         (POST_H_MM[1], BASE_THICKNESS_MM + FRONT_GUSSET_MM[1])],
        POST_WIDTH_MM,
    )
    bracket = profile_prism(bracket_profile_points(), bar_width())
    bar, bar_bores = bar_in_case_frame()
    from_case = case_matrix()
    bar = to_arm_frame(bar.transformed(from_case))
    bar_bores = [to_arm_frame(bore.transformed(from_case)) for bore in bar_bores]
    base, rail_cutters = rail_parts()
    base = to_arm_frame(base)
    rail_cutters = [to_arm_frame(cutter) for cutter in rail_cutters]
    arm = base.fuse([post, gusset, bracket, bar]).cut(Part.makeCompound(bar_bores + rail_cutters))
    bed_side = box_between((-1000.0, 1000.0), (-1000.0, 1000.0), (0.0, 1000.0))
    return single_solid(arm.common(bed_side))


# Checks.

def check_probes(name, shape, probes):
    for point, solid in probes:
        if shape.isInside(vector(point), 1e-6, True) != solid:
            raise SystemExit(f"error: {name} is {'open' if solid else 'solid'} at {point}")


def check_valid(name, shape):
    if not shape.isValid():
        raise SystemExit(f"error: {name} is not a valid solid")


def downward_faces(shape):
    """Planar faces off the bed that face down by more than 45 degrees,
    in the print orientation."""
    bed = shape.BoundBox.ZMin
    flagged = []
    for face in shape.Faces:
        if not isinstance(face.Surface, Part.Plane):
            continue
        u0, u1, v0, v1 = face.ParameterRange
        normal = face.normalAt((u0 + u1) / 2.0, (v0 + v1) / 2.0)
        if normal.z < OVERHANG_NORMAL_LIMIT and face.BoundBox.ZMin > bed + 1e-3:
            flagged.append(face)
    return flagged


def overhang_report(shape):
    flagged = downward_faces(shape)
    if not flagged:
        return "none"
    largest = max(flagged, key=lambda face: face.Area)
    box = largest.BoundBox
    return (f"{len(flagged)} faces, {sum(face.Area for face in flagged):.1f} mm2, largest "
            f"{max(box.XLength, box.YLength):.1f} mm across")


def check_t_nut(t_nut):
    check_valid("the T-nut", t_nut)
    half_length = T_NUT_LENGTH_MM / 2.0
    half_width = T_NUT_WIDTH_MM / 2.0
    height = t_nut_height()
    corner = (half_length - 0.15, half_width - 0.15, -0.5)
    check_probes("the T-nut", t_nut, [
        ((0.0, 0.0, -T_NUT_PLATE_MM / 2.0), False),  # bolt hole
        ((2.0, 0.0, -T_NUT_PLATE_MM - 1.0), False),  # nut pocket
        ((half_length - 0.5, 0.0, -T_NUT_PLATE_MM / 2.0), True),  # plate
        ((half_length - 0.5, 0.0, -T_NUT_PLATE_MM - 0.5), True),  # pocket end wall
        (corner, True),  # square corner
        ((-corner[0], -corner[1], corner[2]), True),
        ((corner[0], -corner[1], corner[2]), False),  # rounded corner
        ((-corner[0], corner[1], corner[2]), False),
        ((half_length - 0.3, 0.0, -height + 0.2), False),  # chamfer
    ])
    if abs(t_nut.BoundBox.ZLength - height) > 1e-6:
        raise SystemExit(f"error: the T-nut is {t_nut.BoundBox.ZLength:.3f} mm tall, expected {height:.3f}")


def t_nut_figures():
    """Margins of the printed T-nut in the slot, swelling included."""
    printed_width = T_NUT_WIDTH_MM + 2.0 * PRINT_SWELLING_PER_SIDE_MM
    printed_radius = t_nut_rotation_radius() + PRINT_SWELLING_PER_SIDE_MM
    corner_radius = math.hypot(T_NUT_LENGTH_MM / 2.0, T_NUT_WIDTH_MM / 2.0) + PRINT_SWELLING_PER_SIDE_MM
    half_inner = SLOT_INNER_WIDTH_MM / 2.0
    # A square corner's distance across the slot after turning theta
    # from along it is corner_radius * sin(theta - phase).
    phase = math.atan2(T_NUT_WIDTH_MM / 2.0, T_NUT_LENGTH_MM / 2.0)
    stop = math.degrees(math.asin(min(1.0, half_inner / corner_radius)) + phase)
    nut_top_depth = SLOT_LIP_THICKNESS_MM + T_NUT_PLATE_MM
    bolt_tip_depth = M3_BOLT_LENGTH_MM - BOLT_HEAD_SEAT_HEIGHT_MM
    return {
        "neck_margin": (SLOT_NECK_WIDTH_MM - printed_width) / 2.0,
        "turn_margin": half_inner - printed_radius,
        "stop_degrees": stop,
        "lip_overlap": (T_NUT_LENGTH_MM - SLOT_NECK_WIDTH_MM) / 2.0,
        "thread_engagement": min(bolt_tip_depth - nut_top_depth, M3_NUT_THICKNESS_MM),
        "bolt_to_slot_bottom": SLOT_DEPTH_MM - bolt_tip_depth,
    }


def check_t_nut_figures(figures):
    if figures["neck_margin"] <= 0 or figures["turn_margin"] <= 0:
        raise SystemExit("error: the printed T-nut does not pass the slot's neck or turn in it")
    if figures["thread_engagement"] < 1.5 or figures["bolt_to_slot_bottom"] <= 0:
        raise SystemExit("error: the M3 bolt does not reach through the nut or hits the slot's bottom")


def check_case(case_back, case_front):
    check_valid("the back shell", case_back)
    check_valid("the front shell", case_front)
    v = case_outline_center_v()
    hole = BOARD_HOLE_CENTERS_MM[0]
    socket_v = -outer_offset() - SOCK_SOCKET_DEPTH_MM / 2.0
    check_probes("the back shell", case_back, [
        ((BOARD_WIDTH_MM / 2.0, 16.0, -1.0), False),  # cavity
        ((hole[0] + INSERT_BORE_DIAMETER_MM / 2.0 + 0.3, hole[1], -1.0), True),  # standoff
        ((hole[0], hole[1], -INSERT_BORE_DEPTH_MM + 0.2), False),  # insert bore
        ((hole[0], hole[1], -INSERT_BORE_DEPTH_MM - 0.2), True),  # floor under it
        ((BOARD_WIDTH_MM / 2.0, -1.2, -2.0), False),  # ribbon slot
        ((BOARD_WIDTH_MM / 2.0, socket_v, -SOCK_SOCKET_HEIGHT_MM / 2.0 + 0.2), False),  # socket
        ((BOARD_WIDTH_MM / 2.0, socket_v, -SOCK_SOCKET_HEIGHT_MM / 2.0 - 0.2), True),
        ((EAR_CENTERS_U_MM[0], v, case_back_w() + 1.0), False),  # ear hole
        ((EAR_CENTERS_U_MM[0] - 2.0, v, case_back_w() + 1.0), True),  # ear
    ])
    front = case_front_w()
    check_probes("the front shell", case_front, [
        ((BOARD_WIDTH_MM / 2.0, 16.0, 2.0), False),  # cavity
        ((LENS_CENTER_MM[0], LENS_CENTER_MM[1], front - 0.5), False),  # lens window
        ((hole[0], hole[1], 2.0), False),  # screw hole
        ((hole[0] + 2.0, hole[1], 2.0), True),  # boss
        ((hole[0] + 2.0, hole[1], front - 0.5), False),  # counterbore
        ((BOARD_WIDTH_MM / 2.0, 20.0, front - 0.5), True),  # front plate
    ])


def check_no_overlap(name, first, second):
    volume = first.common(second).Volume
    if volume > CONTACT_VOLUME_LIMIT_MM3:
        raise SystemExit(f"error: {name} overlap by {volume:.3f} mm3")


def check_board_fit(case_back, case_front_assembled):
    board = board_model()
    check_no_overlap("the board and the back shell", board, case_back)
    check_no_overlap("the board and the front shell", board, case_front_assembled)


# The printer's keep-outs and the camera's coverage, in the printer frame.

def bed_plate_y_range(travel_position):
    front = NOZZLE_Y_MM - travel_position - (BED_PLATE_SIZE_MM - PRINT_AREA_SIZE_MM) / 2.0
    return front, front + BED_PLATE_SIZE_MM


def keep_out_boxes():
    """Boxes the arm and case must stay clear of, over the whole travel
    and print height."""
    swept_front = bed_plate_y_range(Y_TRAVEL_MM)[0]
    swept_back = bed_plate_y_range(0.0)[1]
    margin = (BED_PLATE_SIZE_MM - PRINT_AREA_SIZE_MM) / 2.0
    knob_x = BED_PLATE_X_MM[1] - LEVELLING_KNOB_INSET_MM
    print_top = BED_TOP_Z_MM + MAXIMUM_PRINT_HEIGHT_MM
    gantry = GANTRY_RIGHT_END_BOX_MM
    return {
        "right upright": UPRIGHT_BOX_MM,
        "X gantry's right end, swept up": (gantry[0], gantry[1], (gantry[2][0], 450.0)),
        "bed plate over the travel": (
            BED_PLATE_X_MM, (swept_front, swept_back),
            (BED_TOP_Z_MM - BED_PLATE_THICKNESS_MM, BED_TOP_Z_MM),
        ),
        "levelling knobs over the travel": (
            (knob_x - LEVELLING_KNOB_RADIUS_MM, knob_x + LEVELLING_KNOB_RADIUS_MM),
            (swept_front, swept_back), LEVELLING_KNOB_Z_MM,
        ),
        "print volume over the travel": (
            (BED_PLATE_X_MM[0] + margin, BED_PLATE_X_MM[1] - margin),
            (swept_front + margin, swept_back - margin), (BED_TOP_Z_MM, print_top),
        ),
    }


def bed_points(travel_position):
    """A grid over the print area with the bed at that Y position."""
    left = BED_PLATE_X_MM[0] + (BED_PLATE_SIZE_MM - PRINT_AREA_SIZE_MM) / 2.0
    step = PRINT_AREA_SIZE_MM / (COVERAGE_GRID - 1)
    return [
        (left + column * step, NOZZLE_Y_MM - travel_position + row * step, BED_TOP_Z_MM)
        for column in range(COVERAGE_GRID) for row in range(COVERAGE_GRID)
    ]


def in_view(point, lens, axes):
    forward, right, up = axes
    offset = tuple(p - q for p, q in zip(point, lens))
    depth = dot(offset, forward)
    if depth <= 0.0:
        return False
    across = math.degrees(math.atan2(abs(dot(offset, right)), depth))
    upward = math.degrees(math.atan2(abs(dot(offset, up)), depth))
    return across <= HORIZONTAL_FIELD_OF_VIEW_DEGREES / 2.0 and upward <= VERTICAL_FIELD_OF_VIEW_DEGREES / 2.0


def segment_hits_box(start, end, box):
    low, high = 0.0, 1.0
    for axis in range(3):
        minimum, maximum = box[axis]
        delta = end[axis] - start[axis]
        if abs(delta) < 1e-12:
            if not minimum <= start[axis] <= maximum:
                return False
            continue
        first, second = sorted(((minimum - start[axis]) / delta, (maximum - start[axis]) / delta))
        low, high = max(low, first), min(high, second)
        if low > high:
            return False
    return True


def coverage_by_travel(lens, axes, occluders):
    """For each sampled Y position, the share of the print area in view
    and not hidden behind an occluder."""
    shares = []
    for step in range(COVERAGE_TRAVEL_STEPS):
        travel_position = Y_TRAVEL_MM * step / (COVERAGE_TRAVEL_STEPS - 1)
        points = bed_points(travel_position)
        seen = [
            point for point in points
            if in_view(point, lens, axes) and not any(segment_hits_box(lens, point, box) for box in occluders)
        ]
        shares.append((travel_position, len(seen) / len(points)))
    return shares


def lens_position():
    return case_to_printer((LENS_CENTER_MM[0], LENS_CENTER_MM[1], case_front_w()))


# Print orientations.

def t_nut_print(shape):
    return shape.transformed(App.Matrix(1, 0, 0, 0, 0, -1, 0, 0, 0, 0, -1, 0, 0, 0, 0, 1))


def case_back_print(shape):
    return shape.transformed(App.Matrix(1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, -case_back_w(), 0, 0, 0, 1))


def case_front_print(shape):
    return shape.transformed(App.Matrix(1, 0, 0, 0, 0, -1, 0, 0, 0, 0, -1, case_front_w(), 0, 0, 0, 1))


def on_bed_origin(shape):
    box = shape.BoundBox
    moved = shape.copy()
    moved.translate(App.Vector(-box.XMin, -box.YMin, -box.ZMin))
    return moved


def assembled_parts(arm, t_nut, case_back, case_front):
    """The parts in the printer frame, the front shell held off the back
    shell by the bosses' press."""
    t_nut_placed = t_nut.copy()
    t_nut_placed.translate(App.Vector(BOLT_POSITION_MM[0], BOLT_POSITION_MM[1], -SLOT_LIP_THICKNESS_MM))
    return {
        "arm": arm.transformed(arm_matrix()),
        "t_nut": t_nut_placed,
        "case_back": case_back.transformed(case_matrix()),
        "case_front": case_front.transformed(case_matrix(FRONT_BOSS_PRESS_MM)),
    }


def screw_access_cylinders():
    """The two ear screws' axes from the ears' fronts outward, as wide
    as a driver around a screw head, in the case frame."""
    v = case_outline_center_v()
    start = case_back_w() + EAR_THICKNESS_MM
    return [cylinder_z((center_u, v), 2.5, (start, start + 60.0)) for center_u in EAR_CENTERS_U_MM]


def main():
    arguments = script_arguments(sys.argv)
    if len(arguments) != 1:
        raise SystemExit(USAGE)
    output_directory = arguments[0]
    if not os.path.isdir(output_directory):
        raise SystemExit(f"error: {output_directory} is not a directory")

    t_nut = build_t_nut()
    check_t_nut(t_nut)
    figures = t_nut_figures()
    check_t_nut_figures(figures)
    case_back = build_case_back()
    case_front = build_case_front()
    check_case(case_back, case_front)
    front_assembled_in_case = case_front.copy()
    front_assembled_in_case.translate(App.Vector(0, 0, FRONT_BOSS_PRESS_MM))
    check_no_overlap("the shells", case_back, front_assembled_in_case)
    check_board_fit(case_back, front_assembled_in_case)
    arm = build_arm()
    check_valid("the arm", arm)

    placed = assembled_parts(arm, t_nut, case_back, case_front)
    check_no_overlap("the arm and the back shell", placed["arm"], placed["case_back"])
    check_no_overlap("the arm and the front shell", placed["arm"], placed["case_front"])
    for access in screw_access_cylinders():
        check_no_overlap("an ear screw's access and the arm", placed["arm"], access.transformed(case_matrix()))
    assembly = Part.makeCompound(list(placed.values()))
    clearances = {
        name: assembly.distToShape(box_between(*box))[0] for name, box in keep_out_boxes().items()
    }
    if min(clearances.values()) <= 0.0:
        raise SystemExit(f"error: the arm or case touches the printer: {clearances}")
    arm_box = placed["arm"].BoundBox
    if arm_box.YMax > RAIL_BACK_END_Y_MM or arm_box.YMin < 0.0:
        raise SystemExit("error: the arm leaves the rail behind the upright")

    prints = {
        "arm": on_bed_origin(arm),
        "t_nut": on_bed_origin(t_nut_print(t_nut)),
        "case_back": on_bed_origin(case_back_print(case_back)),
        "case_front": on_bed_origin(case_front_print(case_front)),
    }
    arm_print_box = prints["arm"].BoundBox
    if sorted((arm_print_box.XLength, arm_print_box.YLength))[1] > BUILD_VOLUME_MM[0] \
            or arm_print_box.ZLength > BUILD_VOLUME_MM[2]:
        raise SystemExit("error: the arm does not fit the printer's build volume")
    for part, shape in prints.items():
        stl_file = os.path.join(output_directory, PART_FILE_NAMES[part])
        mesh = export_stl(shape, stl_file)
        check_closed_mesh(stl_file)
        box = shape.BoundBox
        print(f"{part + ':':12s}{box.XLength:.1f} x {box.YLength:.1f} x {box.ZLength:.1f} mm as printed, "
              f"{shape.Volume / 1000.0:.1f} cm3, downward faces past 45 degrees: {overhang_report(shape)}, "
              f"wrote {stl_file} ({mesh.CountFacets} facets)")

    print(f"T-nut:      {T_NUT_LENGTH_MM} x {T_NUT_WIDTH_MM:.1f} x {t_nut_height():.1f} mm, printed it passes "
          f"the {SLOT_NECK_WIDTH_MM} mm neck with {figures['neck_margin']:.2f} mm a side, turns with "
          f"{figures['turn_margin']:.2f} mm to the slot's sides and jams at {figures['stop_degrees']:.0f} "
          f"degrees, its plate {figures['lip_overlap']:.1f} mm over each lip; an M3 x "
          f"{M3_BOLT_LENGTH_MM:.0f} engages {figures['thread_engagement']:.1f} mm of the nut and ends "
          f"{figures['bolt_to_slot_bottom']:.1f} mm above the slot's bottom")
    print(f"case:       {BOARD_WIDTH_MM + 2 * outer_offset():.1f} x {BOARD_HEIGHT_MM + 2 * outer_offset():.1f} x "
          f"{case_front_w() - case_back_w():.1f} mm, {LENS_WINDOW_SIDE_MM:.1f} mm lens window, sock socket "
          f"{SOCK_SOCKET_WIDTH_MM} x {SOCK_SOCKET_HEIGHT_MM} mm, {SOCK_SOCKET_DEPTH_MM} mm deep; the seam "
          f"stays {FRONT_BOSS_PRESS_MM} mm open on a {BOARD_THICKNESS_MM} mm board")

    lens = lens_position()
    axes = camera_axes(CAMERA_YAW_DEGREES, CAMERA_PITCH_DEGREES)
    right_edge = BED_PLATE_X_MM[1] - (BED_PLATE_SIZE_MM - PRINT_AREA_SIZE_MM) / 2.0
    print(f"camera:     lens at x {lens[0]:.1f}, y {lens[1]:.1f}, z {lens[2]:.1f} mm (printer frame): "
          f"{lens[2] - BED_TOP_Z_MM:.1f} mm above the bed, {lens[0] - right_edge:.1f} mm right of the "
          f"print area, {lens[1] - NOZZLE_Y_MM:.1f} mm behind the nozzle; looking {CAMERA_YAW_DEGREES - 180:.0f} "
          f"degrees from straight left toward the front, {CAMERA_PITCH_DEGREES:.0f} degrees down")
    for label, occluders in (("in view", []), ("unhidden", [UPRIGHT_BOX_MM, GANTRY_RIGHT_END_BOX_MM, X_BEAM_BOX_MM])):
        shares = coverage_by_travel(lens, axes, occluders)
        mean = sum(share for _, share in shares) / len(shares)
        listed = ", ".join(f"{position:.0f}: {share * 100:.0f}" for position, share in shares)
        print(f"coverage:   {label}, % of the print area by bed Y position: {listed}; mean {mean * 100:.0f} %")
    for name, distance in clearances.items():
        print(f"clearance:  {distance:.1f} mm to the {name}")
    print(f"rail:       the arm takes y {arm_box.YMin:.1f} to {arm_box.YMax:.1f} mm behind the upright's back "
          f"face, the rail ends at {RAIL_BACK_END_Y_MM:.0f}; all of the rail in front of the upright stays free")


run_and_exit(main)
