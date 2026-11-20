"""
Survey of India toposheet grid index.

Source: the 1:50,000 Open Series Map sheet index published by ramSeraph
(https://github.com/ramSeraph/india_topo_maps), derived from Survey of
India's OSM_SHEET_INDEX. It is downloaded automatically on first use and
cached under data/toposheet/, so no manual setup is needed.

Each 1:50K feature carries:
    id          classic SoI sheet number, e.g. "78N_12"  (shown as 78N/12)
    OSM_SHEET_  new Open Series Map number, e.g. "G 46H12"

The coarser grids are derived from the 1:50K ids:
    1:250,000   1° x 1° sheets, e.g. "78N"
    1:1,000,000 4° x 4° sheets, e.g. "78"
"""

import json
import math
import os
import re
import threading

import requests

INDEX_URL = (
    "https://github.com/ramSeraph/india_topo_maps/releases/download/"
    "soi-ancillary/index_50k.geojson"
)

CACHE_DIR = os.path.join(
    os.environ.get("DATA_DIR")
    or os.path.join(os.path.dirname(os.path.abspath(__file__)), "data"),
    "toposheet"
)
CACHE_FILE = os.path.join(CACHE_DIR, "index_50k.geojson")

MAX_FEATURES = 2500

_lock = threading.Lock()
_sheets = None  # {"50k": [...], "250k": [...], "1m": [...]}


def _download_index():
    os.makedirs(CACHE_DIR, exist_ok=True)

    response = requests.get(INDEX_URL, timeout=120)
    response.raise_for_status()

    data = response.json()

    if not data.get("features"):
        raise RuntimeError("Downloaded toposheet index has no features.")

    tmp_path = CACHE_FILE + ".tmp"

    with open(tmp_path, "w", encoding="utf-8") as handle:
        json.dump(data, handle)

    os.replace(tmp_path, CACHE_FILE)

    return data


def _bbox_of(ring):
    xs = [c[0] for c in ring]
    ys = [c[1] for c in ring]
    return [min(xs), min(ys), max(xs), max(ys)]


def _snap(bbox, step):
    """Snap a bbox to the enclosing grid cell of size `step` degrees."""

    west = math.floor(round(bbox[0], 6) / step) * step
    south = math.floor(round(bbox[1], 6) / step) * step
    return [west, south, west + step, south + step]


def _build(data):
    sheets_50k = []
    groups_250k = {}

    for feature in data["features"]:
        props = feature.get("properties") or {}
        raw_id = str(props.get("id") or "")
        geometry = feature.get("geometry") or {}

        if geometry.get("type") != "Polygon" or "_" not in raw_id:
            continue

        bbox = _bbox_of(geometry["coordinates"][0])
        prefix, number = raw_id.split("_", 1)

        sheets_50k.append({
            "sheet": f"{prefix}/{number}",
            "osm": (props.get("OSM_SHEET_") or "").strip(),
            "bbox": bbox
        })

        groups_250k.setdefault(prefix, []).append(bbox)

    sheets_250k = []
    groups_1m = {}

    for prefix, boxes in groups_250k.items():
        union = [
            min(b[0] for b in boxes), min(b[1] for b in boxes),
            max(b[2] for b in boxes), max(b[3] for b in boxes)
        ]
        bbox = _snap(union, 1.0)

        sheets_250k.append({"sheet": prefix, "osm": "", "bbox": bbox})

        match = re.match(r"^(\d+)", prefix)
        if match:
            groups_1m.setdefault(match.group(1), []).append(bbox)

    sheets_1m = []

    for number, boxes in groups_1m.items():
        union = [
            min(b[0] for b in boxes), min(b[1] for b in boxes),
            max(b[2] for b in boxes), max(b[3] for b in boxes)
        ]
        sheets_1m.append({"sheet": number, "osm": "", "bbox": _snap(union, 4.0)})

    return {"50k": sheets_50k, "250k": sheets_250k, "1m": sheets_1m}


def load_sheets():
    """Load (downloading on first use) and cache the sheet index in memory."""

    global _sheets

    if _sheets is not None:
        return _sheets

    with _lock:
        if _sheets is not None:
            return _sheets

        if os.path.isfile(CACHE_FILE):
            with open(CACHE_FILE, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        else:
            data = _download_index()

        _sheets = _build(data)

    return _sheets


def _to_feature(sheet, scale):
    w, s, e, n = sheet["bbox"]

    return {
        "type": "Feature",
        "properties": {
            "sheet": sheet["sheet"],
            "osm": sheet["osm"],
            "scale": scale
        },
        "geometry": {
            "type": "Polygon",
            "coordinates": [[[w, s], [e, s], [e, n], [w, n], [w, s]]]
        }
    }


def query(scale, bbox):
    """Return a GeoJSON FeatureCollection of sheets intersecting bbox."""

    sheets = load_sheets()[scale]
    west, south, east, north = bbox

    features = []

    for sheet in sheets:
        w, s, e, n = sheet["bbox"]

        if e < west or w > east or n < south or s > north:
            continue

        features.append(_to_feature(sheet, scale))

        if len(features) >= MAX_FEATURES:
            break

    return {"type": "FeatureCollection", "features": features}
