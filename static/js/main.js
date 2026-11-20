
const map = L.map("map", {
    center: [26.2, 92.9],
    zoom: 6,
    minZoom: 4,
    maxZoom: 18,
    zoomControl: true
});

// --------------------------------------------------
// ESRI SATELLITE BASEMAP
// --------------------------------------------------

const satelliteLayer = L.tileLayer(
    "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
    {
        attribution: "Tiles © Esri",
        maxZoom: 19
    }
);

satelliteLayer.addTo(map);

// --------------------------------------------------
// CONFIRMED SENTINEL HUB LAYERS
// --------------------------------------------------

// NOTE on autozoom: each Sentinel Hub collection enforces its own
// "meters per pixel" resolution cap, and rejects a WMS GetMap request
// with an error image (not a blank tile) once a 256x256 tile's implied
// pixel size exceeds that cap. Pixel size shrinks as zoom increases
// (roughly 156543 * cos(lat) / 2^zoom meters/pixel), so every layer
// needs its OWN minZoom tuned to its collection's cap, not one shared
// value:
//   - S1_GRD_VV_VH (S1GRD collection) tolerates coarser pixels, so
//     zoom 7 is enough (this is the original, confirmed-working case).
//   - All Sentinel-2 (S2L1C) based layers cap at 200 m/pixel, which
//     over Northeast India (~26°N) needs roughly zoom 10 or higher.
// Using a lower zoom than a layer needs is exactly what produced the
// "Pixel size exceeds the limit" text baked into the returned tiles.
const DEFAULT_WMS_MIN_ZOOM = 7;
const S2_WMS_MIN_ZOOM = 10;

const availableLayers = {
    "S1_GRD_VV_VH": {
        label: "SENTINEL-1 VV + VH",
        category: "C-BAND SAR",
        minZoom: DEFAULT_WMS_MIN_ZOOM
    },

    "B08": {
        label: "SENTINEL-2 B08 · NEAR INFRARED",
        category: "NEAR INFRARED",
        minZoom: S2_WMS_MIN_ZOOM
    },

    "SWIR": {
        label: "SENTINEL-2 SWIR",
        category: "SHORTWAVE INFRARED",
        minZoom: S2_WMS_MIN_ZOOM
    },

    "B10": {
        label: "SENTINEL-2 B10 · CIRRUS",
        category: "CIRRUS",
        minZoom: S2_WMS_MIN_ZOOM
    },

    "B11": {
        label: "SENTINEL-2 B11 · SWIR 1610 NM",
        category: "SHORTWAVE INFRARED",
        minZoom: S2_WMS_MIN_ZOOM
    },

    "B12": {
        label: "SENTINEL-2 B12 · SWIR 2190 NM",
        category: "SHORTWAVE INFRARED",
        minZoom: S2_WMS_MIN_ZOOM
    },

    "GEOLOGY": {
        label: "GEOLOGICAL LAYER",
        category: "GEOLOGY",
        minZoom: S2_WMS_MIN_ZOOM
    },

    "MOISTURE_INDEX": {
        label: "MOISTURE INDEX",
        category: "HYDROLOGY",
        minZoom: S2_WMS_MIN_ZOOM
    },

    "PSRI_NIR": {
        label: "PSRI · NEAR INFRARED",
        category: "VEGETATION",
        minZoom: S2_WMS_MIN_ZOOM
    },

    // L-band is not Sentinel Hub: it is served by our own tile route
    // (ALOS PALSAR-2 annual mosaic, Planetary Computer). The server
    // refuses zoom < 8, so that is its minZoom.
    "L_BAND_PALSAR": {
        label: "L-BAND · ALOS PALSAR-2 (2021, HH/HV)",
        category: "L-BAND SAR",
        minZoom: 8,
        tileUrl: "/api/lband/{z}/{x}/{y}.png?year=2021",
        attribution: "ALOS PALSAR-2 © JAXA, via Microsoft Planetary Computer",
        maxNativeZoom: 14
    }
};

// --------------------------------------------------
// PANEL ELEMENTS
// --------------------------------------------------

const layerPanel = document.getElementById("layerPanel");
const layerMenuButton = document.getElementById("layerMenuButton");
const closeLayerPanel = document.getElementById("closeLayerPanel");
const layerLabel = document.getElementById("layerLabel");
const mapStatus = document.getElementById("mapStatus");

const layerOptions = document.querySelectorAll(
    'input[name="mapLayer"]'
);

// Current active overlay
let activeOverlay = null;

// --------------------------------------------------
// PANEL CONTROLS
// --------------------------------------------------

function openLayerPanel() {
    layerPanel.classList.add("open");
}

function closePanel() {
    layerPanel.classList.remove("open");
}

function toggleLayerPanel() {
    layerPanel.classList.toggle("open");
}

layerMenuButton.addEventListener("click", toggleLayerPanel);
closeLayerPanel.addEventListener("click", closePanel);

// --------------------------------------------------
// KEYBOARD SHORTCUTS
// --------------------------------------------------

document.addEventListener("keydown", (event) => {
    const activeElement = document.activeElement;

    const isTyping =
        activeElement &&
        (
            activeElement.tagName === "INPUT" ||
            activeElement.tagName === "TEXTAREA" ||
            activeElement.isContentEditable
        );

    if (isTyping) return;

    if (event.key.toLowerCase() === "j") {
        toggleLayerPanel();
    }

    if (event.key.toLowerCase() === "k") {
        const panel = document.getElementById("drawingsPanel");
        if (panel) {
            panel.classList.toggle("open");
            if (panel.classList.contains("open") && typeof refreshDrawingsList === "function") {
                refreshDrawingsList();
            }
        }
    }

    if (event.key === "Escape") {
        closePanel();
        const panel = document.getElementById("drawingsPanel");
        if (panel) panel.classList.remove("open");
    }
});

// --------------------------------------------------
// STATUS
// --------------------------------------------------

function updateStatus(message) {
    mapStatus.textContent = message;
}

// --------------------------------------------------
// LAYER SELECTION
// --------------------------------------------------

function removeActiveOverlay() {
    if (activeOverlay && map.hasLayer(activeOverlay)) {
        map.removeLayer(activeOverlay);
    }

    activeOverlay = null;
}

function selectLayer(layerId) {

    // Remove previous overlay
    removeActiveOverlay();

    // Satellite remains the permanent basemap
    if (layerId === "satellite") {
        layerLabel.textContent = "ESRI SATELLITE";
        updateStatus("Satellite imagery active");
        return;
    }

    const config = availableLayers[layerId];

    if (!config) {
        updateStatus("Unknown or unavailable layer");
        return;
    }

    // Zoom in when required for Sentinel-1
    if (config.minZoom && map.getZoom() < config.minZoom) {
        map.setZoom(config.minZoom);
    }

    // Create selected overlay: plain XYZ tiles for layers with a tileUrl
    // (L-band), otherwise a Sentinel Hub WMS layer.
    if (config.tileUrl) {
        activeOverlay = L.tileLayer(config.tileUrl, {
            attribution: config.attribution,
            opacity: 0.9,
            minZoom: config.minZoom,
            maxNativeZoom: config.maxNativeZoom,
            maxZoom: 18
        });
    } else {
        activeOverlay = L.tileLayer.wms("/api/wms", {
            layers: layerId,
            format: "image/png",
            transparent: true,
            version: "1.1.1",
            attribution: "Copernicus Sentinel Hub",
            opacity: 0.85,
            tiled: true,
            minZoom: config.minZoom || DEFAULT_WMS_MIN_ZOOM
        });
    }

    updateStatus(`Loading ${config.label}...`);
    layerLabel.textContent = config.label;

    activeOverlay.on("load", () => {
        updateStatus(`${config.label} active`);
    });

    activeOverlay.on("tileerror", () => {
        updateStatus(`Error loading ${config.label}. Check layer configuration.`);
    });

    activeOverlay.addTo(map);
}

// --------------------------------------------------
// RADIO OPTION EVENTS
// --------------------------------------------------

layerOptions.forEach((option) => {
    option.addEventListener("change", function () {

        if (!this.checked) return;

        selectLayer(this.value);
        closePanel();

    });
});

// --------------------------------------------------
// SURVEY OF INDIA TOPOSHEET GRID OVERLAY
// --------------------------------------------------

// The grid changes scale with zoom so each cell stays roughly 90-100 px
// wide and its sheet number always fits inside it:
//   zoom <= 6  -> 1:1,000,000 sheets (4° x 4°),  e.g. "78"
//   zoom 7-8   -> 1:250,000 sheets   (1° x 1°),  e.g. "78N"
//   zoom >= 9  -> 1:50,000 sheets    (15' x 15'), e.g. "78N/12" + OSM no.
function toposheetScaleForZoom(zoom) {
    if (zoom <= 6) return "1m";
    if (zoom <= 8) return "250k";
    return "50k";
}

// Own pane: above the imagery tiles, below drawings, never blocks clicks.
map.createPane("toposheetPane");
map.getPane("toposheetPane").style.zIndex = 350;
map.getPane("toposheetPane").style.pointerEvents = "none";

const toposheetToggle = document.getElementById("toposheetToggle");
const toposheetLayer = L.layerGroup();

let toposheetRequest = null;
let toposheetDebounce = null;

function renderToposheets(collection) {
    toposheetLayer.clearLayers();

    collection.features.forEach((feature) => {
        const { sheet, osm, scale } = feature.properties;
        const ring = feature.geometry.coordinates[0];

        const bounds = L.latLngBounds(
            [ring[0][1], ring[0][0]],
            [ring[2][1], ring[2][0]]
        );

        L.rectangle(bounds, {
            pane: "toposheetPane",
            interactive: false,
            color: "#7fd8ff",
            weight: scale === "50k" ? 1 : 1.5,
            opacity: 0.85,
            fill: false
        }).addTo(toposheetLayer);

        const osmLine = osm ? `<span class="sheet-osm">${osm}</span>` : "";

        L.marker(bounds.getCenter(), {
            pane: "toposheetPane",
            interactive: false,
            keyboard: false,
            icon: L.divIcon({
                className: "toposheet-label",
                html: `<span class="sheet-no">${sheet}</span>${osmLine}`,
                iconSize: [90, 30],
                iconAnchor: [45, 15]
            })
        }).addTo(toposheetLayer);
    });
}

function refreshToposheets() {
    if (!map.hasLayer(toposheetLayer)) return;

    if (toposheetRequest) {
        toposheetRequest.abort();
    }

    toposheetRequest = new AbortController();

    const b = map.getBounds();
    const bbox = [b.getWest(), b.getSouth(), b.getEast(), b.getNorth()]
        .map((v) => v.toFixed(4))
        .join(",");
    const scale = toposheetScaleForZoom(map.getZoom());

    fetch(`/api/toposheets?scale=${scale}&bbox=${bbox}`, {
        signal: toposheetRequest.signal
    })
        .then((response) => response.json().then((data) => ({ ok: response.ok, data })))
        .then(({ ok, data }) => {
            if (!ok) {
                updateStatus(data.error || "Could not load the toposheet grid.");
                return;
            }

            renderToposheets(data);

            const scaleLabel = {
                "1m": "1:1,000,000",
                "250k": "1:250,000",
                "50k": "1:50,000"
            }[scale];

            updateStatus(`Toposheet grid · ${scaleLabel} sheets (zoom in for finer sheets)`);
        })
        .catch((error) => {
            if (error.name !== "AbortError") {
                updateStatus("Could not load the toposheet grid.");
            }
        });
}

map.on("moveend", () => {
    clearTimeout(toposheetDebounce);
    toposheetDebounce = setTimeout(refreshToposheets, 150);
});

toposheetToggle.addEventListener("change", function () {
    if (this.checked) {
        toposheetLayer.addTo(map);
        updateStatus("Loading toposheet grid...");
        refreshToposheets();
    } else {
        if (toposheetRequest) toposheetRequest.abort();
        toposheetLayer.clearLayers();
        map.removeLayer(toposheetLayer);
    }
});

// --------------------------------------------------
// STRUCTURE + LINEAMENT OVERLAYS (checkboxes, WMS via /api/overlay)
// --------------------------------------------------

// Panes sit above the imagery (tile pane, z 200) but below the
// toposheet grid (350) and drawings (400+). Overlays are non-interactive.
map.createPane("structurePane");
map.getPane("structurePane").style.zIndex = 320;
map.getPane("structurePane").style.pointerEvents = "none";

map.createPane("lineamentPane");
map.getPane("lineamentPane").style.zIndex = 330;
map.getPane("lineamentPane").style.pointerEvents = "none";

const overlayConfigs = {
    structure: {
        toggleId: "structureToggle",
        pane: "structurePane",
        label: "Structure map (GSI faults & thrusts, 1:2M)",
        minZoom: 4,
        attribution: "Geological Survey of India, hosted by BGS"
    },
    lineament: {
        toggleId: "lineamentToggle",
        pane: "lineamentPane",
        label: "Lineament map (Bhuvan 1:50K; Mizoram not covered)",
        minZoom: 6,
        attribution: "ISRO / NRSC Bhuvan"
    }
};

Object.entries(overlayConfigs).forEach(([name, config]) => {
    const toggle = document.getElementById(config.toggleId);
    let layer = null;

    toggle.addEventListener("change", function () {
        if (!this.checked) {
            if (layer && map.hasLayer(layer)) map.removeLayer(layer);
            updateStatus(`${config.label} hidden`);
            return;
        }

        if (!layer) {
            layer = L.tileLayer.wms(`/api/overlay/${name}`, {
                pane: config.pane,
                format: "image/png",
                transparent: true,
                version: "1.1.1",
                tiled: true,
                minZoom: config.minZoom,
                attribution: config.attribution
            });

            layer.on("load", () => updateStatus(`${config.label} active`));
            layer.on("tileerror", () => updateStatus(`Error loading ${config.label}`));
        }

        // Same idea as the imagery layers: don't leave the user zoomed
        // out where this overlay draws nothing.
        if (map.getZoom() < config.minZoom) {
            map.setZoom(config.minZoom);
        }

        updateStatus(`Loading ${config.label}...`);
        layer.addTo(map);
    });
});

// --------------------------------------------------
// INITIAL STATE
// --------------------------------------------------

selectLayer("satellite");

console.log("NE India Geo Viewer initialized.");
console.log("Configured layers:", Object.keys(availableLayers));

// --------------------------------------------------
// DRAWING TOOLS (POLYGON / LINE) -> SAVED AS KML
// --------------------------------------------------

// Group that holds whatever shape is currently being drawn/edited on
// the map. Loaded drawings also get added here so they can be edited.
const drawnItems = new L.FeatureGroup();
map.addLayer(drawnItems);

// Tracks the KML file id behind each Leaflet layer currently on the map,
// so edits/deletes know which saved file to update.
const layerToFileId = new WeakMap();

const drawControl = new L.Control.Draw({
    draw: {
        polygon: {
            shapeOptions: { color: "#d6a94b", weight: 2, fillOpacity: 0.25 }
        },
        polyline: {
            shapeOptions: { color: "#d6a94b", weight: 3 }
        },
        rectangle: false,
        circle: false,
        circlemarker: false,
        marker: false
    },
    edit: {
        featureGroup: drawnItems,
        remove: true
    }
});

map.addControl(drawControl);

function layerToGeoJSONFeatures(layer) {
    const geojson = layer.toGeoJSON();
    return geojson.type === "FeatureCollection" ? geojson.features : [geojson];
}

// A new shape was drawn: ask for a name and save it as a KML file.
map.on(L.Draw.Event.CREATED, (event) => {
    const layer = event.layer;

    const name = window.prompt("Name this drawing (saved as KML):", "");

    if (name === null) {
        return; // user cancelled - discard the shape
    }

    drawnItems.addLayer(layer);

    const features = layerToGeoJSONFeatures(layer);

    fetch("/api/kml", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: name || "Untitled drawing", features })
    })
        .then((response) => response.json().then((data) => ({ ok: response.ok, data })))
        .then(({ ok, data }) => {
            if (!ok) {
                updateStatus(data.error || "Could not save drawing.");
                return;
            }

            layerToFileId.set(layer, data.id);
            bindDrawingPopup(layer, data.id, data.name);
            updateStatus(`Saved "${data.name}" as KML.`);
            refreshDrawingsList();
        })
        .catch(() => updateStatus("Could not reach the server to save the drawing."));
});

// An existing shape was edited on the map: push the new geometry to disk.
map.on(L.Draw.Event.EDITED, (event) => {
    event.layers.eachLayer((layer) => {
        const fileId = layerToFileId.get(layer);
        if (!fileId) return;

        fetch(`/api/kml/${fileId}`, {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ features: layerToGeoJSONFeatures(layer) })
        })
            .then((response) => response.json())
            .then(() => updateStatus("Drawing updated."))
            .catch(() => updateStatus("Could not save the edited drawing."));
    });
});

// A shape was removed via the draw toolbar's delete tool.
map.on(L.Draw.Event.DELETED, (event) => {
    event.layers.eachLayer((layer) => {
        const fileId = layerToFileId.get(layer);
        if (!fileId) return;

        fetch(`/api/kml/${fileId}`, { method: "DELETE" })
            .then(() => {
                updateStatus("Drawing deleted.");
                refreshDrawingsList();
            })
            .catch(() => updateStatus("Could not delete the drawing on the server."));
    });
});

// Drawing names are user-typed, so never put them into HTML unescaped.
function escapeHtml(text) {
    return String(text)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#39;");
}

function bindDrawingPopup(layer, fileId, name) {
    layer.bindPopup(
        `<strong>${escapeHtml(name)}</strong><br><span class="kml-popup-hint">Use the edit/delete tools to modify.</span>`
    );
}

// --------------------------------------------------
// SAVED DRAWINGS PANEL
// --------------------------------------------------

const drawingsPanelButton = document.getElementById("drawingsMenuButton");
const drawingsPanel = document.getElementById("drawingsPanel");
const closeDrawingsPanel = document.getElementById("closeDrawingsPanel");
const drawingsList = document.getElementById("drawingsList");

function toggleDrawingsPanel() {
    drawingsPanel.classList.toggle("open");
    if (drawingsPanel.classList.contains("open")) {
        refreshDrawingsList();
    }
}

if (drawingsPanelButton) {
    drawingsPanelButton.addEventListener("click", toggleDrawingsPanel);
}

if (closeDrawingsPanel) {
    closeDrawingsPanel.addEventListener("click", () => {
        drawingsPanel.classList.remove("open");
    });
}

function refreshDrawingsList() {
    if (!drawingsList) return;

    fetch("/api/kml")
        .then((response) => response.json())
        .then((items) => renderDrawingsList(items))
        .catch(() => {
            drawingsList.innerHTML = '<div class="drawings-empty">Could not load saved drawings.</div>';
        });
}

function renderDrawingsList(items) {
    drawingsList.innerHTML = "";

    if (!items.length) {
        drawingsList.innerHTML = '<div class="drawings-empty">No saved drawings yet. Draw a polygon or line on the map.</div>';
        return;
    }

    items.forEach((item) => {
        const row = document.createElement("div");
        row.className = "drawing-row";

        row.innerHTML = `
            <span class="drawing-name" title="${escapeHtml(item.name)}">${escapeHtml(item.name)}</span>
            <div class="drawing-actions">
                <button class="drawing-btn" data-action="load" title="Load on map">Load</button>
                <button class="drawing-btn" data-action="rename" title="Rename">Rename</button>
                <a class="drawing-btn" data-action="download" title="Download .kml for Google Earth / QGIS"
                   href="/api/kml/${encodeURIComponent(item.id)}?download=1">KML</a>
                <button class="drawing-btn drawing-btn-danger" data-action="delete" title="Delete">Delete</button>
            </div>
        `;

        row.querySelector('[data-action="load"]').addEventListener("click", () => loadDrawing(item.id));
        row.querySelector('[data-action="rename"]').addEventListener("click", () => renameDrawing(item.id, item.name));
        row.querySelector('[data-action="delete"]').addEventListener("click", () => deleteDrawing(item.id));

        drawingsList.appendChild(row);
    });
}

function loadDrawing(fileId) {
    updateStatus("Loading drawing...");

    fetch(`/api/kml/${fileId}`)
        .then((response) => response.text())
        .then((kmlText) => {
            const parsed = parseKmlToLayers(kmlText);

            parsed.forEach((layer) => {
                layerToFileId.set(layer, fileId);
                drawnItems.addLayer(layer);

                const popupName = layer.feature && layer.feature.properties
                    ? layer.feature.properties.name
                    : fileId;

                bindDrawingPopup(layer, fileId, popupName || fileId);
            });

            if (parsed.length) {
                const group = L.featureGroup(parsed);
                map.fitBounds(group.getBounds(), { maxZoom: 15 });
            }

            updateStatus("Drawing loaded.");
        })
        .catch(() => updateStatus("Could not load the drawing."));
}

function renameDrawing(fileId, currentName) {
    const newName = window.prompt("Rename drawing:", currentName);

    if (!newName || newName.trim() === "" || newName === currentName) {
        return;
    }

    fetch(`/api/kml/${fileId}/rename`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: newName.trim() })
    })
        .then((response) => response.json().then((data) => ({ ok: response.ok, data })))
        .then(({ ok, data }) => {
            if (!ok) {
                updateStatus(data.error || "Could not rename drawing.");
                return;
            }

            updateStatus(`Renamed to "${data.name}".`);
            refreshDrawingsList();
        })
        .catch(() => updateStatus("Could not reach the server to rename the drawing."));
}

function deleteDrawing(fileId) {
    if (!window.confirm("Delete this saved drawing? This cannot be undone.")) {
        return;
    }

    fetch(`/api/kml/${fileId}`, { method: "DELETE" })
        .then((response) => response.json())
        .then(() => {
            drawnItems.eachLayer((layer) => {
                if (layerToFileId.get(layer) === fileId) {
                    drawnItems.removeLayer(layer);
                }
            });

            updateStatus("Drawing deleted.");
            refreshDrawingsList();
        })
        .catch(() => updateStatus("Could not delete the drawing."));
}

// --------------------------------------------------
// MINIMAL KML -> LEAFLET PARSER
// (Point / LineString / MultiLineString / Polygon / MultiPolygon)
// --------------------------------------------------

function parseCoordinateText(text) {
    return text
        .trim()
        .split(/\s+/)
        .filter(Boolean)
        .map((pair) => {
            const [lon, lat] = pair.split(",").map(Number);
            return [lat, lon];
        });
}

function parseKmlToLayers(kmlText) {
    const dom = new DOMParser().parseFromString(kmlText, "text/xml");
    const placemarks = Array.from(dom.getElementsByTagName("Placemark"));
    const layers = [];

    placemarks.forEach((placemark) => {
        const nameEl = placemark.getElementsByTagName("name")[0];
        const name = nameEl ? nameEl.textContent : "Shape";

        const polygons = Array.from(placemark.getElementsByTagName("Polygon"));
        const lines = Array.from(placemark.getElementsByTagName("LineString"));
        const points = Array.from(placemark.getElementsByTagName("Point"));

        polygons.forEach((polygon) => {
            const outerEl = polygon.getElementsByTagName("outerBoundaryIs")[0];
            const outerCoordsEl = outerEl && outerEl.getElementsByTagName("coordinates")[0];

            if (!outerCoordsEl) return;

            const outerLatLngs = parseCoordinateText(outerCoordsEl.textContent);

            const innerLatLngs = Array.from(polygon.getElementsByTagName("innerBoundaryIs"))
                .map((inner) => {
                    const coordsEl = inner.getElementsByTagName("coordinates")[0];
                    return coordsEl ? parseCoordinateText(coordsEl.textContent) : [];
                })
                .filter((ring) => ring.length);

            const latlngs = innerLatLngs.length ? [outerLatLngs, ...innerLatLngs] : outerLatLngs;

            const layer = L.polygon(latlngs, { color: "#d6a94b", weight: 2, fillOpacity: 0.25 });
            layer.feature = { properties: { name } };
            layers.push(layer);
        });

        lines.forEach((line) => {
            const coordsEl = line.getElementsByTagName("coordinates")[0];
            if (!coordsEl) return;

            const latlngs = parseCoordinateText(coordsEl.textContent);
            const layer = L.polyline(latlngs, { color: "#d6a94b", weight: 3 });
            layer.feature = { properties: { name } };
            layers.push(layer);
        });

        points.forEach((point) => {
            const coordsEl = point.getElementsByTagName("coordinates")[0];
            if (!coordsEl) return;

            const [latlng] = parseCoordinateText(coordsEl.textContent);
            if (!latlng) return;

            const layer = L.marker(latlng);
            layer.feature = { properties: { name } };
            layers.push(layer);
        });
    });

    return layers;
}
