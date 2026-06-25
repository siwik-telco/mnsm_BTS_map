# MNSM — Mobile Network Station Map

**MNSM** (Mapa Nadajników Sieci Mobilnej) is a desktop application for visualizing Polish mobile network base stations (BTS) within a user-defined radius around any given address. Beyond basic station plotting, MNSM uniquely retrieves and renders antenna azimuth data — a capability absent from most publicly available BTS mapping tools — giving engineers, researchers, and RF professionals a precise view of sector coverage directions.

---

## Features

- **Address-based geolocation** via the [OpenCage Geocoding API](https://opencagedata.com/) — resolves a free-text address to WGS84 coordinates and automatically determines the Polish voivodeship
- **Radius-filtered BTS search** (1–10 km) using geodesic distance calculation against a local CSV database sourced from [BTSearch](https://btsearch.pl/)
- **Interactive Folium map** rendered inside a `QWebEngineView` widget with operator-color-coded SVG icons and per-station popups showing frequency bands and radio technologies (2G/3G/4G/5G)
- **Antenna azimuth visualization** — directional lines drawn on the map for each sector, derived from official measurement PDF reports published by [SI2PEM](https://si2pem.gov.pl/) (the Polish national EM field monitoring system)
- **Automated PDF pipeline** — fetches station metadata from the SI2PEM REST API, queries a WFS GeoServer across six measurement feature types, downloads all associated PDF reports in parallel (up to 5 concurrent threads), extracts azimuth values using `pdfplumber`, and exports the results to per-station CSV files
- **Non-blocking UI** — all network I/O and data processing runs in dedicated `QThread` workers with `pyqtSignal` progress reporting to the main thread

---

## Architecture

```
mnsm/
├── main.py                  # Entry point — bootstraps QApplication
├── config.ini               # Runtime configuration (paths, PDF page number)
├── mnsm/
│   ├── config.py            # Config loader, operator color map, voivodeship mapping, azimuth header list
│   ├── ui/
│   │   └── main_window.py   # MainWindow (QMainWindow) — UI layout and worker orchestration
│   ├── workers/
│   │   ├── data_worker.py   # DataWorker (QThread) — CSV loading and geodesic filtering
│   │   └── pdf_worker.py    # PdfWorker (QThread) — SI2PEM API, WFS queries, PDF download & parsing
│   └── utils/
│       ├── geo.py           # OpenCage geocoding wrapper
│       ├── map_utils.py     # Folium map builder, SVG icon factory, azimuth line renderer
│       └── pdf_utils.py     # pdfplumber-based azimuth extraction, CSV exporter
```

### Data Flow

```
User Input (address, API key, radius)
        │
        ▼
   geo.py — OpenCage API → (lat, lon, voivodeship)
        │
        ▼
   DataWorker — reads output.csv (BTSearch DB)
              — filters by voivodeship ID
              — filters by geodesic distance ≤ radius
        │
        ▼
   map_utils.build_map() — Folium map with BTS markers + popup details
        │
        ▼  [optional — "Pobierz dane azymutów anten"]
   PdfWorker — SI2PEM REST API → station bounding box
             — WFS GetFeature (6 feature types) → PDF URLs
             — ThreadPoolExecutor (max_workers=5) → download PDFs
             — pdf_utils.extract_information_from_pdf() → azimuths
             — export_to_csv() → antenna_data_{StationId}.csv
        │
        ▼
   map_utils.build_map() (re-run) — loads per-station CSV
                                   — draws azimuth direction lines on map
```

---

## Module Reference

### `config.py`
Reads `config.ini` via `configparser`. Exposes:

| Constant | Type | Description |
|---|---|---|
| `DATABASE_PATH` | `str` | Path to the BTSearch CSV database (default: `output.csv`) |
| `PDF_DIR` | `str` | Directory for downloaded PDFs (default: `pdfs/`) |
| `EXTRACTED_TEXT_DIR` | `str` | Directory for debug text dumps from PDFs (default: `extracted_texts/`) |
| `PDF_PAGE_NR` | `int` | PDF page number to extract azimuth tables from (default: `3`) |
| `WOJEWODZTW_MAP` | `dict` | Maps English OpenCage voivodeship names to Polish `wojewodztwo_id` values used in the BTSearch CSV |
| `OPERATOR_COLORS_DISPLAY` | `dict` | Maps operator names (T-Mobile, Orange, Play, Plus) to display colors |
| `AZIMUTH_HEADERS` | `list` | Accepted column header names for azimuth detection in PDF tables |

### `workers/data_worker.py` — `DataWorker(QThread)`
Loads the BTSearch CSV database using `pandas.read_csv()` with explicit column selection (`siec_id`, `LONGuke`, `LATIuke`, `StationId`, `wojewodztwo_id`, `pasmo`, `standard`) and UTF-8-BOM encoding. Filters rows by voivodeship ID using the `WOJEWODZTW_MAP` lookup, then computes geodesic distance for each station via `geopy.distance.geodesic` and retains only those within the specified radius. Emits a `result(pd.DataFrame)` signal on completion and a `progress(int)` signal in 10% steps.

### `workers/pdf_worker.py` — `PdfWorker(QThread)`
Processes a list of `StationId` values sequentially. For each station:
1. Queries `https://si2pem.gov.pl/api/public/base_station?search={id}` to retrieve the station's bounding box (`boundingbox` field, EPSG:4326).
2. Constructs WFS 1.0.0 `GetFeature` requests against `https://si2pem.gov.pl/geoserver/public/wfs` for six feature types: `measures_all`, `measures_7`, `measures_7_14`, `measures_14_21`, `measures_21_28`, `measures_28`.
3. Collects unique PDF URLs from the GeoJSON `features[].properties.url` field.
4. Downloads all PDFs concurrently using `concurrent.futures.ThreadPoolExecutor` (up to 5 workers).
5. Delegates parsing to `pdf_utils.extract_information_from_pdf()` and exports results to `antenna_data_{StationId}.csv`.

### `utils/geo.py`
Wraps the OpenCage REST API (`https://api.opencagedata.com/geocode/v1/json`) with a 10-second timeout. Returns a `(lat, lon)` tuple and the `state` component from the first geocoding result.

### `utils/map_utils.py`
- **`create_svg_icon(operators, operator_colors, size)`** — generates a Folium `DivIcon` with an inline SVG circle. Single-operator stations get a solid-fill circle; multi-operator co-sites get a pie-chart split.
- **`load_azimuth_data(station_id)`** — reads `antenna_data_{StationId}.csv` and returns a list of float azimuth values (0–360°).
- **`build_map(user_location, filtered_df, radius_km)`** — constructs a `folium.Map` (CartoDB Positron tiles), places a reference marker at the user's address, iterates over grouped `(lat, lon)` positions, adds SVG-icon markers with HTML popups (operator, frequency band, technology), and draws azimuth lines using trigonometric projection: `Δlat = length·cos(θ)`, `Δlon = length·sin(θ)` where `θ` is the azimuth in radians and `length = 0.01·(radius_km / 2)` degrees.

### `utils/pdf_utils.py`
- **`extract_information_from_pdf(pdf_path, expected_station_id)`** — opens the PDF with `pdfplumber`, navigates to page `PDF_PAGE_NR`, validates that the expected `StationId` appears in the extracted text, locates the first table, resolves azimuth column indices by matching headers against `AZIMUTH_HEADERS` (using `re.search` with word boundaries), extracts integer degree values via regex `(\d{1,3})\s*°`, and returns a dict `{'Station ID', 'PDF File', 'Azymuts'}`.
- **`export_to_csv(data, filename)`** — writes extracted azimuth records to a CSV file with columns `Station ID`, `PDF File`, `Azymuts`.

### `ui/main_window.py` — `MainWindow(QMainWindow)`
Builds a `QVBoxLayout` containing: address `QLineEdit`, OpenCage API key `QLineEdit`, radius `QSpinBox` (1–10 km), three action buttons, a `QWebEngineView` for the interactive map, dual `QProgressBar` widgets (data loading / PDF processing), and a status `QLabel`. Worker threads are started with `QThread.start()` and communicate exclusively via Qt signals to ensure thread safety.

---

## Prerequisites

- Python 3.9+
- PyQt5 with QtWebEngine (`PyQt5`, `PyQtWebEngine`)
- `pandas`
- `folium`
- `geopy`
- `pdfplumber`
- `requests`
- An [OpenCage API key](https://opencagedata.com/api) (free tier available)
- BTSearch database CSV file (`output.csv`) — downloadable from [btsearch.pl](https://btsearch.pl/)

Install Python dependencies:

```bash
pip install PyQt5 PyQtWebEngine pandas folium geopy pdfplumber requests
```

---

## Configuration

Edit `config.ini` before running:

```ini
[Paths]
database_path = output.csv
pdf_dir = pdfs
extracted_text_dir = extracted_texts

[Settings]
pdf_page_nr = 3
```

| Key | Description |
|---|---|
| `database_path` | Path to the BTSearch station CSV (semicolon-delimited, UTF-8-BOM) |
| `pdf_dir` | Output directory for downloaded SI2PEM measurement PDFs |
| `extracted_text_dir` | Output directory for plain-text page dumps (debugging) |
| `pdf_page_nr` | Page number (1-indexed) in SI2PEM PDFs that contains the antenna table |

---

## Usage

```bash
python main.py
```

> **Note:** On Windows, run as Administrator. Application startup may take 20–60 seconds due to QtWebEngine initialization.

**Workflow:**

1. Enter a Polish address in the address field.
2. Provide a valid OpenCage API key.
3. Set the search radius (1–10 km).
4. Click **"Wyświetl mapę"** — the map loads with color-coded BTS markers.
5. *(Optional)* Click **"Pobierz dane azymutów anten"** to fetch SI2PEM measurement PDFs and extract azimuth data. This may take 15 seconds to 20 minutes depending on the number of stations and network speed.
6. Click **"Wyczyść mapę"**, then **"Wyświetl mapę"** again to redraw the map with azimuth direction lines overlaid on each station.

---

## External Data Sources

| Source | Usage |
|---|---|
| [BTSearch](https://btsearch.pl/) | Local CSV database of Polish BTS stations with coordinates, operator, frequency band, and radio standard |
| [OpenCage Geocoding API](https://opencagedata.com/) | Forward geocoding of user-provided addresses to WGS84 coordinates and voivodeship identification |
| [SI2PEM REST API](https://si2pem.gov.pl/) | Base station metadata retrieval (bounding boxes) |
| [SI2PEM WFS GeoServer](https://si2pem.gov.pl/geoserver/public/wfs) | OGC WFS 1.0.0 feature queries for EM measurement records with associated PDF report URLs |

---

## Known Limitations & Ongoing Work

- SI2PEM PDF retrieval fails for a subset of stations due to inconsistent API responses or missing bounding boxes; error handling logs these cases and skips affected stations gracefully.
- Azimuth line length on the map is approximated using a linear degree-based projection (`length = 0.01 · radius_km / 2`) and does not account for actual sector beam width or Earth curvature at larger radii.
- The application requires Administrator privileges on Windows due to QtWebEngine's sandboxing requirements.
- The BTSearch CSV database must be downloaded and updated manually.

---

## License

This project is provided as-is for educational and research purposes. Refer to the respective terms of service of BTSearch, OpenCage, and SI2PEM before deploying in a production or commercial context.
