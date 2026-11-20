# AORVIS Radar Viewer

A Flask + Leaflet web app for viewing Sentinel satellite imagery over
Northeast India, and drawing/managing map annotations (polygons and
lines) that are saved to disk as KML files.

## Features

- Satellite basemap (Esri World Imagery).
- Sentinel-1 (C-band SAR) and Sentinel-2 spectral/derived layers,
  proxied through a Flask backend to Copernicus Data Space Sentinel Hub
  (so API credentials never reach the browser).
- Draw polygons and lines directly on the map (Leaflet.draw toolbar).
- Drawings are saved, loaded, renamed, edited and deleted as `.kml`
  files on the server (`data/kml/`) — no database required.
- Auto-zoom: selecting any WMS layer automatically zooms the map in
  to the minimum zoom that layer needs, so imagery doesn't come back
  blank when you're zoomed far out.
- L-band SAR (ALOS PALSAR-2), plus Structure Map (GSI faults/thrusts)
  and Lineament Map (Bhuvan) overlays, all from free public sources.
- Survey of India toposheet grid overlay showing real sheet numbers
  (e.g. `78N/12` plus the new OSM number `G 46H12`). It switches
  between 1:1M, 1:250K and 1:50K sheets as you zoom.

## Setup

```bash
python -m venv venv
venv\Scripts\activate          # Windows
pip install -r requirements.txt
```

Create a `.env` file in the project root:

```
SENTINEL_CLIENT_ID=your_client_id
SENTINEL_CLIENT_SECRET=your_client_secret
SENTINEL_INSTANCE_ID=your_sentinel_hub_instance_id
```

Run the app:

```bash
python app.py
```

Then open http://127.0.0.1:5000/.

The first time you turn on the toposheet grid, the server downloads the
sheet index (~1 MB) from GitHub and caches it in `data/toposheet/`.
After that it works offline.

## Deploying for free (Render + Neon)

Netlify won't work for this app: it hosts static sites and short
serverless functions, not a long-running Flask server. Render runs it
as-is. Everything below is free and needs no credit card.

Render's free plan wipes its disk on every redeploy and whenever the app
sleeps, so saved drawings are kept in a free **Neon** Postgres database
instead. (Locally, drawings are still plain `.kml` files in `data/kml/`.
Either way they're real KML, and the **Download** button in the DRAWINGS panel (or in a drawing's popup)
downloads one for Google Earth or QGIS.)

1. **Neon** (https://neon.com): sign up, create a project, and copy the
   connection string (starts with `postgresql://`). The app creates its
   own table on first use.
2. **GitHub**: push this folder to a private repo. `.env`, `venv/` and
   saved drawings are git-ignored, so no secrets are uploaded.
3. **Render** (https://render.com): **New → Blueprint**, pick the repo.
   It reads [render.yaml](render.yaml) and asks for these values:
   `SENTINEL_CLIENT_ID`, `SENTINEL_CLIENT_SECRET`, `SENTINEL_INSTANCE_ID`
   (from your local `.env`), `APP_PASSWORD` (anything you choose, shared
   with your office) and `DATABASE_URL` (the Neon string).
4. Open the Render URL. Login: username `aorvis` (or `APP_USERNAME`) and
   your `APP_PASSWORD`.

Things to know:

- **Cold starts.** The free plan sleeps after ~15 minutes idle, and the
  first visit afterwards takes about a minute. Neon also pauses when idle
  and wakes in a second or two.
- **Set `APP_PASSWORD`.** Without it anyone with the URL can use your
  Sentinel Hub quota and delete drawings.
- Free tier limits: 750 instance hours/month on Render, 0.5 GB storage on
  Neon. Both are far more than this app needs.
- To run the production server locally (Linux/macOS/WSL):
  `gunicorn app:app --bind 0.0.0.0:8000`.

## Project layout

```
app.py                 Flask app: pages, WMS proxy, KML drawings API,
                        toposheet grid API
kml_utils.py            GeoJSON <-> KML helpers, safe filename handling
kml_store.py            Where drawings live: local files, or Postgres if DATABASE_URL is set
toposheet.py            SoI toposheet index: download, cache, bbox query
templates/index.html    Main viewer page
static/js/main.js       Map, layer switching, drawing tools, KML panel
static/css/style.css    Styling
data/kml/                Saved drawings, one .kml file per drawing
data/toposheet/          Auto-downloaded toposheet index (git-ignored)
last.py, last.html,
static/*/last.*          Earlier prototype of the viewer (not served
                          by app.py); kept for reference, safe to remove
```

## Map layers

| Layer | Source | Notes |
|---|---|---|
| Esri Satellite | Esri World Imagery | Permanent basemap |
| S1_GRD_VV_VH | Sentinel-1 GRD, C-band SAR | VV+VH composite |
| B08, B10, B11, B12 | Sentinel-2 bands | NIR / Cirrus / SWIR |
| SWIR | Sentinel-2 derived | Shortwave infrared composite |
| GEOLOGY | Sentinel-2 derived | Geological visualization |
| MOISTURE_INDEX | Sentinel-2 derived | Hydrology |
| PSRI_NIR | Sentinel-2 derived | Vegetation (plant senescence) |
| Toposheet Grid (overlay) | Survey of India 1:50K sheet index | Checkbox; shows on top of any layer |
| L_BAND_PALSAR | ALOS PALSAR-2 annual mosaic (JAXA) via Microsoft Planetary Computer | 25 m, HH/HV false color, year 2021, zoom ≥ 8 |
| Structure Map (overlay) | GSI faults & thrusts 1:2M, hosted by BGS | Checkbox; regional scale |
| Lineament Map (overlay) | ISRO/NRSC Bhuvan 1:50K | Checkbox; Assam, Arunachal, Meghalaya, Manipur, Nagaland, Tripura, Sikkim (no Mizoram) |

Each Sentinel Hub collection has its own resolution limit, so each
layer has its own minimum zoom (`availableLayers` in
`static/js/main.js`): Sentinel-1 needs zoom 7 and Sentinel-2 layers
need zoom 10. Selecting a layer while zoomed out further than its
minimum automatically zooms the map in.

### Other API routes

| Path | Purpose |
|---|---|
| `GET /api/lband/{z}/{x}/{y}.png?year=2015..2021` | L-band tiles (proxied from Planetary Computer) |
| `GET /api/overlay/structure` and `/api/overlay/lineament` | WMS proxies for the two checkbox overlays |

### Toposheet grid API

`GET /api/toposheets?scale=50k|250k|1m&bbox=west,south,east,north`
returns a GeoJSON FeatureCollection of sheet cells. Each feature has
`sheet` (e.g. `78N/12`), `osm` (e.g. `G 46H12`, 1:50K only) and
`scale` properties.

## Drawing & KML workflow

1. Use the polygon/line tools in the Leaflet.draw toolbar (top-left of
   the map) to draw a shape.
2. You'll be prompted for a name; the shape is POSTed to
   `/api/kml` and saved as `data/kml/<slug>.kml`.
3. Open the **DRAWINGS** panel (button in the top bar, or press `K`) to
   see every saved drawing, with **Load**, **Rename** and **Delete**
   actions.
4. **Load** fetches the KML, parses it in the browser, and adds it back
   to the map as an editable layer — use the toolbar's edit tool to
   modify it; edits are PUT back to the server automatically.
5. **Rename** changes both the display name (`<name>` inside the KML)
   and the underlying filename.
6. **Delete** removes the shape from the map and deletes the `.kml`
   file.

### KML drawings API

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/kml` | List saved drawings |
| GET | `/api/kml/<id>` | Raw KML content of one drawing |
| POST | `/api/kml` | Save a new drawing (`{name, features}` GeoJSON) |
| PUT | `/api/kml/<id>` | Overwrite a drawing's geometry |
| POST | `/api/kml/<id>/rename` | Rename a drawing |
| DELETE | `/api/kml/<id>` | Delete a drawing |

See `CONTEXT.md` for background, decisions, and open work.
