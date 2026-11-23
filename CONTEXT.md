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
   Render's **free** plan plus a free **Neon** Postgres (user wants no
   cost). Netlify was ruled out: no long-running server. Render free has
   no persistent disk, so `kml_store.py` stores drawings in Postgres when
   `DATABASE_URL` is set and in `data/kml/*.kml` files otherwise (same
   interface, same KML content). Also added: `render.yaml`, gunicorn
   (1 worker + 4 threads for 512 MB RAM), `/healthz`, env-based
   `DATA_DIR`/`PORT`/`FLASK_DEBUG`, and an optional HTTP Basic login
   (`APP_USERNAME`/`APP_PASSWORD`; off when unset). Also fixed: rename
   now XML-escapes names (names with `&`/`<` used to corrupt the KML),
   and drawing names are HTML-escaped in the panel and popups.
   **Testing gap:** the Postgres store was only run against an in-memory
   SQLite stand-in for `psycopg` (no Postgres server could be started in
   the dev session), so the first real Neon run is the first check of
   the SQL. The file store was tested for real.

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
6. **Multi-layer zoom/loading fix (2026-11-23).** Symptom: radar +
   lineament selected, zoom out → lineament failed; zoom back in →
   lineament never returned and the radar status said loading failed.
   Causes and fixes:
   - Layers vanished silently below their `minZoom`. Now the map's
     `minZoom` follows the highest `minZoom` among the layers that are on
     (`setZoomFloor` in `main.js`); this also covers ticking an overlay
     and `fitBounds` when loading a drawing.
   - A failed overlay tile was returned as a transparent PNG cached for
     1 h, so it stayed blank after Bhuvan recovered. Upstream failures
     are now `502` + `Cache-Control: no-store` (`_tile_error`), and the
     browser retries a failed tile twice (`watchTileLayer`).
   - One shared status line: layers overwrote each other. Each layer now
     owns a part of the status line (`setLayerStatus`).
   - Tiles abandoned on zoom kept server threads busy for up to 60 s.
     Upstream calls now share a pooled `requests.Session` with
     `(5, 25)` s timeouts, and Render runs 8 threads.
   - Lineament `minZoom` 6 → 8 (z6 tiles span a whole state at 1:50K).
   - Also: token refresh is single-flight (lock); an expired L-band
     search id is re-registered once, not once per tile.
   Tested with real Leaflet 1.9.4 / Leaflet.draw 1.0.4 in headless
   Chrome against simulated upstreams (no internet in the test box);
   the Postgres SQL in `kml_store.py` was run against a real
   PostgreSQL 16 server (through psql, not psycopg). Not tested against
   the live Sentinel Hub / Bhuvan / BGS / Planetary Computer services.
7. **Viewport watcher (2026-11-23).** Report: after zooming out and back
   in, parts of the radar layer that had not loaded before stayed empty.
   Tiles that failed (upstream timeout / rate limit) stayed failed until
   the user moved the map. Now `checkViewport()` in `main.js` runs after
   every move and every 8 s: it asks Leaflet to create any missing tile in
   view (`layer._update()`) and re-requests failed ones (one request per
   tile per check, so a rate-limited source isn't hammered). The status
   line shows the share of the view loaded. Uses Leaflet's internal
   `_tiles` / `_update`, fine for the pinned Leaflet 1.9.4; re-check if
   Leaflet is upgraded. Considered and rejected: preloading all of NE India
   before allowing interaction - it only covers one zoom level (each zoom
   level needs its own tiles; NE India at zoom 12 alone is thousands of
   tiles), so it can't make zoomed-in views complete.
   Also: one-off drawing messages now stay visible for 4 s, and status
   parts keep a fixed order.

