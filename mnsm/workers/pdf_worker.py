import concurrent.futures
import json
import logging
import os
from urllib.parse import urlencode

import requests
from PyQt5.QtCore import QThread, pyqtSignal

from mnsm.config import PDF_DIR
from mnsm.utils.pdf_utils import export_to_csv, extract_information_from_pdf

_WFS_BASE_URL = "https://si2pem.gov.pl/geoserver/public/wfs"
_API_BASE_URL = "https://si2pem.gov.pl/api/public/base_station"
_FEATURE_TYPES = [
    'public:measures_all', 'public:measures_14_21', 'public:measures_21_28',
    'public:measures_28', 'public:measures_7', 'public:measures_7_14',
]


class PdfWorker(QThread):
    progress = pyqtSignal(int)
    result = pyqtSignal(list)

    def __init__(self, station_ids):
        super().__init__()
        self.station_ids = [str(sid) for sid in station_ids]
        self.extracted_data = []

    def run(self) -> None:
        try:
            total = len(self.station_ids)
            for idx, station_id in enumerate(self.station_ids, start=1):
                info = self._process_station(station_id)
                if info:
                    self.extracted_data.append(info)
                self.progress.emit(int(idx / total * 100))
            self.result.emit(self.extracted_data)
        except Exception as exc:
            logging.error("PdfWorker error: %s", exc)
            self.result.emit([])

    def _get_base_station_info(self, station_id: str):
        url = f"{_API_BASE_URL}?search={station_id}"
        try:
            resp = requests.get(url, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, list) and data:
                return data[0]
        except requests.RequestException as exc:
            logging.error("API request failed for station %s: %s", station_id, exc)
        return None

    def _build_wfs_url(self, bbox: list, feature_type: str) -> str:
        params = {
            'service': 'WFS', 'version': '1.0.0', 'request': 'GetFeature',
            'typeName': feature_type, 'outputFormat': 'application/json',
            'bbox': f"{bbox[2]},{bbox[0]},{bbox[3]},{bbox[1]},EPSG:4326",
        }
        return f"{_WFS_BASE_URL}?{urlencode(params)}"

    def _get_feature_data(self, wfs_url: str):
        try:
            resp = requests.get(wfs_url, timeout=30)
            resp.raise_for_status()
            return resp.json()
        except (requests.RequestException, json.JSONDecodeError) as exc:
            logging.error("WFS request failed: %s", exc)
        return None

    def _extract_pdf_urls(self, geojson: dict) -> set:
        urls = set()
        for feat in geojson.get('features', []):
            props = feat.get('properties', {})
            url = props.get('url') or props.get('pdf_url') or props.get('PDF_URL')
            if url:
                urls.add(url)
        return urls

    def _download_pdf(self, pdf_url: str):
        try:
            resp = requests.get(pdf_url, timeout=30)
            resp.raise_for_status()
        except requests.RequestException as exc:
            logging.error("PDF download failed (%s): %s", pdf_url, exc)
            return None
        os.makedirs(PDF_DIR, exist_ok=True)
        path = os.path.join(PDF_DIR, pdf_url.split('/')[-1])
        with open(path, 'wb') as fh:
            fh.write(resp.content)
        return path

    def _collect_pdf_urls(self, bbox: list) -> set:
        all_urls = set()
        for feature_type in _FEATURE_TYPES:
            data = self._get_feature_data(self._build_wfs_url(bbox, feature_type))
            if data:
                all_urls.update(self._extract_pdf_urls(data))
        return all_urls

    def _process_station(self, station_id: str):
        station = self._get_base_station_info(station_id)
        if not station:
            return None
        bbox = station.get('boundingbox', [])
        if len(bbox) != 4:
            return None

        pdf_urls = self._collect_pdf_urls(bbox)
        if not pdf_urls:
            return None

        downloaded = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
            futures = {pool.submit(self._download_pdf, u): u for u in pdf_urls}
            for future in concurrent.futures.as_completed(futures):
                path = future.result()
                if path:
                    downloaded.append(path)

        if not downloaded:
            return None

        extracted = [e for e in (extract_information_from_pdf(p, station_id) for p in downloaded) if e]
        if not extracted:
            return None

        export_to_csv(extracted, filename=f'antenna_data_{station_id}.csv')
        return extracted