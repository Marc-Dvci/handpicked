"""Render a benchmark of photos of known geometry, to measure the finger-width error of metrology.py.

    blender -b -P tools/render_bench.py -- --out <dir> --n 40 --seed 1 --hdri <studio.hdr> [--samples 48]

Case i is drawn from random.Random(seed * 1000 + i) and writes bench_{i:03d}.png (RGB) and bench_{i:03d}.json: the
ground truth in millimetres, the projected sheet corners and ring landmarks in pixels. A case whose two files already
exist is skipped, so an interrupted run resumes.

Units: 1 Blender unit = 1 mm (scene unit scale 0.001), Z up. The A4 sheet lies in z = 0, centred on the origin, with
the sheet's +Y (its 297 mm side) pointing up in the image. The hand lies in the sheet frame with its fingers toward +Y.

Scene choices:
- The camera sensor matches the 35 mm-equivalent diagonal (43.27 mm), so the lens focal length is the 35 mm-equivalent
  focal length the metrology reads from EXIF.
- The camera looks at a point near the sheet centre from a direction tilted up to 22 degrees from vertical, so it sits
  h x tan(tilt) to the side of the centre, as a hand-held phone does.
- The table is 2400 mm square, so the frame never reaches past it at high tilt.
- The HDRI lights the scene through a greyscale node and is not visible to the camera; one 1.0e6 W area light adds
  soft finger shadows without clipping the paper or light skin to white.
"""
import argparse
import json
import math
import os
import random
import sys
import time

import bpy
from bpy_extras.object_utils import world_to_camera_view
from mathutils import Matrix, Vector

RES_X, RES_Y = 1512, 2016
DIAG_35 = math.hypot(36.0, 24.0)
SENSOR_LONG = DIAG_35 * RES_Y / math.hypot(RES_X, RES_Y)     # sensor size along the image's long side (AUTO fit)

SHEET_W, SHEET_H = 210.0, 297.0
MARGIN_PX = 40
TABLES = {"light_oak": (0.55, 0.38, 0.22), "walnut": (0.25, 0.15, 0.08), "grey_laminate": (0.45, 0.45, 0.45)}
SKINS = {"light": (0.80, 0.60, 0.50), "medium": (0.62, 0.42, 0.30), "dark": (0.32, 0.20, 0.14)}

LIGHT_ENERGY = 1.0e6     # area light power (W): bare paper near 230 sRGB, nothing clipped; --energy overrides it
LIGHT_SIZE = 400.0       # mm
TABLE_SIZE = 2400.0      # mm; the brief's 600 mm table lets the frame reach past its edge at high tilt

RING_LEN = 75.0
KNUCKLE_FROM, KNUCKLE_TO = 45.0, 55.0
MCP_BEFORE_BASE = 12.0   # landmark 13 sits this far inside the palm, along the finger axis
PIP_ALONG = 50.0         # landmark 14 is the knuckle's centre, this far along the finger
MIDDLE_W, LITTLE_W, INDEX_W = 1.05, 0.85, 0.95
MIDDLE_LEN, LITTLE_LEN, INDEX_LEN = 78.0, 65.0, 70.0
INDEX_GAP = 5.0
PALM_LEN, PALM_T, PALM_MIN_W = 90.0, 20.0, 80.0
MAX_TIP = max(RING_LEN, MIDDLE_LEN, LITTLE_LEN, INDEX_LEN)


# ----------------------------------------------------------------------------------------------- sampling
def sample_case(rng):
    c = {
        "table": rng.choice(list(TABLES)),
        "skin": rng.choice(list(SKINS)),
        "w_ring": rng.uniform(14.0, 20.0),
        "depth_ratio": rng.uniform(0.90, 1.00),
    }
    c["w_knuckle"] = c["w_ring"] * rng.uniform(1.02, 1.12)
    c["gap_mid"] = rng.uniform(3.0, 9.0)
    c["gap_little"] = rng.uniform(3.0, 9.0)
    c["yaw"] = rng.uniform(-12.0, 12.0)
    c["hand_off"] = (rng.uniform(-15.0, 15.0), rng.uniform(-15.0, 15.0))
    c["hand_rot"] = rng.uniform(-10.0, 10.0)
    c["focal"] = rng.uniform(24.0, 28.0)
    c["height"] = rng.uniform(300.0, 520.0)
    c["tilt"] = rng.uniform(0.0, 22.0)
    c["azimuth"] = rng.uniform(0.0, 360.0)
    c["roll"] = rng.uniform(-8.0, 8.0)
    c["target"] = (rng.uniform(-20.0, 20.0), rng.uniform(-20.0, 20.0))
    c["paper"] = rng.uniform(0.85, 0.90)
    c["light_pos"] = (rng.uniform(-300.0, 300.0), rng.uniform(-300.0, 300.0), rng.uniform(750.0, 850.0))
    c["light_energy"] = LIGHT_ENERGY * rng.uniform(0.8, 1.2)
    return c


def hand_layout(c):
    """Finger x positions and the hand-frame shift. Base-frame: ring finger axis at x = 0, finger bases at y = 0,
    palm from y = -PALM_LEN to 0. The shift centres the hand's bounding box on the hand-frame origin."""
    wr = c["w_ring"]
    wm, wl, wi = MIDDLE_W * wr, LITTLE_W * wr, INDEX_W * wr
    x_mid = -(wr / 2 + c["gap_mid"] + wm / 2)
    x_little = wr / 2 + c["gap_little"] + wl / 2
    x_index = x_mid - (wm / 2 + INDEX_GAP + wi / 2)
    left, right = x_index - wi / 2, x_little + wl / 2
    xs = -(left + right) / 2
    ys = -(-PALM_LEN + MAX_TIP) / 2
    fingers = {
        "index": (x_index, wi, INDEX_LEN),
        "middle": (x_mid, wm, MIDDLE_LEN),
        "ring": (0.0, wr, RING_LEN),
        "little": (x_little, wl, LITTLE_LEN),
    }
    return {"xs": xs, "ys": ys, "fingers": fingers, "palm_w": max(PALM_MIN_W, right - left + 8.0)}


# ----------------------------------------------------------------------------------------------- scene
def reset_scene(hdri, samples):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc = bpy.context.scene
    sc.render.engine = "CYCLES"
    prefs = bpy.context.preferences.addons["cycles"].preferences
    device_type = None
    for dev_type in ("OPTIX", "CUDA"):
        try:
            prefs.compute_device_type = dev_type
            prefs.get_devices()
            if any(d.type == dev_type for d in prefs.devices):
                for d in prefs.devices:
                    d.use = d.type == dev_type
                sc.cycles.device = "GPU"
                device_type = dev_type
                break
        except Exception:
            continue
    sc.cycles.samples = samples
    sc.cycles.use_denoising = True
    if device_type == "OPTIX":
        try:
            sc.cycles.denoiser = "OPTIX"
        except Exception:
            pass
    sc.render.film_transparent = False
    sc.render.resolution_x = RES_X
    sc.render.resolution_y = RES_Y
    sc.render.resolution_percentage = 100
    sc.render.image_settings.file_format = "PNG"
    sc.render.image_settings.color_mode = "RGB"
    sc.render.image_settings.color_depth = "8"
    sc.view_settings.view_transform = "Standard"
    sc.view_settings.look = "None"
    sc.view_settings.exposure = 0.0
    sc.view_settings.gamma = 1.0
    sc.unit_settings.scale_length = 0.001
    world = bpy.data.worlds.new("studio")
    sc.world = world
    world.use_nodes = True
    nt = world.node_tree
    env = nt.nodes.new("ShaderNodeTexEnvironment")
    env.image = bpy.data.images.load(hdri)
    gray = nt.nodes.new("ShaderNodeRGBToBW")   # neutral light: a coloured HDRI tints the shadows on the paper
    bg = nt.nodes["Background"]
    bg.inputs["Strength"].default_value = 1.0
    nt.links.new(env.outputs["Color"], gray.inputs["Color"])
    nt.links.new(gray.outputs["Val"], bg.inputs["Color"])
    world.cycles_visibility.camera = False      # lights the scene, background stays black
    return sc


def make_camera(sc, c):
    cam_data = bpy.data.cameras.new("cam")
    cam_data.lens = c["focal"]
    cam_data.sensor_fit = "AUTO"
    cam_data.sensor_width = SENSOR_LONG
    cam_data.clip_start = 1.0
    cam_data.clip_end = 20000.0
    cam = bpy.data.objects.new("cam", cam_data)
    sc.collection.objects.link(cam)
    sc.camera = cam
    return cam


def camera_pose(c, height):
    """Camera-to-world matrix: optical axis tilted from vertical toward the azimuth, aimed at a point near the
    sheet centre, at the given height above the sheet plane, with the sheet's long side vertical in the image."""
    t, az = math.radians(c["tilt"]), math.radians(c["azimuth"])
    target = Vector((c["target"][0], c["target"][1], 0.0))
    fwd = Vector((math.sin(t) * math.cos(az), math.sin(t) * math.sin(az), -math.cos(t)))
    pos = target - fwd * (height / math.cos(t))
    back = -fwd
    yaw = math.radians(c["yaw"])
    up_ref = Vector((-math.sin(yaw), math.cos(yaw), 0.0))          # the sheet's +Y in world
    up = up_ref - up_ref.dot(back) * back
    up.normalize()
    right = up.cross(back)
    r = math.radians(c["roll"])
    right, up = right * math.cos(r) + up * math.sin(r), -right * math.sin(r) + up * math.cos(r)
    return Matrix(((right.x, up.x, back.x, pos.x),
                   (right.y, up.y, back.y, pos.y),
                   (right.z, up.z, back.z, pos.z),
                   (0.0, 0.0, 0.0, 1.0)))


def sheet_corners_world(c):
    """Sheet corners in the sheet frame, TL, TR, BR, BL (TL = top-left with +Y up), then yawed into the world."""
    hw, hh = SHEET_W / 2, SHEET_H / 2
    rot = Matrix.Rotation(math.radians(c["yaw"]), 4, "Z")
    local = [(-hw, hh, 0.0), (hw, hh, 0.0), (hw, -hh, 0.0), (-hw, -hh, 0.0)]
    return [(rot @ Vector(p)) for p in local]


def corners_visible(sc, cam, c):
    for p in sheet_corners_world(c):
        v = world_to_camera_view(sc, cam, p)
        if v.z <= 0.0:
            return False
        px, py = v.x * RES_X, (1.0 - v.y) * RES_Y
        if not (MARGIN_PX <= px <= RES_X - MARGIN_PX and MARGIN_PX <= py <= RES_Y - MARGIN_PX):
            return False
    return True


def place_camera(sc, c):
    """Camera at the sampled height; if a corner is cut, raise it 20 mm and retry (up to 20 times)."""
    cam = make_camera(sc, c)
    h = c["height"]
    for _ in range(21):
        cam.matrix_world = camera_pose(c, h)
        if corners_visible(sc, cam, c):
            return cam, h
        h += 20.0
    return None, None


def smooth(ob):
    for poly in ob.data.polygons:
        poly.use_smooth = True


def cylinder_part(name, x, y0, y1, w, d, mat, rounded):
    """An elliptical cylinder along +Y from y0 to y1 (hand frame), cross-section w across and d tall, its bottom on
    z = 0. If rounded, the far end y1 is closed by an ellipsoid of the same cross-section."""
    cap = w / 2 if rounded else 0.0
    ya, yb = y0, y1 - cap
    bpy.ops.mesh.primitive_cylinder_add(vertices=48, radius=1.0, depth=2.0, location=(x, (ya + yb) / 2, d / 2))
    body = bpy.context.active_object
    body.name = name
    body.scale = (w / 2, d / 2, (yb - ya) / 2)
    body.rotation_euler = (math.pi / 2, 0.0, 0.0)
    body.data.materials.append(mat)
    smooth(body)
    parts = [body]
    if rounded:
        bpy.ops.mesh.primitive_uv_sphere_add(radius=1.0, segments=32, ring_count=16, location=(x, yb, d / 2))
        tip = bpy.context.active_object
        tip.name = name + "_tip"
        tip.scale = (w / 2, w / 2, d / 2)
        tip.data.materials.append(mat)
        smooth(tip)
        parts.append(tip)
    return parts


def make_palm(width, mat, y_centre, z_top):
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=(0.0, y_centre, z_top / 2))
    palm = bpy.context.active_object
    palm.name = "palm"
    palm.scale = (width, PALM_LEN, z_top)
    bpy.ops.object.select_all(action="DESELECT")
    palm.select_set(True)
    bpy.context.view_layer.objects.active = palm
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    bev = palm.modifiers.new("bevel", "BEVEL")
    bev.width = 4.0
    bev.segments = 3
    bev.limit_method = "ANGLE"
    palm.data.materials.append(mat)
    return palm


def skin_material(base):
    m = bpy.data.materials.new("skin")
    m.use_nodes = True
    p = m.node_tree.nodes["Principled BSDF"]
    p.inputs["Base Color"].default_value = (*base, 1.0)
    p.inputs["Roughness"].default_value = 0.5
    p.inputs["Subsurface Weight"].default_value = 0.1
    return m


def paper_material(v):
    m = bpy.data.materials.new("paper")
    m.use_nodes = True
    p = m.node_tree.nodes["Principled BSDF"]
    p.inputs["Base Color"].default_value = (v, v, v, 1.0)
    p.inputs["Roughness"].default_value = 0.9
    return m


def table_material(kind):
    base = TABLES[kind]
    m = bpy.data.materials.new("table")
    m.use_nodes = True
    nt = m.node_tree
    p = nt.nodes["Principled BSDF"]
    coord = nt.nodes.new("ShaderNodeTexCoord")
    wave = nt.nodes.new("ShaderNodeTexWave")
    wave.wave_type = "BANDS"
    wave.bands_direction = "X"
    wave.inputs["Scale"].default_value = 0.03
    wave.inputs["Distortion"].default_value = 14.0
    wave.inputs["Detail"].default_value = 3.0
    nt.links.new(coord.outputs["Object"], wave.inputs["Vector"])
    mix = nt.nodes.new("ShaderNodeMixRGB")
    mix.inputs["Color1"].default_value = (*[0.72 * x for x in base], 1.0)
    mix.inputs["Color2"].default_value = (*[min(1.0, 1.08 * x) for x in base], 1.0)
    nt.links.new(wave.outputs["Fac"], mix.inputs["Fac"])
    nt.links.new(mix.outputs["Color"], p.inputs["Base Color"])
    bump = nt.nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.08
    nt.links.new(wave.outputs["Fac"], bump.inputs["Height"])
    nt.links.new(bump.outputs["Normal"], p.inputs["Normal"])
    p.inputs["Roughness"].default_value = 0.45
    return m


def empty(name, parent=None, location=(0.0, 0.0, 0.0), rot_z=0.0):
    ob = bpy.data.objects.new(name, None)
    ob.empty_display_size = 10.0
    bpy.context.scene.collection.objects.link(ob)
    ob.location = location
    ob.rotation_euler = (0.0, 0.0, rot_z)
    if parent is not None:
        ob.parent = parent
    return ob


def build_scene(sc, c, cam):
    """Table, sheet, hand and light. Returns the projected landmark and corner data."""
    skin = skin_material(SKINS[c["skin"]])
    dr, wr, wk = c["depth_ratio"], c["w_ring"], c["w_knuckle"]
    lay = hand_layout(c)
    xs, ys = lay["xs"], lay["ys"]

    bpy.ops.mesh.primitive_plane_add(size=TABLE_SIZE, location=(0.0, 0.0, -0.1))
    table = bpy.context.active_object
    table.name = "table"
    table.data.materials.append(table_material(c["table"]))

    sheet_frame = empty("sheet_frame", rot_z=math.radians(c["yaw"]))
    bpy.ops.mesh.primitive_plane_add(size=2.0, location=(0.0, 0.0, 0.0))
    sheet = bpy.context.active_object
    sheet.name = "sheet"
    sheet.scale = (SHEET_W / 2, SHEET_H / 2, 1.0)
    sheet.data.materials.append(paper_material(c["paper"]))
    sheet.parent = sheet_frame

    hand = empty("hand", parent=sheet_frame, location=(c["hand_off"][0], c["hand_off"][1], 0.0),
                 rot_z=math.radians(c["hand_rot"]))
    for name, (x, w, length) in lay["fingers"].items():
        d = dr * w
        for part in cylinder_part(name, x + xs, -8.0 + ys, length + ys, w, d, skin, rounded=True):
            part.parent = hand
    dk = dr * wk
    for part in cylinder_part("knuckle", xs, KNUCKLE_FROM + ys, KNUCKLE_TO + ys, wk, dk, skin, rounded=False):
        part.parent = hand
    palm = make_palm(lay["palm_w"], skin, -PALM_LEN / 2 + ys, PALM_T)
    palm.parent = hand

    light = bpy.data.lights.new("key", "AREA")
    light.shape = "SQUARE"
    light.size = LIGHT_SIZE
    light.energy = c["light_energy"]
    lob = bpy.data.objects.new("key", light)
    sc.collection.objects.link(lob)
    lp = Vector(c["light_pos"])
    lob.location = lp
    lob.rotation_mode = "QUATERNION"
    lob.rotation_quaternion = (-lp).to_track_quat("-Z", "Y")

    bpy.context.view_layer.update()
    mcp_local = Vector((xs, -MCP_BEFORE_BASE + ys, dr * wr / 2))
    pip_local = Vector((xs, PIP_ALONG + ys, dk / 2))
    mcp_w = hand.matrix_world @ mcp_local
    pip_w = hand.matrix_world @ pip_local
    return {"mcp": mcp_w, "pip": pip_w}


def project(sc, cam, p):
    v = world_to_camera_view(sc, cam, p)
    return [round(v.x * RES_X, 2), round((1.0 - v.y) * RES_Y, 2)]


# ----------------------------------------------------------------------------------------------- per case
def render_case(i, seed, out_dir, hdri, samples):
    rng = random.Random(seed * 1000 + i)
    for _ in range(200):
        c = sample_case(rng)
        sc = reset_scene(hdri, samples)
        cam, h = place_camera(sc, c)
        if cam is not None:
            break
    else:
        raise RuntimeError(f"case {i}: no camera placement found")
    c["height"] = h

    lm = build_scene(sc, c, cam)
    corners = [project(sc, cam, p) for p in sheet_corners_world(c)]
    landmarks = {"13": project(sc, cam, lm["mcp"]), "14": project(sc, cam, lm["pip"])}

    name = f"bench_{i:03d}"
    png = os.path.join(out_dir, name + ".png")
    sc.render.filepath = png
    bpy.ops.render.render(write_still=True)

    meta = {
        "case": i, "seed": seed,
        "ring_width_mm": round(c["w_ring"], 4), "knuckle_width_mm": round(c["w_knuckle"], 4),
        "depth_ratio": round(c["depth_ratio"], 5), "focal_35mm": round(c["focal"], 4),
        "camera_height_mm": round(h, 3), "tilt_deg": round(c["tilt"], 3), "yaw_deg": round(c["yaw"], 3),
        "skin": c["skin"], "table": c["table"], "image_size": [RES_X, RES_Y],
        "sheet_corners_px": corners,
        "landmarks_px": landmarks,
        "ring_axis_mm": {"mcp": [round(v, 3) for v in lm["mcp"]], "pip": [round(v, 3) for v in lm["pip"]]},
    }
    with open(os.path.join(out_dir, name + ".json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=1)
    return meta


def main():
    global LIGHT_ENERGY
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--n", type=int, default=40)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--samples", type=int, default=48)
    ap.add_argument("--hdri", required=True, help="studio HDRI, e.g. Poly Haven studio_small_09 (CC0)")
    ap.add_argument("--energy", type=float, default=LIGHT_ENERGY, help="area light power, W (exposure tuning)")
    args = ap.parse_args(argv)
    LIGHT_ENERGY = args.energy
    out_dir, hdri = os.path.abspath(args.out), os.path.abspath(args.hdri)
    os.makedirs(out_dir, exist_ok=True)
    for i in range(args.n):
        name = f"bench_{i:03d}"
        if os.path.exists(os.path.join(out_dir, name + ".png")) and os.path.exists(os.path.join(out_dir, name + ".json")):
            print("skip", name, flush=True)
            continue
        t0 = time.time()
        meta = render_case(i, args.seed, out_dir, hdri, args.samples)
        print(f"rendered {name} table={meta['table']} skin={meta['skin']} W={meta['ring_width_mm']} "
              f"H={meta['camera_height_mm']} in {time.time() - t0:.1f}s", flush=True)


if __name__ == "__main__":
    main()
