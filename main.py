import os
import uuid
import shutil
import pandas as pd
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from cad_parser import parse_cad_file
from fpdf import FPDF

app = FastAPI(title="Universal CAD Analyzer API")

# Enable CORS for local testing
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# App directories
UPLOAD_DIR = "uploads"
STATIC_DIR = "static"
MODELS_DIR = os.path.join(STATIC_DIR, "models")
REPORTS_DIR = "reports"

for d in [UPLOAD_DIR, STATIC_DIR, MODELS_DIR, REPORTS_DIR]:
    os.makedirs(d, exist_ok=True)

# In-memory storage for CAD analysis results
ANALYSIS_STORE = {}

# Predefined material databases
MATERIAL_DATABASE = {
    "Steel (Low Carbon)": 7.85,
    "Stainless Steel (304)": 8.00,
    "Aluminum (6061-T6)": 2.70,
    "Titanium (Ti-6Al-4V)": 4.43,
    "Copper": 8.96,
    "Brass": 8.50,
    "PLA (Plastic)": 1.24,
    "ABS (Plastic)": 1.04,
    "Carbon Fiber": 1.75
}

@app.post("/api/analyze")
async def analyze_file(file: UploadFile = File(...)):
    file_uuid = str(uuid.uuid4())
    filename = file.filename
    ext = os.path.splitext(filename)[1].lower()
    
    # Save uploaded file
    file_path = os.path.join(UPLOAD_DIR, f"{file_uuid}{ext}")
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
        
    glb_filename = f"{file_uuid}.glb"
    glb_path = os.path.join(MODELS_DIR, glb_filename)
    
    try:
        # We start with Steel density (7.85) as baseline for CAD formats
        # or PLA (1.24) if it's a mesh format, but let's default to Steel.
        default_density = 7.85
        summary, parts = parse_cad_file(file_path, glb_path, default_density)
        
        # Save in database
        ANALYSIS_STORE[file_uuid] = {
            "summary": summary,
            "parts": parts,
            "file_path": file_path,
            "glb_path": glb_path,
            "original_filename": filename
        }
        
        return {
            "uuid": file_uuid,
            "summary": summary,
            "parts": parts,
            "model_url": f"/static/models/{glb_filename}"
        }
        
    except Exception as e:
        # Clean up files on error
        if os.path.exists(file_path):
            os.remove(file_path)
        if os.path.exists(glb_path):
            os.remove(glb_path)
        raise HTTPException(status_code=400, detail=f"Failed to analyze CAD file: {str(e)}")

@app.post("/api/recalculate/{file_uuid}/{part_index}")
async def recalculate_part(
    file_uuid: str,
    part_index: int,
    material: str = Form(...),
    density: float = Form(...)
):
    if file_uuid not in ANALYSIS_STORE:
        raise HTTPException(status_code=404, detail="Analysis session not found.")
        
    session = ANALYSIS_STORE[file_uuid]
    parts = session["parts"]
    
    # Find targeted part (part_index is 1-indexed)
    target_part = None
    for p in parts:
        if p["part_index"] == part_index:
            target_part = p
            break
            
    if not target_part:
        raise HTTPException(status_code=404, detail="Part index not found.")
        
    # Recalculate
    target_part["material"] = material
    target_part["density"] = density
    # mass = volume_cm3 * density
    target_part["mass_g"] = round(target_part["volume_cm3"] * density, 2)
    
    # Recalculate total summary mass
    total_mass_g = sum(p["mass_g"] for p in parts)
    session["summary"]["total_mass_g"] = round(total_mass_g, 2)
    
    return {
        "summary": session["summary"],
        "parts": parts
    }

@app.get("/api/export/csv/{file_uuid}")
async def export_csv(file_uuid: str):
    if file_uuid not in ANALYSIS_STORE:
        raise HTTPException(status_code=404, detail="Analysis session not found.")
        
    session = ANALYSIS_STORE[file_uuid]
    df = pd.DataFrame(session["parts"])
    
    # Select and rename columns for presentation
    columns_map = {
        "part_index": "Part Index",
        "name": "Component Name",
        "material": "Material",
        "density": "Density (g/cm³)",
        "volume_cm3": "Volume (cm³)",
        "area_cm2": "Surface Area (cm²)",
        "bbox_x_mm": "Length X (mm)",
        "bbox_y_mm": "Width Y (mm)",
        "bbox_z_mm": "Height Z (mm)",
        "mass_g": "Mass (g)",
        "com_x": "COM X (mm)",
        "com_y": "COM Y (mm)",
        "com_z": "COM Z (mm)",
        "type": "Geometry Type"
    }
    df = df[list(columns_map.keys())].rename(columns=columns_map)
    
    csv_path = os.path.join(REPORTS_DIR, f"BOM_{file_uuid}.csv")
    df.to_csv(csv_path, index=False)
    
    return FileResponse(
        csv_path,
        media_type="text/csv",
        filename=f"BOM_{os.path.splitext(session['original_filename'])[0]}.csv"
    )

@app.get("/api/export/excel/{file_uuid}")
async def export_excel(file_uuid: str):
    if file_uuid not in ANALYSIS_STORE:
        raise HTTPException(status_code=404, detail="Analysis session not found.")
        
    session = ANALYSIS_STORE[file_uuid]
    parts = session["parts"]
    summary = session["summary"]
    
    # 1. Create Parts Dataframe
    df_parts = pd.DataFrame(parts)
    columns_map = {
        "part_index": "Part Index",
        "name": "Component Name",
        "material": "Material",
        "density": "Density (g/cm³)",
        "volume_cm3": "Volume (cm³)",
        "area_cm2": "Surface Area (cm²)",
        "bbox_x_mm": "Length X (mm)",
        "bbox_y_mm": "Width Y (mm)",
        "bbox_z_mm": "Height Z (mm)",
        "mass_g": "Mass (g)",
        "com_x": "COM X (mm)",
        "com_y": "COM Y (mm)",
        "com_z": "COM Z (mm)",
        "type": "Geometry Type"
    }
    df_parts = df_parts[list(columns_map.keys())].rename(columns=columns_map)
    
    # 2. Create Summary Dataframe
    summary_data = {
        "Metric": [
            "File Name", "CAD Format", "Total Assembly Volume", 
            "Total Assembly Area", "Outer Envelope Length (X)", 
            "Outer Envelope Width (Y)", "Outer Envelope Height (Z)", 
            "Total Estimated Mass", "Total Components/Parts"
        ],
        "Value": [
            summary["file_name"], summary["format"], f"{summary['total_volume_cm3']} cm³",
            f"{summary['total_area_cm2']} cm²", f"{summary['bbox_x_mm']} mm",
            f"{summary['bbox_y_mm']} mm", f"{summary['bbox_z_mm']} mm",
            f"{summary['total_mass_g']} g", summary["num_parts"]
        ]
    }
    df_summary = pd.DataFrame(summary_data)
    
    xlsx_path = os.path.join(REPORTS_DIR, f"CAD_Analysis_{file_uuid}.xlsx")
    
    # Write to multiple sheets
    with pd.ExcelWriter(xlsx_path, engine="openpyxl") as writer:
        df_summary.to_excel(writer, sheet_name="Overview", index=False)
        df_parts.to_excel(writer, sheet_name="Components List", index=False)
        
    return FileResponse(
        xlsx_path,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=f"CAD_Analysis_{os.path.splitext(session['original_filename'])[0]}.xlsx"
    )

@app.get("/api/export/json/{file_uuid}")
async def export_json(file_uuid: str):
    if file_uuid not in ANALYSIS_STORE:
        raise HTTPException(status_code=404, detail="Analysis session not found.")
    return JSONResponse(content=ANALYSIS_STORE[file_uuid]["parts"])


class PDFReport(FPDF):
    def header(self):
        self.set_fill_color(15, 23, 42) # Dark Slate Blue
        self.rect(0, 0, 210, 40, "F")
        self.set_font("Helvetica", "B", 20)
        self.set_text_color(255, 255, 255)
        self.cell(0, 20, "TitanCAD Analyzer Report", ln=1, align="C")
        self.set_font("Helvetica", "I", 10)
        self.cell(0, 5, "Automated Engineering Properties & Physical Metrology Breakdown", ln=1, align="C")
        self.ln(15)

    def footer(self):
        self.set_y(-15)
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(100, 116, 139)
        self.cell(0, 10, f"Page {self.page_no()}/{{nb}} | TitanCAD Engineering Systems", align="C")


@app.get("/api/export/pdf/{file_uuid}")
async def export_pdf(file_uuid: str):
    if file_uuid not in ANALYSIS_STORE:
        raise HTTPException(status_code=404, detail="Analysis session not found.")
        
    session = ANALYSIS_STORE[file_uuid]
    summary = session["summary"]
    parts = session["parts"]
    
    pdf = PDFReport()
    pdf.alias_nb_pages()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)
    
    # Overview Section
    pdf.set_font("Helvetica", "B", 14)
    pdf.set_text_color(30, 41, 59)
    pdf.cell(0, 10, "1. Executive Summary", ln=1)
    pdf.set_draw_color(99, 102, 241) # Indigo accent line
    pdf.set_line_width(0.5)
    pdf.line(10, pdf.get_y(), 200, pdf.get_y())
    pdf.ln(5)
    
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(71, 85, 105)
    
    # Metadata table
    metadata = [
        ("File Name:", summary["file_name"]),
        ("CAD Format:", summary["format"]),
        ("Total Parts Count:", str(summary["num_parts"])),
        ("Assembly Envelope Dimensions:", f"{summary['bbox_x_mm']} x {summary['bbox_y_mm']} x {summary['bbox_z_mm']} mm"),
        ("Total Assembly Volume:", f"{summary['total_volume_cm3']} cm³"),
        ("Total Surface Area:", f"{summary['total_area_cm2']} cm²"),
        ("Total Estimated Weight:", f"{summary['total_mass_g']} g"),
        ("Structure Type:", "Assembly (Multi-solid)" if summary["is_assembly"] else "Single Solid Part")
    ]
    
    for label, val in metadata:
        pdf.set_font("Helvetica", "B", 10)
        pdf.cell(60, 7, label, 0)
        pdf.set_font("Helvetica", "", 10)
        pdf.cell(130, 7, val, 0, 1)
        
    pdf.ln(10)
    
    # Components Breakdown
    pdf.set_font("Helvetica", "B", 14)
    pdf.set_text_color(30, 41, 59)
    pdf.cell(0, 10, "2. Component Breakdown", ln=1)
    pdf.line(10, pdf.get_y(), 200, pdf.get_y())
    pdf.ln(5)
    
    # Table headers
    pdf.set_fill_color(226, 232, 240) # Slate background
    pdf.set_font("Helvetica", "B", 8)
    pdf.set_text_color(15, 23, 42)
    
    col_widths = [15, 40, 35, 25, 25, 25, 25] # Total 190
    headers = ["Index", "Part Name", "Material", "Vol (cm³)", "Area (cm²)", "Mass (g)", "BBox XxYxZ (mm)"]
    
    for w, h in zip(col_widths, headers):
        pdf.cell(w, 8, h, 1, 0, "C", True)
    pdf.ln()
    
    # Rows
    pdf.set_font("Helvetica", "", 8)
    pdf.set_text_color(71, 85, 105)
    
    for p in parts:
        dims_str = f"{int(p['bbox_x_mm'])}x{int(p['bbox_y_mm'])}x{int(p['bbox_z_mm'])}"
        pdf.cell(col_widths[0], 7, str(p["part_index"]), 1, 0, "C")
        pdf.cell(col_widths[1], 7, p["name"], 1, 0, "L")
        pdf.cell(col_widths[2], 7, p["material"], 1, 0, "L")
        pdf.cell(col_widths[3], 7, str(p["volume_cm3"]), 1, 0, "R")
        pdf.cell(col_widths[4], 7, str(p["area_cm2"]), 1, 0, "R")
        pdf.cell(col_widths[5], 7, str(p["mass_g"]), 1, 0, "R")
        pdf.cell(col_widths[6], 7, dims_str, 1, 0, "C")
        pdf.ln()
        
    pdf_path = os.path.join(REPORTS_DIR, f"Report_{file_uuid}.pdf")
    pdf.output(pdf_path)
    
    return FileResponse(
        pdf_path,
        media_type="application/pdf",
        filename=f"Report_{os.path.splitext(session['original_filename'])[0]}.pdf"
    )

# Serve Frontend static assets
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

@app.get("/")
async def root():
    return RedirectResponse(url="/static/index.html")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
