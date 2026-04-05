import sys
import requests
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QVBoxLayout, QWidget,
    QLineEdit, QPushButton, QProgressBar, QLabel, QMessageBox, QSpinBox
)
from PyQt5.QtGui import QIcon
from PyQt5.QtWebEngineWidgets import QWebEngineView
from PyQt5.QtCore import QThread, pyqtSignal
import folium
import pandas as pd
import io
import logging
from geopy.distance import geodesic
import os
import concurrent.futures
import pdfplumber
import re
import csv
from urllib.parse import urlencode
from math import cos, sin, radians  
import json
import configparser

# Konfiguracja
config = configparser.ConfigParser()
config.read('config.ini')
DATABASE_PATH = config.get('Paths', 'database_path', fallback='output.csv')
PDF_DIR = config.get('Paths', 'pdf_dir', fallback='pdfs')
EXTRACTED_TEXT_DIR = config.get('Paths', 'extracted_text_dir', fallback='extracted_texts')
PDF_PAGE_NR = config.getint('Settings', 'pdf_page_nr', fallback=3)

# Ustawienia logowania
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Mapowanie województw
WOJEWODZTW_MAP = {
    "Podlaskie Voivodeship": "Podlaskie",
    "West Pomeranian Voivodeship": "Zachodniopomorskie",
    "Greater Poland Voivodeship": "Wielkopolskie",
    "Warmian-Masurian Voivodeship": "Warmińsko-Mazurskie",
    "Lesser Poland Voivodeship": "Małopolskie",
    "Lubin Voivodeship": "Lubuskie",
    "Holy Cross Voivodeship": "Świętokrzyskie",
    "Masovian Voivodeship": "Mazowieckie",
    "Opole Voivodeship": "Opolskie",
    "Silesian Voivodeship": "Śląskie",
    "Lower Silesian Voivodeship": "Dolnośląskie",
    "Lubusz Voivodeship": "Lubuskie",
    "Kuyavian-Pomeranian Voivodeship": "Kujawsko-Pomorskie",
    "Łódź Voivodeship": "Łódzkie",
    "Subcarpathian Voivodeship": "Podkarpackie",
    "Pomeranian Voivodeship": "Pomorskie",
}

def normalize_operator_name(name):
    """
    Normalizuje nazwę operatora poprzez usunięcie znaków specjalnych i przekształcenie na małe litery.
    
    Args:
        name (str): Nazwa operatora do normalizacji.
        
    Returns:
        str: Znormalizowana nazwa operatora.
    """
    return re.sub(r'[^a-zA-Z0-9]', '', name).lower()

# Mapowanie operatorów na kolory z normalizacją
OPERATOR_COLORS = {
    normalize_operator_name('Tmobile'): 'pink',
    normalize_operator_name('T-Mobile'): 'pink',
    normalize_operator_name('Play'): 'purple',
    normalize_operator_name('Orange'): 'orange',
    normalize_operator_name('Plus'): 'green'
}

# Lista możliwych nagłówków kolumn zawierających azymuty
AZIMUTH_HEADERS = [
    'Azymut H', 'Azimuth H', 'Kierunek H', 'Direction H',
    'Azymut', 'Azimuth', 'Kierunek', 'Direction'
]

def create_svg_icon(operators, operator_colors, size=30):
    """
    Tworzy SVG ikony z kolorami operatorów.
    
    Args:
        operators (list): Lista operatorów.
        operator_colors (dict): Słownik mapujący operatorów na kolory.
        size (int): Rozmiar SVG.
        
    Returns:
        folium.DivIcon: Utworzony DivIcon z SVG.
    """
    svg = f'<svg width="{size}" height="{size}" xmlns="http://www.w3.org/2000/svg">'
    svg += f'<circle cx="{size/2}" cy="{size/2}" r="{size/2 - 1}" fill="white" stroke="black" stroke-width="1"/>'

    if len(operators) == 1:
        color = operator_colors.get(operators[0], 'gray')
        svg = f'<svg width="{size}" height="{size}" xmlns="http://www.w3.org/2000/svg">'
        svg += f'<circle cx="{size/2}" cy="{size/2}" r="{size/2 - 1}" fill="{color}" stroke="black" stroke-width="1"/>'
    else:
        num_operators = len(operators)
        angle_step = 360 / num_operators
        for i, operator in enumerate(operators):
            color = operator_colors.get(operator, 'gray')
            start_angle = i * angle_step
            end_angle = (i + 1) * angle_step
            start_rad = start_angle * (3.141592653589793 / 180)
            end_rad = end_angle * (3.141592653589793 / 180)
            x1 = size/2 + (size/2 - 1) * cos(start_rad)
            y1 = size/2 + (size/2 - 1) * sin(start_rad)
            x2 = size/2 + (size/2 - 1) * cos(end_rad)
            y2 = size/2 + (size/2 - 1) * sin(end_rad)
            large_arc = 1 if angle_step > 180 else 0
            svg += f'<path d="M {size/2},{size/2} L {x1},{y1} A {size/2 - 1},{size/2 - 1} 0 {large_arc},1 {x2},{y2} Z" fill="{color}" stroke="black" stroke-width="1"/>'

    svg += '</svg>'
    return folium.DivIcon(html=svg)

class Worker(QThread):
    progress = pyqtSignal(int)
    result = pyqtSignal(pd.DataFrame)

    def __init__(self, location, wojewodztwo, radius):
        super().__init__()
        self.location = location
        self.wojewodztwo = wojewodztwo
        self.radius_km = radius
        self.filtered_df = pd.DataFrame()

    def run(self):
        try:
            df = pd.read_csv(
                'output.csv',
                delimiter=';',
                encoding='utf-8-sig',
                usecols=['siec_id', 'LONGuke', 'LATIuke', 'StationId', 'wojewodztwo_id', 'pasmo', 'standard'],
                dtype={
                    'siec_id': str,
                    'LONGuke': float,
                    'LATIuke': float,
                    'StationId': str, 
                    'wojewodztwo_id': str,
                    'pasmo': str,
                    'standard': str
                }
            )
            logging.info(f"Kolumny w CSV: {df.columns.tolist()}")
            df['StationId'] = df['StationId'].astype(str)
            df['pasmo'] = df['pasmo'].astype(str)
            df['siec_id'] = df['siec_id'].astype(str)
            mapped_wojewodztwo = WOJEWODZTW_MAP.get(self.wojewodztwo, self.wojewodztwo)
            df = df[df['wojewodztwo_id'] == mapped_wojewodztwo]
            self.filtered_df = self.filter_transmitters_by_location(df, self.location, self.radius_km)
            self.result.emit(self.filtered_df)
        except Exception as e:
            logging.error(f"Error reading CSV file: {e}")
            self.result.emit(pd.DataFrame())

    def filter_transmitters_by_location(self, df, location, radius_km):
        df['distance'] = df.apply(
            lambda row: geodesic(location, (row['LATIuke'], row['LONGuke'])).km, axis=1
        )
        filtered_df = df[df['distance'] <= radius_km].drop(columns=['distance'])

        total = len(df)
        for i in range(0, 101, 10):
            self.progress.emit(i)

        return filtered_df

class PdfWorker(QThread):
    progress = pyqtSignal(int)
    result = pyqtSignal(list)

    def __init__(self, station_ids):
        super().__init__()
        self.station_ids = station_ids
        self.extracted_data = []

    def run(self):
        try:
            total = len(self.station_ids)
            processed = 0
            for station_id in self.station_ids:
                station_id = str(station_id)  
                info = self.process_station(station_id)
                if info:
                    self.extracted_data.append(info)
                processed += 1
                self.progress.emit(int((processed / total) * 100))
            self.result.emit(self.extracted_data)
        except Exception as e:
            logging.error(f"Error in PdfWorker: {e}")
            self.result.emit([])

    def get_base_station_info(self, base_station_id):
        """
        Pobiera informacje o nadajniku na podstawie jego ID.
        """
        url = f"https://si2pem.gov.pl/api/public/base_station?search={base_station_id}"
        response = requests.get(url, timeout=15)
        if response.status_code != 200:
            logging.error(f"Błąd HTTP {response.status_code} podczas pobierania informacji o nadajniku.")
            return None
        data = response.json()
        if isinstance(data, list) and len(data) > 0:
            return data[0]
        else:
            logging.error(f"Nie znaleziono nadajnika o ID: {base_station_id}")
            return None

    def construct_wfs_getfeature_url(self, bbox, feature_type='public:measures_all', output_format='application/json'):
        """
        Konstrukcja URL do zapytania WFS GetFeature z filtrem BBOX.
        """
        base_url = "https://si2pem.gov.pl/geoserver/public/wfs"
        params = {
            'service': 'WFS',
            'version': '1.0.0',
            'request': 'GetFeature',
            'typeName': feature_type,
            'outputFormat': output_format,
            'bbox': f"{bbox[2]},{bbox[0]},{bbox[3]},{bbox[1]},EPSG:4326"
        }
        query_string = urlencode(params)
        return f"{base_url}?{query_string}"

    def get_feature_data(self, wfs_url):
        """
        Wysyła zapytanie WFS GetFeature i zwraca dane GeoJSON.
        """
        response = requests.get(wfs_url)
        if response.status_code != 200:
            logging.error(f"Błąd HTTP {response.status_code} podczas pobierania danych WFS.")
            return None
        try:
            data = response.json()
            return data
        except json.JSONDecodeError as e:
            logging.error(f"Błąd dekodowania JSON: {e}")
            return None

    def extract_pdf_urls(self, geojson_data):
        """
        Ekstrahuje URL-e do PDF z danych GeoJSON.
        Zakładam, że URL do PDF znajduje się w polu 'url' w properties.
        """
        pdf_urls = set()
        features = geojson_data.get('features', [])
        for feature in features:
            properties = feature.get('properties', {})
            pdf_url = properties.get('url') or properties.get('pdf_url') or properties.get('PDF_URL')
            if pdf_url:
                pdf_urls.add(pdf_url)
        return pdf_urls

    def download_pdf(self, pdf_url, save_directory='pdfs'):
        """
        Pobiera plik PDF z podanego URL i zapisuje go w określonym katalogu.
        """
        response = requests.get(pdf_url)
        if response.status_code != 200:
            logging.error(f"Błąd HTTP {response.status_code} podczas pobierania PDF z {pdf_url}.")
            return None
        filename = pdf_url.split('/')[-1]
        save_path = os.path.join(save_directory, filename)
        os.makedirs(save_directory, exist_ok=True)
        with open(save_path, 'wb') as f:
            f.write(response.content)
        logging.info(f"PDF zapisany jako: {save_path}")
        return save_path

    def extract_information_from_pdf(self, pdf_path, expected_station_id):
        """
        Ekstrahuje informacje o azymutach z pliku PDF.
        Zakłada, że tabela z azymutami znajduje się na trzeciej stronie PDF-a.
        """
        if not os.path.exists(pdf_path):
            logging.error(f"Plik PDF {pdf_path} nie istnieje.")
            return {
                'Station ID': expected_station_id,
                'PDF File': os.path.basename(pdf_path),
                'Azymuts': 'Plik nie istnieje'
            }

        pdf = pdfplumber.open(pdf_path)

        if len(pdf.pages) < 3:
            logging.warning(f"PDF {pdf_path} ma mniej niż 3 strony.")
            pdf.close()
            return {
                'Station ID': expected_station_id,
                'PDF File': os.path.basename(pdf_path),
                'Azymuts': 'Nie znaleziono tabel'
            }

        page_number = 3
        page = pdf.pages[2]
        text = page.extract_text()
        if not text:
            logging.error(f"Brak tekstu na stronie {page_number} w PDF: {pdf_path}")
            pdf.close()
            return {
                'Station ID': expected_station_id,
                'PDF File': os.path.basename(pdf_path),
                'Azymuts': 'Brak tekstu'
            }

        text_save_path = os.path.join('extracted_texts', f"{os.path.basename(pdf_path)}_page_{page_number}.txt")
        os.makedirs('extracted_texts', exist_ok=True)
        with open(text_save_path, 'w', encoding='utf-8') as f:
            f.write(text)
        logging.debug(f"Zapisano wyciągnięty tekst ze strony {page_number} w PDF: {pdf_path} do {text_save_path}")

        if expected_station_id not in text:
            logging.error(f"ID stacji {expected_station_id} nie znaleziono na trzeciej stronie PDF: {pdf_path}")
            pdf.close()
            return {
                'Station ID': expected_station_id,
                'PDF File': os.path.basename(pdf_path),
                'Azymuts': 'ID stacji nie znaleziono'
            }

        tables = page.extract_tables()
        if not tables:
            logging.warning(f"Nie znaleziono tabel na stronie {page_number} w PDF: {pdf_path}")
            pdf.close()
            return {
                'Station ID': expected_station_id,
                'PDF File': os.path.basename(pdf_path),
                'Azymuts': 'Nie znaleziono tabel'
            }

        table = tables[0]
        headers = table[0]
        normalized_headers = [header.strip().lower() if header else '' for header in headers]
        azimuth_col_indices = [
            i for i, header in enumerate(normalized_headers)
            if any(re.search(r'\b{}\b'.format(re.escape(h.lower())), header) for h in AZIMUTH_HEADERS)
        ]

        if not azimuth_col_indices:
            logging.warning(f"Nie znaleziono kolumny z azymutami w tabeli na stronie {page_number} w PDF: {pdf_path}")
            pdf.close()
            return {
                'Station ID': expected_station_id,
                'PDF File': os.path.basename(pdf_path),
                'Azymuts': 'Nie znaleziono kolumny z azymutami'
            }

        logging.debug(f"Znalezione nagłówki tabeli: {headers}")
        logging.debug(f"Indeksy kolumn z azymutami: {azimuth_col_indices}")

        azimuths = []
        for row in table[1:]:
            for index in azimuth_col_indices:
                if index < len(row):
                    azimuth_value = row[index].strip() if row[index] else ''
                    if azimuth_value:
                        match = re.match(r'(\d{1,3})\s*°', azimuth_value)
                        if match:
                            az_value = int(match.group(1))
                            if 0 <= az_value <= 360:
                                azimuths.append(str(az_value) + '°')
                            else:
                                logging.warning(f"Niewłaściwa wartość azymutu: {azimuth_value} w PDF: {pdf_path}")
                        else:
                            azimuths.append(azimuth_value)

        pdf.close()

        if not azimuths:
            logging.warning(f"Nie znaleziono azymutów w tabeli PDF: {pdf_path}")
            return {
                'Station ID': expected_station_id,
                'PDF File': os.path.basename(pdf_path),
                'Azymuts': 'Nie znaleziono azymutów'
            }

        return {
            'Station ID': expected_station_id,
            'PDF File': os.path.basename(pdf_path),
            'Azymuts': azimuths
        }

    def process_feature_type(self, bbox, feature_type):
        """
        Przetwarza jedną warstwę WFS GetFeature, zwraca zebrane URL-e do PDF.
        """
        wfs_url = self.construct_wfs_getfeature_url(bbox, feature_type=feature_type)
        logging.info(f"Wysyłanie zapytania WFS GetFeature dla warstwy '{feature_type}': {wfs_url}")

        geojson_data = self.get_feature_data(wfs_url)
        if not geojson_data:
            logging.error(f"Nie udało się pobrać danych dla warstwy '{feature_type}'.")
            return set()

        pdf_urls = self.extract_pdf_urls(geojson_data)
        if pdf_urls:
            logging.info(f"Znaleziono {len(pdf_urls)} PDF-ów w warstwie '{feature_type}'.")
        else:
            logging.info(f"Nie znaleziono PDF-ów w warstwie '{feature_type}'.")

        return pdf_urls

    def export_to_csv(self, data, filename='antenna_data.csv'):
        """
        Eksportuje wyekstrahowane dane do pliku CSV.

        Args:
            data (list): Lista słowników zawierających wyekstrahowane informacje.
            filename (str): Nazwa pliku CSV.
        """
        if not data:
            logging.info("Brak danych do eksportu.")
            return

        with open(filename, mode='w', newline='', encoding='utf-8') as file:
            writer = csv.writer(file)
            writer.writerow(['Station ID', 'PDF File', 'Azymuts'])
            for entry in data:
                azimuths = ', '.join(entry['Azymuts']) if isinstance(entry['Azymuts'], list) else entry['Azymuts']
                writer.writerow([entry['Station ID'], entry['PDF File'], azimuths])
        logging.info(f"Dane zostały wyeksportowane do {filename}")

    def process_station(self, station_id):
        """
        Przetwarza pojedynczy StationId: pobiera informacje, PDF-y i ekstrakcję danych.
        """
        station_id = str(station_id)  # Upewnij się, że station_id jest ciągiem znaków
        base_station = self.get_base_station_info(station_id)
        if not base_station:
            return None

        bbox = base_station.get('boundingbox', [])
        if len(bbox) != 4:
            logging.error("Nieprawidłowy bounding box.")
            return None
        min_lat, max_lat, min_lon, max_lon = bbox
        logging.info(f"Bounding box dla StationId {station_id}: {bbox}")

        feature_types = [
            'public:measures_all',
            'public:measures_14_21',
            'public:measures_21_28',
            'public:measures_28',
            'public:measures_7',
            'public:measures_7_14'
        ]

        all_pdf_urls = set()
        for feature_type in feature_types:
            pdf_urls = self.process_feature_type(bbox, feature_type)
            all_pdf_urls.update(pdf_urls)

        if not all_pdf_urls:
            logging.info(f"Nie znaleziono żadnych PDF-ów dla StationId {station_id}.")
            return None

        logging.info(f"Łączna liczba unikalnych PDF-ów dla StationId {station_id}: {len(all_pdf_urls)}")

        downloaded_pdfs = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            future_to_url = {executor.submit(self.download_pdf, url): url for url in all_pdf_urls}
            for future in concurrent.futures.as_completed(future_to_url):
                url = future_to_url[future]
                pdf_path = future.result()
                if pdf_path:
                    downloaded_pdfs.append(pdf_path)

        if not downloaded_pdfs:
            logging.info(f"Żaden PDF nie został pomyślnie pobrany dla StationId {station_id}.")
            return None

        extracted_data = []
        for pdf_path in downloaded_pdfs:
            info = self.extract_information_from_pdf(pdf_path, station_id)
            if info:
                extracted_data.append(info)

        if not extracted_data:
            logging.info(f"Nie udało się wyekstrahować żadnych informacji z PDF-ów dla StationId {station_id}.")
            return None

        self.export_to_csv(extracted_data, filename=f'antenna_data_{station_id}.csv')
        return extracted_data

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("MNSM by Merituum")
        self.setGeometry(100, 100, 800, 800)
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.layout = QVBoxLayout(self.central_widget)
        
        self.setWindowIcon(QIcon("ikona.ico"))

        self.address_input = QLineEdit(self)
        self.address_input.setPlaceholderText("Podaj adres: ")
        self.layout.addWidget(self.address_input)

        self.api_key_input = QLineEdit(self)
        self.api_key_input.setPlaceholderText("Podaj klucz API (OpenCage)")
        self.layout.addWidget(self.api_key_input)

        self.radius_spinbox = QSpinBox(self)
        self.radius_spinbox.setRange(1, 10)
        self.radius_spinbox.setValue(1)
        self.radius_spinbox.setPrefix("Promień[km]: ")
        self.layout.addWidget(self.radius_spinbox)

        self.show_map_button = QPushButton("Wyświetl mapę", self)
        self.show_map_button.clicked.connect(self.show_map)
        self.layout.addWidget(self.show_map_button)

        self.download_pdf_button = QPushButton("Pobierz dane azymutów anten", self)
        self.download_pdf_button.clicked.connect(self.run_pdf_worker)
        self.download_pdf_button.clicked.connect(self.show_map)
        self.layout.addWidget(self.download_pdf_button)

        self.clear_map_button = QPushButton("Wyczyść mapę", self)
        self.clear_map_button.clicked.connect(self.clear_map)
        self.layout.addWidget(self.clear_map_button)

        self.map_view = QWebEngineView(self)
        self.layout.addWidget(self.map_view, 3)

        self.progress_bar = QProgressBar(self)
        self.layout.addWidget(self.progress_bar)

        self.pdf_progress_bar = QProgressBar(self)
        self.pdf_progress_bar.setVisible(False)
        self.layout.addWidget(self.pdf_progress_bar)

        self.status_label = QLabel(self)
        self.layout.addWidget(self.status_label)

        self.worker = None

    def show_map(self):
        address = self.address_input.text()
        api_key = self.api_key_input.text()
        
     
        radius = self.radius_spinbox.value()
        if not api_key:
            self.status_label.setText("Klucz API, który został podany jest niepoprawny.")
            return
        location, wojewodztwo = self.get_location_from_opencage(address, api_key)
        if location and wojewodztwo:
            self.start_worker(location, wojewodztwo, radius)
        else:
            self.status_label.setText("Nie udało się pobrać lokalizacji.")
    def get_location_from_opencage(self, address, api_key):
        """
        Pobiera współrzędne geograficzne i województwo na podstawie adresu, używając OpenCage API.
        
        Args:
            address (str): Adres do geokodowania.
            api_key (str): Klucz API OpenCage.
            
        Returns:
            tuple: ((lat, lon), wojewodztwo) lub (None, None) w przypadku błędu.
        """
        url = f'https://api.opencagedata.com/geocode/v1/json?q={address}&key={api_key}'
        try:
            response = requests.get(url)
            response.raise_for_status()
            data = response.json()
            if data and data['results']:
                lat = float(data['results'][0]['geometry']['lat'])
                lon = float(data['results'][0]['geometry']['lng'])
                components = data['results'][0]['components']
                wojewodztwo = components.get('state', None)
                logging.info(f"Pobrano lokalizację dla adresu {address}: ({lat}, {lon}), województwo: {wojewodztwo}")
                return (lat, lon), wojewodztwo
            else:
                logging.warning(f"Brak wyników geokodowania dla adresu: {address}")
                return None, None
        except requests.RequestException as e:
            logging.error(f"Błąd podczas geokodowania adresu {address}: {e}")
            return None, None

    def start_worker(self, location, wojewodztwo, radius):
        """
        Uruchamia wątek Worker do filtrowania nadajników na podstawie lokalizacji i promienia.
        
        Args:
            location (tuple): Współrzędne (lat, lon).
            wojewodztwo (str): Nazwa województwa.
            radius (int): Promień wyszukiwania w kilometrach.
        """
        self.worker = Worker(location, wojewodztwo, radius)
        self.worker.progress.connect(self.update_progress)
        self.worker.result.connect(self.display_map)
        self.worker.start()
        logging.info(f"Rozpoczęto filtrowanie nadajników dla lokalizacji {location}, województwo: {wojewodztwo}, promień: {radius} km")

    def load_azimuth_data(self, station_id):
        """
        Wczytywanie danych o azymutach z pliku CSV dla danego StationId.
        
        Args:
            station_id (str): ID stacji.
            
        Returns:
            list: Lista azymutów (w stopniach) lub pusta lista w przypadku błędu.
        """
        station_id = str(station_id)  # Upewnij się, że station_id jest ciągiem znaków
        csv_file = f'antenna_data_{station_id}.csv'
        if not os.path.exists(csv_file):
            logging.warning(f"Brak pliku CSV z danymi azymutów dla StationId {station_id}")
            return []

        azimuths = []
        logging.info(f"Wczytywanie azymutów z pliku {csv_file}")
        try:
            with open(csv_file, mode='r', encoding='utf-8') as file:
                reader = csv.DictReader(file)
                for row in reader:
                    azymuts_str = row.get('Azymuts', '')
                    if azymuts_str:
                        azimuth_list = [az.strip() for az in azymuts_str.split(',')]
                        for az in azimuth_list:
                            try:
                                azimuth_value = float(az.replace('°', ''))
                                if 0 <= azimuth_value <= 360:
                                    azimuths.append(azimuth_value)
                                    logging.debug(f"Dodano azymut: {azimuth_value} dla StationId {station_id}")
                            except ValueError:
                                logging.warning(f"Nieprawidłowy format azymutu: {az} w pliku {csv_file}")
        except Exception as e:
            logging.error(f"Błąd podczas wczytywania danych azymutów z {csv_file}: {e}")
        logging.info(f"Wczytano {len(azimuths)} azymutów dla StationId {station_id}")
        return azimuths

    def update_progress(self, value):
        """
        Aktualizuje pasek postępu podczas filtrowania nadajników.
        
        Args:
            value (int): Wartość postępu (0-100).
        """
        self.progress_bar.setValue(value)

    def display_map(self, filtered_df):
        """
        Wyświetla mapę z nadajnikami i liniami azymutów.
        
        Args:
            filtered_df (pd.DataFrame): Filtrowane dane nadajników.
        """
        self.progress_bar.setValue(100)

        if filtered_df.empty:
            self.status_label.setText("Brak danych, spróbuj ponownie później.")
            logging.warning("Brak nadajników w podanym promieniu.")
            return

        user_lat, user_lon = self.worker.location
        # map_ = folium.Map(location=[user_lat, user_lon], zoom_start=12)
        map_ = folium.Map(
            location=[user_lat, user_lon],
            zoom_start=12,
            tiles='CartoDB positron'
        )
        folium.Marker(
            [user_lat, user_lon],
            tooltip="Podany adres",
            icon=folium.Icon(color="blue", icon="info-sign")
        ).add_to(map_)

        operator_colors = {
            'T-Mobile': 'pink',
            'Orange': 'orange',
            'Play': 'purple',
            'Plus': 'green'
        }

        grouped = filtered_df.groupby(['LATIuke', 'LONGuke'])

        # Dynamiczna długość linii azymutów na podstawie promienia
        radius_km = self.radius_spinbox.value()
        length = 0.01 * (radius_km / 2)  # Proporcjonalna długość linii

        for (lat, lon), group in grouped:
            operator_info = []
            color_blocks = []
            station_ids = group['StationId'].unique()
            if len(station_ids) > 0:
                station_id = station_ids[0]  # Używamy pierwszego StationId do wczytania azymutów
            else:
                continue

            operators = group['siec_id'].unique()  # Lista operatorów dla tego nadajnika
            for operator, sub_group in group.groupby('siec_id'):
                bands = sub_group.groupby('pasmo')['standard'].apply(lambda x: ', '.join(x.unique()))
                details = [f"{pasmo} ({technologie})" for pasmo, technologie in bands.items()]
                operator_info.append(f"{operator}: " + '; '.join(details))
                color = operator_colors.get(operator, 'blue')
                color_blocks.append(f'<div style="flex: 1; background-color: {color};"></div>')

            tooltip_text = '<br>'.join(operator_info)

            html = f'''
                <div style="width: 30px; height: 30px; display: flex; border-radius: 50%; border: 2px solid #000;">
                    {''.join(color_blocks)}
                </div>
            '''
            icon = folium.DivIcon(html=html)

            folium.Marker(
                [lat, lon],
                tooltip=tooltip_text,
                icon=icon
            ).add_to(map_)

            # Wczytaj azymuty
            azimuths = self.load_azimuth_data(station_id)
            if azimuths:
                # Dla każdego operatora, rysujemy jego azymuty z odpowiednim kolorem
                for i, operator in enumerate(operators):
                    line_color = operator_colors.get(operator, 'red')
                    logging.info(f"Rysowanie azymutów dla operatora {operator} z kolorem {line_color}")
                    
                    # Każdy operator otrzymuje swój własny zestaw azymutów, przesunięty lekko dla lepszej widoczności
                    offset = (i - len(operators)/2) * 0.00005  # Małe przesunięcie między liniami operatorów
                    
                    for azimuth in azimuths:
                        # Lekko przesuń początek i koniec linii dla lepszej widoczności
                        start_lat = lat + offset * cos(radians(azimuth + 90))
                        start_lon = lon + offset * sin(radians(azimuth + 90))
                        end_lat = start_lat + length * cos(radians(azimuth))
                        end_lon = start_lon + length * sin(radians(azimuth))
                        
                        # Rysuj czarną linię jako obramowanie (grubsza)
                        folium.PolyLine(
                            locations=[[start_lat, start_lon], [end_lat, end_lon]],
                            weight=4,  # Grubsza linia jako obramowanie
                            color='black',  # Kolor obramowania
                            opacity=0.8,
                            tooltip=f'Operator: {operator}, Azymut: {azimuth}°'
                        ).add_to(map_)
                        
                        # Rysuj linię w kolorze operatora (cieńsza, na wierzchu)
                        folium.PolyLine(
                            locations=[[start_lat, start_lon], [end_lat, end_lon]],
                            weight=2,  # Cieńsza linia w kolorze operatora
                            color=line_color,  # Kolor operatora
                            opacity=0.8,
                            tooltip=f'Operator: {operator}, Azymut: {azimuth}°'
                        ).add_to(map_)

        data = io.BytesIO()
        map_.save(data, close_file=False)
        self.map_view.setHtml(data.getvalue().decode())
        self.progress_bar.setValue(0)
        self.status_label.setText("Mapa z azymutami została wygenerowana.")
        logging.info(f"Mapa wygenerowana z {len(grouped)} nadajnikami.")

    def run_pdf_worker(self):
        """
        Uruchamia wątek PdfWorker do pobierania i przetwarzania PDF-ów dla wybranych StationId.
        """
        if not hasattr(self, 'worker') or self.worker is None:
            self.status_label.setText("Najpierw wyświetl mapę, aby wybrać nadajniki.")
            logging.warning("Próba uruchomienia PdfWorker bez wcześniejszego filtrowania nadajników.")
            return

        filtered_df = getattr(self.worker, 'filtered_df', pd.DataFrame())
        if filtered_df.empty:
            self.status_label.setText("Brak nadajników do pobrania PDF.")
            logging.warning("Brak nadajników w filtered_df.")
            return

        station_ids = filtered_df['StationId'].unique()
        logging.info(f"Przetwarzane StationIds: {list(station_ids)}")

        self.pdf_progress_bar.setVisible(True)
        self.pdf_progress_bar.setValue(0)

        self.pdf_worker = PdfWorker(station_ids)
        self.pdf_worker.progress.connect(self.update_pdf_progress)
        self.pdf_worker.result.connect(self.pdf_processing_finished)
        self.pdf_worker.start()

    def update_pdf_progress(self, value):
        """
        Aktualizuje pasek postępu podczas pobierania i przetwarzania PDF-ów.
        
        Args:
            value (int): Wartość postępu (0-100).
        """
        self.pdf_progress_bar.setValue(value)

    def pdf_processing_finished(self, extracted_data):
        """
        Obsługuje zakończenie przetwarzania PDF-ów.
        
        Args:
            extracted_data (list): Lista wyekstrahowanych danych z PDF-ów.
        """
        self.pdf_progress_bar.setValue(100)
        self.pdf_progress_bar.setVisible(False)
        if not extracted_data:
            self.status_label.setText("Nie udało się pobrać lub przetworzyć PDF-ów.")
            logging.warning("Brak danych po przetworzeniu PDF-ów.")
            return

        self.status_label.setText("PDF-y zostały pobrane i przetworzone pomyślnie.")
        message = "PDF-y zostały pobrane i przetworzone.\nDane zostały zapisane do plików CSV."
        QMessageBox.information(self, "Sukces", message)
        logging.info(f"Pomyślnie przetworzono {len(extracted_data)} PDF-ów.")

    def clear_map(self):
        """
        Czyści mapę i resetuje dane.
        """
        self.map_view.setHtml("")
        self.progress_bar.setValue(0)
        self.pdf_progress_bar.setValue(0)
        self.status_label.setText("Mapa została wyczyszczona.")
        self.worker = None
        logging.info("Mapa i dane zostały wyczyszczone.")
        # todo: change texts displayed in program, that are not necesarly correct

if __name__ == "__main__":
    app = QApplication(sys.argv)
    main_window = MainWindow()
    main_window.show()
    sys.exit(app.exec_()) 
