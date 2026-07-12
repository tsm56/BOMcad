import os
import math
import cadquery as cq
import trimesh
from cad_parser import parse_cad_file
from fastapi.testclient import TestClient
from main import app

def run_brep_tests():
    print("=== Running B-Rep (STEP) Verification Tests ===")
    
    # 1. Create a synthetic B-Rep Assembly using CadQuery
    # Part 1: Box (10x20x30 mm) -> Volume = 6000 mm³ = 6.0 cm³
    # Surface Area = 2*(10*20 + 20*30 + 10*30) = 2*(200 + 600 + 300) = 2200 mm² = 22.0 cm²
    box = cq.Solid.makeBox(10, 20, 30)
    
    # Part 2: Cylinder (radius=5 mm, height=15 mm) -> Volume = pi * r² * h = 25 * pi * 15 ≈ 1178.097 mm³ = 1.178 cm³
    # Surface Area = 2 * pi * r * h + 2 * pi * r² = 2 * pi * 5 * 15 + 2 * pi * 25 = 150*pi + 50*pi = 200*pi ≈ 628.318 mm² = 6.283 cm²
    cylinder = cq.Solid.makeCylinder(5, 15)
    cylinder = cylinder.translate((50, 50, 50)) # Shift to prevent intersection
    
    # Assembly
    compound = cq.Compound.makeCompound([box, cylinder])
    temp_step_path = "temp_test_model.step"
    compound.exportStep(temp_step_path)
    
    temp_glb_path = "static/models/temp_test_model.glb"
    
    try:
        # Run parsing with steel density (7.85 g/cm³)
        summary, parts = parse_cad_file(temp_step_path, temp_glb_path, density_g_cm3=7.85)
        
        print("Summary:")
        for k, v in summary.items():
            print(f"  {k}: {v}")
            
        print("Parts details:")
        for p in parts:
            print(f"  Part {p['part_index']}: Volume = {p['volume_cm3']} cm³, Mass = {p['mass_g']} g, Dims = {p['bbox_x_mm']}x{p['bbox_y_mm']}x{p['bbox_z_mm']} mm")
            
        # Assertions
        assert summary["num_parts"] == 2, f"Expected 2 parts, got {summary['num_parts']}"
        assert summary["is_assembly"] is True, "Expected model to be parsed as assembly"
        assert math.isclose(parts[0]["volume_cm3"], 6.0, abs_tol=1e-2), f"Expected box volume ~6.0, got {parts[0]['volume_cm3']}"
        assert math.isclose(parts[1]["volume_cm3"], 1.178, abs_tol=1e-2), f"Expected cylinder volume ~1.178, got {parts[1]['volume_cm3']}"
        assert os.path.exists(temp_glb_path), "Visual GLB file was not created"
        
        print("B-Rep Verification tests: PASSED\n")
        
    finally:
        # Clean up files
        if os.path.exists(temp_step_path):
            os.remove(temp_step_path)
        if os.path.exists(temp_glb_path):
            os.remove(temp_glb_path)

def run_mesh_tests():
    print("=== Running Mesh (STL) Verification Tests ===")
    
    # 1. Create a synthetic STL using trimesh
    # Spherical mesh with radius=10 mm -> Volume = (4/3)*pi*r³ = 4188.79 mm³ = 4.189 cm³
    # Surface Area = 4*pi*r² = 400*pi ≈ 1256.63 mm² = 12.566 cm²
    mesh = trimesh.creation.icosphere(subdivisions=3, radius=10.0)
    temp_stl_path = "temp_test_mesh.stl"
    mesh.export(temp_stl_path)
    
    temp_glb_path = "static/models/temp_test_mesh.glb"
    
    try:
        # Run parsing with default density (1.24 g/cm³ - PLA plastic)
        summary, parts = parse_cad_file(temp_stl_path, temp_glb_path, density_g_cm3=1.24)
        
        print("Summary:")
        for k, v in summary.items():
            print(f"  {k}: {v}")
            
        print("Parts details:")
        for p in parts:
            print(f"  Part {p['part_index']}: Volume = {p['volume_cm3']} cm³, Mass = {p['mass_g']} g, Dims = {p['bbox_x_mm']}x{p['bbox_y_mm']}x{p['bbox_z_mm']} mm")
            
        # Assertions
        assert summary["num_parts"] == 1, f"Expected 1 part, got {summary['num_parts']}"
        assert summary["is_assembly"] is False, "Expected single mesh not assembly"
        assert math.isclose(parts[0]["volume_cm3"], 4.189, abs_tol=1e-1), f"Expected volume ~4.189, got {parts[0]['volume_cm3']}"
        assert os.path.exists(temp_glb_path), "Visual GLB file was not created"
        
        print("Mesh Verification tests: PASSED\n")
        
    finally:
        # Clean up files
        if os.path.exists(temp_stl_path):
            os.remove(temp_stl_path)
        if os.path.exists(temp_glb_path):
            os.remove(temp_glb_path)

def run_api_tests():
    print("=== Running FastAPI API Endpoint Verification Tests ===")
    client = TestClient(app)
    
    # Use sample_bracket_with_hole.step from the workspace
    step_file_path = "sample_bracket_with_hole.step"
    if not os.path.exists(step_file_path):
        print(f"Skipping API tests: {step_file_path} not found.")
        return
        
    with open(step_file_path, "rb") as f:
        response = client.post("/api/analyze", files={"file": (step_file_path, f, "application/octet-stream")})
        
    assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
    data = response.json()
    
    assert "uuid" in data, "Response missing 'uuid'"
    assert "summary" in data, "Response missing 'summary'"
    assert "parts" in data, "Response missing 'parts'"
    assert "model_url" in data, "Response missing 'model_url'"
    
    file_uuid = data["uuid"]
    summary = data["summary"]
    parts = data["parts"]
    
    print(f"Uploaded model successfully. UUID: {file_uuid}")
    print(f"Parts count: {summary['num_parts']}")
    
    # Recalculate
    part_idx = parts[0]["part_index"]
    recalc_response = client.post(
        f"/api/recalculate/{file_uuid}/{part_idx}",
        data={"material": "Aluminum (6061-T6)", "density": 2.70}
    )
    assert recalc_response.status_code == 200, f"Recalculate failed: {recalc_response.text}"
    recalc_data = recalc_response.json()
    
    updated_parts = recalc_data["parts"]
    updated_part = next(p for p in updated_parts if p["part_index"] == part_idx)
    assert updated_part["material"] == "Aluminum (6061-T6)"
    assert updated_part["density"] == 2.70
    expected_mass = round(updated_part["volume_cm3"] * 2.70, 2)
    assert math.isclose(updated_part["mass_g"], expected_mass, abs_tol=1e-2)
    
    # Export CSV
    csv_resp = client.get(f"/api/export/csv/{file_uuid}")
    assert csv_resp.status_code == 200
    assert csv_resp.headers["content-type"] == "text/csv; charset=utf-8"
    
    # Export Excel
    excel_resp = client.get(f"/api/export/excel/{file_uuid}")
    assert excel_resp.status_code == 200
    
    # Export JSON
    json_resp = client.get(f"/api/export/json/{file_uuid}")
    assert json_resp.status_code == 200
    assert len(json_resp.json()) == len(parts)
    
    # Export PDF
    pdf_resp = client.get(f"/api/export/pdf/{file_uuid}")
    assert pdf_resp.status_code == 200
    assert pdf_resp.headers["content-type"] == "application/pdf"
    
    # Clean up generated files
    try:
        # main.py stores file in uploads/, models in static/models/, and reports in reports/
        upload_path = os.path.join("uploads", f"{file_uuid}.step")
        glb_path = os.path.join("static", "models", f"{file_uuid}.glb")
        csv_path = os.path.join("reports", f"BOM_{file_uuid}.csv")
        excel_path = os.path.join("reports", f"CAD_Analysis_{file_uuid}.xlsx")
        pdf_path = os.path.join("reports", f"Report_{file_uuid}.pdf")
        
        for path in [upload_path, glb_path, csv_path, excel_path, pdf_path]:
            if os.path.exists(path):
                os.remove(path)
    except Exception as e:
        print(f"Error cleaning up test files: {e}")
        
    print("API Endpoint Verification tests: PASSED\n")

if __name__ == "__main__":
    run_brep_tests()
    run_mesh_tests()
    run_api_tests()
    print("All tests completed successfully!")
