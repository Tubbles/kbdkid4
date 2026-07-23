"""Shared helpers for this repo's headless FreeCAD scripts.

Locating the PCB body and its mounting drills inside a LibrePCB STEP
export, plus the scaffolding that makes freecadcmd usable as a script
interpreter. Unlike the export scripts this module has no entry point,
so it is safe to import from probes and other scripts.

The scaffolding exists because freecadcmd (observed on 1.0.0) executes
command line scripts with __name__ set to the file's stem, runs them
twice, always exits 0 even when the script raised, and its option
parser intercepts dash-prefixed arguments even after "--pass". Hence
scripts take key=value words, parse everything after "--pass", and
leave through run_and_exit(), which flushes and calls os._exit() so CI
sees a real exit code and the second run never happens.
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

# The board's mounting drills, which standoffs and plate holes line up
# with.
MOUNTING_HOLE_DIAMETER_MM = 2.4
MOUNTING_HOLE_TOLERANCE_MM = 0.1

# LibrePCB names the board body "PCB" ("PCB1", "PCB2", ... for multiple
# outlines); depending on the FreeCAD version the imported object carries
# the product label ("PCB") or the instance label ("PCB:1").
BOARD_LABEL_PATTERN = re.compile(r"^PCB\d*(:\d+)?$")
BOARD_THICKNESS_RANGE_MM = (0.2, 5.0)
PARTNER_FACE_AREA_TOLERANCE = 0.05

MESH_LINEAR_DEFLECTION_MM = 0.05
MESH_ANGULAR_DEFLECTION_DEGREES = 15.0


def script_arguments(argv):
    """Return the arguments meant for this script.

    Under freecadcmd, sys.argv contains freecadcmd's own arguments too;
    everything after "--pass" is ours. Under a plain python interpreter
    the usual convention applies.
    """
    if "--pass" in argv:
        return argv[argv.index("--pass") + 1 :]
    return argv[1:]


def import_assembly(step_file):
    document = App.newDocument("assembly")
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


def project_to_plane(point, plane_point, normal):
    return point.sub(normal * normal.dot(point.sub(plane_point)))


def mounting_hole_centers(board_shape, up, plane_point):
    """Centers of the board's mounting drills, projected onto the given
    plane.

    A mounting drill appears in the board solid as cylindrical faces of
    the configured diameter with their axis along the board normal,
    together spanning the full circle. The full-circle test excludes
    outline corner arcs; the diameter tolerance excludes pad drills and
    vias (this board's other drills are 0.3, 0.5 and 2.0 mm).
    """
    angular_spans = {}
    centers = {}
    for face in board_shape.Faces:
        surface = face.Surface
        if not isinstance(surface, Part.Cylinder):
            continue
        if abs(surface.Axis.dot(up)) < 0.999:
            continue
        diameter = 2.0 * surface.Radius
        if abs(diameter - MOUNTING_HOLE_DIAMETER_MM) > MOUNTING_HOLE_TOLERANCE_MM:
            continue
        center = project_to_plane(surface.Center, plane_point, up)
        key = (round(center.x, 2), round(center.y, 2), round(center.z, 2))
        parameter_range = face.ParameterRange
        angular_spans[key] = angular_spans.get(key, 0.0) + (
            parameter_range[1] - parameter_range[0]
        )
        centers[key] = center
    found = [
        centers[key]
        for key, span in angular_spans.items()
        if span > 1.9 * math.pi
    ]
    if not found:
        raise SystemExit(
            f"error: no {MOUNTING_HOLE_DIAMETER_MM} mm mounting holes found "
            "in the board"
        )
    return sorted(found, key=lambda center: (center.x, center.y))


def export_stl(shape, stl_file):
    mesh = MeshPart.meshFromShape(
        Shape=shape,
        LinearDeflection=MESH_LINEAR_DEFLECTION_MM,
        AngularDeflection=math.radians(MESH_ANGULAR_DEFLECTION_DEGREES),
        Relative=False,
    )
    mesh.write(stl_file)
    return mesh


def run_and_exit(main_function):
    """Run a script's main() and leave through os._exit(), giving CI a
    real exit code and preventing freecadcmd's second run (see the
    module docstring)."""
    exit_code = 0
    try:
        main_function()
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
