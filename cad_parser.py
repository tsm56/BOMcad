import os
import trimesh
import cadquery as cq
from cadquery import Shape
from OCP.IGESControl import IGESControl_Reader
from OCP.IFSelect import IFSelect_RetDone

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
        # Get single shape if only one, or a compound if multiple roots exist
        if reader.NbShapes() > 0:
            topods_shape = reader.OneShape()
            return Shape.cast(topods_shape)
        else:
            raise ValueError("No shapes found in the IGES file.")
    else:
        raise ValueError(f"Could not read IGES file: status code {status}")

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
        # Load step file using cadquery importer
        wp = cq.importers.importStep(file_path)
        shape = wp.val()
    else:
        # Load IGES file
        shape = read_iges(file_path)
        
    solids = shape.Solids()
    is_assembly = len(solids) > 1
    
    # If no solids, treat the entire shape as a single part (e.g. face models)
    parts_list = solids if len(solids) > 0 else [shape]
    
    parts_data = []
    assembly_container = cq.Assembly()
    
    total_volume_cm3 = 0.0
    total_area_cm2 = 0.0
    
    # Bounding Box calculations for the unified envelope
    overall_bb = shape.BoundingBox()
    
    for idx, part in enumerate(parts_list):
        part_name = f"Part_{idx + 1}"
        
        # Geometry metrics
        v_mm3 = part.Volume()
        v_cm3 = v_mm3 / 1000.0  # mm³ to cm³
        a_mm2 = part.Area()
        a_cm2 = a_mm2 / 100.0   # mm² to cm²
        
        total_volume_cm3 += v_cm3
        total_area_cm2 += a_cm2
        
        # Bounding box of the part
        bb = part.BoundingBox()
        w_x = bb.xlen
        w_y = bb.ylen
        w_z = bb.zlen
        
        # Center of mass
        com = part.Center()
        
        # B-Rep entity counts
        try:
            faces = len(part.Faces())
            edges = len(part.Edges())
            vertices = len(part.Vertices())
        except Exception:
            faces = 0
            edges = 0
            vertices = 0
            
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
            "density": density_g_cm3
        })
        
        # Add to assembly for visualization
        assembly_container.add(part, name=part_name, color=hex_to_cq_color(color_hex))
        
    # Save visualization GLB
    # Make sure we build the directory if it doesn't exist
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
        "vertices_count": sum(p["vertices"] for p in parts_data)
    }
    
    return summary, parts_data

def parse_mesh_cad(file_path, glb_path, density_g_cm3):
    """Parses polygonal mesh files (STL, OBJ, GLTF/GLB) using Trimesh"""
    mesh = trimesh.load(file_path)
    
    parts_data = []
    
    # If trimesh loaded it as a Scene (multiple nodes/geometries)
    if isinstance(mesh, trimesh.Scene):
        geometries = mesh.geometry
        is_assembly = len(geometries) > 1
        
        # Export the scene to GLB directly
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
        
        idx = 0
        for name, geom in geometries.items():
            part_name = f"Mesh_{idx + 1}"
            
            # Geometry calculations
            v_cm3 = geom.volume / 1000.0 if geom.is_watertight else 0.0
            a_cm2 = geom.area / 100.0
            
            total_volume_cm3 += v_cm3
            total_area_cm2 += a_cm2
            
            # Bounding box
            bounds = geom.bounds
            w_x = bounds[1][0] - bounds[0][0]
            w_y = bounds[1][1] - bounds[0][1]
            w_z = bounds[1][2] - bounds[0][2]
            
            # Center of mass
            com = geom.center_mass
            
            # Mesh statistics
            faces = len(geom.faces)
            vertices = len(geom.vertices)
            total_faces += faces
            total_vertices += vertices
            
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
                "faces": faces, # triangles count
                "edges": 0,
                "vertices": vertices,
                "type": "Polygonal Mesh",
                "material": "Unknown Material",
                "density": density_g_cm3
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
            "vertices_count": total_vertices
        }
        
    else:
        # Single Trimesh geometry (e.g. STL)
        os.makedirs(os.path.dirname(glb_path), exist_ok=True)
        # Create a scene out of the single mesh and export it to GLB
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
            "edges": 0,
            "vertices": vertices,
            "type": "Polygonal Mesh",
            "material": "Unknown Material",
            "density": density_g_cm3
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
            "vertices_count": vertices
        }
        
    return summary, parts_data
