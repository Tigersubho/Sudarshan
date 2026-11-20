# Context & working notes

This file tracks background and decisions that aren't obvious from the
code alone — useful for picking the project back up later.

## What this project is

A radar/satellite data viewer for Northeast India (AORVIS). The goal is
a single map where different imagery sources (SAR, spectral, derived
indices) can be toggled, and where the user can draw polygons/lines on
top to mark areas of interest — with those annotations persisted as
standard KML files that can be opened in other GIS tools (Google Earth,
QGIS, etc.), not locked into a database.

## Current architecture

- **Backend**: Flask (`app.py`). Acts as an OAuth-authenticated proxy
  to Copernicus Data Space's Sentinel Hub WMS service, so the
  `SENTINEL_CLIENT_ID`/`SECRET`/`INSTANCE_ID` in `.env` never reach the
  browser. Also exposes a small REST API (`/api/kml/...`) backed by
  plain files in `data/kml/` — one `.kml` file per drawing.
- **Frontend**: Leaflet (basemap + WMS overlays) + Leaflet.draw
  (polygon/line drawing toolbar), vanilla JS, no build step.
- **Storage**: KML files on disk, not a database. `kml_utils.py`
  converts between Leaflet's GeoJSON (`layer.toGeoJSON()`) and KML on
  save, and the frontend has its own minimal KML parser
  (`parseKmlToLayers` in `main.js`) to load shapes back onto the map
  for editing — this avoids pulling in a KML-parsing JS dependency.

## Decisions worth remembering

- **Why files, not a DB**: the user wants drawings they can "open,
  modify, load, or rename" as KML — i.e. portable files, not rows in a
  database. Filenames are derived from the drawing's display name
  (slugified) so the files on disk are human-readable too.
- **Why minimal custom KML parsing instead of a library**: the app
  only ever needs to draw/load points, lines and polygons (what
  Leaflet.draw produces), so a full KML library was unnecessary
  surface area. If more KML features are ever needed (styles,
  folders, time data), consider swapping in `@tmcw/togeojson` or
  `leaflet-omnivore` instead of extending the hand-rolled parser.
- **Legacy files**: `last.py`, `templates/last.html`,
  `static/js/last.js`, `static/css/last.css` are an earlier prototype
  of the same viewer with only the Sentinel-1 layer wired up. They are
  not imported/served by `app.py` and can be deleted once confirmed
  unneeded — kept for now since nobody asked for their removal.

## Known issues / open work

1. **Toposheet grid: DONE (2026-11-20).** Checkbox overlay in the
   layer panel ("OVERLAYS" group) that sits on top of whichever
   imagery layer is selected.
   - Data: the Survey of India 1:50K Open Series sheet index
     (5,113 sheets, India only) from
     `github.com/ramSeraph/india_topo_maps` release `soi-ancillary`,
     file `index_50k.geojson`. `toposheet.py` downloads it on first
     request and caches it in `data/toposheet/` (git-ignored). Each
     sheet has the classic number (`78N/12`) and the new OSM number
     (`G 46H12`). Spot-checked: Guwahati 78N/12, Shillong 78O/14,
     Imphal 83H/13, Delhi 53H/2.
   - 1:250K (1°, e.g. `78N`) and 1:1M (4°, e.g. `78`) sheets are
     derived from the 50K ids and snapped to the 1° / 4° grid.
   - API: `GET /api/toposheets?scale=50k|250k|1m&bbox=w,s,e,n`, capped
     at 2,500 features per response.
   - Frontend picks the scale from zoom (≤6 → 1M, 7–8 → 250K, ≥9 → 50K)
     so labels always fit in their cells; refetches on `moveend`.
   - No cells over Bangladesh, Bhutan or Myanmar. That's expected,
     because the SoI index only covers Indian territory.

2. **L-band, Structure Map and Lineament Map: DONE (2026-11-20).**
   All three use free public sources with no API key, and were checked
   with real tiles over NE India.
   - **Radar Data (L-Band)** is a radio imagery layer
     (`L_BAND_PALSAR`). Source: Microsoft Planetary Computer,
     collection `alos-palsar-mosaic` (JAXA ALOS-2 PALSAR-2 annual 25 m
     mosaics, HH/HV, 2015–2021). Rendered as the HH/HV/HH÷HV
     false-color composite. `GET /api/lband/{z}/{x}/{y}.png?year=2021`
     registers a mosaic search once per year (cached 6 h, re-registered
     if it expires), then proxies the tile. Tiles with no data return a
     transparent PNG rather than an error. The upstream server rejects
     zoom < 8, so `minZoom` is 8. Limitation: these are yearly
     mosaics ending in 2021, not recent scenes. For recent data, NISAR
     (launched July 2025) comes through NASA Earthdata/ASF, which needs a
     free login and per-scene processing, so it would be a separate job.
   - **Structure Map** is a checkbox overlay. Source: GSI faults and
     thrusts at 1:2M, hosted by the British Geological Survey
     (`ogc.bgs.ac.uk/cgi-bin/BGS_GSI_Geology/wms`, layers
     `IND_GSI_2M_Faults`, `IND_GSI_2M_Thrusts`). Regional structures
     only (MBT, Naga thrust), not local mapping. The source draws black
     lines, which vanish on the satellite basemap, so
     `.leaflet-structure-pane` in `style.css` inverts them to white
     with a dark halo.
   - **Lineament Map** is a checkbox overlay. Source: ISRO/NRSC Bhuvan
     WMS (`bhuvan-vec2.nrsc.gov.in/bhuvan/wms`), 1:50K layers
     `lineament:{AS,AR,ML,MN,NL,TR,SK}_LN50K_0506`, requested together.
     **Mizoram has no layer.** The tiles carry a Bhuvan watermark, and
     density varies a lot by state (Meghalaya is very dense, others are
     sparse). That reflects the source data.
   - Both overlays go through `GET /api/overlay/<structure|lineament>`,
     which only accepts those two names and fixes the layer list
     server-side, so the browser can't make the server fetch arbitrary
     layers. Upstream errors become a transparent tile. Tiles are
     cached for an hour.
   - Draw order (Leaflet pane z-index): imagery 200 < structure 320 <
     lineament 330 < toposheet grid 350 < drawings 400+.

3. **Python HTTPS + Avast.** This machine runs Avast Web/Mail Shield,
   which re-signs HTTPS with its own root certificate. Windows trusts
   that root but Python's bundled `certifi` doesn't, so `requests`
   failed with `CERTIFICATE_VERIFY_FAILED` against every host.
   `app.py` now calls `truststore.inject_into_ssl()` (new dependency)
   so Python uses the Windows certificate store. Don't remove it, and
   don't "fix" SSL errors by disabling verification.
3b. **Deployment prep (2026-11-20).** Not deployed yet. Target is
   Render (see README). Netlify was ruled out: no long-running
   server, no persistent disk. Added `render.yaml`, `gunicorn`,
   `/healthz`, env-based `DATA_DIR`/`PORT`/`FLASK_DEBUG`, and an
   optional HTTP Basic login (`APP_USERNAME`/`APP_PASSWORD`; off when
   unset, so local dev is unchanged). The project folder was not a Git
   repo at this point, and Render deploys from one. The KML store is
   plain files, so on Render it needs the paid persistent disk.

4. **Autozoom fix (2026-11-20, revised same day)**: originally only
   `S1_GRD_VV_VH` had a `minZoom`, so other WMS layers would come back
   as Sentinel Hub **error tiles** when zoomed out — not blank, but a
   tile whose pixels literally render the text "Pixel size of X meters
   per pixel exceeds the limit 200.00 meters per pixel for collection
   S2L1C. Please revise the resolution...". Each Sentinel Hub
   collection enforces its own max meters-per-pixel, and that shrinks
   roughly as `156543 * cos(lat) / 2^zoom`, so **different collections
   need different minZoom values, not one shared constant**:
   - `S1_GRD_VV_VH` (S1GRD collection) tolerates coarser pixels →
     zoom 7 is enough (original, confirmed-working value).
   - Every Sentinel-2 (S2L1C) based layer (`B08`, `SWIR`, `B10`,
     `B11`, `B12`, `GEOLOGY`, `MOISTURE_INDEX`, `PSRI_NIR`) caps at
     200 m/pixel, which over Northeast India (~26°N) needs roughly
     zoom 10+. These now use `S2_WMS_MIN_ZOOM = 10` in
     `static/js/main.js`.
   First pass used one `DEFAULT_WMS_MIN_ZOOM = 7` for every layer,
   which fixed S1 but was still too low for the S2 layers — if a
   layer still shows a "Pixel size... exceeds the limit" tile, raise
   that layer's `minZoom` further (check the collection's documented
   resolution cap and solve `156543*cos(lat)/2^z <= cap` for `z`).
5. **Drawing/KML feature added 2026-11-20**: polygon/line drawing,
   KML persistence (save/load/rename/delete/edit) via
   `/api/kml*` endpoints and the DRAWINGS panel (`K` to toggle). Not
   yet covered by automated tests — verified manually via
   `app.test_client()` (create → list → get → rename → delete).
   Possible follow-ups: bulk export/import of KML, undo for deletes,
   and folder/grouping support if the number of saved drawings grows
   large.
