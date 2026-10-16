"""Export one shell of a 3D-printable carrying case for the keyboard
(STL) from the board's STEP model.

The case carries both halves laid sole to sole, keys facing outward,
in two shells that meet at the seam, the plane where the two halves'
rubber soles touch. Each shell holds one half by its tray, keys toward
the shell's floor. From the seam inward comes a tray pocket, the
tray's outside plus CASE_CLEARANCE_MM per side, as deep as the tray
and its sole. At its bottom the tray's rim rests on a step, so the
keycaps never touch the case and no key is held down. Beyond the step
a key pocket, the tray's outside less STEP_OVERLAP_MM per side, is
deep enough for the keycaps, a clearance and padding glued to the
floor, and the floor closes it. The pockets are built from the
tray's sharpened board outline with the tray's concentric corner
rule, so their corners are concentric with the tray's. The outside is
a rounded rectangle WALL_MM beyond the tray pocket's bounding box,
its corners concentric with the pocket's where the board's corners
touch that box.

Both halves charge in the closed case: the north wall gets a notch
from the seam over the tray's power switch window and one over its USB
window, the latter sized for a plug's grip, and the two shells'
notches form one slot across the seam. Four disc magnets per shell, in
pockets in the seam face, hold the shells together, and a Velcro band
around the closed case the short way, through a tunnel in the north
and the south wall of each shell, backs them up.

Runs headless under FreeCAD's console interpreter (see board_step.py
for the freecadcmd quirks that shape the invocation):

    freecadcmd scripts/export_case.py --pass <pcb.step> <case.stl> [right]

Without "right" it exports the left half's shell, with "right" the
right half's. Each shell follows its tray's opening direction, which
tray_shape.py decides for both scripts: in the STEP frame the left
half's tray opens toward the board's top side (+Z), where that half's
keys are, with its sole below, and the right half's tray is built
with the board's other side up (see export_tray.py). Stacked sole to sole, the right half below,
both boards share their x and y, so both shells are built at the same
x and y as their trays: the left one over the left half's keys,
opening toward -Z, the right one under the right half's, opening
toward +Z. The STL is in printing orientation, floor on z = 0 and
opening up: the left shell turned over, the right one as built.

The design values live in the constants below and in tray_shape.py
(the tray's dimensions and where its windows sit). Everything else
derives from them.
"""

import math
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import FreeCAD as App
import Part

from board_step import (
    check_closed_mesh,
    component_placements,
    component_positions,
    export_stl,
    find_board,
    import_assembly,
    offset_outline,
    pick_resting_face,
    run_and_exit,
    script_arguments,
)
from tray_shape import (
    DEFAULT_DEPTH_MM,
    DEFAULT_FLOOR_MM,
    DEFAULT_GAP_MM,
    DEFAULT_STANDOFF_HEIGHT_MM,
    DEFAULT_WALL_MM,
    MCU_NAME,
    POWER_SWITCH_NAME,
    component_protrusions,
    fillet_prism_corners,
    outline_straight_segments,
    sharpen_outline,
    switch_window_center_and_direction,
    switch_window_height_band,
    tray_corner_radius,
    tray_opens_toward_positive_axis,
    usb_connector_end,
    usb_window_center_and_direction,
    usb_window_height_band,
    wall_outward,
)

# All in mm, heights measured from the seam into the shell. Each half
# stands on a rubber sole glued under its tray's floor. The tray's
# dimensions are tray_shape.py's defaults.
SOLE_THICKNESS_MM = 1.0

# The tray pocket is the tray's outside plus CASE_CLEARANCE_MM per
# side, from the seam to the tray's rim. The rim (the tray wall's top)
# rests on the step there, and the key pocket beyond it is the tray's
# outside less STEP_OVERLAP_MM per side, so the rim covers
# STEP_OVERLAP_MM of the step with the tray centered. The plate
# rests on the board, which rests on the tray's
# DEFAULT_STANDOFF_HEIGHT_MM standoffs, so with the board's 1.6 mm and
# the plate's 2.2 mm its top lies 0.1 mm below the rim
# (DEFAULT_DEPTH_MM above the tray floor). It sits inside the tray,
# held sideways by the tray's inner wall, and neither the step nor the
# key pocket comes near it.
CASE_CLEARANCE_MM = 0.3
STEP_OVERLAP_MM = 0.5

# A half with switches and keycaps stands just under KEY_HEIGHT_MM
# tall from its sole's underside (user, 2026-10-16). The key pocket
# reaches KEY_CLEARANCE_MM past the keycaps plus PADDING_MM for the
# padding glued onto the floor (the walls and the step get none).
KEY_HEIGHT_MM = 24.0
KEY_CLEARANCE_MM = 1.0
PADDING_MM = 1.0
FLOOR_MM = 2.0

# The outside is a rounded rectangle WALL_MM beyond the tray pocket's
# bounding box, so the column stagger makes the wall thicker in
# places.
WALL_MM = 2.4

# The notches over the tray's windows, cut through the whole wall from
# the seam and centered on each window along the wall. The power
# switch's is SWITCH_NOTCH_WIDTH_MM wide and reaches
# SWITCH_NOTCH_MARGIN_MM past the window's far edge. The USB one
# clears an assumed plug grip (the part of the plug a hand holds) of
# USB_PLUG_GRIP_WIDTH_MM x USB_PLUG_GRIP_HEIGHT_MM, centered on the
# window, by USB_PLUG_GRIP_MARGIN_MM per side and beyond its far edge.
# Both start at the seam, so the two shells' notches form one slot and
# both halves can charge at once.
SWITCH_NOTCH_WIDTH_MM = 12.0
SWITCH_NOTCH_MARGIN_MM = 1.0
USB_PLUG_GRIP_WIDTH_MM = 13.0
USB_PLUG_GRIP_HEIGHT_MM = 7.0
USB_PLUG_GRIP_MARGIN_MM = 0.5

# 5 x 3 mm disc magnets, four per shell, glued into blind pockets in
# the seam face, 0.3 mm deeper than the magnet: room for the glue, and
# the magnet stays below the seam even when the slicer rounds the depth
# to a layer, so it never holds the shells apart. Three sit at the given board x on the north or the
# south wall (the board's +Y or -Y edge), the fourth on the notches'
# wall halfway between the switch and USB notches' facing edges. Each
# is centered across the wall between the tray pocket and the outside.
# 6 mm magnets would fit only the thickest stretches of wall. One
# shell's magnets go in with one pole out, the other shell's with the
# other.
MAGNET_POCKET_DIAMETER_MM = 5.3
MAGNET_POCKET_DEPTH_MM = 3.3
MAGNET_POSITIONS_MM = ((18.8, "north"), (47.15, "south"), (66.2, "south"))

# A 10 x 2 mm Velcro band backs the magnets up: it runs around the
# closed case the short way at board x VELCRO_X_MM, through a tunnel in
# the north and the south wall of each shell from the seam face to the
# floor face, centered across the wall, and outside across the floors.
# Both shells' tunnels line up at the seam. Where the band turns from
# a tunnel onto the floor, the tunnel's inner edge is chamfered at 45
# degrees.
VELCRO_X_MM = 85.25
VELCRO_TUNNEL_LENGTH_MM = 11.0  # along the wall
VELCRO_TUNNEL_WIDTH_MM = 2.6  # across the wall
VELCRO_TUNNEL_CHAMFER_MM = 1.0

# The thinnest plastic left around a magnet pocket or a tunnel, to the
# pockets, the notches, each other and the outside: two nozzle widths.
MINIMUM_WALL_MM = 0.8

# Implementation tuning, rarely worth touching.
CUT_EXTRA_MM = 1.0  # cutters overshoot the faces they open
VOLUME_TOLERANCE = 0.001  # relative, for the volume checks
PROBE_SEGMENT_MINIMUM_LENGTH_MM = 10.0  # outline segments probed at their middle

USAGE = """\
usage: freecadcmd scripts/export_case.py --pass <pcb.step> <case.stl> [right]

  right  export the right half's shell instead of the left half's\
"""

WALL_SIDE_SIGNS = {"north": 1.0, "south": -1.0}


class ShellFrame:
    """Where a shell sits in the STEP frame: the seam plane's z, and
    `into`, the unit vector along Z from the seam into the shell."""

    def __init__(self, seam_z, into):
        self.seam_z = seam_z
        self.into = into

    def point(self, x, y, height):
        """The point over board position (x, y), `height` above the seam."""
        return App.Vector(x, y, self.seam_z).add(self.into * height)


class Notch:
    """A notch through the wall over one of the tray's windows."""

    def __init__(self, label, center, direction, outward, width, reach, cutter, detail):
        self.label = label
        self.center = center  # on the board outline
        self.direction = direction  # along the wall
        self.outward = outward
        self.width = width
        self.reach = reach  # from the seam
        self.cutter = cutter
        self.detail = detail  # for the report


class Hole:
    """A magnet pocket or a Velcro tunnel at board position `center`
    on the north or south wall."""

    def __init__(self, label, center, side, cutter):
        self.label = label
        self.center = center
        self.side = side
        self.cutter = cutter


class CaseShell:
    """One shell as built in the STEP frame, with the cutters of its
    features, which the checks and the report need."""

    def __init__(self):
        self.solid = None
        self.frame = None
        self.outline_wire = None
        self.sharp_outline = None
        self.exterior = None
        self.exterior_corner_radius = None
        self.tray_pocket = None
        self.tray_pocket_radii = None  # (convex, concave)
        self.key_pocket = None
        self.key_pocket_radii = None
        self.notches = []
        self.magnets = []
        self.tunnels = []


def tray_outside_offset():
    """How far the tray's outside lies beyond the board outline."""
    return DEFAULT_GAP_MM + DEFAULT_WALL_MM


def tray_floor_height():
    """The tray floor's top above the seam: the sole and the floor."""
    return SOLE_THICKNESS_MM + DEFAULT_FLOOR_MM


def tray_pocket_depth():
    """From the seam to the tray's rim, where the step is."""
    return tray_floor_height() + DEFAULT_DEPTH_MM


def key_pocket_top():
    return KEY_HEIGHT_MM + KEY_CLEARANCE_MM + PADDING_MM


def shell_height():
    return key_pocket_top() + FLOOR_MM


def parse_arguments(argument_list):
    right = "right" in argument_list
    positionals = [argument for argument in argument_list if argument != "right"]
    if len(positionals) != 2:
        raise SystemExit(USAGE)
    return positionals[0], positionals[1], right


def shell_frame(document, board_shape, outline_face_pair, right):
    """(the board face the tray rests against, the shell's frame). The
    tray opens the way tray_shape.py decides for export_tray.py too,
    and a shell continues its tray's direction from the seam, which
    lies the tray floor and the sole below the tray's cavity floor.
    export_tray.py builds that floor level with the board's resting
    face."""
    axis = outline_face_pair[0].Surface.Axis
    if abs(axis.z) < 0.999:
        raise SystemExit("error: the board does not lie in the STEP frame's XY plane")
    above, below = component_protrusions(document, board_shape, axis)
    resting_face, up = pick_resting_face(
        outline_face_pair, tray_opens_toward_positive_axis(above, below, axis, right)
    )
    seam_z = resting_face.Surface.Position.z - up.z * tray_floor_height()
    return resting_face, ShellFrame(seam_z, up)


def moved_to_height(wire, frame, height):
    """A copy of a wire lying parallel to the seam, moved to `height`
    above it."""
    moved = wire.copy()
    moved.translate(
        App.Vector(0, 0, frame.point(0, 0, height).z - moved.Vertexes[0].Point.z)
    )
    return moved


def pocket_cutter(sharp_outline, offset, convex_radius, concave_radius, frame, top):
    """(cutter, its base polygon) for a pocket from the seam to `top`:
    the sharpened outline offset by `offset` with its corners filleted,
    extruded from CUT_EXTRA_MM below the seam."""
    polygon = moved_to_height(offset_outline(sharp_outline, offset), frame, -CUT_EXTRA_MM)
    prism = Part.Face(polygon).extrude(frame.into * (top + CUT_EXTRA_MM))
    cutter = fillet_prism_corners(prism, polygon, frame.into, convex_radius, concave_radius)
    return cutter, polygon


def cross_section_area(cutter, top):
    """The area of a straight pocket cutter's cross section."""
    return cutter.Volume / (top + CUT_EXTRA_MM)


def planar_faces_at_height(shape, frame, height):
    """The shape's planar faces parallel to the seam at `height`."""
    z = frame.point(0, 0, height).z
    return [
        face
        for face in shape.Faces
        if isinstance(face.Surface, Part.Plane)
        and abs(face.BoundBox.ZMin - z) < 1e-6
        and abs(face.BoundBox.ZMax - z) < 1e-6
    ]


def exterior_body(pocket_polygon, frame, corner_radius):
    """The shell's outside: the tray pocket's bounding box grown by
    WALL_MM, from the seam to the floor face, its vertical corners
    rounded with `corner_radius`."""
    box = pocket_polygon.BoundBox
    low_x, high_x = box.XMin - WALL_MM, box.XMax + WALL_MM
    low_y, high_y = box.YMin - WALL_MM, box.YMax + WALL_MM
    corners = [
        frame.point(x, y, 0.0)
        for x, y in ((low_x, low_y), (high_x, low_y), (high_x, high_y), (low_x, high_y))
    ]
    rectangle = Part.makePolygon(corners + [corners[0]])
    prism = Part.Face(rectangle).extrude(frame.into * shell_height())
    return fillet_prism_corners(prism, rectangle, frame.into, corner_radius, 0.0)


def cut_one_solid(shape, cutter, label):
    """Cut and check that one valid solid is left."""
    result = shape.cut(cutter)
    if not result.isValid() or len(result.Solids) != 1:
        raise SystemExit(f"error: cutting the {label} broke the solid")
    return result


def cut_checked(shape, cutter, expected_removed, label):
    """cut_one_solid(), and check that the cut removed the expected
    volume, which must be worked out without the cut."""
    result = cut_one_solid(shape, cutter, label)
    removed = shape.Volume - result.Volume
    if abs(removed - expected_removed) > VOLUME_TOLERANCE * expected_removed + 0.01:
        raise SystemExit(
            f"error: the {label} removed {removed:.2f} mm3, expected "
            f"{expected_removed:.2f} mm3; geometry is off"
        )
    return result


def notch_cutter(outline_wire, frame, center, direction, width, reach, outer):
    """(cutter, outward) for a notch through the wall: `width` along the
    wall centered on `center` (on the board outline, which lies inside
    the tray pocket), out to `outer` beyond it, from below the seam to
    `reach` above it."""
    outward = wall_outward(outline_wire, center, direction, frame.into)
    base = frame.point(center.x, center.y, -CUT_EXTRA_MM)
    half_width = width / 2.0
    corners = [
        base.add(direction * -half_width),
        base.add(direction * half_width),
        base.add(direction * half_width).add(outward * outer),
        base.add(direction * -half_width).add(outward * outer),
    ]
    prism = Part.Face(Part.makePolygon(corners + [corners[0]])).extrude(
        frame.into * (reach + CUT_EXTRA_MM)
    )
    return prism, outward


def polygon_crossings(polygon, x):
    """The y values where a polygon's edges cross the line at board x."""
    crossings = []
    for edge in polygon.Edges:
        start, end = edge.Vertexes[0].Point, edge.Vertexes[1].Point
        if (start.x - x) * (end.x - x) < 0:
            crossings.append(start.y + (end.y - start.y) * (x - start.x) / (end.x - start.x))
    return crossings


def wall_middle(pocket_polygon, exterior_box, x, side):
    """The y of the wall's middle at board x on the north or the south
    wall, halfway between the tray pocket and the outside."""
    crossings = polygon_crossings(pocket_polygon, x)
    if side == "north":
        return (max(crossings) + exterior_box.YMax) / 2.0
    return (min(crossings) + exterior_box.YMin) / 2.0


def facing_edge(notch, other):
    """The point on the board outline where `notch` ends toward
    `other`, along the wall."""
    toward = 1.0 if notch.direction.dot(other.center.sub(notch.center)) > 0 else -1.0
    return notch.center.add(notch.direction * (toward * notch.width / 2.0))


def between_notches(first, second):
    """(board x, wall side) halfway between two notches' facing edges,
    on the wall they open."""
    x = (facing_edge(first, second).x + facing_edge(second, first).x) / 2.0
    return x, "north" if first.outward.y > 0 else "south"


def magnet_cutter(frame, center):
    return Part.makeCylinder(
        MAGNET_POCKET_DIAMETER_MM / 2.0,
        MAGNET_POCKET_DEPTH_MM + CUT_EXTRA_MM,
        frame.point(center.x, center.y, -CUT_EXTRA_MM),
        frame.into,
    )


def tunnel_inner_face_y(center, side):
    """The y of a tunnel's face toward the board's middle."""
    return center.y - WALL_SIDE_SIGNS[side] * VELCRO_TUNNEL_WIDTH_MM / 2.0


def tunnel_cutter(frame, center, side):
    """A cutter for a Velcro tunnel: from below the seam face to past
    the floor face, with its inner edge at the floor face chamfered.
    The chamfer's cutter is a triangular prism along the tunnel whose
    slanted face is the chamfer, its other two faces inside the tunnel
    and past the floor face."""
    half_length = VELCRO_TUNNEL_LENGTH_MM / 2.0
    half_width = VELCRO_TUNNEL_WIDTH_MM / 2.0
    corners = [
        frame.point(center.x + along, center.y + across, -CUT_EXTRA_MM)
        for along, across in (
            (-half_length, -half_width),
            (half_length, -half_width),
            (half_length, half_width),
            (-half_length, half_width),
        )
    ]
    tunnel = Part.Face(Part.makePolygon(corners + [corners[0]])).extrude(
        frame.into * (shell_height() + 2.0 * CUT_EXTRA_MM)
    )
    sign = WALL_SIDE_SIGNS[side]  # toward the tunnel from its inner face
    inner_y = tunnel_inner_face_y(center, side)
    chamfer = VELCRO_TUNNEL_CHAMFER_MM
    into_tunnel = 0.1
    floor_face = shell_height()
    start_x = center.x - half_length
    triangle = [
        frame.point(start_x, inner_y + sign * into_tunnel, floor_face - chamfer - into_tunnel),
        frame.point(start_x, inner_y - sign * (chamfer + CUT_EXTRA_MM), floor_face + CUT_EXTRA_MM),
        frame.point(start_x, inner_y + sign * into_tunnel, floor_face + CUT_EXTRA_MM),
    ]
    chamfer_prism = Part.Face(Part.makePolygon(triangle + [triangle[0]])).extrude(
        App.Vector(VELCRO_TUNNEL_LENGTH_MM, 0, 0)
    )
    cutter = tunnel.fuse(chamfer_prism).removeSplitter()
    if not cutter.isValid() or len(cutter.Solids) != 1:
        raise SystemExit("error: the Velcro tunnel's cutter is not one solid")
    return cutter


def tunnel_removed_volume():
    """What a tunnel takes out of the wall: the tunnel through the
    shell's height and the chamfer's triangle along it."""
    return VELCRO_TUNNEL_LENGTH_MM * (
        VELCRO_TUNNEL_WIDTH_MM * shell_height() + VELCRO_TUNNEL_CHAMFER_MM**2 / 2.0
    )


def magnet_removed_volume():
    return math.pi * (MAGNET_POCKET_DIAMETER_MM / 2.0) ** 2 * MAGNET_POCKET_DEPTH_MM


def window_notches(outline_wire, frame, right, outer):
    """The power switch and USB notches, centered on the tray's windows
    (tray_shape.py places them) and reaching past them by the margins."""
    switch_by_name = component_positions(re.compile(re.escape(POWER_SWITCH_NAME)))
    if POWER_SWITCH_NAME not in switch_by_name:
        raise SystemExit(
            f"error: power switch '{POWER_SWITCH_NAME}' not found in the board sources"
        )
    mcu_by_name = component_placements(re.compile(re.escape(MCU_NAME)))
    if MCU_NAME not in mcu_by_name:
        raise SystemExit(f"error: microcontroller '{MCU_NAME}' not found in the board sources")
    board_underside = DEFAULT_STANDOFF_HEIGHT_MM  # the board rests on the tray's standoffs
    segments = outline_straight_segments(outline_wire)
    switch_center, switch_direction = switch_window_center_and_direction(
        segments, switch_by_name[POWER_SWITCH_NAME]
    )
    switch_bottom, switch_top = (
        tray_floor_height() + height for height in switch_window_height_band(board_underside)
    )
    switch_reach = switch_top + SWITCH_NOTCH_MARGIN_MM
    usb_center, usb_direction = usb_window_center_and_direction(
        segments, usb_connector_end(mcu_by_name[MCU_NAME]), switch_center
    )
    usb_bottom, usb_top = (
        tray_floor_height() + height for height in usb_window_height_band(board_underside, right)
    )
    usb_middle = (usb_bottom + usb_top) / 2.0
    usb_reach = usb_middle + USB_PLUG_GRIP_HEIGHT_MM / 2.0 + USB_PLUG_GRIP_MARGIN_MM
    usb_width = USB_PLUG_GRIP_WIDTH_MM + 2.0 * USB_PLUG_GRIP_MARGIN_MM
    notches = []
    for label, center, direction, width, reach, detail in (
        (f"{POWER_SWITCH_NAME} switch", switch_center, switch_direction,
         SWITCH_NOTCH_WIDTH_MM, switch_reach,
         f"window {switch_bottom:.2f} to {switch_top:.2f} mm"),
        ("USB", usb_center, usb_direction, usb_width, usb_reach,
         f"{USB_PLUG_GRIP_WIDTH_MM} x {USB_PLUG_GRIP_HEIGHT_MM} mm plug grip "
         f"centered {usb_middle:.2f} mm, window {usb_bottom:.2f} to {usb_top:.2f} mm"),
    ):
        cutter, outward = notch_cutter(outline_wire, frame, center, direction, width, reach, outer)
        notches.append(Notch(label, center, direction, outward, width, reach, cutter, detail))
    return notches


def build_case(document, board_shape, outline_face_pair, right):
    """The shell for the left or the right half, in the STEP frame."""
    case = CaseShell()
    resting_face, case.frame = shell_frame(document, board_shape, outline_face_pair, right)
    frame = case.frame
    case.outline_wire = resting_face.OuterWire
    case.sharp_outline = sharpen_outline(case.outline_wire, frame.into)

    # The tray's corner rule, carried on concentrically: the tray's
    # outside bends with tray_corner_radius() on its convex corners and
    # that less the tray's wall on its concave ones.
    tray_corner = tray_corner_radius(
        offset_outline(case.sharp_outline, tray_outside_offset()),
        DEFAULT_GAP_MM,
        DEFAULT_WALL_MM,
    )
    tray_concave_corner = tray_corner - DEFAULT_WALL_MM
    case.tray_pocket_radii = (
        tray_corner + CASE_CLEARANCE_MM,
        tray_concave_corner - CASE_CLEARANCE_MM,
    )
    case.key_pocket_radii = (
        tray_corner - STEP_OVERLAP_MM,
        tray_concave_corner + STEP_OVERLAP_MM,
    )
    case.tray_pocket, pocket_polygon = pocket_cutter(
        case.sharp_outline, tray_outside_offset() + CASE_CLEARANCE_MM,
        *case.tray_pocket_radii, frame, tray_pocket_depth(),
    )
    case.key_pocket, _ = pocket_cutter(
        case.sharp_outline, tray_outside_offset() - STEP_OVERLAP_MM,
        *case.key_pocket_radii, frame, key_pocket_top(),
    )
    case.exterior_corner_radius = case.tray_pocket_radii[0] + WALL_MM
    case.exterior = exterior_body(pocket_polygon, frame, case.exterior_corner_radius)

    shell = cut_checked(
        case.exterior, case.tray_pocket,
        cross_section_area(case.tray_pocket, tray_pocket_depth()) * tray_pocket_depth(),
        "tray pocket",
    )
    shell = cut_checked(
        shell, case.key_pocket,
        cross_section_area(case.key_pocket, key_pocket_top())
        * (key_pocket_top() - tray_pocket_depth()),
        "key pocket",
    )

    outer = case.exterior.BoundBox.DiagonalLength  # past the outside from anywhere
    case.notches = window_notches(case.outline_wire, frame, right, outer)
    for notch in case.notches:
        shell = cut_one_solid(shell, notch.cutter, f"{notch.label} notch")

    exterior_box = case.exterior.BoundBox
    magnet_positions = MAGNET_POSITIONS_MM + (between_notches(*case.notches),)
    for x, side in magnet_positions:
        center = App.Vector(x, wall_middle(pocket_polygon, exterior_box, x, side), 0.0)
        case.magnets.append(Hole(f"{side} magnet pocket", center, side, magnet_cutter(frame, center)))
    for side in ("north", "south"):
        center = App.Vector(
            VELCRO_X_MM, wall_middle(pocket_polygon, exterior_box, VELCRO_X_MM, side), 0.0
        )
        case.tunnels.append(Hole(f"{side} Velcro tunnel", center, side, tunnel_cutter(frame, center, side)))
    for magnet in case.magnets:
        shell = cut_checked(shell, magnet.cutter, magnet_removed_volume(), magnet.label)
    for tunnel in case.tunnels:
        shell = cut_checked(shell, tunnel.cutter, tunnel_removed_volume(), tunnel.label)
    case.solid = shell.removeSplitter()
    if not case.solid.isValid() or len(case.solid.Solids) != 1:
        raise SystemExit("error: the shell is not one valid solid")
    return case


def expect(solid, point, want_solid, what):
    if solid.isInside(point, 1e-6, True) != want_solid:
        raise SystemExit(
            f"error: {what} is {'open' if want_solid else 'solid'} at "
            f"({point.x:.2f}, {point.y:.2f}, {point.z:.2f})"
        )


def distance_to_box_side(point, outward, box):
    """How far a ray from `point` along the horizontal unit vector
    `outward` runs before it leaves the box in plan view."""
    limits = []
    for component, low, high, start in (
        (outward.x, box.XMin, box.XMax, point.x),
        (outward.y, box.YMin, box.YMax, point.y),
    ):
        if component > 1e-9:
            limits.append((high - start) / component)
        elif component < -1e-9:
            limits.append((low - start) / component)
    return min(limits)


def check_pockets(case):
    """Probe the pockets, the step, the walls and the floor at the
    middle of every long straight stretch of the outline, and the
    floor over the board's middle."""
    solid, frame = case.solid, case.frame
    tray_pocket_offset = tray_outside_offset() + CASE_CLEARANCE_MM
    key_pocket_offset = tray_outside_offset() - STEP_OVERLAP_MM
    tray_middle = tray_pocket_depth() / 2.0
    key_middle = (tray_pocket_depth() + key_pocket_top()) / 2.0
    for start, vector in outline_straight_segments(case.sharp_outline):
        if vector.Length < PROBE_SEGMENT_MINIMUM_LENGTH_MM:
            continue
        direction = App.Vector(vector).normalize()
        middle = start.add(direction * (vector.Length / 2.0))
        outward = wall_outward(case.sharp_outline, middle, direction, frame.into)

        def at(offset, height):
            point = middle.add(outward * offset)
            return frame.point(point.x, point.y, height)

        expect(solid, at(tray_pocket_offset - 0.1, tray_middle), False, "the tray pocket")
        expect(solid, at(tray_pocket_offset + 0.1, tray_middle), True, "the wall beside the tray pocket")
        expect(solid, at((tray_pocket_offset + key_pocket_offset) / 2.0, tray_pocket_depth() + 0.3),
               True, "the step")
        expect(solid, at(key_pocket_offset - 0.1, key_middle), False, "the key pocket")
        expect(solid, at(key_pocket_offset + 0.1, key_middle), True, "the wall beside the key pocket")
    board_middle = Part.Face(case.outline_wire).CenterOfMass
    for height, want_solid, what in (
        (key_pocket_top() - 0.3, False, "the key pocket under the floor"),
        (key_pocket_top() + 0.3, True, "the floor"),
        (shell_height() - 0.3, True, "the floor"),
    ):
        expect(solid, frame.point(board_middle.x, board_middle.y, height), want_solid, what)


def check_notches(case):
    """Probe each notch: open through the wall's middle up to its reach,
    the wall solid above it and beside it."""
    exterior_box = case.exterior.BoundBox
    pocket_offset = tray_outside_offset() + CASE_CLEARANCE_MM
    for notch in case.notches:
        outside = distance_to_box_side(notch.center, notch.outward, exterior_box)
        wall_center = notch.center.add(notch.outward * ((pocket_offset + outside) / 2.0))
        what = f"the {notch.label} notch"
        for along, height, want_solid in (
            (0.0, 0.3, False),
            (0.0, notch.reach / 2.0, False),
            (0.0, notch.reach - 0.3, False),
            (0.0, notch.reach + 0.3, True),
            (notch.width / 2.0 + 0.3, notch.reach / 2.0, True),
            (-(notch.width / 2.0 + 0.3), notch.reach / 2.0, True),
        ):
            point = wall_center.add(notch.direction * along)
            expect(case.solid, case.frame.point(point.x, point.y, height), want_solid, what)


def check_holes(case):
    """Probe each magnet pocket and Velcro tunnel: open inside, solid
    just beyond, the tunnels open along their length and the chamfer
    open at the floor face."""
    solid, frame = case.solid, case.frame
    radius = MAGNET_POCKET_DIAMETER_MM / 2.0
    depth = MAGNET_POCKET_DEPTH_MM
    for magnet in case.magnets:
        x, y = magnet.center.x, magnet.center.y
        for dx, dy, height, want_solid in (
            (0.0, 0.0, 0.3, False),
            (0.0, 0.0, depth - 0.3, False),
            (0.0, 0.0, depth + 0.3, True),
            (radius + 0.3, 0.0, depth / 2.0, True),
            (-(radius + 0.3), 0.0, depth / 2.0, True),
            (0.0, radius + 0.3, depth / 2.0, True),
            (0.0, -(radius + 0.3), depth / 2.0, True),
        ):
            expect(solid, frame.point(x + dx, y + dy, height), want_solid, f"the {magnet.label}")
    half_length = VELCRO_TUNNEL_LENGTH_MM / 2.0
    half_width = VELCRO_TUNNEL_WIDTH_MM / 2.0
    for tunnel in case.tunnels:
        x, y = tunnel.center.x, tunnel.center.y
        what = f"the {tunnel.label}"
        for along in (-(half_length - 0.3), 0.0, half_length - 0.3):
            for height in (0.3, tray_pocket_depth(), key_pocket_top(), shell_height() - 0.3):
                expect(solid, frame.point(x + along, y, height), False, what)
        middle = shell_height() / 2.0
        for dx, dy in (
            (half_length + 0.3, 0.0),
            (-(half_length + 0.3), 0.0),
            (0.0, half_width + 0.3),
            (0.0, -(half_width + 0.3)),
        ):
            expect(solid, frame.point(x + dx, y + dy, middle), True, f"the wall beside {what}")
        toward_tunnel = WALL_SIDE_SIGNS[tunnel.side]
        inner_y = tunnel_inner_face_y(tunnel.center, tunnel.side)
        chamfer = VELCRO_TUNNEL_CHAMFER_MM
        expect(solid, frame.point(x, inner_y - toward_tunnel * 0.5, shell_height() - 0.25),
               False, f"the chamfer of {what}")
        expect(solid, frame.point(x, inner_y - toward_tunnel * 0.3, shell_height() - chamfer - 0.3),
               True, f"the floor below the chamfer of {what}")


def outside_faces(case):
    """The outside's faces that bound the wall: all but the seam face
    and the floor face, which the pockets and tunnels open onto."""
    excluded = planar_faces_at_height(case.exterior, case.frame, 0.0) + planar_faces_at_height(
        case.exterior, case.frame, shell_height()
    )
    return Part.makeCompound(
        [face for face in case.exterior.Faces if not any(face.isSame(other) for other in excluded)]
    )


def thinnest_wall(hole_cutter, voids):
    """(distance, label) of the void nearest a cutter: the thinnest
    plastic left between them."""
    return min((hole_cutter.distToShape(shape)[0], label) for label, shape in voids)


def check_walls(case):
    """Measure the plastic around every magnet pocket and tunnel, to
    the pockets, the notches, each other and the outside, against
    MINIMUM_WALL_MM. Returns one (distance, nearest void) per magnet
    pocket, then per tunnel."""
    voids = [
        ("tray pocket", case.tray_pocket),
        ("key pocket", case.key_pocket),
        ("outside", outside_faces(case)),
    ]
    voids += [(f"{notch.label} notch", notch.cutter) for notch in case.notches]
    holes = case.magnets + case.tunnels
    walls = []
    for hole in holes:
        others = [(other.label, other.cutter) for other in holes if other is not hole]
        distance, nearest = thinnest_wall(hole.cutter, voids + others)
        if distance < MINIMUM_WALL_MM:
            raise SystemExit(
                f"error: the {hole.label} at ({hole.center.x:.2f}, {hole.center.y:.2f}) "
                f"leaves {distance:.2f} mm to the {nearest}, less than {MINIMUM_WALL_MM} mm"
            )
        walls.append((distance, nearest))
    return walls


def notch_clearances(case):
    """For each notch, the distance to the nearest magnet pocket or
    tunnel (check_walls has held them to their minimum walls)."""
    holes = case.magnets + case.tunnels
    return [
        min(notch.cutter.distToShape(hole.cutter)[0] for hole in holes)
        for notch in case.notches
    ]


def turn_for_printing(solid, frame):
    """The shell with its floor on z = 0 and its opening up: one that
    opens toward -Z (the left one) is turned through 180 degrees about
    the X axis first."""
    turned = solid.copy()
    if frame.into.z > 0:
        turned.rotate(turned.BoundBox.Center, App.Vector(1, 0, 0), 180)
    turned.translate(App.Vector(0, 0, -turned.BoundBox.ZMin))
    box = turned.BoundBox
    if abs(box.ZMin) > 0.01 or abs(box.ZMax - shell_height()) > 0.01:
        raise SystemExit(
            f"error: the turned shell spans z {box.ZMin:.2f}..{box.ZMax:.2f}, "
            f"expected 0.00..{shell_height():.2f}"
        )
    center = box.Center
    expect(turned, App.Vector(center.x, center.y, FLOOR_MM / 2.0), True, "the turned shell's floor")
    expect(turned, App.Vector(center.x, center.y, shell_height() - 0.3), False,
           "the turned shell's opening")
    return turned


def main():
    step_file, stl_file, right = parse_arguments(script_arguments(sys.argv))
    document = import_assembly(step_file)
    board_description, board_shape, outline_face_pair = find_board(document)

    case = build_case(document, board_shape, outline_face_pair, right)
    check_pockets(case)
    check_notches(case)
    check_holes(case)
    walls = check_walls(case)
    clearances = notch_clearances(case)
    turned = turn_for_printing(case.solid, case.frame)
    mesh = export_stl(turned, stl_file)
    check_closed_mesh(stl_file)

    half = "right" if right else "left"
    board_box = board_shape.BoundBox
    box = case.exterior.BoundBox
    print(f"board:   {board_description}, {board_box.XLength:.2f} x {board_box.YLength:.2f} mm")
    print(f"case:    {half} shell, {box.XLength:.2f} x {box.YLength:.2f} x {shell_height():.2f} mm "
          f"({2.0 * shell_height():.2f} mm closed), wall {WALL_MM} mm beyond the tray "
          f"pocket's bounding box, corners rounded {case.exterior_corner_radius:.2f} mm, "
          f"volume {case.solid.Volume / 1000.0:.2f} cm3, built opening toward {'-' if case.frame.into.z > 0 else '+'}Z over the "
          f"{half} half's keys{', turned over for printing' if case.frame.into.z > 0 else ''}")
    print(f"pockets: tray pocket from the seam to {tray_pocket_depth():.2f} mm (the tray's "
          f"outside plus {CASE_CLEARANCE_MM} mm per side, corners "
          f"{case.tray_pocket_radii[0]:.2f} / {case.tray_pocket_radii[1]:.2f} mm), key pocket "
          f"to {key_pocket_top():.2f} mm (the tray's outside less {STEP_OVERLAP_MM} mm per side, "
          f"corners {case.key_pocket_radii[0]:.2f} / {case.key_pocket_radii[1]:.2f} mm, keys "
          f"{KEY_HEIGHT_MM} mm plus {KEY_CLEARANCE_MM} mm clearance and {PADDING_MM} mm "
          f"padding), floor {FLOOR_MM} mm")
    print(f"step:    {CASE_CLEARANCE_MM + STEP_OVERLAP_MM:.2f} mm wide at {tray_pocket_depth():.2f} "
          f"mm from the seam, the tray's {DEFAULT_WALL_MM} mm rim on {STEP_OVERLAP_MM:.2f} mm "
          f"of it with the tray centered")
    for notch, clearance in zip(case.notches, clearances):
        print(f"notch:   {notch.label}, {notch.width:.1f} mm wide at ({notch.center.x:.2f}, "
              f"{notch.center.y:.2f}), from the seam to {notch.reach:.2f} mm ({notch.detail} "
              f"from the seam), {clearance:.2f} mm from the nearest magnet pocket or tunnel")
    magnet_list = ", ".join(
        f"({magnet.center.x:.2f}, {magnet.center.y:.2f}) wall {distance:.2f} mm"
        for magnet, (distance, _nearest) in zip(case.magnets, walls)
    )
    print(f"magnets: {len(case.magnets)} pockets {MAGNET_POCKET_DIAMETER_MM} mm across, "
          f"{MAGNET_POCKET_DEPTH_MM} mm deep in the seam face at {magnet_list} "
          f"(at least {MINIMUM_WALL_MM} mm)")
    tunnel_list = ", ".join(
        f"({tunnel.center.x:.2f}, {tunnel.center.y:.2f}) wall {distance:.2f} mm to the {nearest}"
        for tunnel, (distance, nearest) in zip(case.tunnels, walls[len(case.magnets):])
    )
    print(f"velcro:  {len(case.tunnels)} tunnels {VELCRO_TUNNEL_LENGTH_MM} x "
          f"{VELCRO_TUNNEL_WIDTH_MM} mm from the seam face to the floor face, inner edge at "
          f"the floor chamfered {VELCRO_TUNNEL_CHAMFER_MM} mm, at {tunnel_list} "
          f"(at least {MINIMUM_WALL_MM} mm)")
    print(f"wrote:   {stl_file} ({mesh.CountFacets} facets)")


run_and_exit(main)
