"""Export the 3D-printable axle of a solder spool holder (STL).

A cradle holds the axle by the stub on each end face, and the solder
spool hangs on the axle's body by its bore. The spools this is for
have a rim inside the bore at one face, about 2 mm wide and 2 mm high
(1.8 mm on some), so on a plain cylinder they rest on the rim at one
end and on the bore at the other and do not lie flat. The body gets a
groove under the rim, so the bore rests on the body along its whole
length, and the groove also keeps the spool from sliding along the
axle.
The spool sits centered on the body with its rim face toward the
groove's end. A spool put on the other way round needs the axle turned
over.

Runs headless under FreeCAD's console interpreter (see board_step.py
for the freecadcmd quirks that shape the invocation):

    freecadcmd scripts/export_spool_axle.py --pass <axle.stl>

The axle's axis is the Z axis, with one stub's end face on z = 0.
"""

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import FreeCAD as App
import Part

from board_step import check_closed_mesh, export_stl, run_and_exit, script_arguments

# The body the spool's bore rests on, with its two end edges rounded.
BODY_DIAMETER_MM = 19.0
BODY_LENGTH_MM = 39.5
BODY_EDGE_RADIUS_MM = 1.12

# The stub centered on each end face, which the cradle holds, with its
# free end's edge rounded.
STUB_DIAMETER_MM = 7.9
STUB_LENGTH_MM = 2.6
STUB_EDGE_RADIUS_MM = 0.7

# The spool is 27 mm long (27.5 mm bore, 45 mm across). Its rim is
# taken to sit flush with the spool's face, so the rim's center is half
# its 2 mm width in from the face. The groove fits a 2.0 mm rim with
# 0.3 mm of play per side, and is deeper than the rim is high so the
# rim never bottoms out.
SPOOL_LENGTH_MM = 27.0
SPOOL_RIM_CENTER_FROM_FACE_MM = 1.0
GROOVE_WIDTH_MM = 2.6
GROOVE_DEPTH_MM = 2.4

# Implementation tuning, rarely worth touching.
CUT_EXTRA_MM = 1.0  # the groove cutter overshoots the body's surface
VOLUME_TOLERANCE = 1e-6  # relative

USAGE = """\
usage: freecadcmd scripts/export_spool_axle.py --pass <axle.stl>\
"""


def groove_center_from_body_end():
    """Along the axis from the body's end face nearest the groove: the
    spool centered on the body, plus its rim's offset from its face."""
    return (BODY_LENGTH_MM - SPOOL_LENGTH_MM) / 2.0 + SPOOL_RIM_CENTER_FROM_FACE_MM


def circle_edges_at(shape, height):
    return [
        edge
        for edge in shape.Edges
        if isinstance(edge.Curve, Part.Circle) and abs(edge.Curve.Center.z - height) < 1e-6
    ]


def rounded_cylinder(radius, length, base_height, edge_radius, rounded_end_heights):
    """A cylinder along Z from base_height, with the edges of the end
    faces at rounded_end_heights rounded to edge_radius."""
    cylinder = Part.makeCylinder(radius, length, App.Vector(0, 0, base_height))
    edges = [
        edge for height in rounded_end_heights for edge in circle_edges_at(cylinder, height)
    ]
    return cylinder.makeFillet(edge_radius, edges)


def groove_cutter(groove_center):
    """A ring around the body, GROOVE_WIDTH_MM long along Z centered on
    groove_center, reaching GROOVE_DEPTH_MM into it."""
    bottom = App.Vector(0, 0, groove_center - GROOVE_WIDTH_MM / 2.0)
    outer = Part.makeCylinder(BODY_DIAMETER_MM / 2.0 + CUT_EXTRA_MM, GROOVE_WIDTH_MM, bottom)
    inner = Part.makeCylinder(BODY_DIAMETER_MM / 2.0 - GROOVE_DEPTH_MM, GROOVE_WIDTH_MM, bottom)
    return outer.cut(inner)


def build_axle():
    body_bottom = STUB_LENGTH_MM
    body_top = body_bottom + BODY_LENGTH_MM
    body = rounded_cylinder(
        BODY_DIAMETER_MM / 2.0, BODY_LENGTH_MM, body_bottom,
        BODY_EDGE_RADIUS_MM, [body_bottom, body_top],
    )
    bottom_stub = rounded_cylinder(
        STUB_DIAMETER_MM / 2.0, STUB_LENGTH_MM, 0.0, STUB_EDGE_RADIUS_MM, [0.0]
    )
    top_stub = rounded_cylinder(
        STUB_DIAMETER_MM / 2.0, STUB_LENGTH_MM, body_top,
        STUB_EDGE_RADIUS_MM, [body_top + STUB_LENGTH_MM],
    )
    axle = body.fuse([bottom_stub, top_stub]).removeSplitter()
    groove_center = body_bottom + groove_center_from_body_end()
    return axle.cut(groove_cutter(groove_center)), groove_center


def rounded_edge_volume(radius, edge_radius):
    """The volume a rounded edge of that radius takes off the end of a
    cylinder of the given radius: the corner square less the quarter
    disc, swept around the axis (Pappus)."""
    return 2.0 * math.pi * edge_radius**2 * (
        radius - edge_radius / 2.0
        - math.pi / 4.0 * (radius - edge_radius)
        - edge_radius / 3.0
    )


def expected_volume():
    body_radius = BODY_DIAMETER_MM / 2.0
    stub_radius = STUB_DIAMETER_MM / 2.0
    groove_radius = body_radius - GROOVE_DEPTH_MM
    return (
        math.pi * body_radius**2 * BODY_LENGTH_MM
        - 2.0 * rounded_edge_volume(body_radius, BODY_EDGE_RADIUS_MM)
        + 2.0 * math.pi * stub_radius**2 * STUB_LENGTH_MM
        - 2.0 * rounded_edge_volume(stub_radius, STUB_EDGE_RADIUS_MM)
        - math.pi * (body_radius**2 - groove_radius**2) * GROOVE_WIDTH_MM
    )


def check_axle(axle, groove_center):
    """One valid solid of the analytic volume, open in the groove and
    solid just beside and below it."""
    if len(axle.Solids) != 1 or not axle.isValid():
        raise SystemExit(f"error: the axle is {len(axle.Solids)} solids or not valid")
    expected = expected_volume()
    if abs(axle.Volume - expected) > VOLUME_TOLERANCE * expected:
        raise SystemExit(
            f"error: the axle is {axle.Volume:.4f} mm3, expected {expected:.4f} mm3"
        )
    body_radius = BODY_DIAMETER_MM / 2.0
    half_width = GROOVE_WIDTH_MM / 2.0
    probes = [
        (body_radius - GROOVE_DEPTH_MM / 2.0, groove_center, False),
        (body_radius - GROOVE_DEPTH_MM - 0.2, groove_center, True),
        (body_radius - 0.2, groove_center - half_width - 0.2, True),
        (body_radius - 0.2, groove_center + half_width + 0.2, True),
    ]
    for radius, height, solid in probes:
        if axle.isInside(App.Vector(radius, 0, height), 1e-6, True) != solid:
            raise SystemExit(
                f"error: the axle is {'open' if solid else 'solid'} at radius "
                f"{radius:.2f} mm, z {height:.2f} mm"
            )


def main():
    arguments = script_arguments(sys.argv)
    if len(arguments) != 1:
        raise SystemExit(USAGE)
    stl_file = arguments[0]
    axle, groove_center = build_axle()
    check_axle(axle, groove_center)
    mesh = export_stl(axle, stl_file)
    check_closed_mesh(stl_file)

    box = axle.BoundBox
    print(f"axle:   {box.XLength:.2f} mm across, {box.ZLength:.2f} mm long, "
          f"{axle.Volume:.1f} mm3")
    print(f"body:   {BODY_DIAMETER_MM} x {BODY_LENGTH_MM} mm, edges rounded "
          f"{BODY_EDGE_RADIUS_MM} mm")
    print(f"stubs:  {STUB_DIAMETER_MM} x {STUB_LENGTH_MM} mm on each end, free "
          f"edges rounded {STUB_EDGE_RADIUS_MM} mm")
    print(f"groove: {GROOVE_WIDTH_MM} mm wide, {GROOVE_DEPTH_MM} mm deep, centered "
          f"{groove_center_from_body_end():.2f} mm from the body's end face "
          f"(z {groove_center:.2f}), for a {SPOOL_LENGTH_MM} mm spool centered "
          f"on the body")
    print(f"wrote:  {stl_file} ({mesh.CountFacets} facets)")


run_and_exit(main)
