"""Export the 3D-printable switch plate (STL) with mounting screw holes.

The plate model is reused from kbdkid3: a parametric switch cell
replicated by a point array into the left plate, with a mirrored right
plate alongside in the same document. The left plate is what gets
exported; the word "right" mirrors the finished export across the
board's center line for the other half, since the board is reversible
and the right half is the left one turned over.

The kbdkid3 plate does not share the kbdkid4 board's origin. The
script aligns it by matching the plate's switch cutout centers to the
board's key switch positions (parsed from the board sources), refusing
anything but a pure translation, and then trims the plate's outer
edges so it fits the tray. Below the microcontroller, next to the
thumb key column, the plate extends sideways to the tray wall.

The board's top right corner, the microcontroller area, has no switch
cells, so the plate extends over it to cover the whole board. The
through-hole parts soldered on the board's underside (the nice!nano,
the battery connector) have their leads sticking up there, so the
extension's underside gets a conical recess at every lead drill found
in the STEP, stopping PLATE_SKIN_MM short of the top face so nothing
shows through. The reset switch gets a pin hole through the plate, to
press it with a SIM ejector pin, and a pocket in the underside for its
body and pads.

The word "covered" makes the variant for a half without the key at
COVERED_SWITCH_NAME (the bottom row's third key, hard to reach): its
switch cutout is filled in solid, flush with the plate's top and bottom
faces, so the board under it is no longer exposed. The key's diode
stays soldered there, so the cover gets a rectangular pit on its
underside, rotated with the diode and DIODE_PIT_DEPTH_MM deep. On the
right half the mirror puts the cover over that half's own key and
diode, which the script checks against the board sources.

The STL is written upside down, top face on z = 0 and the recesses
opening upward, so it prints as is without supports.

Finally the whole pattern of switch cutouts, screw holes, lead
recesses, the reset hole and pocket, and any diode pit is shifted
along +X by pattern_shift (default DEFAULT_PATTERN_SHIFT_MM) while
the outline stays exactly where it is: the first printed plates sat
right in the tray but their holes drifted off the board's features
toward the nice!nano side, and a plate printed with a 0.5 mm shift
came out offset about as far the other way, so 0.25 mm is the current
try. The cause of the drift is still open (SUGGESTIONS.md).

Last, side_shave (default DEFAULT_SIDE_SHAVE_MM) comes off the
plate's west and east edges: the printed plate is a snug fit
across the tray's width.

Right before export the plate's touching solids (the kbdkid3 cells,
the tab, the corner slab, any cover and the strips the pattern shift
fills) are fused into one, so slicers get a single closed mesh
instead of one with coincident internal walls at every solid's
boundary.

The screws clamp the PCB onto the tray's standoffs and the plate sits
over their heads, held down by the switches, so head-sized clearance
holes are cut where the board has its mounting drills, detected in
the kbdkid4 STEP exactly like the tray places its standoffs, so the
plate holes always track the PCB. Every position is cut, even one
that sits mostly in open plate area: whatever sliver of material
protrudes into the screw's path must go. The printout reports how
much plate material surrounds each hole.

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
import Mesh
import Part

from board_step import (
    component_placements,
    component_positions,
    drill_centers,
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

# The screws clamp the PCB onto the tray's standoffs and the plate sits
# over their heads, held down by the switches, so the plate's holes
# swallow the heads.
SCREW_HEAD_DIAMETER_MM = 3.77  # measured
SCREW_HEAD_CLEARANCE_MM = 0.4  # extra so a printed hole clears the head
PLATE_HOLE_DIAMETER_MM = SCREW_HEAD_DIAMETER_MM + SCREW_HEAD_CLEARANCE_MM

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

# The corner extension: bounded on the inside by the switch column's
# east edge and the thumb cell's top edge (both silhouette edges), to
# the east by the board outline plus CORNER_OVERHANG_MM, which like
# the tab ends 0.05 mm short of the tray wall at its default 0.4 mm
# gap, and to the north by the switch column's top edge, so it stays
# flush with the cells beside it rather than following the outline
# there. Every drill up to LEAD_DRILL_MAX_DIAMETER_MM in that corner is
# a through-hole lead (the board's other drills there are the 2.4 mm
# mounting drill); each gets a frustum recess from the underside,
# LEAD_CONE_BASE_DIAMETER_MM wide at the underside narrowing to
# LEAD_CONE_TOP_DIAMETER_MM, reaching to PLATE_SKIN_MM below the top
# face: two 0.2 mm print layers, since the recesses showed through a
# single one.
CORNER_OVERHANG_MM = 0.35
LEAD_DRILL_MAX_DIAMETER_MM = 1.5
LEAD_CONE_BASE_DIAMETER_MM = 2.5
LEAD_CONE_TOP_DIAMETER_MM = 1.0
PLATE_SKIN_MM = 0.4

# The reset switch in that corner is an E-Switch TL3315 style micro
# tactile switch, 4.5 x 4.5 x 0.55 mm, pressed with a SIM ejector pin
# through a RESET_PIN_HOLE_DIAMETER_MM hole centered on it. On its
# footprint (ESWITCH_TL3315NF100Q) the pads' copper spans the given
# half extents along the footprint's x and y, beyond the body's 2.25
# mm. The plate's underside gets a pocket over both, aligned with the
# footprint, RESET_POCKET_MARGIN_MM wider per side and
# RESET_POCKET_DEPTH_MM deep (the switch plus solder and clearance),
# so the rest of the plate's thickness guides the pin. The plate rests
# on the board, so the depth counts from its underside.
RESET_SWITCH_NAME = "S3"
# The board level switches (reset and power), among which the right
# half's reset switch is found: the flipped one at S3's position.
BOARD_SWITCH_NAME_PATTERN = re.compile(r"S[0-9]")
RESET_PIN_HOLE_DIAMETER_MM = 1.5
RESET_FOOTPRINT_HALF_EXTENTS_MM = (2.575, 2.30)  # pads and body, along footprint x and y
RESET_POCKET_MARGIN_MM = 0.5
RESET_POCKET_DEPTH_MM = 1.0

# The covered variant (the word "covered"): one bottom row key is hard
# to reach and left out, so its switch cutout is filled in solid. Its
# diode stays soldered under the cover, which gets a rectangular pit on
# its underside, rotated with the diode. The diode is a SOD-123 (package
# SOD3717X135, measured 1.14 mm tall on the board 2026-10-12) on its
# "Hand Soldering" footprint: the pads' copper spans DIODE_PAD_SPAN_MM
# along the body axis, the body is DIODE_BODY_WIDTH_MM wide across it.
# The pit clears both by DIODE_PIT_MARGIN_MM per side (solder fillets,
# print swelling). It is DIODE_PIT_DEPTH_MM deep, leaving three 0.2 mm
# print layers of the 2.2 mm plate over it: a single layer printed
# translucent over a pit this wide. The right half is the same board
# turned over and its plate is the left one mirrored, so a flipped key
# switch and a flipped diode must sit at exactly the covered ones'
# positions there.
COVERED_SWITCH_NAME = "S123"  # third key from the left in the bottom row
COVERED_DIODE_NAME = "D123"
DIODE_NAME_PATTERN = re.compile(r"D[0-9]{3}")  # this project's key diodes
DIODE_PAD_SPAN_MM = 5.25
DIODE_BODY_WIDTH_MM = 1.56
DIODE_PIT_MARGIN_MM = 0.5
DIODE_PIT_DEPTH_MM = 1.6
COUNTERPART_POSITION_TOLERANCE_MM = 0.01

# Shift of the whole hole pattern along +X relative to the outline, in
# mm, applied last (before the turn and the mirror). On the right half
# it mirrors along with everything else, toward that half's nano side.
DEFAULT_PATTERN_SHIFT_MM = 0.25

# The printed plate is a snug fit across the tray's width; take this
# much off the plate's west and east edges (its extremes along x) at
# the very end, so it comes out 2 x DEFAULT_SIDE_SHAVE_MM narrower.
# The north and south edges stay as they are.
DEFAULT_SIDE_SHAVE_MM = 0.1

# Below this much surrounding plate material a cut is a clearance
# cutout in mostly open plate area rather than a supported screw hole
# (one mounting position lands at a four-cell junction cutout). Only
# affects reporting: every position is cut either way, since whatever
# sliver protrudes into the screw's path must go.
SUPPORTED_HOLE_THRESHOLD = 0.5

# The plate's solids only touch, so fusing them into one before export
# must keep the volume: equal within 1e-13 (relative) on FreeCAD 1.0.
# This allows for numerical noise and still catches the loss of
# anything larger than about 0.01 mm3.
FUSE_VOLUME_TOLERANCE = 1e-6  # relative

USAGE = f"""\
usage: freecadcmd scripts/export_plate.py --pass <pcb.step> <plate.fcstd>
           <plate.stl> [right] [covered]
           [hole_diameter={PLATE_HOLE_DIAMETER_MM}]
           [pattern_shift={DEFAULT_PATTERN_SHIFT_MM}]
           [side_shave={DEFAULT_SIDE_SHAVE_MM}]

  right          export the right half: the plate mirrored across the
                 board's center line
  covered        fill the switch cutout of {COVERED_SWITCH_NAME} solid, with a pit in
                 its underside for {COVERED_DIODE_NAME}, for a plate without that key
                 (on the right half these are S243 and D243)
  pattern_shift  move every cutout, hole and recess this far along +X
                 (toward the nice!nano side on the left half) while the
                 outline stays put, mm
  side_shave     take this much off the plate's west and east edges, mm
  hole_diameter  clearance holes over the screw heads, mm (the measured
                 {SCREW_HEAD_DIAMETER_MM} mm head plus \
{SCREW_HEAD_CLEARANCE_MM} mm)\
"""


class Arguments:
    def __init__(self):
        self.step_file = None
        self.fcstd_file = None
        self.stl_file = None
        self.hole_diameter = PLATE_HOLE_DIAMETER_MM
        self.pattern_shift = DEFAULT_PATTERN_SHIFT_MM
        self.side_shave = DEFAULT_SIDE_SHAVE_MM
        self.right = False
        self.covered = False


def parse_arguments(argument_list):
    arguments = Arguments()
    positionals = []
    for argument in argument_list:
        if argument == "right":
            arguments.right = True
        elif argument == "covered":
            arguments.covered = True
        elif "=" in argument:
            key, _, value = argument.partition("=")
            if key not in ("hole_diameter", "pattern_shift", "side_shave"):
                raise SystemExit(f"error: unknown option '{key}'\n{USAGE}")
            try:
                setattr(arguments, key, float(value))
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


def extend_corner(plate, outline_wire, tab_y_range):
    """Cover the switch-less corner of the board with a slab from the
    switch column's east edge (the rightmost vertical silhouette edge
    above the thumb cell) and the thumb cell's top edge out to the
    board outline plus CORNER_OVERHANG_MM, but no further north than
    the column's top edge. The slab abuts the cells and the tab
    without overlapping them, like the cells abut each other. Returns
    (plate, slab, west_x, south_y, north_y).
    """
    _y_low, south_y = tab_y_range
    box = plate.BoundBox
    plate_center_x = (box.XMin + box.XMax) / 2.0
    candidates = []
    for edge in plate_silhouette_bottom_face(plate).OuterWire.Edges:
        start = edge.valueAt(edge.FirstParameter)
        end = edge.valueAt(edge.LastParameter)
        if abs(start.x - end.x) > 0.01:
            continue
        if min(start.y, end.y) < south_y - 0.01:
            continue
        if start.x < plate_center_x:
            continue
        candidates.append((start.x, max(start.y, end.y)))
    if not candidates:
        raise SystemExit(
            "error: no vertical silhouette edge above the thumb cell to "
            "extend the corner from"
        )
    west_x, north_y = max(candidates)
    prism = Part.Face(offset_outline(outline_wire, CORNER_OVERHANG_MM)).extrude(
        App.Vector(0, 0, box.ZLength)
    )
    prism.translate(App.Vector(0, 0, box.ZMin))
    region = Part.makeBox(
        200.0, north_y - south_y, box.ZLength, App.Vector(west_x, south_y, box.ZMin)
    )
    slab = prism.common(region)
    if len(slab.Solids) != 1 or slab.Volume <= 0:
        raise SystemExit("error: the corner extension is not a single solid")
    if abs(slab.BoundBox.YMax - north_y) > 0.01:
        raise SystemExit(
            f"error: the corner extension reaches y {slab.BoundBox.YMax:.2f}, "
            f"not the column's top edge at {north_y:.2f}"
        )
    return (
        Part.makeCompound(list(plate.Solids) + [slab]),
        slab,
        west_x,
        south_y,
        north_y,
    )


def inside_any(compound, point):
    return any(solid.isInside(point, 1e-6, True) for solid in compound.Solids)


def cut_lead_cones(plate, lead_centers):
    """Cut a frustum recess into the plate's underside at each lead,
    leaving PLATE_SKIN_MM of the top face. Returns (plate, height)."""
    box = plate.BoundBox
    height = box.ZLength - PLATE_SKIN_MM
    if height <= 0:
        raise SystemExit("error: the plate is thinner than the skin above the cones")
    base_radius = LEAD_CONE_BASE_DIAMETER_MM / 2.0
    top_radius = LEAD_CONE_TOP_DIAMETER_MM / 2.0
    slope = (base_radius - top_radius) / height
    extra = 1.0  # the frustum continues below the underside for a clean cut
    cones = [
        Part.makeCone(
            base_radius + slope * extra,
            top_radius,
            height + extra,
            App.Vector(center.x, center.y, box.ZMin - extra),
            App.Vector(0, 0, 1),
        )
        for center in lead_centers
    ]
    volume_before = plate.Volume
    cut = plate.cut(Part.makeCompound(cones))
    removed_volume = volume_before - cut.Volume
    frustum_volume = (
        math.pi * height / 3.0
        * (base_radius**2 + base_radius * top_radius + top_radius**2)
    )
    expected_volume = len(lead_centers) * frustum_volume
    if abs(removed_volume - expected_volume) > 0.01 * expected_volume:
        raise SystemExit(
            f"error: the lead cones removed {removed_volume:.2f} mm3, expected "
            f"{expected_volume:.2f} mm3; a cone is not fully inside the plate"
        )
    for center in lead_centers:
        skin = App.Vector(center.x, center.y, box.ZMax - PLATE_SKIN_MM / 2.0)
        if not inside_any(cut, skin):
            raise SystemExit(
                f"error: the cone at ({center.x:.2f}, {center.y:.2f}) broke "
                "through the plate's top"
            )
        recess = App.Vector(center.x, center.y, box.ZMin + 0.3)
        if inside_any(cut, recess):
            raise SystemExit(
                f"error: the cone at ({center.x:.2f}, {center.y:.2f}) did not "
                "open the underside"
            )
    return cut, height


def reset_pocket_cone_clearance(switch, half_x, half_y, lead_centers):
    """The gap between the reset pocket and the nearest lead cone at the
    plate's underside, where both are widest. An overlap is an error.
    The pocket is a rectangle with the given half extents along the
    switch footprint's axes."""
    base_radius = LEAD_CONE_BASE_DIAMETER_MM / 2.0
    axis_x = footprint_x_axis(switch)
    axis_y = App.Vector(-axis_x.y, axis_x.x, 0.0)
    clearance = None
    for lead in lead_centers:
        offset = lead.sub(switch.position)
        outside_x = max(abs(offset.dot(axis_x)) - half_x, 0.0)
        outside_y = max(abs(offset.dot(axis_y)) - half_y, 0.0)
        gap = math.hypot(outside_x, outside_y) - base_radius
        if gap <= 0.0:
            raise SystemExit(
                f"error: the reset pocket overlaps the lead cone at "
                f"({lead.x:.2f}, {lead.y:.2f})"
            )
        if clearance is None or gap < clearance:
            clearance = gap
    return clearance


def cut_reset_hole(plate, lead_centers):
    """Cut a pin hole through the plate, centered on the reset switch,
    and a pocket for the switch in the plate's underside, aligned with
    its footprint and clear of the lead cones. Returns (plate, center,
    pocket length, pocket width, cone clearance)."""
    switch = placement_by_name(RESET_SWITCH_NAME)
    half_x, half_y = (
        extent + RESET_POCKET_MARGIN_MM for extent in RESET_FOOTPRINT_HALF_EXTENTS_MM
    )
    clearance = reset_pocket_cone_clearance(switch, half_x, half_y, lead_centers)
    box = plate.BoundBox
    depth = RESET_POCKET_DEPTH_MM
    if depth >= box.ZLength:
        raise SystemExit("error: the reset pocket is as deep as the plate is thick")
    radius = RESET_PIN_HOLE_DIAMETER_MM / 2.0
    center = switch.position
    extra = 1.0  # the cutters continue past the plate's faces for a clean cut
    pocket = Part.makeBox(
        2.0 * half_x,
        2.0 * half_y,
        depth + extra,
        App.Vector(-half_x, -half_y, box.ZMin - extra),
    )
    pocket.rotate(App.Vector(0, 0, 0), App.Vector(0, 0, 1), switch.rotation_degrees)
    pocket.translate(center)
    hole = Part.makeCylinder(
        radius,
        box.ZLength + 2.0 * extra,
        App.Vector(center.x, center.y, box.ZMin - extra),
        App.Vector(0, 0, 1),
    )
    volume_before = plate.Volume
    cut = plate.cut(pocket.fuse(hole))
    removed_volume = volume_before - cut.Volume
    expected_volume = (
        4.0 * half_x * half_y * depth + math.pi * radius**2 * (box.ZLength - depth)
    )
    if abs(removed_volume - expected_volume) > 0.01 * expected_volume:
        raise SystemExit(
            f"error: the reset pocket and pin hole removed {removed_volume:.2f} mm3, "
            f"expected {expected_volume:.2f} mm3; they are not fully inside plate "
            "material"
        )
    validate_reset_cut(cut, switch, half_x, half_y, depth, radius)
    return cut, center, 2.0 * half_x, 2.0 * half_y, clearance


def validate_reset_cut(plate, switch, half_x, half_y, depth, radius):
    """Probe the reset pocket and pin hole in footprint coordinates: the
    pocket open near its corners up to its depth and no further, plate
    just outside its sides, the hole open through the rest of the
    plate and no wider."""
    box = plate.BoundBox

    def is_solid(local_x, local_y, z):
        point = switch.map_point(App.Vector(local_x, local_y, 0.0))
        return inside_any(plate, App.Vector(point.x, point.y, z))

    above_pocket = box.ZMin + depth + 0.1
    for sign_x, sign_y in ((1, 1), (1, -1), (-1, 1), (-1, -1)):
        local_x = sign_x * (half_x - 0.2)
        local_y = sign_y * (half_y - 0.2)
        if is_solid(local_x, local_y, box.ZMin + 0.1) or is_solid(
            local_x, local_y, box.ZMin + depth - 0.1
        ):
            raise SystemExit("error: the reset pocket did not open the underside")
        if not is_solid(local_x, local_y, above_pocket):
            raise SystemExit("error: the plate above the reset pocket is missing")
    for local_x, local_y in (
        (half_x + 0.2, 0.0), (-(half_x + 0.2), 0.0),
        (0.0, half_y + 0.2), (0.0, -(half_y + 0.2)),
    ):
        if not is_solid(local_x, local_y, box.ZMin + 0.1):
            raise SystemExit("error: the reset pocket is larger than intended")
    if is_solid(0.0, 0.0, above_pocket) or is_solid(0.0, 0.0, box.ZMax - 0.1):
        raise SystemExit("error: the reset pin hole does not reach the top face")
    if not is_solid(radius + 0.1, 0.0, box.ZMax - 0.1):
        raise SystemExit("error: the reset pin hole is wider than intended")


def placement_by_name(name):
    """The board placement of the component called `name`, from the
    board sources."""
    placements = component_placements(re.compile(re.escape(name)))
    if name not in placements:
        raise SystemExit(f"error: '{name}' not found in the board sources")
    return placements[name]


def flipped_counterpart(name_pattern, placement, kind):
    """The one flipped part matching `name_pattern` at exactly
    `placement`'s position, as (name, placement)."""
    matches = sorted(
        (
            (name, other)
            for name, other in component_placements(name_pattern).items()
            if other.flipped
            and other.position.sub(placement.position).Length
            < COUNTERPART_POSITION_TOLERANCE_MM
        ),
        key=lambda match: match[0],
    )
    if len(matches) != 1:
        raise SystemExit(
            f"error: expected one flipped {kind} for the right half at "
            f"({placement.position.x:.3f}, {placement.position.y:.3f}), "
            f"found {len(matches)}; the mirrored plate would not fit there"
        )
    return matches[0]


def footprint_x_axis(placement):
    """The footprint's x axis (a diode's body axis) in board
    coordinates, as a unit vector."""
    return placement.map_point(App.Vector(1, 0, 0)).sub(
        placement.map_point(App.Vector(0, 0, 0))
    )


def right_half_counterparts(switch, diode):
    """Names of the right half's key switch and diode under the cover:
    the flipped parts at exactly the covered switch's and diode's
    positions, the diode lying along the same board axis. The right
    plate is the left one mirrored, so without them the cover and the
    pit would not fit that half. The pit is symmetric, so the diode may
    point either way along that axis."""
    switch_name, _switch_counterpart = flipped_counterpart(
        SWITCH_NAME_PATTERN, switch, "key switch"
    )
    diode_name, diode_counterpart = flipped_counterpart(
        DIODE_NAME_PATTERN, diode, "diode"
    )
    sine = footprint_x_axis(diode).cross(footprint_x_axis(diode_counterpart)).z
    if abs(sine) > 1e-6:
        raise SystemExit(
            f"error: the right half's {diode_name} does not lie along the same "
            f"board axis as {COVERED_DIODE_NAME} (rotation "
            f"{diode_counterpart.rotation_degrees:.1f} against "
            f"{diode.rotation_degrees:.1f} degrees); the mirrored pit would not fit"
        )
    return [switch_name, diode_name]


def right_half_reset_switch(switch):
    """Name of the right half's reset switch: the flipped board level
    switch at exactly the left one's position, its footprint lying
    along the same board axis. The right plate is the left one
    mirrored, so without it the reset pocket and pin hole would not
    fit that half. The pocket is symmetric, so the footprint may point
    either way along that axis."""
    name, counterpart = flipped_counterpart(
        BOARD_SWITCH_NAME_PATTERN, switch, "reset switch"
    )
    sine = footprint_x_axis(switch).cross(footprint_x_axis(counterpart)).z
    if abs(sine) > 1e-6:
        raise SystemExit(
            f"error: the right half's {name} does not lie along the same board "
            f"axis as {RESET_SWITCH_NAME} (rotation "
            f"{counterpart.rotation_degrees:.1f} against "
            f"{switch.rotation_degrees:.1f} degrees); the mirrored reset pocket "
            "would not fit"
        )
    return name


def solid_bottom_outline(solid):
    """The outer wire of a solid's bottom face."""
    bottom = solid.BoundBox.ZMin
    bottom_faces = [
        face
        for face in solid.Faces
        if isinstance(face.Surface, Part.Plane)
        and abs(face.BoundBox.ZMin - bottom) < 0.001
        and abs(face.BoundBox.ZMax - bottom) < 0.001
    ]
    if len(bottom_faces) != 1:
        raise SystemExit(
            f"error: expected one bottom face on the covered cell, found "
            f"{len(bottom_faces)}"
        )
    return bottom_faces[0].OuterWire


def cutout_bounding_volume(cell):
    """An upper bound for the volume of a cell's cutout: the bounding
    box around every inner wire of the cell's horizontal faces (the
    cutout's openings and the steps inside it), times the cell's
    thickness."""
    inner_wires = [
        wire
        for face in cell.Faces
        if isinstance(face.Surface, Part.Plane) and abs(face.Surface.Axis.z) > 0.999
        for wire in face.Wires
        if not wire.isSame(face.OuterWire)
    ]
    if not inner_wires:
        raise SystemExit("error: the covered cell has no cutout openings")
    box = inner_wires[0].BoundBox
    for wire in inner_wires[1:]:
        box.add(wire.BoundBox)
    return box.XLength * box.YLength * cell.BoundBox.ZLength


def cover_switch_cell(plate, position):
    """Fill the switch cutout at `position` solid: the cell holding it
    (the one solid whose bounding box contains it) is replaced by a
    full-thickness prism of its outer boundary, so its outline and its
    contact with the neighbouring cells stay as they are and the other
    solids are left alone. Returns the plate."""
    indices = [
        index
        for index, solid in enumerate(plate.Solids)
        if solid.BoundBox.XMin < position.x < solid.BoundBox.XMax
        and solid.BoundBox.YMin < position.y < solid.BoundBox.YMax
    ]
    if len(indices) != 1:
        raise SystemExit(
            f"error: expected one plate cell at ({position.x:.2f}, "
            f"{position.y:.2f}) to cover, found {len(indices)}"
        )
    cell = plate.Solids[indices[0]]
    box = plate.BoundBox
    middle = App.Vector(position.x, position.y, box.Center.z)
    if cell.isInside(middle, 1e-6, True):
        raise SystemExit(
            f"error: the cell at ({position.x:.2f}, {position.y:.2f}) has no "
            "switch cutout to cover"
        )
    outline = solid_bottom_outline(cell)
    cover = Part.Face(outline).extrude(App.Vector(0, 0, box.ZLength))
    if cell.cut(cover).Volume > 0.001:
        raise SystemExit("error: the cover does not enclose the cell it replaces")
    cover_box = cover.BoundBox
    if abs(cover_box.ZMin - box.ZMin) > 0.001 or abs(cover_box.ZMax - box.ZMax) > 0.001:
        raise SystemExit(
            f"error: the cover spans z {cover_box.ZMin:.3f} to "
            f"{cover_box.ZMax:.3f}, not the plate's {box.ZMin:.3f} to "
            f"{box.ZMax:.3f}"
        )
    filled_volume = cover.Volume - cell.Volume
    cutout_bound = cutout_bounding_volume(cell)
    if not 0 < filled_volume < cutout_bound:
        raise SystemExit(
            f"error: covering the cell filled {filled_volume:.2f} mm3, expected "
            f"more than 0 and less than the {cutout_bound:.2f} mm3 box around "
            "the cutout"
        )
    solids = list(plate.Solids)
    solids[indices[0]] = cover
    covered = Part.makeCompound(solids)
    if not inside_any(covered, middle):
        raise SystemExit(
            f"error: the cutout at ({position.x:.2f}, {position.y:.2f}) is "
            "still open after covering"
        )
    return covered


def cut_diode_pit(plate, diode):
    """Cut a rectangular pit into the plate's underside for the diode
    under the cover, rotated with the diode, DIODE_PIT_DEPTH_MM deep.
    Returns (plate, length, width, depth)."""
    box = plate.BoundBox
    length = DIODE_PAD_SPAN_MM + 2.0 * DIODE_PIT_MARGIN_MM
    width = DIODE_BODY_WIDTH_MM + 2.0 * DIODE_PIT_MARGIN_MM
    depth = DIODE_PIT_DEPTH_MM
    extra = 1.0  # the pit continues below the underside for a clean cut
    pit = Part.makeBox(
        length,
        width,
        depth + extra,
        App.Vector(-length / 2.0, -width / 2.0, box.ZMin - extra),
    )
    pit.rotate(App.Vector(0, 0, 0), App.Vector(0, 0, 1), diode.rotation_degrees)
    pit.translate(diode.position)
    volume_before = plate.Volume
    cut = plate.cut(pit)
    removed_volume = volume_before - cut.Volume
    expected_volume = length * width * depth
    if abs(removed_volume - expected_volume) > 0.01 * expected_volume:
        raise SystemExit(
            f"error: the diode pit removed {removed_volume:.2f} mm3, expected "
            f"{expected_volume:.2f} mm3; it is not fully inside plate material"
        )
    center = diode.position
    if inside_any(cut, App.Vector(center.x, center.y, box.ZMin + 0.3)):
        raise SystemExit("error: the diode pit did not open the underside")
    if not inside_any(cut, App.Vector(center.x, center.y, box.ZMax - PLATE_SKIN_MM / 2.0)):
        raise SystemExit("error: the diode pit broke through the plate's top")
    return cut, length, width, depth


def turn_upside_down(plate, recess_centers):
    """Rotate the plate 180 degrees about the X axis through its center
    and drop it onto z = 0, so it prints with its top face on the bed
    and the recesses (lead cones, diode pit) at `recess_centers`
    opening upward. Returns the flipped plate."""
    center = plate.BoundBox.Center
    plate.rotate(center, App.Vector(1, 0, 0), 180)
    plate.translate(App.Vector(0, 0, -plate.BoundBox.ZMin))
    box = plate.BoundBox
    for recess in recess_centers:
        flipped = App.Vector(recess.x, 2.0 * center.y - recess.y, 0.0)
        if not inside_any(plate, flipped.add(App.Vector(0, 0, PLATE_SKIN_MM / 2.0))):
            raise SystemExit("error: after flipping, the skin above a recess is not at the bottom")
        if inside_any(plate, flipped.add(App.Vector(0, 0, box.ZMax - 0.3))):
            raise SystemExit("error: after flipping, a recess does not open at the top")
    return plate


def check_turned_reset_pocket(plate, reset_center, depth):
    """After turn_upside_down: the reset pocket around `reset_center`
    (shifted and mirrored along with the pattern) opens upward to
    `depth`, and the pin hole runs on down to the bed. The turn mapped
    y to 2 * center y - y about the plate's center, which it left
    where it was. The probes sit off the center by more than the hole's
    radius and less than the pocket's half width, so they land in the
    pocket beside the hole whatever the footprint's rotation."""
    box = plate.BoundBox
    turned = App.Vector(reset_center.x, 2.0 * box.Center.y - reset_center.y, 0.0)
    hole_radius = RESET_PIN_HOLE_DIAMETER_MM / 2.0
    pocket_half_width = min(RESET_FOOTPRINT_HALF_EXTENTS_MM) + RESET_POCKET_MARGIN_MM
    distance = (hole_radius + pocket_half_width) / 2.0
    for offset_x, offset_y in ((distance, 0.0), (-distance, 0.0), (0.0, distance), (0.0, -distance)):
        point = turned.add(App.Vector(offset_x, offset_y, 0.0))
        if inside_any(plate, point.add(App.Vector(0, 0, box.ZMax - depth + 0.1))):
            raise SystemExit("error: after flipping, the reset pocket does not open at the top")
        if not inside_any(plate, point.add(App.Vector(0, 0, box.ZMax - depth - 0.1))):
            raise SystemExit("error: after flipping, the plate under the reset pocket is missing")
    for z in (0.1, (box.ZMax - depth) / 2.0):
        if inside_any(plate, turned.add(App.Vector(0, 0, z))):
            raise SystemExit("error: after flipping, the reset pin hole does not reach the bed")


def shift_pattern(plate, shift):
    """Move every cutout, hole and recess by `shift` along +X while the
    outline stays where it is: translate the plate, clip it back to its
    original silhouette, and fill the strips that open along the edges
    it moved away from. Returns the plate."""
    if shift == 0:
        return plate
    box = plate.BoundBox
    outline = plate_silhouette_bottom_face(plate).OuterWire
    prism = Part.Face(outline).extrude(App.Vector(0, 0, box.ZLength + 2.0))
    prism.translate(App.Vector(0, 0, box.ZMin - 1.0 - outline.BoundBox.ZMin))
    moved_prism = prism.copy()
    moved_prism.translate(App.Vector(shift, 0, 0))
    moved = plate.copy()
    moved.translate(App.Vector(shift, 0, 0))
    # Clip solid by solid: a common() of the whole compound silently
    # drops a cell (observed on FreeCAD 1.0), the per-solid ones do not.
    clipped_solids = []
    for solid in moved.Solids:
        clipped_solids.extend(solid.common(prism).Solids)
    clipped = Part.makeCompound(clipped_solids)
    fill = prism.cut(moved_prism)
    # The prism overshoots the plate's faces by 1 mm; trim the fill to
    # the plate's own thickness.
    fill = fill.common(Part.makeBox(
        box.XLength + 2.0, box.YLength + 2.0, box.ZLength,
        App.Vector(box.XMin - 1.0, box.YMin - 1.0, box.ZMin),
    ))
    result = Part.makeCompound(list(clipped.Solids) + list(fill.Solids))
    new_box = result.BoundBox
    for before, after, axis in (
        (box.XMin, new_box.XMin, "x min"), (box.XMax, new_box.XMax, "x max"),
        (box.YMin, new_box.YMin, "y min"), (box.YMax, new_box.YMax, "y max"),
    ):
        if abs(before - after) > 0.01:
            raise SystemExit(
                f"error: shifting the pattern moved the outline's {axis} from "
                f"{before:.3f} to {after:.3f}"
            )
    if abs(result.Volume - plate.Volume) > 0.005 * plate.Volume:
        raise SystemExit(
            f"error: shifting the pattern changed the plate volume from "
            f"{plate.Volume:.1f} to {result.Volume:.1f} mm3; a hole must sit "
            "within the shift of an edge"
        )
    return result


def shave_sides(plate, shave):
    """Take `shave` off the plate's west and east edges (its extremes
    along x), leaving the north and south edges and the hole pattern
    where they are. Returns the plate."""
    if shave == 0:
        return plate
    box = plate.BoundBox
    keep = Part.makeBox(
        box.XLength - 2.0 * shave, box.YLength + 2.0, box.ZLength + 2.0,
        App.Vector(box.XMin + shave, box.YMin - 1.0, box.ZMin - 1.0),
    )
    # What should go: the silhouette prism outside the kept box, which
    # equals the plate there as long as no cutout reaches a side edge.
    outline = plate_silhouette_bottom_face(plate).OuterWire
    silhouette = Part.Face(outline).extrude(App.Vector(0, 0, box.ZLength))
    silhouette.translate(App.Vector(0, 0, box.ZMin - outline.BoundBox.ZMin))
    expected_removed = silhouette.cut(keep).Volume
    # Clip solid by solid, as in shift_pattern.
    kept = []
    for solid in plate.Solids:
        kept.extend(solid.common(keep).Solids)
    shaved = Part.makeCompound(kept)
    new_box = shaved.BoundBox
    for expected, actual, axis in (
        (box.XMin + shave, new_box.XMin, "x min"),
        (box.XMax - shave, new_box.XMax, "x max"),
        (box.YMin, new_box.YMin, "y min"),
        (box.YMax, new_box.YMax, "y max"),
    ):
        if abs(expected - actual) > 0.01:
            raise SystemExit(
                f"error: shaving the sides put the outline's {axis} at "
                f"{actual:.3f}, expected {expected:.3f}"
            )
    removed = plate.Volume - shaved.Volume
    if abs(removed - expected_removed) > 0.01 * expected_removed:
        raise SystemExit(
            f"error: shaving the sides removed {removed:.2f} mm3, expected "
            f"{expected_removed:.2f} mm3; a cutout must reach a side edge"
        )
    return shaved


def mirror_for_right_half(plate, recess_centers):
    """Mirror the plate across the YZ plane through its center: the
    right half's plate, since the board is reversible and that half
    is the left one turned over, cells, screw holes, lead recesses,
    reset hole and pocket, and any diode pit included. Returns (plate,
    recess centers) both mirrored.

    This has to run before turn_upside_down: Shape.mirror works on
    the geometry and drops a placement set by rotate or translate
    (observed on FreeCAD 1.0), which would silently undo the turn.
    """
    center = plate.BoundBox.Center
    volume_before = plate.Volume
    mirrored = plate.mirror(center, App.Vector(1, 0, 0))
    if not mirrored.isValid() or abs(mirrored.Volume - volume_before) > 1e-6 * volume_before:
        raise SystemExit("error: mirroring the plate changed its volume")
    mirrored_recesses = [
        App.Vector(2.0 * center.x - recess.x, recess.y, recess.z)
        for recess in recess_centers
    ]
    return mirrored, mirrored_recesses


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


def fuse_into_one_solid(plate):
    """Fuse the plate's touching solids into one, so the STL is a single
    closed shell without internal walls. A boolean on the whole compound
    has silently dropped a cell before (see shift_pattern), hence the
    checks: the result must be one valid solid with the compound's
    volume, since the solids only touch and nothing may be lost.
    Returns the solid."""
    volume_before = plate.Volume
    fused = plate.Solids[0].multiFuse(plate.Solids[1:]).removeSplitter()
    if not fused.isValid() or len(fused.Solids) != 1:
        raise SystemExit(
            f"error: fusing the plate gave {len(fused.Solids)} solids "
            f"(valid: {fused.isValid()}), expected one valid solid"
        )
    if abs(fused.Volume - volume_before) > FUSE_VOLUME_TOLERANCE * volume_before:
        raise SystemExit(
            f"error: fusing the plate changed its volume from {volume_before:.4f} "
            f"to {fused.Volume:.4f} mm3; a solid was lost or two overlapped"
        )
    return fused.Solids[0]


def check_closed_mesh(stl_file):
    """Fail on an STL that is not one closed, manifold shell free of
    self-intersections, read back from the file itself since STL
    stores single precision coordinates. Remove a failing file: it
    must never be left behind as if it were fine."""
    mesh = Mesh.Mesh(stl_file)
    problems = []
    if not mesh.isSolid():
        problems.append("not closed")
    if mesh.hasNonManifolds():
        problems.append("non-manifold")
    components = mesh.countComponents()
    if components != 1:
        problems.append(f"{components} separate components")
    if mesh.hasSelfIntersections():
        problems.append("self-intersecting")
    if problems:
        os.remove(stl_file)
        raise SystemExit(
            f"error: the plate mesh is {', '.join(problems)}, removed {stl_file}"
        )


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
    plate, slab, corner_west_x, corner_south_y, corner_north_y = extend_corner(
        plate, resting_face.OuterWire, tab_y_range
    )
    lead_centers = [
        center
        for center, _diameter in drill_centers(
            board_shape, up, resting_face.Surface.Position,
            0.0, LEAD_DRILL_MAX_DIAMETER_MM,
        )
        if center.x >= corner_west_x and center.y >= corner_south_y
    ]
    if not lead_centers:
        raise SystemExit("error: no lead drills found in the corner extension")
    plate, cone_height = cut_lead_cones(plate, lead_centers)
    if arguments.right:
        right_reset_name = right_half_reset_switch(placement_by_name(RESET_SWITCH_NAME))
    plate, reset_center, pocket_length, pocket_width, cone_clearance = cut_reset_hole(
        plate, lead_centers
    )
    pit_centers = []
    if arguments.covered:
        covered_switch = placement_by_name(COVERED_SWITCH_NAME)
        covered_diode = placement_by_name(COVERED_DIODE_NAME)
        if arguments.right:
            counterpart_names = right_half_counterparts(covered_switch, covered_diode)
        plate = cover_switch_cell(plate, covered_switch.position)
        plate, pit_length, pit_width, pit_depth = cut_diode_pit(plate, covered_diode)
        pit_centers = [covered_diode.position]
    box = plate.BoundBox
    plate, supports = drill_holes(plate, hole_centers, arguments.hole_diameter)
    plate = shift_pattern(plate, arguments.pattern_shift)
    # The lead cones and the diode pit both have to open upward once
    # the plate is turned over, so they travel together from here on.
    recess_centers = [
        App.Vector(recess.x + arguments.pattern_shift, recess.y, recess.z)
        for recess in lead_centers + pit_centers
    ]
    # The reset pocket travels along too but gets its own check after
    # the turn: the recesses' skin probe would land in its pin hole.
    reset_probe = App.Vector(
        reset_center.x + arguments.pattern_shift, reset_center.y, reset_center.z
    )
    plate = shave_sides(plate, arguments.side_shave)
    if arguments.right:
        plate, mirrored = mirror_for_right_half(plate, recess_centers + [reset_probe])
        recess_centers, reset_probe = mirrored[:-1], mirrored[-1]
    plate = turn_upside_down(plate, recess_centers)
    check_turned_reset_pocket(plate, reset_probe, RESET_POCKET_DEPTH_MM)
    solid_count = len(plate.Solids)
    plate = fuse_into_one_solid(plate)
    mesh = export_stl(plate, arguments.stl_file)
    check_closed_mesh(arguments.stl_file)

    print(f"board:      {board_description}, {len(hole_centers)} mounting drills")
    print(f"plate:      '{PLATE_OBJECT_NAME}' from {arguments.fcstd_file}, "
          f"{box.XLength:.2f} x {box.YLength:.2f} x {box.ZLength:.2f} mm, "
          f"{solid_count} solids fused into one")
    print(f"aligned:    moved ({alignment.x:+.3f}, {alignment.y:+.3f}) mm onto the "
          f"board's switch grid ({len(switches)} switches), outer edges "
          f"trimmed {PLATE_EDGE_TRIM_MM} mm")
    print(f"tab:        {MCU_TAB_EXTENSION_MM} mm extension below {MCU_NAME} to "
          f"the tray wall, x {tab_edge_x:.2f} -> {tab_edge_x + MCU_TAB_EXTENSION_MM:.2f}, "
          f"y {tab_y_range[0]:.2f}..{tab_y_range[1]:.2f}")
    slab_box = slab.BoundBox
    print(f"corner:     covered from x {corner_west_x:.2f} and y {corner_south_y:.2f} "
          f"to the outline plus {CORNER_OVERHANG_MM} mm eastward (x to "
          f"{slab_box.XMax:.2f}) and to the column's top edge at y "
          f"{corner_north_y:.2f}, {slab.Volume / box.ZLength:.0f} mm2")
    print(f"cones:      {len(lead_centers)} lead recesses in the corner, "
          f"{LEAD_CONE_BASE_DIAMETER_MM} mm at the underside narrowing to "
          f"{LEAD_CONE_TOP_DIAMETER_MM} mm, {cone_height:.2f} mm tall, "
          f"{PLATE_SKIN_MM} mm of plate left above them")
    reset_note = ""
    if arguments.right:
        reset_note = f", where the right half has {right_reset_name}"
    print(f"reset:      {RESET_PIN_HOLE_DIAMETER_MM} mm pin hole for "
          f"{RESET_SWITCH_NAME} at ({reset_center.x:.2f}, {reset_center.y:.2f}), "
          f"{pocket_length:.2f} x {pocket_width:.2f} mm pocket "
          f"{RESET_POCKET_DEPTH_MM:.2f} mm deep in the underside for the switch, "
          f"{box.ZLength - RESET_POCKET_DEPTH_MM:.2f} mm of plate left to guide the "
          f"pin, {cone_clearance:.2f} mm clear of the nearest lead cone{reset_note}")
    if arguments.covered:
        switch = covered_switch.position
        diode = covered_diode.position
        right_note = ""
        if arguments.right:
            right_note = (f", where the right half has {counterpart_names[0]} and "
                          f"{counterpart_names[1]}")
        print(f"cover:      {COVERED_SWITCH_NAME}'s cutout at ({switch.x:.2f}, "
              f"{switch.y:.2f}) filled solid, {pit_length:.2f} x {pit_width:.2f} mm "
              f"pit {pit_depth:.2f} mm deep in the underside for "
              f"{COVERED_DIODE_NAME} at ({diode.x:.2f}, {diode.y:.2f}), rotated "
              f"{covered_diode.rotation_degrees:.0f} degrees, "
              f"{box.ZLength - pit_depth:.2f} mm of plate left above it{right_note}")
    for center, support in zip(hole_centers, supports):
        note = ""
        if support < SUPPORTED_HOLE_THRESHOLD:
            note = " (mostly open plate area, clearance cut only)"
        print(f"hole:       ({center.x:9.4f}, {center.y:8.4f}) "
              f"{arguments.hole_diameter} mm, {support * 100.0:5.1f} % "
              f"supported{note}")
    print(f"shift:      hole pattern moved {arguments.pattern_shift:+.2f} mm along x "
          f"relative to the outline, which stays put")
    print(f"sides:      {arguments.side_shave:.2f} mm shaved off the west and east "
          f"edges, plate {plate.BoundBox.XLength:.2f} mm wide")
    print(f"half:       {'right, mirrored across the board center line' if arguments.right else 'left'}")
    print(f"print:      written upside down, top face on z = 0 and the lead "
          f"recesses opening upward, {plate.BoundBox.ZLength:.2f} mm tall")
    print(f"wrote:      {arguments.stl_file} ({mesh.CountFacets} facets)")


run_and_exit(main)
