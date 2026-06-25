import configparser
import logging
import re

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

_config = configparser.ConfigParser()
_config.read('config.ini')

DATABASE_PATH: str = _config.get('Paths', 'database_path', fallback='output.csv')
PDF_DIR: str = _config.get('Paths', 'pdf_dir', fallback='pdfs')
EXTRACTED_TEXT_DIR: str = _config.get('Paths', 'extracted_text_dir', fallback='extracted_texts')
PDF_PAGE_NR: int = _config.getint('Settings', 'pdf_page_nr', fallback=3)

WOJEWODZTW_MAP: dict = {
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

def normalize_operator_name(name: str) -> str:
    return re.sub(r'[^a-zA-Z0-9]', '', name).lower()

OPERATOR_COLORS: dict = {
    normalize_operator_name('T-Mobile'): 'pink',
    normalize_operator_name('Play'):     'purple',
    normalize_operator_name('Orange'):   'orange',
    normalize_operator_name('Plus'):     'green',
}

OPERATOR_COLORS_DISPLAY: dict = {
    'T-Mobile': 'pink',
    'Orange':   'orange',
    'Play':     'purple',
    'Plus':     'green',
}

AZIMUTH_HEADERS: list = [
    'Azymut H', 'Azimuth H', 'Kierunek H', 'Direction H',
    'Azymut', 'Azimuth', 'Kierunek', 'Direction',
]