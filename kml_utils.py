"""
Helpers for turning Leaflet-drawn GeoJSON features into KML documents
and back again, plus safe filename handling for the KML store.

Only the geometry types the drawing tools can produce are supported:
Point, LineString and Polygon (and their Multi* equivalents).
"""

import re
import time
from xml.sax.saxutils import escape

KML_EXTENSION = ".kml"

_SLUG_RE = re.compile(r"[^a-z0-9\-]+")


def slugify(name: str) -> str:
    """Turn a display name into a safe filename stem (no extension)."""

    base = (name or "").strip().lower()
    base = base.replace("_", "-")
    base = _SLUG_RE.sub("-", base)
    base = re.sub(r"-+", "-", base).strip("-")

    if not base:
        base = f"drawing-{int(time.time())}"

    return base


def is_safe_id(file_id: str) -> bool:
    """Reject anything that is not a plain slug (no path traversal)."""

    return bool(file_id) and bool(re.fullmatch(r"[a-z0-9\-]+", file_id))


def _coord_to_kml(coord):
    lon, lat = coord[0], coord[1]
    alt = coord[2] if len(coord) > 2 else 0

    return f"{lon},{lat},{alt}"


def _ring_to_kml(coordinates):
    return " ".join(_coord_to_kml(c) for c in coordinates)


def _geometry_to_kml(geometry: dict) -> str:
    gtype = geometry.get("type")
    coords = geometry.get("coordinates")

    if gtype == "Point":
        return f"<Point><coordinates>{_coord_to_kml(coords)}</coordinates></Point>"

    if gtype == "LineString":
        return (
            "<LineString><tessellate>1</tessellate>"
            f"<coordinates>{_ring_to_kml(coords)}</coordinates></LineString>"
        )

    if gtype == "MultiLineString":
        parts = "".join(
            "<LineString><tessellate>1</tessellate>"
            f"<coordinates>{_ring_to_kml(line)}</coordinates></LineString>"
            for line in coords
        )
        return f"<MultiGeometry>{parts}</MultiGeometry>"

    if gtype == "Polygon":
        outer = coords[0] if coords else []
        inner_rings = coords[1:] if len(coords) > 1 else []

        inner_kml = "".join(
            f"<innerBoundaryIs><LinearRing><coordinates>{_ring_to_kml(ring)}"
            "</coordinates></LinearRing></innerBoundaryIs>"
            for ring in inner_rings
        )

        return (
            "<Polygon><outerBoundaryIs><LinearRing>"
            f"<coordinates>{_ring_to_kml(outer)}</coordinates>"
            f"</LinearRing></outerBoundaryIs>{inner_kml}</Polygon>"
        )

    if gtype == "MultiPolygon":
        parts = "".join(
            _geometry_to_kml({"type": "Polygon", "coordinates": poly})
            for poly in coords
        )
        return f"<MultiGeometry>{parts}</MultiGeometry>"

    raise ValueError(f"Unsupported geometry type: {gtype}")


_STYLE_BLOCK = """
    <Style id="polygonStyle">
      <LineStyle><color>ffd6a94b</color><width>2</width></LineStyle>
      <PolyStyle><color>554ba9d6</color></PolyStyle>
    </Style>
    <Style id="lineStyle">
      <LineStyle><color>ffd6a94b</color><width>3</width></LineStyle>
    </Style>
    <Style id="pointStyle">
      <IconStyle><color>ffd6a94b</color><scale>1.0</scale></IconStyle>
    </Style>
"""

_STYLE_FOR_TYPE = {
    "Point": "#pointStyle",
    "LineString": "#lineStyle",
    "MultiLineString": "#lineStyle",
    "Polygon": "#polygonStyle",
    "MultiPolygon": "#polygonStyle",
}


def features_to_kml(name: str, features: list) -> str:
    """Build a KML document string from a list of GeoJSON Feature dicts."""

    placemarks = []

    for index, feature in enumerate(features):
        geometry = feature.get("geometry") or {}
        properties = feature.get("properties") or {}

        placemark_name = escape(str(properties.get("name") or f"Shape {index + 1}"))
        description = escape(str(properties.get("description") or ""))

        style_url = _STYLE_FOR_TYPE.get(geometry.get("type"), "#lineStyle")

        try:
            geometry_kml = _geometry_to_kml(geometry)
        except ValueError:
            continue

        placemarks.append(
            "<Placemark>"
            f"<name>{placemark_name}</name>"
            f"<description>{description}</description>"
            f"<styleUrl>{style_url}</styleUrl>"
            f"{geometry_kml}"
            "</Placemark>"
        )

    document_name = escape(name or "Untitled drawing")

    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<kml xmlns="http://www.opengis.net/kml/2.2">\n'
        "  <Document>\n"
        f"    <name>{document_name}</name>\n"
        f"{_STYLE_BLOCK}"
        f"    {''.join(placemarks)}\n"
        "  </Document>\n"
        "</kml>\n"
    )
