
import base64
import hmac
import os
import threading
import time

# Use the operating system's certificate store for HTTPS. Without this,
# Python only trusts its bundled certifi list, and HTTPS fails on machines
# where antivirus (e.g. Avast Web Shield) or a corporate proxy re-signs
# traffic with a root that only Windows trusts. Must run before requests
# opens any connection.
try:
    import truststore
    truststore.inject_into_ssl()
except ImportError:
    pass  # optional; Python falls back to certifi

import requests

from flask import Flask, render_template, request, Response, jsonify
from dotenv import load_dotenv

from xml.sax.saxutils import escape

from kml_utils import features_to_kml, is_safe_id, slugify
from kml_store import make_store
import toposheet

load_dotenv()

app = Flask(__name__)

# --------------------------------------------------
# OPTIONAL PASSWORD (set APP_PASSWORD in the environment when deployed)
# --------------------------------------------------

# Without this, anyone with the URL could spend the Sentinel Hub quota and
# delete saved drawings. Unset locally = no login prompt.
APP_USERNAME = os.environ.get("APP_USERNAME", "aorvis")
APP_PASSWORD = os.environ.get("APP_PASSWORD")


@app.before_request
def require_password():
    if not APP_PASSWORD or request.path == "/healthz":
        return None

    auth = request.authorization

    if (
        auth
        and hmac.compare_digest(auth.username or "", APP_USERNAME)
        and hmac.compare_digest(auth.password or "", APP_PASSWORD)
    ):
        return None

    return Response(
        "Login required.",
        status=401,
        headers={"WWW-Authenticate": 'Basic realm="AORVIS Radar Viewer"'}
    )


# --------------------------------------------------
# KML DRAWING STORAGE
# --------------------------------------------------

# DATA_DIR lets a host point storage at a persistent disk (e.g. /var/data
# on Render). Locally it defaults to ./data next to this file.
DATA_DIR = os.environ.get("DATA_DIR") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data"
)

# Local files by default; a Postgres table when DATABASE_URL is set (see
# kml_store.py for why).
store = make_store(DATA_DIR)


def _extract_doc_name(xml_text, fallback):
    try:
        import xml.etree.ElementTree as ET

        root = ET.fromstring(xml_text)
        ns = {"kml": "http://www.opengis.net/kml/2.2"}
        name_el = root.find(".//kml:Document/kml:name", ns)

        if name_el is not None and name_el.text:
            return name_el.text.strip()
    except Exception:
        pass

    return fallback

# --------------------------------------------------
# SENTINEL HUB CREDENTIALS
# --------------------------------------------------

CLIENT_ID = os.getenv("SENTINEL_CLIENT_ID")
CLIENT_SECRET = os.getenv("SENTINEL_CLIENT_SECRET")
INSTANCE_ID = os.getenv("SENTINEL_INSTANCE_ID")

TOKEN_URL = (
    "https://identity.dataspace.copernicus.eu/"
    "auth/realms/CDSE/protocol/openid-connect/token"
)

WMS_URL = (
    f"https://sh.dataspace.copernicus.eu/"
    f"ogc/wms/{INSTANCE_ID}"
)

access_token = None
token_expiry = 0


# --------------------------------------------------
# ALLOWED WMS LAYERS
# --------------------------------------------------

ALLOWED_LAYERS = {
    "S1_GRD_VV_VH",
    "B08",
    "SWIR",
    "B10",
    "B11",
    "B12",
    "GEOLOGY",
    "MOISTURE_INDEX",
    "PSRI_NIR"
}


# --------------------------------------------------
# AUTHENTICATION
# --------------------------------------------------

def get_access_token():
    global access_token, token_expiry

    if access_token and time.time() < token_expiry:
        return access_token

    if not CLIENT_ID or not CLIENT_SECRET:
        raise RuntimeError(
            "Missing Sentinel Hub OAuth credentials in .env"
        )

    response = requests.post(
        TOKEN_URL,
        data={
            "grant_type": "client_credentials",
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET
        },
        timeout=30
    )

    response.raise_for_status()

    token_data = response.json()

    access_token = token_data["access_token"]

    token_expiry = (
        time.time() + token_data.get("expires_in", 3600) - 60
    )

    return access_token


# --------------------------------------------------
# HOME PAGE
# --------------------------------------------------

@app.route("/healthz")
def healthz():
    return "ok"


@app.route("/")
def index():
    return render_template("index.html")


# --------------------------------------------------
# SENTINEL HUB WMS PROXY
# --------------------------------------------------

@app.route("/api/wms")
def wms_proxy():

    if not INSTANCE_ID:
        return jsonify({
            "error": "Sentinel Hub Instance ID is missing."
        }), 503

    # Get requested layer
    requested_layer = (
        request.args.get("layers")
        or request.args.get("LAYERS")
    )

    # Validate layer ID
    if requested_layer not in ALLOWED_LAYERS:
        return jsonify({
            "error": "Invalid or unavailable layer ID."
        }), 400

    try:
        token = get_access_token()

        # Only forward the WMS parameters required by Leaflet
        allowed_parameters = {
            "version",
            "styles",
            "format",
            "transparent",
            "width",
            "height",
            "bbox",
            "srs",
            "crs"
        }

        params = {}

        for key, value in request.args.items():
            if key.lower() in allowed_parameters:
                params[key.upper()] = value

        params.update({
            "SERVICE": "WMS",
            "REQUEST": "GetMap",
            "LAYERS": requested_layer
        })

        response = requests.get(
            WMS_URL,
            params=params,
            headers={
                "Authorization": f"Bearer {token}"
            },
            timeout=60
        )

        content_type = response.headers.get(
            "Content-Type",
            "image/png"
        )

        return Response(
            response.content,
            status=response.status_code,
            content_type=content_type
        )

    except requests.RequestException:
        app.logger.exception("Sentinel Hub WMS request failed")

        return jsonify({
            "error": "Could not retrieve Sentinel Hub imagery."
        }), 502

    except Exception:
        app.logger.exception("WMS proxy error")

        return jsonify({
            "error": "Sentinel Hub authentication or configuration error."
        }), 500


# --------------------------------------------------
# WMS CAPABILITIES
# --------------------------------------------------

@app.route("/api/capabilities")
def capabilities():

    if not INSTANCE_ID:
        return jsonify({
            "error": "Sentinel Hub Instance ID is missing."
        }), 503

    try:
        token = get_access_token()

        response = requests.get(
            WMS_URL,
            params={
                "SERVICE": "WMS",
                "REQUEST": "GetCapabilities"
            },
            headers={
                "Authorization": f"Bearer {token}"
            },
            timeout=60
        )

        return Response(
            response.content,
            status=response.status_code,
            content_type=response.headers.get(
                "Content-Type",
                "application/xml"
            )
        )

    except requests.RequestException:
        app.logger.exception(
            "Sentinel Hub capabilities request failed"
        )

        return jsonify({
            "error": "Could not retrieve layer information."
        }), 502

    except Exception:
        app.logger.exception("Capabilities service error")

        return jsonify({
            "error": "Authentication or configuration error."
        }), 500


# --------------------------------------------------
# PUBLIC OVERLAY WMS PROXY (STRUCTURE + LINEAMENT MAPS)
# --------------------------------------------------

# Allow-list: the browser asks for an overlay by short name only, so it
# can never make this server fetch an arbitrary URL or layer.
OVERLAY_SOURCES = {
    # GSI faults + thrusts (1:2M), hosted by the British Geological Survey
    "structure": {
        "url": "https://ogc.bgs.ac.uk/cgi-bin/BGS_GSI_Geology/wms",
        "layers": "IND_GSI_2M_Faults,IND_GSI_2M_Thrusts"
    },
    # ISRO/NRSC Bhuvan 1:50K lineaments for the NE states
    # (Mizoram has no lineament layer on Bhuvan)
    "lineament": {
        "url": "https://bhuvan-vec2.nrsc.gov.in/bhuvan/wms",
        "layers": ",".join(
            f"lineament:{code}_LN50K_0506"
            for code in ("AS", "AR", "ML", "MN", "NL", "TR", "SK")
        )
    }
}

OVERLAY_FORWARD_PARAMS = {
    "version", "format", "transparent", "width", "height",
    "bbox", "srs", "crs"
}

# 1x1 fully transparent PNG, returned for tiles that have no data
TRANSPARENT_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA"
    "60e6kgAAAABJRU5ErkJggg=="
)


def _png_response(content, status=200):
    return Response(
        content,
        status=status,
        content_type="image/png",
        headers={"Cache-Control": "public, max-age=3600"}
    )


@app.route("/api/overlay/<name>")
def overlay_proxy(name):
    source = OVERLAY_SOURCES.get(name)

    if source is None:
        return jsonify({"error": "Unknown overlay."}), 404

    params = {
        key.upper(): value
        for key, value in request.args.items()
        if key.lower() in OVERLAY_FORWARD_PARAMS
    }

    params.update({
        "SERVICE": "WMS",
        "REQUEST": "GetMap",
        "LAYERS": source["layers"],
        "STYLES": ""
    })

    try:
        response = requests.get(source["url"], params=params, timeout=60)

        content_type = response.headers.get("Content-Type", "")

        # WMS servers report errors as XML with HTTP 200. Don't hand that
        # to the browser as if it were a tile.
        if response.status_code != 200 or not content_type.startswith("image/"):
            app.logger.warning(
                "Overlay %s upstream problem: %s %s",
                name, response.status_code, response.text[:200]
            )
            return _png_response(TRANSPARENT_PNG)

        return _png_response(response.content)

    except requests.RequestException:
        app.logger.exception("Overlay %s request failed", name)
        return jsonify({"error": "Could not retrieve overlay."}), 502


# --------------------------------------------------
# L-BAND SAR (ALOS PALSAR-2 ANNUAL MOSAICS)
# --------------------------------------------------

# Microsoft Planetary Computer, collection "alos-palsar-mosaic":
# JAXA ALOS/ALOS-2 PALSAR annual mosaics, 25 m, HH/HV. No API key.
PC_MOSAIC_BASE = "https://planetarycomputer.microsoft.com/api/data/v1/mosaic"
LBAND_COLLECTION = "alos-palsar-mosaic"
LBAND_YEARS = range(2015, 2022)
LBAND_DEFAULT_YEAR = 2021
LBAND_MIN_ZOOM = 8  # the server rejects anything lower

# HH / HV / HH-over-HV false-color composite (Microsoft's own preset)
LBAND_RENDER_PARAMS = [
    ("collection", LBAND_COLLECTION),
    ("expression", "HH;HV;HH/HV"),
    ("rescale", "0,9000"),
    ("rescale", "0,4000"),
    ("rescale", "0,2"),
    ("asset_as_band", "true"),
    ("format", "png")
]

_lband_searches = {}  # year -> (search id, expiry timestamp)
_lband_lock = threading.Lock()
LBAND_SEARCH_TTL = 6 * 3600


def _lband_search_id(year, force_refresh=False):
    """Register (once per year, then cache) a mosaic search for that year."""

    with _lband_lock:
        cached = _lband_searches.get(year)

        if cached and not force_refresh and time.time() < cached[1]:
            return cached[0]

        response = requests.post(
            f"{PC_MOSAIC_BASE}/register",
            json={
                "filter-lang": "cql2-json",
                "filter": {
                    "op": "and",
                    "args": [
                        {"op": "=", "args": [
                            {"property": "collection"}, LBAND_COLLECTION
                        ]},
                        {"op": "anyinteracts", "args": [
                            {"property": "datetime"},
                            {"interval": [
                                f"{year}-01-01", f"{year}-12-31T23:59:59Z"
                            ]}
                        ]}
                    ]
                }
            },
            timeout=30
        )
        response.raise_for_status()

        search_id = response.json()["searchid"]
        _lband_searches[year] = (search_id, time.time() + LBAND_SEARCH_TTL)

        return search_id


@app.route("/api/lband/<int:z>/<int:x>/<int:y>.png")
def lband_tile(z, x, y):
    try:
        year = int(request.args.get("year", LBAND_DEFAULT_YEAR))
    except ValueError:
        return jsonify({"error": "year must be a number."}), 400

    if year not in LBAND_YEARS:
        return jsonify({
            "error": f"year must be {LBAND_YEARS[0]}-{LBAND_YEARS[-1]}."
        }), 400

    if z < LBAND_MIN_ZOOM:
        return _png_response(TRANSPARENT_PNG)

    try:
        for attempt in (0, 1):
            search_id = _lband_search_id(year, force_refresh=bool(attempt))

            response = requests.get(
                f"{PC_MOSAIC_BASE}/{search_id}/tiles/WebMercatorQuad/"
                f"{z}/{x}/{y}@1x",
                params=LBAND_RENDER_PARAMS,
                timeout=60
            )

            # A cached search id can expire server-side; re-register once.
            if response.status_code in (400, 404) and attempt == 0 \
                    and "No assets" not in response.text \
                    and "minimum zoom" not in response.text:
                continue

            break

        if response.status_code == 200:
            return _png_response(response.content)

        # 404 "No assets found for tile" = outside the mosaic's coverage
        if response.status_code == 404:
            return _png_response(TRANSPARENT_PNG)

        app.logger.warning(
            "L-band upstream problem: %s %s",
            response.status_code, response.text[:200]
        )
        return jsonify({"error": "L-band tile unavailable."}), 502

    except requests.RequestException:
        app.logger.exception("L-band tile request failed")
        return jsonify({"error": "Could not retrieve L-band imagery."}), 502


# --------------------------------------------------
# SURVEY OF INDIA TOPOSHEET GRID
# --------------------------------------------------

@app.route("/api/toposheets")
def toposheets():
    """
    Toposheet grid cells intersecting the requested bbox.

    Query params:
        bbox   west,south,east,north (degrees)
        scale  50k | 250k | 1m
    """

    scale = (request.args.get("scale") or "50k").lower()

    if scale not in ("50k", "250k", "1m"):
        return jsonify({"error": "scale must be 50k, 250k or 1m."}), 400

    try:
        bbox = [float(v) for v in (request.args.get("bbox") or "").split(",")]
        if len(bbox) != 4:
            raise ValueError
    except ValueError:
        return jsonify({"error": "bbox must be west,south,east,north."}), 400

    try:
        return jsonify(toposheet.query(scale, bbox))

    except requests.RequestException:
        app.logger.exception("Toposheet index download failed")
        return jsonify({
            "error": "Could not download the toposheet index."
        }), 502


# --------------------------------------------------
# KML DRAWINGS API
# --------------------------------------------------

def _unique_id(base_id, ignore_id=None):
    """base_id, or base_id-2, -3... if that id is already taken."""

    candidate = base_id
    counter = 1

    while candidate != ignore_id and store.exists(candidate):
        counter += 1
        candidate = f"{base_id}-{counter}"

    return candidate


@app.route("/api/kml", methods=["GET"])
def list_kml():
    """List every saved drawing (polygon/line KML documents)."""

    items = [
        {
            "id": file_id,
            "name": _extract_doc_name(content, file_id),
            "modified": modified
        }
        for file_id, content, modified in store.list_all()
    ]

    items.sort(key=lambda item: item["modified"], reverse=True)

    return jsonify(items)


@app.route("/api/kml/<file_id>", methods=["GET"])
def get_kml(file_id):
    """Return the raw KML of one saved drawing (?download=1 saves a file)."""

    if not is_safe_id(file_id):
        return jsonify({"error": "Invalid drawing id."}), 400

    content = store.get(file_id)

    if content is None:
        return jsonify({"error": "Drawing not found."}), 404

    response = Response(content, mimetype="application/vnd.google-earth.kml+xml")

    if request.args.get("download"):
        response.headers["Content-Disposition"] = (
            f'attachment; filename="{file_id}.kml"'
        )

    return response


@app.route("/api/kml", methods=["POST"])
def create_kml():
    """Save a new drawing (features drawn in the browser) as KML."""

    payload = request.get_json(silent=True) or {}

    name = (payload.get("name") or "").strip() or "Untitled drawing"
    features = payload.get("features") or []

    if not isinstance(features, list) or not features:
        return jsonify({"error": "No drawn features were provided."}), 400

    file_id = _unique_id(slugify(name))

    store.put(file_id, features_to_kml(name, features))

    return jsonify({"id": file_id, "name": name}), 201


@app.route("/api/kml/<file_id>", methods=["PUT"])
def update_kml(file_id):
    """Overwrite an existing drawing's geometry (edit/modify)."""

    if not is_safe_id(file_id):
        return jsonify({"error": "Invalid drawing id."}), 400

    existing = store.get(file_id)

    if existing is None:
        return jsonify({"error": "Drawing not found."}), 404

    payload = request.get_json(silent=True) or {}
    features = payload.get("features") or []

    if not isinstance(features, list) or not features:
        return jsonify({"error": "No drawn features were provided."}), 400

    name = (
        payload.get("name") or _extract_doc_name(existing, file_id) or file_id
    ).strip()

    store.put(file_id, features_to_kml(name, features))

    return jsonify({"id": file_id, "name": name})


@app.route("/api/kml/<file_id>/rename", methods=["POST"])
def rename_kml(file_id):
    """Rename a saved drawing (display name + its id)."""

    if not is_safe_id(file_id):
        return jsonify({"error": "Invalid drawing id."}), 400

    content = store.get(file_id)

    if content is None:
        return jsonify({"error": "Drawing not found."}), 404

    payload = request.get_json(silent=True) or {}
    new_name = (payload.get("name") or "").strip()

    if not new_name:
        return jsonify({"error": "A new name is required."}), 400

    # The Document <name> is the first <name> in the file. Both sides are
    # XML-escaped so names like "Block A & B" can't corrupt the KML.
    old_name = _extract_doc_name(content, file_id)

    content = content.replace(
        f"<name>{escape(old_name)}</name>",
        f"<name>{escape(new_name)}</name>",
        1
    )

    new_id = _unique_id(slugify(new_name), ignore_id=file_id)

    store.rename(file_id, new_id, content)

    return jsonify({"id": new_id, "name": new_name})


@app.route("/api/kml/<file_id>", methods=["DELETE"])
def delete_kml(file_id):
    """Delete a saved drawing."""

    if not is_safe_id(file_id):
        return jsonify({"error": "Invalid drawing id."}), 400

    if not store.delete(file_id):
        return jsonify({"error": "Drawing not found."}), 404

    return jsonify({"status": "deleted", "id": file_id})


# --------------------------------------------------
# RUN APPLICATION
# --------------------------------------------------

if __name__ == "__main__":
    # Local development only. In production gunicorn imports `app`
    # (see render.yaml), so none of this runs there.
    app.run(
        host="127.0.0.1",
        port=int(os.environ.get("PORT", 5000)),
        debug=os.environ.get("FLASK_DEBUG", "1") == "1"
    )
