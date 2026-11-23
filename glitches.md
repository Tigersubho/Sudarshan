# Radar Viewer: autozoom and multi-select glitch report

**Scope:** check only. No project file was edited. Checksums of every source file match the uploaded zip.
**Date:** 2026-11-23
**Build checked:** `Radar Viewer` zip (main.js 821 lines, app.py 727 lines)
**Revision 2 (13:10):** full page re-run with real Leaflet 1.9.4 and Leaflet.draw 1.0.4 (your uploaded copies). Results are in section 6. Sections 1, 2 and 4 are updated to match.

---

## 1. The reported bug, explained

> Select radar data and the lineament map, then zoom out. The lineament fails to load. Zoom back in: the lineament does not come back, and the radar says loading failed.

Four separate faults combine to cause this. Each one is listed in section 2.

**What the full-page run with real Leaflet showed (section 6):**
- **"Lineament never comes back" reproduced exactly (A3).** If the lineament tiles fail while loading (Bhuvan overloaded or erroring), they stay blank after Bhuvan recovers and after you zoom out and back in. 24 of 24 tiles were blank, and the status bar said *"Lineament map … active"*.
- **A plain zoom out and back in, with Bhuvan healthy, recovered fine** (A, B). Real Leaflet plus the browser cache restored both layers within about 2 s. So the bug needs an upstream failure at some point. The zoom-out burst is what makes that failure likely.
- **"Radar says loading failed" reproduced (F).** It happens when Sentinel Hub rejects some tiles. The error text shows only while other tiles are still loading. Once they finish, it turns into *"… active"* while the broken tiles stay as holes (4 of 28), and they're never retried.

| Step | What happens | Glitch |
|---|---|---|
| Zoom out to 6 | The radar layer drops below its `minZoom` (S1 = 7, L-band = 8, S2 = 10). Leaflet removes it with no message, and the top bar still names it. The lineament map now requests z6 tiles, each about 5.6° wide, so a 1:50K Bhuvan layer has to be drawn at continental scale. These requests are slow or fail upstream. | G1, G3 |
| Zoom out to 5 | The lineament map also drops below its `minZoom` (6), and Leaflet cancels the z6 tiles in the browser. **The server keeps running each cancelled upstream call for up to 60 s.** | G3 |
| Zoom back in | New radar and lineament tiles wait behind those orphaned calls (heavy case, test T2 below; the full-page scroll-wheel run in section 6 showed a milder +1–4 s). In the Render-like test (4 threads), S1 tiles took **13–17 s instead of 0.3–1.9 s**, and L-band tiles took **20–22 s**. Any tile that errors in that window sets the status to *"Error loading … Check layer configuration."* That message stays until every tile in the layer has finished. | G3, G5, G6 |
| Lineament never returns | When Bhuvan failed, the server sent a **transparent 1×1 PNG with `Cache-Control: max-age=3600`**. The browser reuses that blank tile for an hour, even after Bhuvan recovers. In test T1, 24 of 24 tiles were still blank and 0 were re-fetched. The layer also reports "active", so nothing looks wrong. | G2 |

---

## 2. Glitch list

Severity: **High** = data missing or wrong. **Med** = misleading or slow. **Low** = efficiency or robustness.

### G1 · High · Layers silently disappear below their minZoom, and zooming out is never limited
- **Where:** `main.js` L5 (map `minZoom: 4`), L226–228, L236/L249 (per-layer `minZoom`), L453.
- **What:** Leaflet removes every tile of a layer and requests nothing while the zoom is below that layer's `minZoom`. The app gives no hint ("zoom in to see S1") and does not stop the user zooming out. `layerLabel` and the status line keep showing the layer as active.
- **Matrix:** 30 of the 40 imagery × overlay combinations have a zoom band where some selected layers show and others are silently gone (section 3).
- **Evidence:** traced in the code against how Leaflet 1.9.4's GridLayer handles `minZoom`.

### G2 · High · A failed overlay tile is cached as a blank tile for an hour
- **Where:** `app.py` L395–402 (an upstream error becomes `TRANSPARENT_PNG`) and L361–367 (`Cache-Control: public, max-age=3600` on every response, including that fallback). The same applies to the L-band fallback at L516.
- **What:** When Bhuvan or BGS returns an XML error, the browser gets a 200 transparent PNG and caches it. Zooming back to tiles it has seen before loads them from cache, so the layer "does not come back". Leaflet fires `load`, so the status says *"Lineament map … active"*.
- **Full-page confirmation (A3, real Leaflet):** after Bhuvan failed during the first load and then recovered, zooming 7 → 5 → 7 left **24/24 lineament tiles blank** while the status said *"Lineament map … active"*.
- **Evidence (T1, both server modes):** Bhuvan returned errors, the 24 z7 tiles came back 1 px wide, then Bhuvan recovered. After zooming out and back in, **24/24 tiles were still blank, served from cache in 0–1 ms, and 0 were re-fetched upstream.**

### G3 · High · Cancelled tiles keep running on the server and block the next tiles
- **Where:** `app.py` L238–245 (`/api/wms`, timeout 60), L391 (overlay, timeout 60), L496–501 (L-band, timeout 60). `render.yaml` uses `--workers 1 --threads 4`.
- **What:** The proxy is synchronous. When Leaflet aborts a tile on zoom change (it sets `img.src` to an empty GIF), the server's upstream call keeps going. Big low-zoom lineament tiles take the longest, so they hold the threads the longest.
- **Evidence (T2, Render-like 4 threads, Bhuvan slow at z6):**
  - S1 z7 before zooming out: 0.3–1.9 s.
  - S1 z8 after zooming in: **13.3–17.2 s**.
  - Lineament z8 after zooming in: **19.9–35.3 s**.
  - All 4 threads were busy with Bhuvan calls.
- **Evidence (T3, L-band + lineament):** L-band z9 after zooming in took **20.3–21.8 s** (normally ~0.3–1.3 s). Lineament took 24.8–39.9 s.
- **Local dev server (unbounded threads):** radar was not blocked, but orphaned calls piled up to **12–19 concurrent Bhuvan requests from one user**. That load makes upstream throttling and errors more likely, which then triggers G2 and G6. All layers also share the browser's 6-connection limit for one origin, so lineament z8 still took 4.3–13.3 s.

### G4 · Med · The lineament map's minZoom of 6 is too coarse for its data
- **Where:** `main.js` L431 (`minZoom: 6`).
- **What:** At z6 one 256 px tile covers about 5.6° (≈2.2 km/px over NE India) and asks Bhuvan to draw 1:50K lineaments for 7 states. This is the most likely reason the lineament map "fails" right after zooming out. The S1/L-band minZooms (7/8) are higher than the lineament's, so every zoom-out crosses this band first.
- **Evidence:** traced in the code and checked against tile-scale arithmetic. Bhuvan's real behaviour at z6 could not be tested offline.

### G5 · Med · One shared status line: the last message wins and is often wrong
- **Where:** `main.js` L190 (`updateStatus`), L256–262 (radar), L457–458 (overlays), L378 + L387 (toposheet writes on every `moveend`).
- **What:**
  - Radar, structure, lineament and toposheet all write to the same `#mapStatus`, so one layer's error is overwritten by another's "active", or the other way round.
  - The radar's `tileerror` text says *"Check layer configuration"* even for temporary upstream errors (429, timeout).
  - The error stays until that layer's `load` fires. Under G3 that is 15–35 s.
  - Below `minZoom`, neither `loading` nor `load` fires, so the last "active" message stays on screen while the layer is invisible.
  - With the toposheet grid on, every pan or zoom replaces any radar or overlay error with "Toposheet grid · …".

### G6 · Med · Upstream errors become blank tiles that are never retried
- **Where:** `app.py` L252–256 (`/api/wms` passes the upstream status code straight through), L406–408, L518–526 (502).
- **Evidence (T4, both modes):**
  - Sentinel Hub rejecting 1 request in 7 with 429 gave **3/24 S1 tile errors**.
  - Bhuvan dropping connections gave **24/24 lineament 502s**.
  - Planetary Computer returning 429 gave **24/24 L-band 502s**.
- **Full-page confirmation (F, G, real Leaflet):** 1-in-7 Sentinel Hub 429s left **4 broken S1 tiles of 28**. The status showed *"Error loading … Check layer configuration"* for about 1 s, then switched to *"SENTINEL-1 VV + VH active"*. 8 s later the holes were still there, with no retry. After a pan, 3 more holes appeared under an *"active"* status.
- **What:** Leaflet never retries a failed tile, so holes stay until the user pans or zooms past that tile. Zoom-in/zoom-out bursts are exactly what trigger rate limits.

### G7 · Med · Autozoom only satisfies the layer just toggled, not the whole selection
- **Where:** `main.js` L226–228, L463–465, L693.
- **What:**
  - Ticking the lineament box at zoom 4–5 jumps only to 6. An active S1, L-band or S2 layer stays hidden.
  - Loading a saved drawing calls `fitBounds(…, {maxZoom: 15})` with no lower limit. A large drawing can zoom out past the active imagery's `minZoom` (for example below 10 for any S2 layer) and hide it silently.
  - Zooming with the scroll wheel, the − button or a pinch is never limited to the highest `minZoom` in the active selection.

### G8 · Low · The L-band search registration holds a global lock during a network call
- **Where:** `app.py` L442–474.
- **Evidence (T5):** with a 6 s registration, **all 24 first L-band tiles waited ≥6.3 s.** The same lock is held for the forced re-registration retry, so after the 6 h TTL every L-band tile stalls again.

### G9 · Low · Concurrent token fetches on a cold start
- **Where:** `app.py` L138–169 (no lock around the token refresh).
- **Evidence (T2):** **4–5 token requests** were made for one cold-start burst of S1 tiles.

### G10 · Low · No connection reuse to upstream servers
- **Where:** `app.py` L238, L391, L496 (`requests.get` without a `Session`).
- **What:** every tile opens a new TCP/TLS connection to Sentinel Hub, Bhuvan or Planetary Computer. This adds latency to each tile and makes G3 worse. Found by reading the code.

### G11 · Info · Sentinel Hub error images are not detected
- **Where:** `app.py` L252–256.
- **What:** a "Pixel size … exceeds the limit" response is a 200 image, so it is drawn as a tile of error text and does not count as an error.
- **Current values:** S2 at minZoom 10 gives ≈137 m/px at 26°N, under the 200 m cap. S1 at 7 gives ≈1,097 m/px. The S1GRD cap could not be checked offline, so S1 at zoom 7 is not verified.

---

## 3. Combination matrix (imagery × overlays)

The `minZoom` values were read from `main.js` by script: S1 = 7, S2 layers (B08, SWIR, B10, B11, B12, GEOLOGY, MOISTURE_INDEX, PSRI_NIR) = 10, L-band = 8, structure = 4, lineament = 6. The toposheet grid has no `minZoom`, so it is visible at every zoom and doesn't change any row. That gives 40 combinations, or 80 counting toposheet on and off.

"Hidden" = zooms where at least one selected layer is silently missing. "Partial" = zooms where some selected layers show and others are gone, which is the confusing case.

| Imagery | Overlays | Hidden at zoom | Partial at zoom |
|---|---|---|---|
| S1 (7) | none | 4–6 | — |
| S1 (7) | structure | 4–6 | 4–6 |
| S1 (7) | lineament | 4–6 | 6 |
| S1 (7) | structure + lineament | 4–6 | 4–6 |
| any S2 (10) ×8 | none | 4–9 | — |
| any S2 (10) ×8 | structure | 4–9 | 4–9 |
| any S2 (10) ×8 | lineament | 4–9 | 6–9 |
| any S2 (10) ×8 | structure + lineament | 4–9 | 4–9 |
| L-band (8) | none | 4–7 | — |
| L-band (8) | structure | 4–7 | 4–7 |
| L-band (8) | lineament | 4–7 | 6–7 |
| L-band (8) | structure + lineament | 4–7 | 4–7 |

30 of 40 combinations have a partial band. Every combination that includes the lineament map also has a band where the lineament's heavy low-zoom tiles load while the radar is gone (G3, G4).

---

## 4. UAT scenarios

| # | Scenario | Expected | Actual | Result |
|---|---|---|---|---|
| U1 | S1 + lineament: zoom 7 → 6 → 5 → 7 (the reported case) | Both layers back within a few seconds | **Real Leaflet:** with Bhuvan healthy, both returned in ~2 s (browser cache), but S1 vanished at 6 with *"Lineament … active"* shown (A). If the lineament had failed during loading, it stayed blank after recovery (A3). Radar errors come from upstream rejections (F). | **FAIL** (G1, G2, G5, G6) |
| U2 | L-band + lineament: zoom out, then scroll back in over another area | Both back | **Real Leaflet:** L-band hidden from zoom 7 down while the status said *"L-BAND … active"*. After scrolling back in, lineament took 5 s (dev) or 9 s (Render-like) and showed no loading message. The synthetic stress test (T3) reached 20–40 s. | **FAIL** (G1, G3, G5) |
| U3 | Any S2 layer + structure + lineament, zoom 10 → 8 | Told that S2 needs zoom ≥ 10 | **Real Leaflet (C):** B08 dropped to 0 tiles at zoom 8; the top bar still said *"SENTINEL-2 B08"* and the status said *"Structure map … active"* | **FAIL** (G1, G5) |
| U4 | S1 active, tick lineament at zoom 4 | Zoom jumps to a level where both show | **Real Leaflet (D):** zoom jumped to 6, the lineament loaded, S1 stayed at 0 tiles, and the status said *"Lineament … active"* | **FAIL** (G7) |
| U5 | Any S2 layer active, load a large saved drawing | Imagery stays visible | **Real Leaflet (E):** the map jumped from zoom 10 to 6, B08 dropped to 0 tiles, and the status said *"Drawing loaded."* | **FAIL** (G7) |
| U6 | S1 under Sentinel Hub rate limiting | Failed tiles retried | **Real Leaflet (F):** 4/28 tiles broken. The error message lasted ~1 s, then switched to *"active"*. No retry after 8 s. | **FAIL** (G5, G6) |
| U7 | Any radar + toposheet grid, pan around | Radar status stays visible | **Real Leaflet (G):** whichever layer reports last wins (here S1's *"active"*), and 3 broken S1 tiles after the pan were hidden under it | **FAIL** (G5, G6) |
| U8 | L-band first load | Tiles stream in | Every tile waits for the locked registration (≥6.3 s in test) | **FAIL, minor** (G8) |
| U9 | Switch between imagery layers at zoom ≥ 10 | Old layer removed, new one loads | **Real Leaflet (H):** B08 → S1 → L-band → satellite each loaded 24/24 tiles and the old layer was removed | PASS |
| U10 | Structure map alone, any zoom | Always visible | **Real Leaflet (I):** loaded at every zoom from 4 to 8 | PASS |
| U11 | Toposheet grid alone, zoom 4 → 12 | Scale switches 1M → 250K → 50K | **Real Leaflet (J):** 1:1M at zoom 4–6, 1:250K at 7–8, 1:50K at 9–12 | PASS |
| U12 | Draw a polygon with S1 + lineament on | Saved as KML and listed | **Real Leaflet + Leaflet.draw (K):** drawn, named via the prompt, saved, and shown in the Drawings panel; no page errors | PASS |

---

## 5. How this was tested, and what was not

- **Server and browser tests (T1–T5):** the real, unmodified `app.py` ran under two servers.
  - "dev": the Werkzeug threaded server, as `python app.py` runs it.
  - "Render-like": 4 worker threads, modelling `gunicorn --threads 4`.
  - Simulated stand-ins replaced Sentinel Hub, Bhuvan, BGS and Planetary Computer, so they could be made slow, failing or recovering.
  - Headless Chrome requested tiles exactly the way Leaflet 1.9.4 builds them: the same WMS/XYZ URLs, `<img>` tiles, a 1366×768 view over NE India, and cancellation by setting an empty-GIF `src`.
  - Test scripts and raw JSON results are kept separately (`tests/`), outside the project.
- **Full page (revision 2):** real `index.html`, `main.js` and `style.css` with your Leaflet 1.9.4 and Leaflet.draw 1.0.4 files served in place of unpkg. The tests used the real UI: the Layers/Drawings panels, the zoom buttons, the scroll wheel, map dragging and the polygon tool. They ran in headless Chrome at 1366×768, against both server modes. No JavaScript errors occurred in any scenario. The Esri basemap was replaced with a flat tile, and the Leaflet.draw toolbar icons (`images/spritesheet`) were not supplied, so the buttons have no icons. Neither affects behaviour. The simulated tiles are solid colours, so the screenshots are not useful as pictures. The evidence is the tile counts and status text.
- **Before revision 2, not run:** the full page with real Leaflet and Leaflet.draw. The sandbox has no internet, so the unpkg scripts and the real upstream services were unreachable. Map-side behaviour (G1, G4, G5, G7, U3–U5, U9–U11) was traced in the code against Leaflet 1.9.4's GridLayer and TileLayer.
- **Upstream timings are simulated.** The pattern (blocking, caching, error passthrough) is real app behaviour. The exact seconds depend on how slow Bhuvan, Sentinel Hub and Planetary Computer actually are.

---

## 6. Full-page results (real Leaflet 1.9.4 + Leaflet.draw 1.0.4)

Each row is one scripted UAT run through the real UI, sampled every second. "Tiles" counts the `<img>` tiles in that layer's container that are shown, blank, broken or still loading.

The simulated Bhuvan behaves by tile size:
- z6 tiles (wider than 500 km): 20 s, then an error.
- z7: 4 s.
- z8 and above: 0.6 s.
- More than 8 requests at once: error.

| Run | Server | What was done | Result |
|---|---|---|---|
| A | dev / Render-like | S1 + lineament, zoom buttons 7 → 6 → 5 → 7 | Zoom 6: S1 at 0 tiles, status *"Lineament … active"*, label *"SENTINEL-1"*. Zoom 5: everything at 0 tiles, status still *"Lineament … active"*. Back at 7: both complete in 2.2 s from the browser cache. **Recovery OK; status wrong while zoomed out.** |
| A2 | dev / Render-like | Same, but scroll-wheel out and back in over a different area (new tiles) | Back at 8: S1 complete in ~1 s (dev) or ~3 s (Render-like). Lineament complete in 5.2 s (dev) or 7.0 s (Render-like, first tile at 3 s). During that time the status said *"Lineament … active"* with 28 tiles loading. |
| A3 | dev | Lineament first loads while Bhuvan errors; Bhuvan recovers; zoom 7 → 5 → 7 | **24/24 lineament tiles blank after recovery.** Status *"Lineament map … active"*. 0 tiles re-requested. Reproduces "lineament does not come back". |
| B | dev / Render-like | L-band + lineament, zoom buttons 8 → 7 → 6 → 8 | L-band at 0 tiles from zoom 7 down with no message. Recovered in 2.2 s from cache. |
| B2 | dev / Render-like | L-band + lineament, scroll-wheel out/in over a different area | Lineament complete after 4–5 s (dev) or 7–9 s (Render-like). Status said *"L-BAND … active"* throughout. |
| C | dev | B08 + structure + lineament, zoom 10 → 8 | B08 at 0 tiles. Label *"SENTINEL-2 B08"*. Status *"Structure map … active"*. |
| D | dev | S1 at 7, zoom out to 4, tick lineament | Auto-zoom to 6 only. S1 at 0 tiles. Status *"Lineament … active"*. |
| E | dev | B08 at 10, load a saved drawing covering NE India | `fitBounds` went to zoom 6. B08 at 0 tiles. Status *"Drawing loaded."* |
| F | dev | S1 with Sentinel Hub rejecting 1 in 7 requests (429) | 4/28 tiles broken. Error message for ~1 s, then *"SENTINEL-1 VV + VH active"*. No retry after 8 s. |
| G | dev | S1 + toposheet, then drag the map while S1 is failing | 3 broken tiles. The final status was S1's *"active"*, so the errors were hidden. |
| H | dev | B08 → S1 → L-band → satellite at zoom 10 | Each loaded 24/24; the old layer was removed. PASS |
| I | dev | Structure alone, zoom 4 → 8 | Loads at every zoom. PASS |
| J | dev | Toposheet alone, zoom 4 → 12 | Scale labels switch at 7 and 9 as designed. PASS |
| K | dev | Draw a polygon with S1 + lineament on | Prompt answered, KML saved, listed in the Drawings panel. PASS |

**Also observed with real Leaflet:**
- After a zoom-out, Leaflet keeps the previous zoom's lineament tiles on screen, stretched, while the new ones load. That can look like the layer is "stuck" at the old level.
- A single scroll-wheel notch moves 2 zoom levels (7 → 5). This makes it easy to drop below a radar layer's `minZoom` without noticing.

---

## 7. Fix status (revision 3, 2026-11-23)

All fixes are in the delivered project. They were re-tested with real Leaflet 1.9.4 and Leaflet.draw 1.0.4 in headless Chrome, against the same simulated data sources, on both the dev server and the Render-like 8-thread server.

| Glitch | Fix | Where | Re-test result |
|---|---|---|---|
| G1 layers vanish below minZoom | The map's minimum zoom follows the highest minZoom among the layers that are on (`setZoomFloor`). Zoom-out is greyed out at the floor. A `zoomend` check covers zoom requests Leaflet drops during an animation. | `main.js` | A, B, C, D, A2, B2: no selected layer ever drops to 0 tiles; the zoom stays at the floor. **PASS** |
| G2 failed tile cached blank for 1 h | Upstream failure now returns `502` with `Cache-Control: no-store` (`_tile_error`). Good tiles are still cached for 1 h. | `app.py` | T1: after recovery all 24 tiles are re-fetched and shown (was 0). A3/A4: lineament returns after Bhuvan recovers. **PASS** |
| G3 cancelled tiles block threads | One pooled `requests.Session`; tile timeouts (5 s connect, 25 s read) instead of 60 s; Render runs 8 threads instead of 4. | `app.py`, `render.yaml` | Stress test T2 (Render-like): S1 after zoom-in 3.4–8.8 s (was 13.3–17.2). T3: L-band 11.4–14.2 s (was 20.3–21.8). The UI can no longer produce this pattern, because of G1 and G4. **Reduced** (see residual risks) |
| G4 lineament minZoom too coarse | 6 → 8 | `main.js` | Lineament loads at 8+ in every scenario. **PASS** |
| G5 one shared status line | Each layer owns one part of the status line (`setLayerStatus`): loading / active / retrying / N tiles unavailable. | `main.js` | C: *"SENTINEL-2 B08 … active · Structure map … active · Lineament map … active"*. **PASS** |
| G6 failed tiles never retried | Each failed tile is retried twice (1.5 s, then 3 s) before it counts as unavailable (`watchTileLayer`). | `main.js` | F: 1-in-7 Sentinel Hub 429s now end with 24/24 tiles shown (was 4 holes). G: holes after a pan filled within 7.5 s. A5: a short Bhuvan outage healed by retries. **PASS** |
| G7 autozoom ignores the whole selection / fitBounds | Covered by the zoom floor; Leaflet's `fitBounds` respects `minZoom`. | `main.js` | D: ticking the lineament box at zoom 4 ends at 8 with S1 and lineament both shown. E: loading a large drawing kept zoom 10 with B08 shown. **PASS** |
| G8 L-band registration lock | The lock stays (one registration is correct). An expired search id is now re-registered once, not once per tile. | `app.py` | Unit test `test_expired_search_is_reregistered_once`. **PASS** |
| G9 token fetch race | Single-flight refresh under a lock. | `app.py` | Unit test: 8 concurrent calls → 1 token request. **PASS** |
| G10 no connection reuse | Shared `requests.Session` (pool of 16). | `app.py` | Code change; covered by every server test. **PASS** |
| G11 SH error images | No code change. The zoom floor keeps every layer at or above its minZoom, which is what avoids these images. An `EXCEPTIONS` parameter was not added because it couldn't be verified offline against Copernicus. | — | **Mitigated** |

**Other checks:**
- **Unit tests:** `tests/test_app.py`, 7 tests, stdlib `unittest`, no network needed. 7/7 pass.
- **Neon / Postgres:** `kml_store.py` ran against a real PostgreSQL 16 server (put, upsert with quotes, list, rename, delete, idempotent CREATE TABLE): 8/8 pass. No database code change was needed. psycopg itself could not be installed offline.
- **Secrets:** no `.env` value appears in any delivered file. `.env` and `venv/` are not in the package.
- **Unchanged scenarios:** H (switching imagery), I (structure), J (toposheet scales) and K (drawing + saving) still **PASS**.

**Residual risks:**
- Not tested against the live Sentinel Hub, Bhuvan, BGS or Planetary Computer services.
- If Bhuvan is still slow or empty at zoom 8, raise the lineament `minZoom` in `main.js`.
- A WSGI server can't cancel an upstream call when the browser abandons a tile. Shorter timeouts, more threads and the zoom floor reduce the effect but don't remove it.

---

## 8. Re-test of the delivered build (revision 4, 2026-11-23 14:20–14:33)

**What was tested:** a fresh unzip of `Radar_Viewer_fixed.zip` with:
- the full-page UAT (real Leaflet 1.9.4 + Leaflet.draw 1.0.4, headless Chrome): 20 scenarios on the dev server, 6 on the Render-like 8-thread server;
- the server stress tests T1–T5;
- the 7 unit tests;
- the Postgres storage check (8 checks on PostgreSQL 16).

Four new edge-case scenarios were added: L (zoom limit releases when layers are switched off), M (rapid clicking), N (rename and delete in the Drawings panel, with a name containing `& <b>`), O (keyboard shortcuts J/K/Esc).

**Result:** no JavaScript errors in any run. Every original glitch scenario passes. The fixed bugs G1–G10 did not come back.

### Still unresolved

| # | Severity | Issue | Evidence |
|---|---|---|---|
| R1 | Low (UX) | **Drawing messages flash and vanish.** "Drawing loaded.", "Drawing deleted." and "Saved … as KML." are replaced by layer status within 0–0.2 s, so the user barely sees them. An error such as "Could not save drawing" would vanish the same way. | N: "Drawing loaded." at 4.3 s was replaced at 4.5 s; "Drawing deleted." was replaced at the same instant (6.4 s). |
| R2 | Low (UX) | **Status order changes.** After switching imagery, the imagery part moves to the end of the status line instead of staying first. | M: *"Structure map … active · Lineament map … active · SENTINEL-2 B08 … active"*. |
| R3 | Low | **No automatic recovery after retries run out.** If a source is down for longer than the ~4.5 s retry window, its tiles stay "unavailable" until the user pans, zooms or re-ticks the layer. They then load correctly. | A4: 24 tiles unavailable until the lineament box was re-ticked; A3: recovered on zoom-in. |
| R4 | Medium (deploy) | **A slow source can still delay other layers on Render.** Abandoned tile requests keep server threads busy until their upstream call returns (up to 25 s). In the stress test, S1 took up to 5.8 s and L-band 14.4–16.7 s, against ~1.4 s normally. The UI no longer creates the worst case (zoom-6 lineament tiles), but a genuinely slow Bhuvan at zoom 8+ could. | T2/T3 on the Render-like server. On the dev server: no delay. |
| R5 | Info | **Not verifiable offline:** the live Sentinel Hub, Bhuvan, BGS and Planetary Computer services; whether Bhuvan renders well at zoom 8; Sentinel Hub's S1 resolution cap at zoom 7; the psycopg driver against real Neon; real gunicorn (modelled, not installed). G11 (Sentinel Hub error images) is mitigated by the zoom limit, not fixed. | No internet in the test sandbox. |

### Passed
- **Zoom limit (A, B, C, D, A2, B2, L, M):** layers never vanish; the limit rises and falls with the selection; zoom-out is disabled at the limit.
- **Failure recovery (A3, A4, A5, F, G, T1):** retries fill tiles; failures are no longer cached.
- **Drawings (E, K, N):** loading keeps the zoom limit; draw, save, rename (HTML escaped) and delete all work.
- **Imagery switching, structure map, toposheet scales, keyboard shortcuts (H, I, J, O).**
- **Unit tests:** 7/7. **Postgres:** 8/8. **Secrets:** none in the package.

---

## 9. Viewport watcher (revision 5, 2026-11-23 15:00)

**User report:** choose radar data and it loads; zoom out and back in, and the parts that hadn't loaded before stay empty.

**Cause:** a tile that failed (upstream timeout or rate limit) and used up its 2 quick retries stayed failed until the user panned or zoomed to a new spot. Reproduced in P3: during a Sentinel Hub outage longer than the retry window, the view stayed empty even after the source came back.

**Fix: option A, the viewport watcher (`checkViewport` in `main.js`).** After every pan/zoom, and every 8 s, it:
- checks each tile of each layer in the current view;
- asks Leaflet to create any tile it skipped;
- re-requests the failed ones, one request per tile per check, so a rate-limited source isn't hammered.

The status line shows how much of the view has loaded ("loading 66% of view…", "95% of view loaded, re-checking 1 missing tile…").

**Option B (preload all of NE India before allowing interaction) was not built.** Each zoom level needs its own tiles, so a preload covers only one zoom level. NE India at zoom 12 alone is thousands of tiles. It couldn't make zoomed-in views complete, and it would block the map for minutes.

**R1–R3 from section 8, also fixed:**
- Drawing messages now stay visible for 4 s.
- Status parts keep a fixed order (imagery, structure, lineament, toposheet).
- R3 is covered by the watcher.

**Re-test:**
- dev server: 23 scenarios; Render-like server: 8. All pass, with no page errors.
- P3 (outage, map left untouched): the whole view filled within 4 s of the source recovering. Before the fix it stayed empty.
- Unit tests 7/7; T1 failed tiles re-fetched 24/24.

**Still open:**
- **R4:** a slow source can still delay other layers on Render. In the stress test on the Render-like server, L-band took up to 14.2 s.
- **R5:** the live services can't be verified offline.
- The watcher uses Leaflet's internal `_tiles` and `_update`. That's fine for the pinned Leaflet 1.9.4; re-check if Leaflet is upgraded.
