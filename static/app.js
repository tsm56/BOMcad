// TitanCAD App Controller - WebGL Metrology and Dashboard Engine

let scene, camera, orthoCamera, currentCamera, renderer, controls;
let assemblyGroup = null;
let clippingPlane = null;
let raycaster, mouse;
let canvas = null;
let gridHelper = null; // Save reference to update dynamically

// Background Styles Palette
let currentBgIndex = 0;
const BG_STYLES = [
    { name: "Dark Space", bg: 0x090d16, grid: 0x1e293b, gridMain: 0x6366f1 },
    { name: "Studio Grey", bg: 0x27272a, grid: 0x3f3f46, gridMain: 0x71717a },
    { name: "Alabaster White", bg: 0xf8fafc, grid: 0xe2e8f0, gridMain: 0x94a3b8 },
    { name: "Pitch Black", bg: 0x000000, grid: 0x111111, gridMain: 0x333333 }
];

// Measurement Tool State
let isMeasuring = false;
let measurementPoints = [];
let measurementMarkers = [];
let measurementLine = null;
let modelMaxDim = 100; // default boundary size for marker scaling

// Application State
let activeUuid = null;
let activeSummary = {};
let activeParts = [];
let selectedPartIndex = null;
let currentTheme = localStorage.getItem('titancad-theme') || 'dark';

// Datatable Parameters
let currentPage = 1;
const itemsPerPage = 10;
let searchQuery = "";
let typeFilter = "all";
let sortColumn = "part_index";
let sortOrder = "asc"; // 'asc' | 'desc'

// Charts objects
let materialChart = null;
let weightChart = null;

// Preset material densities
const MATERIAL_DENSITIES = {
    "Steel (Low Carbon)": 7.85,
    "Stainless Steel (304)": 8.00,
    "Aluminum (6061-T6)": 2.70,
    "Titanium (Ti-6Al-4V)": 4.43,
    "Copper": 8.96,
    "Brass": 8.50,
    "PLA (Plastic)": 1.24,
    "ABS (Plastic)": 1.04,
    "Carbon Fiber": 1.75
};

// Initialize Application on Page Load
document.addEventListener("DOMContentLoaded", () => {
    // Apply saved theme
    if (currentTheme === 'light') {
        document.body.classList.add('light-theme');
        const icon = document.getElementById('theme-icon');
        if (icon) { icon.className = 'fa-solid fa-moon'; }
    }
    
    initThree();
    setupEventListeners();
    setupDropzone();
});


// 1. Initialize Three.js Viewport
function initThree() {
    const container = document.getElementById("viewer-container");
    canvas = document.getElementById("three-canvas");
    
    // Size to container
    const width = container.clientWidth;
    const height = container.clientHeight;
    canvas.width = width;
    canvas.height = height;

    // Create Scene
    scene = new THREE.Scene();
    scene.background = new THREE.Color(currentTheme === 'light' ? 0xf8fafc : 0x090d16);

    // Perspective Camera
    camera = new THREE.PerspectiveCamera(45, width / height, 0.1, 2000);
    camera.position.set(100, 100, 100);
    currentCamera = camera;

    // Orthographic Camera (for flat structural views)
    const aspect = width / height;
    const d = 100;
    orthoCamera = new THREE.OrthographicCamera(-d * aspect, d * aspect, d, -d, 0.1, 2000);
    orthoCamera.position.set(100, 100, 100);

    // Renderer
    renderer = new THREE.WebGLRenderer({
        canvas: canvas,
        antialias: true,
        alpha: true
    });
    renderer.setSize(width, height);
    renderer.setPixelRatio(window.devicePixelRatio);
    renderer.shadowMap.enabled = true;
    renderer.localClippingEnabled = true;

    // Controls
    controls = new THREE.OrbitControls(currentCamera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.05;
    controls.maxPolarAngle = Math.PI / 2 + 0.1; // Don't go below ground grid

    // Grid & Axes Helpers
    gridHelper = new THREE.GridHelper(300, 60, 0x6366f1, 0x1e293b);
    gridHelper.position.y = -0.1; // Shift slightly down to prevent rendering overlaps
    scene.add(gridHelper);

    const axesHelper = new THREE.AxesHelper(40);
    scene.add(axesHelper);

    // Lights
    const ambientLight = new THREE.AmbientLight(0xffffff, 0.4);
    scene.add(ambientLight);

    const dirLight1 = new THREE.DirectionalLight(0xffffff, 0.6);
    dirLight1.position.set(1, 1, 1).normalize();
    scene.add(dirLight1);

    const dirLight2 = new THREE.DirectionalLight(0xa855f7, 0.25); // Subtle purple highlight fill
    dirLight2.position.set(-1, -1, 1).normalize();
    scene.add(dirLight2);

    // Interaction Setup
    raycaster = new THREE.Raycaster();
    mouse = new THREE.Vector2();

    // Clipping plane init (defaults to cutting from positive X side)
    clippingPlane = new THREE.Plane(new THREE.Vector3(-1, 0, 0), 10000);

    // Handle Resize
    window.addEventListener("resize", onWindowResize);

    // Run Animation Loop
    animate();
}

function animate() {
    requestAnimationFrame(animate);
    
    // Light follows camera for consistent visibility
    const dirLight = scene.children.find(child => child.isDirectionalLight);
    if (dirLight) {
        dirLight.position.copy(currentCamera.position);
    }
    
    controls.update();
    renderer.render(scene, currentCamera);
}

function onWindowResize() {
    const container = document.getElementById("viewer-container");
    const width = container.clientWidth;
    const height = container.clientHeight;

    camera.aspect = width / height;
    camera.updateProjectionMatrix();

    const aspect = width / height;
    const d = 100;
    orthoCamera.left = -d * aspect;
    orthoCamera.right = d * aspect;
    orthoCamera.top = d;
    orthoCamera.bottom = -d;
    orthoCamera.updateProjectionMatrix();

    renderer.setSize(width, height);
}

// 2. Setup File Drag-and-Drop and Uploader
function setupDropzone() {
    const dropzone = document.getElementById("file-dropzone");
    const fileInput = document.getElementById("file-input");
    const btnBrowse = document.getElementById("btn-browse-files");

    btnBrowse.addEventListener("click", (e) => {
        e.stopPropagation();
        fileInput.click();
    });

    fileInput.addEventListener("change", (e) => {
        if (e.target.files.length > 0) {
            handleFileUpload(e.target.files[0]);
        }
    });

    dropzone.addEventListener("dragover", (e) => {
        e.preventDefault();
        dropzone.classList.add("dragover");
    });

    dropzone.addEventListener("dragleave", () => {
        dropzone.classList.remove("dragover");
    });

    dropzone.addEventListener("drop", (e) => {
        e.preventDefault();
        dropzone.classList.remove("dragover");
        if (e.dataTransfer.files.length > 0) {
            handleFileUpload(e.dataTransfer.files[0]);
        }
    });
}

// 3. Upload File API Caller
function handleFileUpload(file) {
    const formData = new FormData();
    formData.append("file", file);

    const progressContainer = document.getElementById("upload-progress");
    const progressFill = document.getElementById("upload-progress-fill");
    const progressText = document.getElementById("upload-progress-text");
    const loadingOverlay = document.getElementById("loading-overlay");
    const statusTitle = document.getElementById("loading-status-title");
    const statusText = document.getElementById("loading-status-text");

    progressContainer.style.display = "block";
    progressFill.style.width = "0%";
    progressText.innerText = "Uploading: 0%";

    // Set loading overlay inside viewer
    loadingOverlay.style.display = "flex";
    statusTitle.innerText = "Uploading File";
    statusText.innerText = `Sending ${file.name} to analysis engine...`;

    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/api/analyze", true);

    xhr.upload.onprogress = (e) => {
        if (e.lengthComputable) {
            const percentComplete = Math.round((e.loaded / e.total) * 100);
            progressFill.style.width = percentComplete + "%";
            progressText.innerText = `Uploading: ${percentComplete}%`;
            if (percentComplete === 100) {
                statusTitle.innerText = "Parsing Geometry";
                statusText.innerText = "Running OpenCascade B-Rep boundary metrology algorithms. This may take a moment for large assemblies...";
            }
        }
    };

    xhr.onload = () => {
        progressContainer.style.display = "none";
        if (xhr.status === 200) {
            const response = JSON.parse(xhr.responseText);
            loadAnalysisData(response);
        } else {
            loadingOverlay.style.display = "none";
            const err = JSON.parse(xhr.responseText);
            alert(`Error: ${err.detail || "Failed to analyze model."}`);
        }
    };

    xhr.onerror = () => {
        progressContainer.style.display = "none";
        loadingOverlay.style.display = "none";
        alert("Upload failed. Check server connection.");
    };

    xhr.send(formData);
}

// 4. Load Geometry and Metadata Response
function loadAnalysisData(data) {
    activeUuid = data.uuid;
    activeSummary = data.summary;
    activeParts = data.parts;
    selectedPartIndex = null;

    // Reset Sliders
    document.getElementById("slider-explode").value = 0;
    document.getElementById("slider-clipping").value = 100;

    // Update Header labels
    document.getElementById("active-file-label").innerText = activeSummary.file_name;
    const formatBadge = document.getElementById("active-format-badge");
    formatBadge.innerText = activeSummary.format;
    formatBadge.style.display = "inline-block";

    // Setup Exports URLs
    document.getElementById("export-csv").href = `/api/export/csv/${activeUuid}`;
    document.getElementById("export-excel").href = `/api/export/excel/${activeUuid}`;
    document.getElementById("export-pdf").href = `/api/export/pdf/${activeUuid}`;
    document.getElementById("export-json").href = `/api/export/json/${activeUuid}`;

    // Reset Inspector View
    document.getElementById("inspector-empty-state").style.display = "block";
    document.getElementById("inspector-card").style.display = "none";

    // Load assembly tree
    buildAssemblyTree();

    // Render Bottom ledger table
    currentPage = 1;
    updateLedgerTable();

    // Load 3D WebGL model
    const loader = new THREE.GLTFLoader();
    const statusText = document.getElementById("loading-status-text");
    statusText.innerText = "Loading tessellated 3D meshes into GPU buffers...";

    loader.load(data.model_url, (gltf) => {
        // Remove old group if exists
        if (assemblyGroup) {
            scene.remove(assemblyGroup);
        }

        assemblyGroup = gltf.scene;
        scene.add(assemblyGroup);

        // Compute group bounding box to adjust camera and center it
        const bbox = new THREE.Box3().setFromObject(assemblyGroup);
        const size = new THREE.Vector3();
        const center = new THREE.Vector3();
        bbox.getSize(size);
        bbox.getCenter(center);

        // Center assembly at origin (0,0,0)
        assemblyGroup.position.sub(center);

        // Cache positions and original materials for outline and explode manipulation
        assemblyGroup.traverse((node) => {
            if (node.isMesh) {
                // Keep record of original local translation relative to centering
                node.userData.originalPosition = node.position.clone();
                node.userData.isCadMesh = true;
                
                // Set double sided materials
                node.material.side = THREE.DoubleSide;
                node.material.clippingPlanes = [clippingPlane];
                node.material.clipShadows = true;

                // Cache original color and emissive properties
                if (node.material.color) {
                    node.userData.originalColor = node.material.color.clone();
                }
                node.userData.originalEmissive = node.material.emissive ? node.material.emissive.clone() : new THREE.Color(0,0,0);
            }
        });

        // Set clipping plane coordinate range based on max extent size
        const maxDim = Math.max(size.x, size.y, size.z);
        
        // Reset clipping plane constant to fit model bounding box
        clippingPlane.constant = maxDim;

        // Position camera to fit model size
        camera.position.set(maxDim * 1.3, maxDim * 1.3, maxDim * 1.3);
        orthoCamera.position.set(maxDim * 1.3, maxDim * 1.3, maxDim * 1.3);
        
        const aspect = canvas.clientWidth / canvas.clientHeight;
        orthoCamera.left = -maxDim * aspect;
        orthoCamera.right = maxDim * aspect;
        orthoCamera.top = maxDim;
        orthoCamera.bottom = -maxDim;
        orthoCamera.updateProjectionMatrix();

        controls.target.set(0, 0, 0);
        controls.update();

        // Turn off loading overlay
        document.getElementById("loading-overlay").style.display = "none";
    }, undefined, (error) => {
        document.getElementById("loading-overlay").style.display = "none";
        alert("3D Loader Error: Could not render model.");
        console.error(error);
    });
}

// 5. Render Hierarchy Assembly Tree
function buildAssemblyTree() {
    const container = document.getElementById("assembly-tree");
    container.innerHTML = ""; // Clear empty state

    const rootWrapper = document.createElement("div");
    rootWrapper.className = "tree-node";
    
    const rootContent = document.createElement("div");
    rootContent.className = "tree-node-content";
    rootContent.innerHTML = `<i class="fa-solid fa-layer-group tree-node-icon"></i> <strong>Assembly (${activeSummary.file_name})</strong>`;
    rootWrapper.appendChild(rootContent);

    const childrenContainer = document.createElement("div");
    childrenContainer.style.marginLeft = "12px";

    activeParts.forEach((part) => {
        const leafNode = document.createElement("div");
        leafNode.className = "tree-node";
        leafNode.id = `tree-node-part-${part.part_index}`;
        
        const leafContent = document.createElement("div");
        leafContent.className = "tree-node-content";
        
        // Apply color indicator bullet matching the mesh
        leafContent.innerHTML = `
            <span class="tree-node-color-indicator" style="background-color: ${part.color};"></span>
            <span>${part.name}</span>
            <span style="color: var(--text-muted); font-size: 0.65rem; margin-left: auto;">${part.mass_g}g</span>
        `;

        leafContent.addEventListener("click", () => {
            selectPart(part.part_index);
            focusCameraOnMesh(part.name);
        });

        leafNode.appendChild(leafContent);
        childrenContainer.appendChild(leafNode);
    });

    rootWrapper.appendChild(childrenContainer);
    container.appendChild(rootWrapper);
}

// 6. Populate Table Ledger List
function updateLedgerTable() {
    const tbody = document.getElementById("parts-ledger-tbody");
    tbody.innerHTML = "";

    // Filter parts
    let filteredParts = activeParts.filter(part => {
        const matchesSearch = part.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
                              part.material.toLowerCase().includes(searchQuery.toLowerCase()) ||
                              part.type.toLowerCase().includes(searchQuery.toLowerCase());
        const matchesType = typeFilter === "all" || part.type === typeFilter;
        return matchesSearch && matchesType;
    });

    // Update count labels
    document.getElementById("table-parts-count").innerText = `${filteredParts.length} components`;

    // Sort parts
    filteredParts.sort((a, b) => {
        let valA = a[sortColumn];
        let valB = b[sortColumn];

        if (typeof valA === 'string') {
            return sortOrder === 'asc' ? valA.localeCompare(valB) : valB.localeCompare(valA);
        } else {
            return sortOrder === 'asc' ? valA - valB : valB - valA;
        }
    });

    // Pagination bounds
    const totalItems = filteredParts.length;
    if (totalItems === 0) {
        tbody.innerHTML = `
            <tr>
                <td colspan="9" class="table-empty-row">
                    <i class="fa-solid fa-magnifying-glass"></i>
                    <p>No matching elements found in the ledger.</p>
                </td>
            </tr>
        `;
        document.getElementById("table-pagination").style.display = "none";
        return;
    }

    document.getElementById("table-pagination").style.display = "flex";
    const startIdx = (currentPage - 1) * itemsPerPage;
    const endIdx = Math.min(startIdx + itemsPerPage, totalItems);
    
    document.getElementById("pagin-start").innerText = startIdx + 1;
    document.getElementById("pagin-end").innerText = endIdx;
    document.getElementById("pagin-total").innerText = totalItems;
    
    // Enable/disable page buttons
    document.getElementById("pagin-prev-btn").disabled = currentPage === 1;
    document.getElementById("pagin-next-btn").disabled = endIdx >= totalItems;

    const pageItems = filteredParts.slice(startIdx, endIdx);

    pageItems.forEach(part => {
        const tr = document.createElement("tr");
        tr.id = `table-row-${part.part_index}`;
        if (selectedPartIndex === part.part_index) {
            tr.className = "active";
        }

        const dims = `${part.bbox_x_mm} x ${part.bbox_y_mm} x ${part.bbox_z_mm}`;
        const com = `${part.com_x}, ${part.com_y}, ${part.com_z}`;

        tr.innerHTML = `
            <td><strong>#${part.part_index}</strong></td>
            <td><span class="tree-node-color-indicator" style="background-color: ${part.color}; vertical-align: middle; margin-right: 6px;"></span>${part.name}</td>
            <td><span class="badge" style="background-color: rgba(255,255,255,0.05); color: var(--text-secondary); border: 1px solid var(--border-color);">${part.type}</span></td>
            <td><strong>${part.material}</strong></td>
            <td>${part.volume_cm3}</td>
            <td>${part.area_cm2}</td>
            <td><span class="font-mono">${dims}</span></td>
            <td class="font-mono highlight-weight" style="color: var(--accent-indigo); font-weight: 700;">${part.mass_g}</td>
            <td><span class="font-mono text-muted">${com}</span></td>
        `;

        tr.addEventListener("click", () => {
            selectPart(part.part_index);
            focusCameraOnMesh(part.name);
        });

        tbody.appendChild(tr);
    });
}

// 7. Select & Highlight Part
function selectPart(partIndex) {
    selectedPartIndex = partIndex;
    const part = activeParts.find(p => p.part_index === partIndex);
    
    // Highlight sidebar inspector details card
    document.getElementById("inspector-empty-state").style.display = "none";
    const inspCard = document.getElementById("inspector-card");
    inspCard.style.display = "block";

    // Set properties values
    document.getElementById("insp-part-index").innerText = `#${part.part_index}`;
    document.getElementById("insp-part-name").innerText = part.name;
    document.getElementById("insp-part-type").innerText = part.type;
    document.getElementById("insp-volume").innerText = part.volume_cm3;
    document.getElementById("insp-area").innerText = part.area_cm2;
    document.getElementById("insp-mass").innerText = part.mass_g;
    document.getElementById("insp-bbox-x").innerText = part.bbox_x_mm;
    document.getElementById("insp-bbox-y").innerText = part.bbox_y_mm;
    document.getElementById("insp-bbox-z").innerText = part.bbox_z_mm;
    document.getElementById("insp-com-x").innerText = part.com_x;
    document.getElementById("insp-com-y").innerText = part.com_y;
    document.getElementById("insp-com-z").innerText = part.com_z;
    
    // Hide/show counts based on solid vs mesh
    if (part.type === "Polygonal Mesh") {
        document.getElementById("insp-lbl-faces").querySelector("span").innerText = "Triangles:";
        document.getElementById("insp-faces").innerText = part.faces;
        document.getElementById("insp-lbl-edges").style.display = "none";
        document.getElementById("insp-vertices").innerText = part.vertices;
    } else {
        document.getElementById("insp-lbl-faces").querySelector("span").innerText = "Faces:";
        document.getElementById("insp-faces").innerText = part.faces;
        document.getElementById("insp-lbl-edges").style.display = "block";
        document.getElementById("insp-edges").innerText = part.edges;
        document.getElementById("insp-vertices").innerText = part.vertices;
    }

    // Material selector defaults
    const materialSelect = document.getElementById("insp-material-select");
    const customDensityGroup = document.getElementById("custom-density-group");
    
    if (MATERIAL_DENSITIES[part.material] !== undefined) {
        materialSelect.value = part.material;
        customDensityGroup.style.display = "none";
    } else {
        materialSelect.value = "Custom Density";
        customDensityGroup.style.display = "block";
        document.getElementById("insp-density-input").value = part.density;
    }

    // Update topology intelligence section
    updateTopologyInspector(part);

    // Highlight row in bottoms table ledger
    document.querySelectorAll("#parts-ledger-tbody tr").forEach(row => {
        row.classList.remove("active");
    });
    const activeRow = document.getElementById(`table-row-${partIndex}`);
    if (activeRow) {
        activeRow.classList.add("active");
    }

    // Highlight item in assembly tree sidebar
    document.querySelectorAll(".tree-node").forEach(node => {
        node.classList.remove("active");
    });
    const activeTreeNode = document.getElementById(`tree-node-part-${partIndex}`);
    if (activeTreeNode) {
        activeTreeNode.classList.add("active");
    }

    // Highlight 3D WebGL mesh in Three.js viewport
    if (assemblyGroup) {
        assemblyGroup.traverse((node) => {
            if (node.isMesh && node.userData.isCadMesh) {
                // Reset emissive
                node.material.emissive.copy(node.userData.originalEmissive);
                
                // Match by mesh node name (which contains "Part_X" or similar)
                if (node.name === part.name || (node.parent && node.parent.name === part.name)) {
                    // Make it glow a bright blue highlight color!
                    node.material.emissive.setHex(0x3b82f6);
                    node.material.emissiveIntensity = 0.55;
                }
            }
        });
    }
}

// 8. Focus camera on target mesh
function focusCameraOnMesh(partName) {
    if (!assemblyGroup) return;

    let targetMesh = null;
    assemblyGroup.traverse((node) => {
        if (node.isMesh && (node.name === partName || (node.parent && node.parent.name === partName))) {
            targetMesh = node;
        }
    });

    if (targetMesh) {
        // Calculate mesh bounding box
        const meshBbox = new THREE.Box3().setFromObject(targetMesh);
        const center = new THREE.Vector3();
        const size = new THREE.Vector3();
        meshBbox.getCenter(center);
        meshBbox.getSize(size);

        // Animate orbit controls center target
        const startTarget = controls.target.clone();
        const duration = 500; // ms
        const startTime = performance.now();

        function animateFocus(time) {
            const progress = Math.min((time - startTime) / duration, 1);
            // Smooth easeOutCubic
            const ease = 1 - Math.pow(1 - progress, 3);
            
            controls.target.lerpVectors(startTarget, center, ease);
            controls.update();

            if (progress < 1) {
                requestAnimationFrame(animateFocus);
            }
        }
        requestAnimationFrame(animateFocus);
    }
}

// 9. Three.js Mouse Clicking Raycasting handler
function onCanvasClick(event) {
    if (!assemblyGroup) return;

    // Calculate mouse position relative to canvas viewport
    const rect = renderer.domElement.getBoundingClientRect();
    mouse.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
    mouse.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;

    raycaster.setFromCamera(mouse, currentCamera);
    
    // Check intersection among children nodes
    const intersects = raycaster.intersectObjects(assemblyGroup.children, true);

    if (intersects.length > 0) {
        if (isMeasuring) {
            handleMeasurementClick(intersects[0].point);
            return;
        }
        
        // Find topmost mesh node with CAD properties mapping
        let targetNode = intersects[0].object;
        while (targetNode && targetNode !== scene) {
            if (targetNode.userData.isCadMesh) {
                break;
            }
            targetNode = targetNode.parent;
        }

        if (targetNode) {
            // Find component index by parsing its mesh name
            const pName = targetNode.name || (targetNode.parent ? targetNode.parent.name : "");
            const matchPart = activeParts.find(p => p.name === pName);
            if (matchPart) {
                selectPart(matchPart.part_index);
            }
        }
    }
}

// Measurement Helper Functions
function toggleMeasureMode() {
    isMeasuring = !isMeasuring;
    const btn = document.getElementById("tool-measure");
    const panel = document.getElementById("measurement-panel");
    
    if (isMeasuring) {
        btn.classList.add("active");
        panel.style.display = "block";
        canvas.style.cursor = "crosshair";
        clearMeasurementData();
    } else {
        btn.classList.remove("active");
        panel.style.display = "none";
        canvas.style.cursor = "default";
        clearMeasurementData();
    }
}

function clearMeasurementData() {
    measurementMarkers.forEach(marker => scene.remove(marker));
    measurementMarkers = [];
    
    if (measurementLine) {
        scene.remove(measurementLine);
        measurementLine = null;
    }
    
    measurementPoints = [];
    
    document.getElementById("measure-p1").innerText = "Click on model...";
    document.getElementById("measure-p2").innerText = "Click on model...";
    document.getElementById("measure-distance").innerText = "-- mm";
    document.getElementById("measure-dx").innerText = "--";
    document.getElementById("measure-dy").innerText = "--";
    document.getElementById("measure-dz").innerText = "--";
}

function createMarker(position, color = 0xef4444) {
    let size = 1.0;
    if (assemblyGroup) {
        const bbox = new THREE.Box3().setFromObject(assemblyGroup);
        const bboxSize = new THREE.Vector3();
        bbox.getSize(bboxSize);
        const maxDim = Math.max(bboxSize.x, bboxSize.y, bboxSize.z);
        size = maxDim * 0.015;
        if (size < 0.1) size = 0.1;
    }
    
    const geometry = new THREE.SphereGeometry(size, 16, 16);
    const material = new THREE.MeshBasicMaterial({ color: color, depthTest: false, depthWrite: false });
    const sphere = new THREE.Mesh(geometry, material);
    sphere.position.copy(position);
    sphere.renderOrder = 999;
    scene.add(sphere);
    return sphere;
}

function drawMeasurementLine(p1, p2, color = 0xf59e0b) {
    const geometry = new THREE.BufferGeometry().setFromPoints([p1, p2]);
    const material = new THREE.LineBasicMaterial({ color: color, depthTest: false, depthWrite: false });
    const line = new THREE.Line(geometry, material);
    line.renderOrder = 998;
    scene.add(line);
    return line;
}

function handleMeasurementClick(point) {
    if (measurementPoints.length >= 2) {
        clearMeasurementData();
    }
    
    if (measurementPoints.length === 0) {
        measurementPoints.push(point);
        const marker = createMarker(point, 0x3b82f6);
        measurementMarkers.push(marker);
        
        document.getElementById("measure-p1").innerText = `${point.x.toFixed(2)}, ${point.y.toFixed(2)}, ${point.z.toFixed(2)}`;
        document.getElementById("measure-p2").innerText = "Click on model...";
    } else if (measurementPoints.length === 1) {
        measurementPoints.push(point);
        const marker = createMarker(point, 0xef4444);
        measurementMarkers.push(marker);
        
        const p1 = measurementPoints[0];
        const p2 = measurementPoints[1];
        
        document.getElementById("measure-p2").innerText = `${p2.x.toFixed(2)}, ${p2.y.toFixed(2)}, ${p2.z.toFixed(2)}`;
        
        const distance = p1.distanceTo(p2);
        const dx = Math.abs(p1.x - p2.x);
        const dy = Math.abs(p1.y - p2.y);
        const dz = Math.abs(p1.z - p2.z);
        
        document.getElementById("measure-distance").innerText = `${distance.toFixed(3)} mm`;
        document.getElementById("measure-dx").innerText = dx.toFixed(2);
        document.getElementById("measure-dy").innerText = dy.toFixed(2);
        document.getElementById("measure-dz").innerText = dz.toFixed(2);
        
        measurementLine = drawMeasurementLine(p1, p2);
    }
}

function toggleBackground() {
    currentBgIndex = (currentBgIndex + 1) % BG_STYLES.length;
    const style = BG_STYLES[currentBgIndex];
    
    scene.background.setHex(style.bg);
    
    if (gridHelper) {
        scene.remove(gridHelper);
    }
    gridHelper = new THREE.GridHelper(300, 60, style.gridMain, style.grid);
    gridHelper.position.y = -0.1;
    scene.add(gridHelper);
}

// 10. Recalculate and update weight
function submitRecalculate() {
    if (!activeUuid || selectedPartIndex === null) return;
    
    const materialSelect = document.getElementById("insp-material-select");
    const customDensityInput = document.getElementById("insp-density-input");
    
    let materialName = materialSelect.value;
    let densityVal = 0.0;
    
    if (materialName === "Custom Density") {
        materialName = "Custom Material";
        densityVal = parseFloat(customDensityInput.value);
        if (isNaN(densityVal) || densityVal <= 0) {
            alert("Please enter a valid positive density.");
            return;
        }
    } else {
        densityVal = MATERIAL_DENSITIES[materialName];
    }

    const recalculateBtn = document.getElementById("btn-recalculate-weight");
    recalculateBtn.disabled = true;
    recalculateBtn.innerHTML = `<i class="fa-solid fa-spinner fa-spin"></i> Recalculating...`;

    const formData = new FormData();
    formData.append("material", materialName);
    formData.append("density", densityVal);

    fetch(`/api/recalculate/${activeUuid}/${selectedPartIndex}`, {
        method: "POST",
        body: formData
    })
    .then(res => res.json())
    .then(data => {
        recalculateBtn.disabled = false;
        recalculateBtn.innerHTML = `<i class="fa-solid fa-arrows-spin"></i> Update Material & Density`;
        
        // Update local state
        activeSummary = data.summary;
        activeParts = data.parts;
        
        // Update tree & table elements list
        buildAssemblyTree();
        updateLedgerTable();
        
        // Refresh active selection view
        selectPart(selectedPartIndex);
    })
    .catch(err => {
        recalculateBtn.disabled = false;
        recalculateBtn.innerHTML = `<i class="fa-solid fa-arrows-spin"></i> Update Material & Density`;
        alert("Recalculation server error.");
        console.error(err);
    });
}

// 11. Explode Assembly logic
function applyExplode(sliderValue) {
    if (!assemblyGroup) return;

    // Use scale factor relative to outer assembly envelope bounds size
    const bbox = new THREE.Box3().setFromObject(assemblyGroup);
    const size = new THREE.Vector3();
    bbox.getSize(size);
    const maxDim = Math.max(size.x, size.y, size.z);
    
    // We move each part along the vector extending from origin
    // since the model was centered at origin (0,0,0)!
    assemblyGroup.traverse((node) => {
        if (node.isMesh && node.userData.originalPosition) {
            // Explode offset along local node position vector direction
            const direction = node.userData.originalPosition.clone().normalize();
            
            // Translate position offset
            const distance = (sliderValue / 100.0) * maxDim * 0.45;
            node.position.copy(node.userData.originalPosition).addScaledVector(direction, distance);
        }
    });
}

// 12. Cross Section clipping planes logic
function applyClipping(sliderValue) {
    if (!assemblyGroup) return;

    // Fetch assembly bounds
    const bbox = new THREE.Box3().setFromObject(assemblyGroup);
    const size = new THREE.Vector3();
    bbox.getSize(size);
    
    // Clipping offset range covers bounding box X scale
    const halfWidth = size.x / 2.0;
    
    // Map slider 0-100% to -halfWidth to +halfWidth
    const positionX = ((sliderValue / 100.0) * size.x) - halfWidth;
    
    if (sliderValue === 100) {
        // Disable clipping by placing boundary outside model extent bounds
        clippingPlane.constant = size.x * 2;
    } else {
        clippingPlane.constant = positionX;
    }
}

// 13. Metrics Dashboard Charts Renderer
function openDashboard() {
    if (!activeUuid) return;
    
    document.getElementById("dashboard-modal").style.display = "flex";

    // Set statistics labels
    document.getElementById("stat-total-parts").innerText = activeSummary.num_parts;
    document.getElementById("stat-total-weight").innerHTML = `${activeSummary.total_mass_g.toLocaleString()} <span class="unit-sub">g</span>`;
    document.getElementById("stat-total-volume").innerHTML = `${activeSummary.total_volume_cm3.toLocaleString()} <span class="unit-sub">cm³</span>`;
    document.getElementById("stat-total-faces").innerText = activeSummary.faces_count.toLocaleString();
    document.getElementById("stat-bbox").innerText = `Length X: ${activeSummary.bbox_x_mm} mm | Width Y: ${activeSummary.bbox_y_mm} mm | Height Z: ${activeSummary.bbox_z_mm} mm`;
    
    // Topology stats
    document.getElementById("stat-total-holes").innerText = (activeSummary.total_holes || 0).toLocaleString();
    document.getElementById("stat-total-bends").innerText = (activeSummary.total_bends || 0).toLocaleString();
    document.getElementById("stat-total-genus").innerText = (activeSummary.total_genus || 0).toLocaleString();
    
    // Face type diversity
    const faceTypeSummary = activeSummary.face_type_summary || {};
    const faceTypeCount = Object.keys(faceTypeSummary).length;
    document.getElementById("stat-face-diversity").innerText = `${faceTypeCount} type${faceTypeCount !== 1 ? 's' : ''}`;

    // Process material distribution values
    const materialCounts = {};
    activeParts.forEach(p => {
        materialCounts[p.material] = (materialCounts[p.material] || 0) + 1;
    });

    const materialLabels = Object.keys(materialCounts);
    const materialData = Object.values(materialCounts);

    // Destroy old chart if exists
    if (materialChart) materialChart.destroy();
    
    const ctxMat = document.getElementById("chart-material-dist").getContext("2d");
    materialChart = new Chart(ctxMat, {
        type: "doughnut",
        data: {
            labels: materialLabels,
            datasets: [{
                data: materialData,
                backgroundColor: ["#6366f1", "#a855f7", "#10b981", "#06b6d4", "#ef4444", "#f59e0b", "#ec4899"],
                borderColor: "#0f1420",
                borderWidth: 2
            }]
        },
        options: {
            responsive: true,
            plugins: {
                legend: {
                    position: "right",
                    labels: { color: "#94a3b8", font: { family: "Plus Jakarta Sans" } }
                }
            }
        }
    });

    // Histogram of weights
    const masses = activeParts.map(p => p.mass_g);
    const maxMass = Math.max(...masses);
    const minMass = Math.min(...masses);
    
    // Split into 5 bins
    const binCount = 5;
    const binWidth = (maxMass - minMass) / binCount;
    const bins = Array(binCount).fill(0);
    const binLabels = [];
    
    for (let i = 0; i < binCount; i++) {
        const binStart = minMass + i * binWidth;
        const binEnd = binStart + binWidth;
        binLabels.push(`${Math.round(binStart)}-${Math.round(binEnd)}g`);
    }

    activeParts.forEach(p => {
        let binIdx = Math.floor((p.mass_g - minMass) / binWidth);
        if (binIdx >= binCount) binIdx = binCount - 1;
        bins[binIdx]++;
    });

    // Destroy old weight histogram if exists
    if (weightChart) weightChart.destroy();
    
    const ctxWeight = document.getElementById("chart-weight-dist").getContext("2d");
    weightChart = new Chart(ctxWeight, {
        type: "bar",
        data: {
            labels: binLabels,
            datasets: [{
                label: "Parts Count",
                data: bins,
                backgroundColor: "rgba(99, 102, 241, 0.6)",
                borderColor: "#6366f1",
                borderWidth: 1.5,
                borderRadius: 5
            }]
        },
        options: {
            responsive: true,
            scales: {
                x: { grid: { color: "rgba(255,255,255,0.05)" }, ticks: { color: "#94a3b8" } },
                y: { grid: { color: "rgba(255,255,255,0.05)" }, ticks: { color: "#94a3b8" }, beginAtZero: true }
            },
            plugins: {
                legend: { display: false }
            }
        }
    });
}

// 14. Topology Intelligence Display
function updateTopologyInspector(part) {
    const topo = part.topology;
    if (!topo) {
        // Hide topology section if no data
        document.getElementById("insp-holes").textContent = "0";
        document.getElementById("insp-bends").textContent = "0";
        document.getElementById("insp-shells").textContent = "0";
        document.getElementById("insp-genus").textContent = "0";
        document.getElementById("insp-hole-details").style.display = "none";
        document.getElementById("insp-face-type-bars").innerHTML = "";
        return;
    }

    // Update grid values
    document.getElementById("insp-holes").textContent = topo.holes || 0;
    document.getElementById("insp-bends").textContent = topo.bends || 0;
    document.getElementById("insp-shells").textContent = topo.shells || 0;
    document.getElementById("insp-genus").textContent = topo.genus || 0;

    // Hole details
    const holeDetailsEl = document.getElementById("insp-hole-details");
    const holeListEl = document.getElementById("insp-hole-list");
    if (topo.through_holes && topo.through_holes.length > 0) {
        holeDetailsEl.style.display = "block";
        holeListEl.innerHTML = topo.through_holes.map((h, i) => {
            const label = h.type === "blind_or_counterbore" ? "Blind/Counterbore" : `Through-Hole ${i + 1}`;
            return `<div class="topo-detail-item">
                <span class="hole-label">${label}</span>
                <span class="hole-val">D ${h.diameter_mm} mm</span>
            </div>`;
        }).join("");
    } else {
        holeDetailsEl.style.display = "none";
    }

    // Face type breakdown bars
    const faceTypesEl = document.getElementById("insp-face-type-bars");
    const faceTypes = topo.face_types || {};
    const totalFaces = Object.values(faceTypes).reduce((a, b) => a + b, 0);
    
    if (totalFaces > 0 && Object.keys(faceTypes).length > 0) {
        const maxCount = Math.max(...Object.values(faceTypes));
        faceTypesEl.innerHTML = Object.entries(faceTypes)
            .sort((a, b) => b[1] - a[1])
            .map(([type, count]) => {
                const pct = maxCount > 0 ? (count / maxCount) * 100 : 0;
                const barClass = type.replace(/\s+/g, '');
                return `<div class="topo-bar-row">
                    <span class="topo-bar-label">${type}</span>
                    <div class="topo-bar-track">
                        <div class="topo-bar-fill ${barClass}" style="width: ${pct}%"></div>
                    </div>
                    <span class="topo-bar-count">${count}</span>
                </div>`;
            }).join("");
    } else {
        faceTypesEl.innerHTML = '<span style="font-size: 0.65rem; color: var(--text-muted);">No face type data available</span>';
    }
}

// 15. Theme Toggle
function toggleTheme() {
    const isLight = document.body.classList.toggle('light-theme');
    currentTheme = isLight ? 'light' : 'dark';
    localStorage.setItem('titancad-theme', currentTheme);
    
    const icon = document.getElementById('theme-icon');
    icon.className = isLight ? 'fa-solid fa-moon' : 'fa-solid fa-sun';
    
    // Update Three.js background and grid colors based on theme
    if (scene) {
        scene.background = new THREE.Color(isLight ? 0xf8fafc : BG_STYLES[currentBgIndex].bg);
    }
    if (gridHelper) {
        scene.remove(gridHelper);
        const gridColor = isLight ? 0xd1d5db : BG_STYLES[currentBgIndex].grid;
        const gridMainColor = isLight ? 0x94a3b8 : BG_STYLES[currentBgIndex].gridMain;
        gridHelper = new THREE.GridHelper(300, 60, gridMainColor, gridColor);
        gridHelper.position.y = -0.1;
        scene.add(gridHelper);
    }
}

// 16. Add UI event handlers
function setupEventListeners() {
    // 3D Canvas selection raycast listener
    canvas.addEventListener("click", onCanvasClick);

    // Sidebar Recalculator Material dropdown custom change handler
    document.getElementById("insp-material-select").addEventListener("change", (e) => {
        const customGroup = document.getElementById("custom-density-group");
        if (e.target.value === "Custom Density") {
            customGroup.style.display = "block";
        } else {
            customGroup.style.display = "none";
        }
    });

    // Submit recalulate button
    document.getElementById("btn-recalculate-weight").addEventListener("click", submitRecalculate);

    // Search bar ledger listener
    document.getElementById("table-search-input").addEventListener("input", (e) => {
        searchQuery = e.target.value;
        currentPage = 1;
        updateLedgerTable();
    });

    // Dropdown filters
    document.getElementById("filter-type-select").addEventListener("change", (e) => {
        typeFilter = e.target.value;
        currentPage = 1;
        updateLedgerTable();
    });

    // Sorting headers listeners
    document.querySelectorAll(".parts-table th").forEach((th, index) => {
        // Skip index column
        if (index === 0) return;
        
        th.style.cursor = "pointer";
        th.addEventListener("click", () => {
            const columnKeys = ["", "name", "type", "material", "volume_cm3", "area_cm2", "bbox_x_mm", "mass_g", "com_x"];
            const key = columnKeys[index];
            
            if (sortColumn === key) {
                sortOrder = sortOrder === "asc" ? "desc" : "asc";
            } else {
                sortColumn = key;
                sortOrder = "asc";
            }
            
            // Update UI headers indicators
            document.querySelectorAll(".parts-table th").forEach(h => {
                h.innerHTML = h.innerText.replace(/ [▲▼]/, "");
            });
            th.innerHTML = th.innerText + (sortOrder === "asc" ? " ▲" : " ▼");
            
            updateLedgerTable();
        });
    });

    // Pagination Click Listeners
    document.getElementById("pagin-prev-btn").addEventListener("click", () => {
        if (currentPage > 1) {
            currentPage--;
            updateLedgerTable();
        }
    });

    document.getElementById("pagin-next-btn").addEventListener("click", () => {
        currentPage++;
        updateLedgerTable();
    });

    // Sliders event change listeners
    document.getElementById("slider-explode").addEventListener("input", (e) => {
        applyExplode(parseInt(e.target.value));
    });

    document.getElementById("slider-clipping").addEventListener("input", (e) => {
        applyClipping(parseInt(e.target.value));
    });

    // Viewer camera views toggle button
    document.getElementById("view-fit").addEventListener("click", () => {
        if (assemblyGroup) {
            const bbox = new THREE.Box3().setFromObject(assemblyGroup);
            const size = new THREE.Vector3();
            bbox.getSize(size);
            const maxDim = Math.max(size.x, size.y, size.z);
            
            controls.target.set(0, 0, 0);
            currentCamera.position.set(maxDim * 1.3, maxDim * 1.3, maxDim * 1.3);
            controls.update();
        }
    });

    document.getElementById("view-ortho").addEventListener("click", (e) => {
        const btn = e.currentTarget;
        if (currentCamera === camera) {
            // Swap to ortho
            currentCamera = orthoCamera;
            btn.classList.add("active");
            
            // Align position
            orthoCamera.position.copy(camera.position);
            orthoCamera.lookAt(controls.target);
            controls.object = orthoCamera;
        } else {
            // Swap to perspective
            currentCamera = camera;
            btn.classList.remove("active");
            
            camera.position.copy(orthoCamera.position);
            camera.lookAt(controls.target);
            controls.object = camera;
        }
        controls.update();
    });

    // Shading options
    document.getElementById("shade-shaded").addEventListener("click", (e) => {
        document.querySelectorAll(".camera-controls .control-btn").forEach(b => {
            if (b.id.startsWith("shade-")) b.classList.remove("active");
        });
        e.currentTarget.classList.add("active");
        
        if (assemblyGroup) {
            assemblyGroup.traverse((node) => {
                if (node.isMesh) {
                    node.material.wireframe = false;
                    node.material.transparent = false;
                    node.material.opacity = 1.0;
                }
            });
        }
    });

    document.getElementById("shade-wireframe").addEventListener("click", (e) => {
        document.querySelectorAll(".camera-controls .control-btn").forEach(b => {
            if (b.id.startsWith("shade-")) b.classList.remove("active");
        });
        e.currentTarget.classList.add("active");
        
        if (assemblyGroup) {
            assemblyGroup.traverse((node) => {
                if (node.isMesh) {
                    node.material.wireframe = true;
                }
            });
        }
    });

    document.getElementById("shade-transparent").addEventListener("click", (e) => {
        document.querySelectorAll(".camera-controls .control-btn").forEach(b => {
            if (b.id.startsWith("shade-")) b.classList.remove("active");
        });
        e.currentTarget.classList.add("active");
        
        if (assemblyGroup) {
            assemblyGroup.traverse((node) => {
                if (node.isMesh) {
                    node.material.wireframe = false;
                    node.material.transparent = true;
                    node.material.opacity = 0.35;
                }
            });
        }
    });

    // Export dropdown toggle trigger button
    const btnExport = document.getElementById("btn-export-dropdown");
    const exportMenu = document.getElementById("export-dropdown-menu");
    
    btnExport.addEventListener("click", (e) => {
        e.stopPropagation();
        exportMenu.classList.toggle("show");
    });
    
    document.addEventListener("click", () => {
        exportMenu.classList.remove("show");
    });

    // Modal view details trigger
    document.getElementById("btn-toggle-dashboard").addEventListener("click", openDashboard);
    document.getElementById("btn-close-dashboard").addEventListener("click", () => {
        document.getElementById("dashboard-modal").style.display = "none";
    });
    document.getElementById("dashboard-modal").addEventListener("click", (e) => {
        if (e.target.id === "dashboard-modal") {
            document.getElementById("dashboard-modal").style.display = "none";
        }
    });

    // Background toggle listener
    document.getElementById("tool-bg-toggle").addEventListener("click", toggleBackground);

    // Measurement tool listeners
    document.getElementById("tool-measure").addEventListener("click", toggleMeasureMode);
    document.getElementById("btn-clear-measurement").addEventListener("click", clearMeasurementData);

    // Theme toggle listener
    document.getElementById("btn-theme-toggle").addEventListener("click", toggleTheme);
}
