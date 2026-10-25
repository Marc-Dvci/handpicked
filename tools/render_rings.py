"""Render dimension-exact solitaire rings for the YouCam Ring Virtual Try-On.

    blender -b -P tools/render_rings.py -- --out assets/rings --hdri <studio.hdr> [--shapes round,oval] [--quick]

Each render is a three-quarter view of a solitaire on an orthographic camera, so a length in the image is the
same fraction of the band's outer diameter as it is on the real ring. The stone-to-band ratio in the image is
`ratio` (stone width / band outer diameter). The Ring VTO maps the anchor points (the band's inner edge) to the
finger, so the band is drawn about 1.15 times the finger width and the stone follows it: on the hand photo the
stone lands at c_shape x `ratio` x band fit times the finger width, with c_shape and the band fit measured by
eval/e3_render_scale.py from renders made with `--marker`.

For every image the script writes `<name>.json` with the projected inner-edge anchor points (the two points the
API calls `ring_anchor_point`), the stone's and the head's pixel extents, and the geometry in millimetres.
"""
import argparse
import json
import math
import os
import sys

import bmesh
import bpy
from bpy_extras.object_utils import world_to_camera_view
from mathutils import Vector

INNER_D = 17.0          # mm, band inner diameter
BAND_T = 1.7            # mm, radial thickness
OUTER_D = INNER_D + 2 * BAND_T   # mm, band outer diameter: stands for the finger width
BAND_W = 2.0            # mm, width along the finger
CLEARANCE = 0.35        # mm, culet above the band
DEPTH_RATIO = 0.62      # total depth / width across
PRONG_R = 0.36          # mm, prong radius (0.72 mm wire)
RES = 1024
ELEVATION = math.radians(70.0)

METALS = {
    "platinum": {"color": (0.80, 0.80, 0.81, 1.0), "rough": 0.14},
    "yellow": {"color": (0.96, 0.73, 0.38, 1.0), "rough": 0.17},
}

# Typical length-to-width ratio per shape (north-south setting: length runs along the finger).
SHAPES = {
    "round": 1.00, "oval": 1.40, "cushion": 1.10, "emerald": 1.40,
    "pear": 1.60, "princess": 1.00, "radiant": 1.25, "marquise": 2.00,
}


# ---------------------------------------------------------------- outlines (unit half-width a=1, half-length b)
def outline_radius(shape, theta, b):
    """Polar radius of the girdle outline at angle theta (0 = across the finger, +X)."""
    c, s = math.cos(theta), math.sin(theta)
    if shape in ("round", "oval"):
        return 1.0 / math.sqrt((c / 1.0) ** 2 + (s / b) ** 2)
    if shape in ("cushion", "princess", "radiant"):
        n = {"cushion": 2.7, "princess": 9.0, "radiant": 5.0}[shape]
        return (abs(c / 1.0) ** n + abs(s / b) ** n) ** (-1.0 / n)
    if shape == "pear":
        # round half towards -Y, a tapering point towards +Y
        if s <= 0:
            return 1.0 / math.sqrt(c ** 2 + (s / 1.0) ** 2) if b < 1 else 1.0
        # tip at (0, b_tip) where the stone length is 1 + b_tip = 2b
        tip = 2.0 * b - 1.0
        # tangent lines from the tip to the unit circle bound the upper half
        lo, hi = 0.0, max(tip, 1.0) + 1.0
        for _ in range(60):
            mid = (lo + hi) / 2
            x, y = mid * c, mid * s
            if _inside_pear(x, y, tip):
                lo = mid
            else:
                hi = mid
        return lo
    if shape == "marquise":
        # intersection of two circles; tips at (0, +-b), half-width 1
        rc = (b * b + 1.0) / 2.0
        lo, hi = 0.0, b + 1.0
        for _ in range(60):
            mid = (lo + hi) / 2
            x, y = mid * c, mid * s
            if (x + rc - 1.0) ** 2 + y ** 2 <= rc ** 2 and (x - rc + 1.0) ** 2 + y ** 2 <= rc ** 2:
                lo = mid
            else:
                hi = mid
        return lo
    if shape == "emerald":
        cut = 0.16 * min(1.0, b)
        lim = [1.0 / abs(c) if abs(c) > 1e-9 else 1e9, b / abs(s) if abs(s) > 1e-9 else 1e9,
               (1.0 + b - cut) / (abs(c) + abs(s))]
        return min(lim)
    raise ValueError(shape)


def _inside_pear(x, y, tip):
    if y <= 0:
        return x * x + y * y <= 1.0
    # convex hull of the unit circle and the tip point (0, tip)
    if x * x + y * y <= 1.0:
        return True
    d = tip
    if d <= 1.0:
        return False
    # tangent point T on the unit circle seen from the tip P = (0, d): sin(angle) = 1 / d
    phi = math.asin(1.0 / d)
    tx, ty = math.cos(phi), math.sin(phi)
    if y < ty or y > d:
        return False
    sx = abs(x)
    # inside when on the origin's side of the line P -> T
    return tx * (y - d) - (ty - d) * sx <= 0


# ---------------------------------------------------------------- stone meshes
def brilliant_points(shape, b, n_girdle=96):
    """Points of a modified brilliant on the unit outline (half-width 1). Depth units: half-width."""
    table, crown_h, girdle, pav = 0.57, 0.30, 0.03, 0.86
    pts = []

    def at(r, th, z):
        rho = outline_radius(shape, th, b)
        pts.append((r * rho * math.cos(th), r * rho * math.sin(th), z))

    for k in range(8):
        at(table, k * math.pi / 4, crown_h)
    for k in range(8):
        th = (k + 0.5) * math.pi / 4
        at(0.79, th, crown_h * 0.50)
    for k in range(16):
        th = k * math.pi / 8
        bump = 0.010 if k % 2 == 0 else 0.0
        at(1.0, th, girdle / 2 + bump)
    for k in range(n_girdle):
        th = 2 * math.pi * k / n_girdle
        at(1.0, th, girdle / 2 * 0.98)
        at(1.0, th, -girdle / 2)
    for k in range(8):
        th = (k + 0.5) * math.pi / 4
        at(0.24, th, -girdle / 2 - pav * (1 - 0.24) * 1.01)
    for k in range(8):
        at(0.55, k * math.pi / 4, -girdle / 2 - pav * (1 - 0.55))
    pts.append((0.0, 0.0, -girdle / 2 - pav))
    return pts


def step_points(b, corner=0.16):
    """Emerald (step) cut on a rectangle with cut corners. Unit half-width."""
    pts = []

    def octagon(sx, sy, z):
        c = corner * min(sx, sy) / 1.0
        for x, y in ((sx - c, sy), (sx, sy - c), (sx, -sy + c), (sx - c, -sy),
                     (-sx + c, -sy), (-sx, -sy + c), (-sx, sy - c), (-sx + c, sy)):
            pts.append((x, y, z))

    girdle = 0.03
    crown = [(0.62, 0.24), (0.80, 0.16), (0.92, 0.08)]   # (scale, z)
    for sc, z in crown:
        octagon(sc, b - (1 - sc), z)
    octagon(1.0, b, girdle / 2)
    octagon(1.0, b, -girdle / 2)
    pav = [(0.84, -0.22), (0.62, -0.48), (0.36, -0.72)]
    for sc, z in pav:
        octagon(sc, max(b - (1 - sc) * 1.05, sc * 0.2), z)
    keel = b - 1.0 + 0.10
    pts.append((0.06, keel, -0.88))
    pts.append((-0.06, keel, -0.88))
    pts.append((0.06, -keel, -0.88))
    pts.append((-0.06, -keel, -0.88))
    return pts


def hull_object(name, pts, scale, offset, mat):
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    verts = [bm.verts.new((p[0] * scale[0], p[1] * scale[1], p[2] * scale[2])) for p in pts]
    bmesh.ops.convex_hull(bm, input=verts)
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new(name, me)
    ob.location = offset
    ob.data.materials.append(mat)
    for poly in ob.data.polygons:
        poly.use_smooth = False
    bpy.context.collection.objects.link(ob)
    return ob


# ---------------------------------------------------------------- materials, scene
def metal_material(kind):
    m = bpy.data.materials.new("metal_" + kind)
    m.use_nodes = True
    p = m.node_tree.nodes["Principled BSDF"]
    p.inputs["Base Color"].default_value = METALS[kind]["color"]
    p.inputs["Metallic"].default_value = 1.0
    p.inputs["Roughness"].default_value = METALS[kind]["rough"]
    return m


def marker_material():
    """Flat green stone for the calibration renders: easy to segment in the try-on output."""
    m = bpy.data.materials.new("marker")
    m.use_nodes = True
    nt = m.node_tree
    for n in list(nt.nodes):
        if n.type != "OUTPUT_MATERIAL":
            nt.nodes.remove(n)
    e = nt.nodes.new("ShaderNodeEmission")
    e.inputs["Color"].default_value = (0.0, 0.85, 0.12, 1.0)
    e.inputs["Strength"].default_value = 1.0
    nt.links.new(e.outputs[0], nt.nodes["Material Output"].inputs["Surface"])
    return m


def diamond_material():
    m = bpy.data.materials.new("diamond")
    m.use_nodes = True
    nt = m.node_tree
    for n in list(nt.nodes):
        if n.type != "OUTPUT_MATERIAL":
            nt.nodes.remove(n)
    g = nt.nodes.new("ShaderNodeBsdfGlass")
    g.inputs["IOR"].default_value = 2.417
    g.inputs["Roughness"].default_value = 0.0
    g.inputs["Color"].default_value = (1, 1, 1, 1)
    if "Dispersion" in g.inputs:
        g.inputs["Dispersion"].default_value = 0.044
    nt.links.new(g.outputs[0], nt.nodes["Material Output"].inputs["Surface"])
    return m


def reset_scene(hdri):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc = bpy.context.scene
    sc.render.engine = "CYCLES"
    prefs = bpy.context.preferences.addons["cycles"].preferences
    for dev_type in ("OPTIX", "CUDA"):
        try:
            prefs.compute_device_type = dev_type
            prefs.get_devices()
            if any(d.type == dev_type for d in prefs.devices):
                for d in prefs.devices:
                    d.use = d.type == dev_type
                sc.cycles.device = "GPU"
                break
        except Exception:
            continue
    sc.cycles.samples = 160
    sc.cycles.use_denoising = True
    sc.cycles.max_bounces = 48
    sc.cycles.transmission_bounces = 32
    sc.cycles.glossy_bounces = 16
    sc.cycles.caustics_reflective = False
    sc.cycles.caustics_refractive = False
    sc.render.film_transparent = True
    sc.render.resolution_x = RES
    sc.render.resolution_y = RES
    sc.render.image_settings.file_format = "PNG"
    sc.render.image_settings.color_mode = "RGBA"
    sc.view_settings.view_transform = "Standard"
    sc.unit_settings.scale_length = 0.001
    world = bpy.data.worlds.new("studio")
    sc.world = world
    world.use_nodes = True
    nt = world.node_tree
    env = nt.nodes.new("ShaderNodeTexEnvironment")
    env.image = bpy.data.images.load(hdri)
    bg = nt.nodes["Background"]
    bg.inputs["Strength"].default_value = 1.35
    gray = nt.nodes.new("ShaderNodeRGBToBW")   # neutral light: no colour cast on platinum or the stone
    nt.links.new(env.outputs["Color"], gray.inputs["Color"])
    nt.links.new(gray.outputs["Val"], bg.inputs["Color"])
    sc.view_settings.exposure = 0.35
    # small hard softboxes give the facets their light and dark contrast
    for i, (pos, power) in enumerate((((-60, -40, 120), 900), ((70, -30, 110), 700), ((0, -120, 60), 500), ((0, 60, 140), 400))):
        light = bpy.data.lights.new(f"box{i}", "AREA")
        light.shape = "SQUARE"
        light.size = 40
        light.energy = power * 40
        ob = bpy.data.objects.new(f"box{i}", light)
        ob.location = pos
        ob.rotation_mode = "QUATERNION"
        ob.rotation_quaternion = (-Vector(pos)).to_track_quat("-Z", "Y")
        sc.collection.objects.link(ob)
    return sc


def add_band(mat):
    major = INNER_D / 2 + BAND_T / 2
    bpy.ops.mesh.primitive_torus_add(major_radius=major, minor_radius=BAND_T / 2, major_segments=192, minor_segments=36,
                                     rotation=(math.pi / 2, 0, 0))
    ob = bpy.context.active_object
    ob.scale = (1.0, 1.0, BAND_W / BAND_T)   # local Z is the ring axis before rotation, so it sets band width
    ob.data.materials.append(mat)
    bpy.ops.object.shade_smooth()
    return ob


def cylinder_between(p0, p1, r, mat, name):
    p0, p1 = Vector(p0), Vector(p1)
    d = p1 - p0
    bpy.ops.mesh.primitive_cylinder_add(radius=r, depth=d.length, vertices=24, location=(p0 + p1) / 2)
    ob = bpy.context.active_object
    ob.rotation_mode = "QUATERNION"
    ob.rotation_quaternion = Vector((0, 0, 1)).rotation_difference(d.normalized())
    ob.name = name
    ob.data.materials.append(mat)
    bpy.ops.object.shade_smooth()
    return ob


def sphere(at, r, mat, name):
    bpy.ops.mesh.primitive_uv_sphere_add(radius=r, location=at, segments=24, ring_count=16)
    ob = bpy.context.active_object
    ob.name = name
    ob.data.materials.append(mat)
    bpy.ops.object.shade_smooth()
    return ob


def prong_angles(shape, b):
    if shape == "pear":
        return [math.pi / 2, math.radians(200), math.radians(340), math.radians(150), math.radians(30)]
    if shape == "marquise":
        return [math.pi / 2, -math.pi / 2, math.radians(25), math.radians(155), math.radians(205), math.radians(335)]
    if shape in ("emerald", "princess", "radiant"):
        a = math.atan2(b, 1.0)
        return [a, math.pi - a, math.pi + a, -a]
    return [math.radians(a) for a in (45, 135, 225, 315)]


def build_ring(shape, ratio, metal, marker=False):
    """Stone width across the finger = ratio * OUTER_D. Returns geometry facts in mm."""
    b = SHAPES[shape]
    w = ratio * OUTER_D                     # mm across the finger
    half = w / 2
    depth = DEPTH_RATIO * w
    band_top = INNER_D / 2 + BAND_T
    pav = 0.86 * half * (DEPTH_RATIO / 0.62)
    girdle_z = band_top + CLEARANCE + depth * 0.70
    mmat, dmat = metal_material(metal), (marker_material() if marker else diamond_material())
    add_band(mmat)
    pts = step_points(b) if shape == "emerald" else brilliant_points(shape, b)
    zscale = depth / 1.19 if shape != "emerald" else depth / 1.12
    hull_object("stone", pts, (half, half, zscale), (0, 0, girdle_z), dmat)
    # prongs: claw over the crown edge, wire down to the band top, plus a gallery rail
    head_xmax = half
    for i, th in enumerate(prong_angles(shape, b)):
        rho = outline_radius(shape, th, b) * half
        out = 0.95 if shape in ("pear", "marquise") and abs(math.sin(th)) > 0.99 else 1.03   # V-prong at a tip
        tip = (rho * out * math.cos(th), rho * out * math.sin(th), girdle_z + 0.10 * depth)
        foot = (0.28 * half * math.cos(th), 0.45 * min(b, 1.6) * half * math.sin(th) * 0.6, band_top - 0.25)
        cylinder_between(tip, foot, PRONG_R, mmat, f"prong{i}")
        sphere(tip, PRONG_R * 1.12, mmat, f"claw{i}")
        head_xmax = max(head_xmax, abs(tip[0]) + PRONG_R * 1.12)
    rail_z = girdle_z - 0.45 * depth * 0.70
    bpy.ops.mesh.primitive_torus_add(major_radius=0.72 * half, minor_radius=PRONG_R * 0.75, location=(0, 0, rail_z),
                                     major_segments=96, minor_segments=16)
    rail = bpy.context.active_object
    rail.scale = (1.0, min(b, 1.6) * 0.9, 1.0)
    rail.data.materials.append(mmat)
    bpy.ops.object.shade_smooth()
    return {"stone_width_mm": w, "stone_length_mm": w * b, "depth_mm": depth, "girdle_z": girdle_z,
            "head_half_width_mm": head_xmax, "band_top": band_top, "ratio_lw": b}


def add_camera(girdle_z):
    cam_data = bpy.data.cameras.new("cam")
    cam_data.type = "ORTHO"
    outer = INNER_D + 2 * BAND_T
    cam_data.ortho_scale = outer * 1.22
    cam = bpy.data.objects.new("cam", cam_data)
    bpy.context.collection.objects.link(cam)
    target = Vector((0, 0, girdle_z * 0.32))
    direction = Vector((0, -math.cos(ELEVATION), math.sin(ELEVATION)))
    cam.location = target + direction * 200.0
    cam.rotation_mode = "QUATERNION"
    cam.rotation_quaternion = (-direction).to_track_quat("-Z", "Y")
    bpy.context.scene.camera = cam
    return cam


def project(cam, p):
    sc = bpy.context.scene
    v = world_to_camera_view(sc, cam, Vector(p))
    return [round(v.x * RES, 2), round((1 - v.y) * RES, 2)]


def render_one(out_dir, shape, ratio, metal, hdri, samples=160, marker=False):
    reset_scene(hdri)
    bpy.context.scene.cycles.samples = samples
    geo = build_ring(shape, ratio, metal, marker)
    cam = add_camera(geo["girdle_z"])
    name = f"{shape}_{'marker' if marker else metal}_r{int(round(ratio * 1000)):03d}"
    sc = bpy.context.scene
    sc.render.filepath = os.path.join(out_dir, name + ".png")
    bpy.ops.render.render(write_still=True)
    half = geo["stone_width_mm"] / 2
    left, right = project(cam, (-INNER_D / 2, 0, 0)), project(cam, (INNER_D / 2, 0, 0))
    outer_l, outer_r = project(cam, (-OUTER_D / 2, 0, 0)), project(cam, (OUTER_D / 2, 0, 0))
    stone_l, stone_r = project(cam, (-half, 0, geo["girdle_z"])), project(cam, (half, 0, geo["girdle_z"]))
    hh = geo["head_half_width_mm"]
    meta = {
        "name": name, "shape": shape, "metal": metal, "ratio": ratio, "image": name + ".png", "marker": marker,
        "resolution": RES, "inner_diameter_mm": INNER_D, "outer_diameter_mm": OUTER_D, "band_width_mm": BAND_W,
        "band_thickness_mm": BAND_T, "fit_width": "outer_diameter_mm",
        "length_to_width": geo["ratio_lw"], "stone_width_mm": round(geo["stone_width_mm"], 4),
        "stone_length_mm": round(geo["stone_length_mm"], 4), "depth_mm": round(geo["depth_mm"], 4),
        "head_width_mm": round(2 * hh, 4),
        "anchor_points": [[int(round(left[0])), int(round(left[1]))], [int(round(right[0])), int(round(right[1]))]],
        "inner_edge_px": [left, right], "outer_edge_px": [outer_l, outer_r], "stone_px": [stone_l, stone_r],
        "px_per_mm": round((right[0] - left[0]) / INNER_D, 5),
        "camera": {"type": "orthographic", "elevation_deg": round(math.degrees(ELEVATION), 1)},
    }
    with open(os.path.join(out_dir, name + ".json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=1)
    return meta


def render_band(out_dir, metal, hdri, samples=112):
    """A plain wedding band in the same view, for the stacked try-on."""
    reset_scene(hdri)
    bpy.context.scene.cycles.samples = samples
    add_band(metal_material(metal))
    cam = add_camera(INNER_D / 2 + BAND_T + 3.0)
    name = f"band_{metal}"
    bpy.context.scene.render.filepath = os.path.join(out_dir, name + ".png")
    bpy.ops.render.render(write_still=True)
    left, right = project(cam, (-INNER_D / 2, 0, 0)), project(cam, (INNER_D / 2, 0, 0))
    meta = {"name": name, "shape": "band", "metal": metal, "image": name + ".png", "resolution": RES,
            "inner_diameter_mm": INNER_D, "outer_diameter_mm": OUTER_D, "band_width_mm": BAND_W,
            "anchor_points": [[int(round(left[0])), int(round(left[1]))], [int(round(right[0])), int(round(right[1]))]]}
    with open(os.path.join(out_dir, name + ".json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=1)
    return meta


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--hdri", required=True)
    ap.add_argument("--shapes", default=",".join(SHAPES))
    ap.add_argument("--metals", default="platinum,yellow")
    ap.add_argument("--ratios", default="")
    ap.add_argument("--quick", action="store_true", help="48 samples, for a look test")
    ap.add_argument("--marker", action="store_true", help="green calibration stones (platinum band only)")
    args = ap.parse_args(argv)
    args.out, args.hdri = os.path.abspath(args.out), os.path.abspath(args.hdri)
    os.makedirs(args.out, exist_ok=True)
    if args.marker:
        args.metals = "platinum"
    for metal in args.metals.split(","):
        if args.marker:
            break
        if not os.path.exists(os.path.join(args.out, f"band_{metal}.json")):
            render_band(args.out, metal, args.hdri, 48 if args.quick else 112)
    ratios = [float(x) for x in args.ratios.split(",")] if args.ratios else [round(0.16 + 0.02 * i, 2) for i in range(27)]
    for shape in args.shapes.split(","):
        for metal in args.metals.split(","):
            for r in ratios:
                name = f"{shape}_{'marker' if args.marker else metal}_r{int(round(r * 1000)):03d}"
                if os.path.exists(os.path.join(args.out, name + ".json")):
                    continue
                meta = render_one(args.out, shape, r, metal, args.hdri, 48 if args.quick else 112, args.marker)
                print("rendered", meta["name"], flush=True)


if __name__ == "__main__":
    main()
