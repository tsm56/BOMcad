import os
import math
import trimesh
import numpy as np
import cadquery as cq
from cadquery import Shape
from OCP.IGESControl import IGESControl_Reader
from OCP.IFSelect import IFSelect_RetDone
from OCP.TopAbs import TopAbs_FACE, TopAbs_EDGE, TopAbs_WIRE, TopAbs_SHELL
from OCP.TopoDS import TopoDS
from OCP.BRep import BRep_Tool
from OCP.TopExp import TopExp_Explorer
import collections

# Premium distinct colors for visual assembly styling
COLORS = [
    "#6366f1",  # Indigo
    "#10b981",  # Emerald
    "#a855f7",  # Purple
    "#f59e0b",  # Amber
    "#ef4444",  # Red
    "#06b6d4",  # Cyan
    "#ec4899",  # Pink
    "#14b8a6",  # Teal
    "#84cc16",  # Lime
    "#f43f5e"   # Rose
]

SURFACE_CLASS_MAP = {
    "Geom_Plane": "planar",
    "Geom_CylindricalSurface": "cylindrical",
    "Geom_ConicalSurface": "conical",
    "Geom_SphericalSurface": "spherical",
    "Geom_ToroidalSurface": "toroidal",
    "Geom_BezierSurface": "freeform",
    "Geom_BSplineSurface": "freeform",
    "Geom_SurfaceOfRevolution": "revolution",
    "Geom_SurfaceOfExtrusion": "extrusion",
    "Geom_OffsetSurface": "offset",
}

EDGE_CLASS_MAP = {
    "Geom_Line": "straight",
    "Geom_Circle": "circular",
    "Geom_Ellipse": "elliptical",
    "Geom_Hyperbola": "curved",
    "Geom_Parabola": "curved",
    "Geom_BezierCurve": "freeform",
    "Geom_BSplineCurve": "freeform",
    "Geom_OffsetCurve": "offset",
}

def _classify_surface(surface):
    """Classify an OCP surface by its concrete Python class name."""
    return SURFACE_CLASS_MAP.get(type(surface).__name__, "other")

def _classify_curve(curve):
    """Classify an OCP curve by its concrete Python class name."""
    return EDGE_CLASS_MAP.get(type(curve).__name__, "other")

def hex_to_cq_color(hex_color):
    """Converts hex color string to cadquery Color object"""
    hex_color = hex_color.lstrip('#')
    r = int(hex_color[0:2], 16) / 255.0
    g = int(hex_color[2:4], 16) / 255.0
    b = int(hex_color[4:6], 16) / 255.0
    return cq.Color(r, g, b)

def read_iges(file_path):
    """Reads IGES file using OCP and returns a cadquery Shape"""
    reader = IGESControl_Reader()
    status = reader.ReadFile(file_path)
    if status == IFSelect_RetDone:
        reader.TransferRoots()
        if reader.NbShapes() > 0:
            topods_shape = reader.OneShape()
            return Shape.cast(topods_shape)
        else:
            raise ValueError("No shapes found in the IGES file.")
    else:
        raise ValueError(f"Could not read IGES file: status code {status}")

def analyze_brep_topology(shape):
    """
    Deep topology analysis of a B-Rep solid.
    Returns a dict with face types, edge types, holes, bends, shells, wires, genus.
    """
    result = {
        "face_types": collections.Counter(),
        "edge_types": collections.Counter(),
        "holes": 0,
        "bends": 0,
        "shells": 0,
        "wires": 0,
        "genus": 0,
        "through_holes": [],
        "bend_details": [],
        "circular_edge_count": 0,
        "straight_edge_count": 0,
        "min_edge_radius": None,
        "max_edge_radius": None,
    }

    # --- Face type analysis ---
    face_explorer = TopExp_Explorer(shape.wrapped, TopAbs_FACE)
    face_count = 0
    cylinder_radii = []

    while face_explorer.More():
        topods_face = TopoDS.Face_s(face_explorer.Current())
        surface = BRep_Tool.Surface_s(topods_face)
        type_name = _classify_surface(surface)
        result["face_types"][type_name] += 1
        face_count += 1

        # Check cylindrical faces for hole/bend detection
        if type_name == "cylindrical":
            try:
                radius = surface.Radius()
                cylinder_radii.append(radius)
            except Exception:
                pass

        face_explorer.Next()

    # --- Edge type analysis ---
    edge_explorer = TopExp_Explorer(shape.wrapped, TopAbs_EDGE)
    edge_count = 0
    circular_radii = []

    while edge_explorer.More():
        topods_edge = TopoDS.Edge_s(edge_explorer.Current())
        try:
            f, l = 0.0, 0.0
            curve_geom = BRep_Tool.Curve_s(topods_edge, f, l)
        except Exception:
            edge_explorer.Next()
            continue

        type_name = _classify_curve(curve_geom)
        result["edge_types"][type_name] += 1
        edge_count += 1

        if type_name == "circular":
            result["circular_edge_count"] += 1
            try:
                r = curve_geom.Radius()
                circular_radii.append(r)
            except Exception:
                pass
        elif type_name == "straight":
            result["straight_edge_count"] += 1

        edge_explorer.Next()

    if circular_radii:
        result["min_edge_radius"] = round(min(circular_radii), 4)
        result["max_edge_radius"] = round(max(circular_radii), 4)

    # --- Shell and wire counting ---
    shell_explorer = TopExp_Explorer(shape.wrapped, TopAbs_SHELL)
    while shell_explorer.More():
        result["shells"] += 1
        shell_explorer.Next()

    wire_explorer = TopExp_Explorer(shape.wrapped, TopAbs_WIRE)
    while wire_explorer.More():
        result["wires"] += 1
        wire_explorer.Next()

    # --- Hole detection ---
    # Heuristic: count unique cylindrical radii. Each distinct radius
    # typically represents one through-hole or bore.
    if cylinder_radii:
        radius_groups = collections.defaultdict(list)
        for r in cylinder_radii:
            # Group radii within 0.01mm tolerance
            placed = False
            for existing_r in radius_groups:
                if abs(r - existing_r) < 0.01:
                    radius_groups[existing_r].append(r)
                    placed = True
                    break
            if not placed:
                radius_groups[r].append(r)

        for radius, instances in radius_groups.items():
            if len(instances) >= 2:
                # 2+ cylindrical faces with same radius = likely a through-hole
                result["holes"] += 1
                result["through_holes"].append({
                    "radius_mm": round(radius, 4),
                    "diameter_mm": round(radius * 2, 4),
                    "face_count": len(instances)
                })
            elif len(instances) == 1:
                # Single cylindrical face with no matching pair could be a counterbore
                # or external cylinder - check if it's small relative to the part
                bbox = shape.BoundingBox()
                max_dim = max(bbox.xlen, bbox.ylen, bbox.zlen)
                if radius * 2 < max_dim * 0.5:
                    # Small single bore - likely a blind hole
                    result["holes"] += 1
                    result["through_holes"].append({
                        "radius_mm": round(radius, 4),
                        "diameter_mm": round(radius * 2, 4),
                        "face_count": len(instances),
                        "type": "blind_or_counterbore"
                    })

    # --- Bend detection ---
    # Bends are cylindrical faces where the axis is parallel to a primary direction
    # and the radius is in a typical sheet-metal/forming range
    if cylinder_radii:
        bbox = shape.BoundingBox()
        max_dim = max(bbox.xlen, bbox.ylen, bbox.zlen)

        for radius in cylinder_radii:
            # Bends typically have radii between 0.5mm and 50mm
            # and the cylindrical surface radius is much smaller than the part
            if 0.1 <= radius <= 100 and radius * 2 < max_dim:
                # Check if this radius already counted as a hole
                is_hole = False
                for hole in result["through_holes"]:
                    if abs(hole["radius_mm"] - radius) < 0.01:
                        is_hole = True
                        break
                if not is_hole:
                    result["bends"] += 1
                    result["bend_details"].append({
                        "radius_mm": round(radius, 4)
                    })

    # --- Genus calculation (Euler-Poincaré) ---
    # For a solid: V - E + F = 2 - 2g  =>  g = (2 - (V - E + F)) / 2
    try:
        verts = len(shape.Vertices())
        edges_n = len(shape.Edges())
        faces_n = len(shape.Faces())
        euler_char = verts - edges_n + faces_n
        genus = max(0, (2 - euler_char) // 2)
        result["genus"] = int(genus)
    except Exception:
        result["genus"] = 0

    # Convert Counter to dict for JSON serialization
    result["face_types"] = dict(result["face_types"])
    result["edge_types"] = dict(result["edge_types"])

    return result

def analyze_mesh_topology(mesh):
    """
    Analyze topology of a trimesh geometry.
    Returns face type breakdown, genus, holes, and edge stats.
    """
    result = {
        "face_types": {},
        "edge_types": {},
        "holes": 0,
        "bends": 0,
        "shells": 1,
        "wires": 0,
        "genus": 0,
        "through_holes": [],
        "bend_details": [],
        "circular_edge_count": 0,
        "straight_edge_count": 0,
        "min_edge_radius": None,
        "max_edge_radius": None,
        "watertight": bool(mesh.is_watertight),
    }

    faces = mesh.faces
    vertices = mesh.vertices

    if len(faces) == 0 or len(vertices) == 0:
        return result

    # --- Face type analysis by dihedral angles ---
    # Classify triangles as flat (part of a planar region) vs curved
    try:
        face_normals = mesh.face_normals
        # Find unique faces by checking normal variation
        flat_count = 0
        curved_count = 0

        # Use face adjacency to find connected planar regions
        if hasattr(mesh, 'face_adjacency') and len(mesh.face_adjacency) > 0:
            adj = mesh.face_adjacency
            # For each pair of adjacent faces, check angle
            visited = set()
            planar_groups = 0

            for pair in adj:
                f0, f1 = pair
                if f0 in visited and f1 in visited:
                    continue
                n0 = face_normals[f0]
                n1 = face_normals[f1]
                cos_angle = np.clip(np.dot(n0, n1), -1, 1)
                angle = math.degrees(math.acos(cos_angle))
                if angle < 5.0:  # Nearly coplanar
                    flat_count += 1
                    visited.add(f0)
                    visited.add(f1)
                else:
                    curved_count += 1
                    visited.add(f0)
                    visited.add(f1)
        else:
            # Fallback: classify by normal consistency with neighbors
            flat_count = len(faces)
            curved_count = 0

        total_classified = flat_count + curved_count
        if total_classified > 0:
            result["face_types"]["planar"] = flat_count
            result["face_types"]["curved"] = curved_count
        else:
            result["face_types"]["triangular"] = len(faces)
    except Exception:
        result["face_types"]["triangular"] = len(faces)

    # --- Edge analysis ---
    try:
        edges = mesh.edges_unique
        edges_set = set(map(tuple, edges.tolist()))

        # Boundary edges (edges shared by only 1 face) = mesh holes
        edge_face_count = collections.Counter()
        for face in faces:
            for i in range(3):
                e = tuple(sorted([face[i], face[(i + 1) % 3]]))
                edge_face_count[e] += 1

        boundary_edges = [e for e, c in edge_face_count.items() if c == 1]
        result["holes"] = len(boundary_edges) // 2  # Rough: each hole needs ~2 boundary edges
        if len(boundary_edges) > 0 and len(boundary_edges) % 2 != 0:
            result["holes"] = max(1, len(boundary_edges) // 2)

        result["straight_edge_count"] = len(boundary_edges)
        result["circular_edge_count"] = len(edges) - len(boundary_edges)
        result["wires"] = len(boundary_edges)
    except Exception:
        pass

    # --- Genus via Euler characteristic ---
    try:
        V = len(mesh.vertices)
        E = len(mesh.edges_unique)
        F = len(mesh.faces)
        euler = V - E + F
        # For watertight: V - E + F = 2 - 2g
        # For non-watertight (open surface): genus calculation differs
        if mesh.is_watertight:
            result["genus"] = max(0, (2 - euler) // 2)
        else:
            # For open surfaces, genus relates to handles
            result["genus"] = max(0, (1 - euler) // 2)
    except Exception:
        pass

    # --- Shell counting via connected components ---
    try:
        if hasattr(mesh, 'body_count'):
            result["shells"] = mesh.body_count
        elif hasattr(mesh, 'faces_batch'):
            result["shells"] = len(set(mesh.faces_batch))
    except Exception:
        pass

    return result

def parse_cad_file(file_path, glb_path, density_g_cm3=7.85):
    """
    Main parser entrypoint. Automatically detects extension and parses.
    Saves the visualization model as a GLB file at glb_path.
    Returns: (summary, parts_data)
    """
    ext = os.path.splitext(file_path)[1].lower()
    
    if ext in ['.step', '.stp', '.iges', '.igs']:
        return parse_brep_cad(file_path, glb_path, ext, density_g_cm3)
    elif ext in ['.stl', '.obj', '.gltf', '.glb']:
        return parse_mesh_cad(file_path, glb_path, density_g_cm3)
    else:
        raise ValueError(f"Unsupported format '{ext}'. Please upload STEP, IGES, STL, OBJ, or GLTF/GLB files.")

def parse_brep_cad(file_path, glb_path, ext, density_g_cm3):
    """Parses B-Rep files (STEP, IGES) using OpenCascade/CadQuery"""
    if ext in ['.step', '.stp']:
        wp = cq.importers.importStep(file_path)
        shape = wp.val()
    else:
        shape = read_iges(file_path)
        
    solids = shape.Solids()
    is_assembly = len(solids) > 1
    parts_list = solids if len(solids) > 0 else [shape]
    
    parts_data = []
    assembly_container = cq.Assembly()
    
    total_volume_cm3 = 0.0
    total_area_cm2 = 0.0
    total_holes = 0
    total_bends = 0
    total_shells = 0
    total_wires = 0
    total_genus = 0
    aggregate_face_types = collections.Counter()
    aggregate_edge_types = collections.Counter()
    
    overall_bb = shape.BoundingBox()
    
    for idx, part in enumerate(parts_list):
        part_name = f"Part_{idx + 1}"
        
        v_mm3 = part.Volume()
        v_cm3 = v_mm3 / 1000.0
        a_mm2 = part.Area()
        a_cm2 = a_mm2 / 100.0
        
        total_volume_cm3 += v_cm3
        total_area_cm2 += a_cm2
        
        bb = part.BoundingBox()
        w_x = bb.xlen
        w_y = bb.ylen
        w_z = bb.zlen
        
        com = part.Center()
        
        try:
            faces = len(part.Faces())
            edges = len(part.Edges())
            vertices = len(part.Vertices())
        except Exception:
            faces = 0
            edges = 0
            vertices = 0

        # Deep topology analysis
        topology = analyze_brep_topology(part)
        
        total_holes += topology["holes"]
        total_bends += topology["bends"]
        total_shells += topology["shells"]
        total_wires += topology["wires"]
        total_genus += topology["genus"]
        aggregate_face_types.update(topology["face_types"])
        aggregate_edge_types.update(topology["edge_types"])
            
        part_mass_g = v_cm3 * density_g_cm3
        color_hex = COLORS[idx % len(COLORS)]
        
        parts_data.append({
            "part_index": idx + 1,
            "name": part_name,
            "volume_cm3": round(v_cm3, 4),
            "area_cm2": round(a_cm2, 4),
            "bbox_x_mm": round(w_x, 3),
            "bbox_y_mm": round(w_y, 3),
            "bbox_z_mm": round(w_z, 3),
            "mass_g": round(part_mass_g, 2),
            "com_x": round(com.x, 3),
            "com_y": round(com.y, 3),
            "com_z": round(com.z, 3),
            "color": color_hex,
            "faces": faces,
            "edges": edges,
            "vertices": vertices,
            "type": "Solid" if len(solids) > 0 else "Shell/Surface",
            "material": "Steel" if density_g_cm3 == 7.85 else "Custom",
            "density": density_g_cm3,
            "topology": {
                "face_types": topology["face_types"],
                "edge_types": topology["edge_types"],
                "holes": topology["holes"],
                "bends": topology["bends"],
                "shells": topology["shells"],
                "wires": topology["wires"],
                "genus": topology["genus"],
                "through_holes": topology["through_holes"],
                "bend_details": topology["bend_details"],
                "circular_edge_count": topology["circular_edge_count"],
                "straight_edge_count": topology["straight_edge_count"],
            }
        })
        
        assembly_container.add(part, name=part_name, color=hex_to_cq_color(color_hex))
        
    os.makedirs(os.path.dirname(glb_path), exist_ok=True)
    assembly_container.save(glb_path)
    
    total_mass_g = total_volume_cm3 * density_g_cm3
    
    summary = {
        "file_name": os.path.basename(file_path),
        "total_volume_cm3": round(total_volume_cm3, 4),
        "total_area_cm2": round(total_area_cm2, 4),
        "bbox_x_mm": round(overall_bb.xlen, 3),
        "bbox_y_mm": round(overall_bb.ylen, 3),
        "bbox_z_mm": round(overall_bb.zlen, 3),
        "total_mass_g": round(total_mass_g, 2),
        "is_assembly": is_assembly,
        "num_parts": len(parts_list),
        "format": ext.upper().lstrip('.'),
        "faces_count": sum(p["faces"] for p in parts_data),
        "vertices_count": sum(p["vertices"] for p in parts_data),
        "total_holes": total_holes,
        "total_bends": total_bends,
        "total_shells": total_shells,
        "total_wires": total_wires,
        "total_genus": total_genus,
        "face_type_summary": dict(aggregate_face_types),
        "edge_type_summary": dict(aggregate_edge_types),
    }
    
    return summary, parts_data

def parse_mesh_cad(file_path, glb_path, density_g_cm3):
    """Parses polygonal mesh files (STL, OBJ, GLTF/GLB) using Trimesh"""
    mesh = trimesh.load(file_path)
    
    parts_data = []
    
    if isinstance(mesh, trimesh.Scene):
        geometries = mesh.geometry
        is_assembly = len(geometries) > 1
        
        os.makedirs(os.path.dirname(glb_path), exist_ok=True)
        mesh.export(glb_path, file_type='glb')
        
        overall_bounds = mesh.bounds
        overall_x = overall_bounds[1][0] - overall_bounds[0][0]
        overall_y = overall_bounds[1][1] - overall_bounds[0][1]
        overall_z = overall_bounds[1][2] - overall_bounds[0][2]
        
        total_volume_cm3 = 0.0
        total_area_cm2 = 0.0
        total_faces = 0
        total_vertices = 0
        total_holes = 0
        total_bends = 0
        total_genus = 0
        aggregate_face_types = collections.Counter()
        
        idx = 0
        for name, geom in geometries.items():
            part_name = f"Mesh_{idx + 1}"
            
            v_cm3 = geom.volume / 1000.0 if geom.is_watertight else 0.0
            a_cm2 = geom.area / 100.0
            
            total_volume_cm3 += v_cm3
            total_area_cm2 += a_cm2
            
            bounds = geom.bounds
            w_x = bounds[1][0] - bounds[0][0]
            w_y = bounds[1][1] - bounds[0][1]
            w_z = bounds[1][2] - bounds[0][2]
            
            com = geom.center_mass
            faces = len(geom.faces)
            vertices = len(geom.vertices)
            total_faces += faces
            total_vertices += vertices

            topology = analyze_mesh_topology(geom)
            total_holes += topology["holes"]
            total_bends += topology["bends"]
            total_genus += topology["genus"]
            aggregate_face_types.update(topology["face_types"])
            
            part_mass_g = v_cm3 * density_g_cm3
            color_hex = COLORS[idx % len(COLORS)]
            
            parts_data.append({
                "part_index": idx + 1,
                "name": part_name,
                "volume_cm3": round(v_cm3, 4),
                "area_cm2": round(a_cm2, 4),
                "bbox_x_mm": round(w_x, 3),
                "bbox_y_mm": round(w_y, 3),
                "bbox_z_mm": round(w_z, 3),
                "mass_g": round(part_mass_g, 2),
                "com_x": round(com[0], 3),
                "com_y": round(com[1], 3),
                "com_z": round(com[2], 3),
                "color": color_hex,
                "faces": faces,
                "edges": topology.get("circular_edge_count", 0) + topology.get("straight_edge_count", 0),
                "vertices": vertices,
                "type": "Polygonal Mesh",
                "material": "Unknown Material",
                "density": density_g_cm3,
                "topology": {
                    "face_types": topology["face_types"],
                    "edge_types": topology["edge_types"],
                    "holes": topology["holes"],
                    "bends": topology["bends"],
                    "shells": topology["shells"],
                    "wires": topology["wires"],
                    "genus": topology["genus"],
                    "watertight": topology.get("watertight", False),
                    "circular_edge_count": topology["circular_edge_count"],
                    "straight_edge_count": topology["straight_edge_count"],
                }
            })
            idx += 1
            
        total_mass_g = total_volume_cm3 * density_g_cm3
        
        summary = {
            "file_name": os.path.basename(file_path),
            "total_volume_cm3": round(total_volume_cm3, 4),
            "total_area_cm2": round(total_area_cm2, 4),
            "bbox_x_mm": round(overall_x, 3),
            "bbox_y_mm": round(overall_y, 3),
            "bbox_z_mm": round(overall_z, 3),
            "total_mass_g": round(total_mass_g, 2),
            "is_assembly": is_assembly,
            "num_parts": len(geometries),
            "format": os.path.splitext(file_path)[1].upper().lstrip('.'),
            "faces_count": total_faces,
            "vertices_count": total_vertices,
            "total_holes": total_holes,
            "total_bends": total_bends,
            "total_shells": len(geometries),
            "total_wires": 0,
            "total_genus": total_genus,
            "face_type_summary": dict(aggregate_face_types),
            "edge_type_summary": {},
        }
        
    else:
        os.makedirs(os.path.dirname(glb_path), exist_ok=True)
        scene = trimesh.Scene()
        scene.add_geometry(mesh, node_name="Part_1")
        scene.export(glb_path, file_type='glb')
        
        v_cm3 = mesh.volume / 1000.0 if mesh.is_watertight else 0.0
        a_cm2 = mesh.area / 100.0
        
        bounds = mesh.bounds
        w_x = bounds[1][0] - bounds[0][0]
        w_y = bounds[1][1] - bounds[0][1]
        w_z = bounds[1][2] - bounds[0][2]
        
        com = mesh.center_mass
        faces = len(mesh.faces)
        vertices = len(mesh.vertices)

        topology = analyze_mesh_topology(mesh)
        
        part_mass_g = v_cm3 * density_g_cm3
        color_hex = COLORS[0]
        
        parts_data.append({
            "part_index": 1,
            "name": "Part_1",
            "volume_cm3": round(v_cm3, 4),
            "area_cm2": round(a_cm2, 4),
            "bbox_x_mm": round(w_x, 3),
            "bbox_y_mm": round(w_y, 3),
            "bbox_z_mm": round(w_z, 3),
            "mass_g": round(part_mass_g, 2),
            "com_x": round(com[0], 3),
            "com_y": round(com[1], 3),
            "com_z": round(com[2], 3),
            "color": color_hex,
            "faces": faces,
            "edges": topology.get("circular_edge_count", 0) + topology.get("straight_edge_count", 0),
            "vertices": vertices,
            "type": "Polygonal Mesh",
            "material": "Unknown Material",
            "density": density_g_cm3,
            "topology": {
                "face_types": topology["face_types"],
                "edge_types": topology["edge_types"],
                "holes": topology["holes"],
                "bends": topology["bends"],
                "shells": topology["shells"],
                "wires": topology["wires"],
                "genus": topology["genus"],
                "watertight": topology.get("watertight", False),
                "circular_edge_count": topology["circular_edge_count"],
                "straight_edge_count": topology["straight_edge_count"],
            }
        })
        
        summary = {
            "file_name": os.path.basename(file_path),
            "total_volume_cm3": round(v_cm3, 4),
            "total_area_cm2": round(a_cm2, 4),
            "bbox_x_mm": round(w_x, 3),
            "bbox_y_mm": round(w_y, 3),
            "bbox_z_mm": round(w_z, 3),
            "total_mass_g": round(part_mass_g, 2),
            "is_assembly": False,
            "num_parts": 1,
            "format": os.path.splitext(file_path)[1].upper().lstrip('.'),
            "faces_count": faces,
            "vertices_count": vertices,
            "total_holes": topology["holes"],
            "total_bends": topology["bends"],
            "total_shells": topology["shells"],
            "total_wires": topology["wires"],
            "total_genus": topology["genus"],
            "face_type_summary": topology["face_types"],
            "edge_type_summary": topology["edge_types"],
        }
        
    return summary, parts_data
