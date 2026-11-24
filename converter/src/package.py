"""Build the Creality Print project package (.3mf) from meshes and settings."""
import datetime
import json
import math
import os
import sys
import zipfile
from xml.sax.saxutils import quoteattr

import numpy as np

from .config import MATERIALS, MAX_PLATES, PLATE_GAP
from .mesh import mesh_report, read_stl, weld
from .settings import (build_settings, load_profile, process_overrides, profile_deltas, stock_path,
                       temperature_overrides)
from .thumbnail import thumbnails

NS = ('xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02" '
      'xmlns:BambuStudio="http://schemas.bambulab.com/package/2021" '
      'xmlns:p="http://schemas.microsoft.com/3dmanufacturing/production/2015/06" requiredextensions="p"')
CONTENT_TYPES = '''<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
 <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
 <Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>
 <Default Extension="png" ContentType="image/png"/>
 <Default Extension="gcode" ContentType="text/x.gcode"/>
</Types>'''
ROOT_RELS = '''<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
 <Relationship Target="/3D/3dmodel.model" Id="rel-1" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>
 <Relationship Target="/Metadata/plate_1.png" Id="rel-2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/thumbnail"/>
 <Relationship Target="/Metadata/plate_1.png" Id="rel-4" Type="http://schemas.bambulab.com/package/2021/cover-thumbnail-middle"/>
<Relationship Target="/Metadata/plate_1_small.png" Id="rel-5" Type="http://schemas.bambulab.com/package/2021/cover-thumbnail-small"/>
</Relationships>'''
CUSTOM_GCODE = '''<?xml version="1.0" encoding="utf-8"?>
<custom_gcodes_per_layer>
<plate>
<plate_info id="1"/>
<mode value="MultiExtruder"/>
</plate>
</custom_gcodes_per_layer>'''


def fmt(x):
    return np.format_float_positional(np.float32(x), unique=True, trim="-")


def object_model(local_verts, faces, mesh_id=1):
    lines = ['<?xml version="1.0" encoding="UTF-8"?>', f'<model unit="millimeter" xml:lang="en-US" {NS}>',
             ' <metadata name="BambuStudio:3mfVersion">1</metadata>', ' <resources>',
             f'  <object id="{mesh_id}" p:UUID="{mesh_id:04x}0000-81cb-4c03-9d28-80fed5dfa1dc" type="model">', '   <mesh>',
             '    <vertices>']
    lines += [f'     <vertex x="{fmt(x)}" y="{fmt(y)}" z="{fmt(z)}"/>' for x, y, z in local_verts]
    lines += ['    </vertices>', '    <triangles>']
    lines += [f'     <triangle v1="{i}" v2="{j}" v3="{k}"/>' for i, j, k in faces.tolist()]
    lines += ['    </triangles>', '   </mesh>', '  </object>', ' </resources>', ' <build/>', '</model>', '']
    return "\n".join(lines)


def plate_origin(index, count, bed_x, bed_y):
    """World offset of plate `index` (0-based), laid out the way the slicer does it:
    ceil(sqrt(count)) columns, a 20 % gap between plates, rows going towards -Y."""
    cols = math.ceil(math.sqrt(count))
    return (index % cols) * bed_x * (1 + PLATE_GAP), -(index // cols) * bed_y * (1 + PLATE_GAP)


def convert(stl_paths, out_path, profile_name, material="pla", nozzle_first=None, nozzle_other=None, bed=None,
            layer_height=None, support=False, extra=None, verbose=True):
    """Write one project. Several STL files give one plate per file.

    Returns {"output", "plates": [...], "warnings": [...], "settings": {...}}.
    verbose=False skips the printed report (used by the web UI).
    """
    say = print if verbose else (lambda *a, **k: None)
    if isinstance(stl_paths, str):
        stl_paths = [stl_paths]
    count = len(stl_paths)
    if count > MAX_PLATES:
        raise SystemExit(f"{count} STL files, but Creality Print allows at most {MAX_PLATES} plates per "
                         f"project; split them over several files")
    stock = json.load(open(stock_path(material)))
    profile = load_profile(profile_name)
    deltas = profile_deltas(profile, material)
    custom, warnings = temperature_overrides(stock, nozzle_first, nozzle_other, bed)
    deltas["filament"].update(custom)
    custom_process, more = process_overrides(stock, layer_height, support)
    deltas["process"] = {**deltas["process"], **custom_process}
    warnings += more
    custom_machine = {}
    for key, value in (extra or {}).items():   # --set KEY=VALUE, applied last
        group = next((g for g in ("process", "filament", "machine") if key in stock["groups"][g]), None)
        if group is None:
            raise SystemExit(f"--set {key}: not a setting of the stock presets")
        deltas[group] = {**deltas[group], key: value}
        {"process": custom_process, "filament": custom, "machine": custom_machine}[group][key] = value
    colour = MATERIALS[material]
    cfg = build_settings(stock, deltas, colour)
    version = stock["creality_print_version"]
    bed = [float(p.split("x")[i]) for i in (0, 1) for p in [cfg["printable_area"][2]]]
    bed_x, bed_y, bed_z = bed[0], bed[1], float(cfg["printable_height"])
    today = datetime.date.today().isoformat()
    samples = 1_500_000 if count == 1 else 300_000

    files = [("[Content_Types].xml", CONTENT_TYPES)]
    object_files, resources, items, objects, plates, assemble, plate_files, rels = [], [], [], [], [], [], [], []
    plate_info = []
    for i, stl_path in enumerate(stl_paths):
        n, mesh_id, obj_id = i + 1, 2 * i + 1, 2 * i + 2
        tag = f"{name_of(stl_path)}: " if count > 1 else ""
        verts, faces = weld(read_stl(stl_path))
        report = mesh_report(verts, faces)
        lo, hi = verts.min(0).astype(np.float64), verts.max(0).astype(np.float64)
        size, centre = hi - lo, (lo + hi) / 2
        ox, oy = plate_origin(i, count, bed_x, bed_y)
        lx, ly, pz = bed_x / 2, bed_y / 2, float(size[2] / 2)   # position on its own plate
        px, py = ox + lx, oy + ly                               # position in the project
        local = verts.astype(np.float64) - centre
        name = name_of(stl_path)

        object_files.append((f"3D/Objects/object_{n}.model", object_model(local, faces, mesh_id)))
        rels.append(f' <Relationship Target="/3D/Objects/object_{n}.model" Id="rel-{n}" '
                    f'Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>')
        resources.append(f'''  <object id="{obj_id}" p:UUID="{n:08x}-61cb-4c03-9d28-80fed5dfa1dc" type="model">
   <components>
    <component p:path="/3D/Objects/object_{n}.model" objectid="{mesh_id}" p:UUID="{n:04x}0000-b206-40ff-9872-83e8017abed1" transform="1 0 0 0 1 0 0 0 1 0 0 0"/>
   </components>
  </object>''')
        items.append(f'  <item objectid="{obj_id}" p:UUID="{obj_id:08x}-b1ec-4553-aec9-835e5b724bb4" '
                     f'transform="1 0 0 0 1 0 0 0 1 {px:g} {py:g} {pz:.9g}" printable="1"/>')
        objects.append(f'''  <object id="{obj_id}">
    <metadata key="name" value={quoteattr(name)}/>
    <metadata key="extruder" value="1"/>
    <part id="{mesh_id}" subtype="normal_part">
      <metadata key="name" value={quoteattr(name)}/>
      <metadata key="matrix" value="1 0 0 0 0 1 0 0 0 0 1 0 0 0 0 1"/>
      <metadata key="source_file" value={quoteattr(name)}/>
      <metadata key="source_object_id" value="0"/>
      <metadata key="source_volume_id" value="0"/>
      <metadata key="source_offset_x" value="{float(centre[0])!r}"/>
      <metadata key="source_offset_y" value="{float(centre[1])!r}"/>
      <metadata key="source_offset_z" value="{float(centre[2])!r}"/>
      <mesh_stat edges_fixed="0" degenerate_facets="0" facets_removed="0" facets_reversed="0" backwards_edges="0"/>
    </part>
  </object>''')
        plate_name = "" if count == 1 else os.path.splitext(name)[0]
        plates.append(f'''  <plate>
    <metadata key="plater_id" value="{n}"/>
    <metadata key="plater_name" value={quoteattr(plate_name)}/>
    <metadata key="locked" value="false"/>
    <metadata key="thumbnail_file" value="Metadata/plate_{n}.png"/>
    <metadata key="thumbnail_no_light_file" value="Metadata/plate_no_light_{n}.png"/>
    <metadata key="top_file" value="Metadata/top_{n}.png"/>
    <metadata key="pick_file" value="Metadata/pick_{n}.png"/>
    <model_instance>
      <metadata key="object_id" value="{obj_id}"/>
      <metadata key="instance_id" value="0"/>
      <metadata key="identify_id" value="{77 + 20 * i}"/>
    </model_instance>
  </plate>''')
        assemble.append(f'   <assemble_item object_id="{obj_id}" instance_id="0" '
                        f'transform="1 0 0 0 1 0 0 0 1 {i * bed_x:g} 0 {pz:.9g}" offset="0 0 0" />')
        bbox = [lx - size[0] / 2, ly - size[1] / 2, lx + size[0] / 2, ly + size[1] / 2]
        plate_files.append((f"Metadata/plate_{n}.json", json.dumps({
            "bbox_all": bbox,
            "bbox_objects": [{"area": size[0] * size[1], "bbox": bbox, "id": 91 + 20 * i,
                              "layer_height": float(cfg["layer_height"]), "name": name}],
            "bed_type": "hot_plate", "filament_colors": [], "filament_ids": [], "first_extruder": 0,
            "is_seq_print": False, "nozzle_diameter": float(cfg["nozzle_diameter"][0]), "version": 2,
        }, separators=(",", ":"))))
        thumbs = thumbnails(verts, faces, colour, n, samples)
        files += [(k, thumbs[k]) for k in (f"Metadata/plate_{n}.png", f"Metadata/plate_{n}_small.png",
                                           f"Metadata/plate_no_light_{n}.png", f"Metadata/top_{n}.png",
                                           f"Metadata/pick_{n}.png")]

        plate_info.append({"plate": n, "name": name, "triangles": int(len(faces)),
                           "size_mm": [round(float(v), 2) for v in size],
                           "volume_cm3": round(report["volume_mm3"] / 1000, 2),
                           "watertight": not (report["open_edges"] or report["flipped_edges"])})
        say(f"model    : {name}  {len(faces)} triangles, {len(verts)} vertices"
            + (f"  -> plate {n}" if count > 1 else ""))
        say(f"size     : {size[0]:.2f} x {size[1]:.2f} x {size[2]:.2f} mm, "
            f"volume {report['volume_mm3'] / 1000:.2f} cm3")
        if report["open_edges"] or report["flipped_edges"]:
            warnings.append(f"{tag}mesh is not watertight ({report['open_edges']} open edges, "
                            f"{report['flipped_edges']} inconsistent edges); repair it in the slicer")
        if size[0] > bed_x or size[1] > bed_y or size[2] > bed_z:
            warnings.append(f"{tag}model exceeds the {bed_x:g} x {bed_y:g} x {bed_z:g} mm build volume")

    main_model = f'''<?xml version="1.0" encoding="UTF-8"?>
<model unit="millimeter" xml:lang="en-US" {NS}>
 <metadata name="Application">Creality_Print V{version} Release</metadata>
 <metadata name="BambuStudio:3mfVersion">1</metadata>
 <metadata name="Copyright"></metadata>
 <metadata name="CreationDate">{today}</metadata>
 <metadata name="Description"></metadata>
 <metadata name="Designer"></metadata>
 <metadata name="DesignerCover"></metadata>
 <metadata name="DesignerUserId"></metadata>
 <metadata name="License"></metadata>
 <metadata name="ModificationDate">{today}</metadata>
 <metadata name="Origin"></metadata>
 <metadata name="Thumbnail_Middle">/Metadata/plate_1.png</metadata>
 <metadata name="Thumbnail_Small">/Metadata/plate_1_small.png</metadata>
 <metadata name="Title"></metadata>
 <resources>
{chr(10).join(resources)}
 </resources>
 <build p:UUID="2c7c17d8-22b5-4d84-8835-1976022ea369">
{chr(10).join(items)}
 </build>
</model>
'''
    model_settings = f'''<?xml version="1.0" encoding="UTF-8"?>
<config>
{chr(10).join(objects)}
{chr(10).join(plates)}
  <assemble>
{chr(10).join(assemble)}
  </assemble>
</config>
'''
    model_rels = ('<?xml version="1.0" encoding="UTF-8"?>\n'
                  '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">\n'
                  + "\n".join(rels) + "\n</Relationships>")
    padded = ".".join(f"{int(p):02d}" if i < 3 else p for i, p in enumerate(version.split(".")))
    slice_info = f'''<?xml version="1.0" encoding="UTF-8"?>
<config>
  <header>
    <header_item key="X-CX-Client-Type" value="creality_print"/>
    <header_item key="X-CX-Client-Version" value="{padded}"/>
  </header>
</config>
'''
    creality = f'''<?xml version="1.0" encoding="UTF-8"?>
<config>
    <metadata key="Company" value="Creality"/>
    <metadata key="Application" value="Creality_Print"/>
    <metadata key="AppVersion" value="{version}"/>
    <metadata key="AppStage" value="Release"/>
    <metadata key="FileVersion" value="1.0"/>
    <metadata key="FileType" value="Undefined"/>
    <metadata key="ProfileVersion" value=""/>
    <metadata key="CreationDate" value="{today}"/>
</config>
'''
    files += plate_files
    files += [("3D/3dmodel.model", main_model), ("3D/_rels/3dmodel.model.rels", model_rels)]
    files += object_files
    files += [
        ("Metadata/project_settings.config", json.dumps(cfg, indent=4, sort_keys=True)),
        ("Metadata/model_settings.config", model_settings),
        ("Metadata/creality.config", creality),
        ("Metadata/custom_gcode_per_layer.xml", CUSTOM_GCODE),
        ("Metadata/slice_info.config", slice_info),
        ("_rels/.rels", ROOT_RELS),
    ]
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as z:
        for arcname, data in files:
            z.writestr(arcname, data)

    if count > 1:
        say(f"plates   : {count}, one STL per plate")
    say(f"printer  : {stock['presets']['machine']}")
    say(f"process  : {stock['presets']['process']}  + profile '{profile_name}'")
    say(f"filament : {stock['presets']['filament']}")
    marked = {"process": custom_process, "filament": custom, "machine": custom_machine}
    for group in ("process", "filament", "machine"):
        for key, value in deltas[group].items():
            say(f"    {key} = {value}" + ("   (custom)" if key in marked[group] else ""))
    say(f"temps    : nozzle {cfg['nozzle_temperature_initial_layer'][0]} C first layer / "
          f"{cfg['nozzle_temperature'][0]} C other layers, bed {cfg['hot_plate_temp_initial_layer'][0]} C / "
          f"{cfg['hot_plate_temp'][0]} C")
    for w in warnings:
        if verbose:
            print(f"WARNING  : {w}", file=sys.stderr)
    say(f"wrote    : {out_path}  ({os.path.getsize(out_path) / 1e6:.1f} MB)")
    first = lambda key: float(cfg[key][0] if isinstance(cfg[key], list) else cfg[key])
    return {
        "output": out_path,
        "plates": plate_info,
        "warnings": warnings,
        "settings": {
            "printer": stock["presets"]["machine"], "process": stock["presets"]["process"],
            "filament": stock["presets"]["filament"], "profile": profile_name, "material": material,
            "layer_height": first("layer_height"), "first_layer_height": first("initial_layer_print_height"),
            "nozzle_first_c": first("nozzle_temperature_initial_layer"), "nozzle_other_c": first("nozzle_temperature"),
            "bed_c": first("hot_plate_temp"), "bed_first_c": first("hot_plate_temp_initial_layer"),
            "support": cfg["enable_support"] in ("1", ["1"]),
            "changed": {g: dict(marked[g]) for g in marked},
        },
    }


def name_of(path):
    return os.path.basename(path)
