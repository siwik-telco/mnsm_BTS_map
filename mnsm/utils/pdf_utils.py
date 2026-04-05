import csv
import logging
import os
import re

import pdfplumber

from mnsm.config import AZIMUTH_HEADERS, EXTRACTED_TEXT_DIR, PDF_PAGE_NR


def extract_information_from_pdf(pdf_path: str, expected_station_id: str) -> dict:
    base = os.path.basename(pdf_path)

    def _fail(msg):
        return {'Station ID': expected_station_id, 'PDF File': base, 'Azymuts': msg}

    if not os.path.exists(pdf_path):
        logging.error("PDF not found: %s", pdf_path)
        return _fail('Plik nie istnieje')

    with pdfplumber.open(pdf_path) as pdf:
        if len(pdf.pages) < PDF_PAGE_NR:
            return _fail('Nie znaleziono tabel')

        page = pdf.pages[PDF_PAGE_NR - 1]
        text = page.extract_text() or ''

        os.makedirs(EXTRACTED_TEXT_DIR, exist_ok=True)
        debug_path = os.path.join(EXTRACTED_TEXT_DIR, f"{base}_page_{PDF_PAGE_NR}.txt")
        with open(debug_path, 'w', encoding='utf-8') as fh:
            fh.write(text)

        if not text:
            return _fail('Brak tekstu')
        if expected_station_id not in text:
            return _fail('ID stacji nie znaleziono')

        tables = page.extract_tables()
        if not tables:
            return _fail('Nie znaleziono tabel')

        table = tables[0]
        headers = table[0]
        norm_headers = [h.strip().lower() if h else '' for h in headers]
        az_indices = [
            i for i, h in enumerate(norm_headers)
            if any(re.search(r'\b{}\b'.format(re.escape(ah.lower())), h) for ah in AZIMUTH_HEADERS)
        ]

        if not az_indices:
            return _fail('Nie znaleziono kolumny z azymutami')

        azimuths = []
        for row in table[1:]:
            for idx in az_indices:
                cell = row[idx].strip() if idx < len(row) and row[idx] else ''
                if not cell:
                    continue
                match = re.match(r'(\d{1,3})\s*°', cell)
                if match:
                    value = int(match.group(1))
                    if 0 <= value <= 360:
                        azimuths.append(f'{value}°')
                else:
                    azimuths.append(cell)

    if not azimuths:
        return _fail('Nie znaleziono azymutów')
    return {'Station ID': expected_station_id, 'PDF File': base, 'Azymuts': azimuths}


def export_to_csv(data: list, filename: str = 'antenna_data.csv') -> None:
    if not data:
        return
    with open(filename, 'w', newline='', encoding='utf-8') as fh:
        writer = csv.writer(fh)
        writer.writerow(['Station ID', 'PDF File', 'Azymuts'])
        for entry in data:
            azimuths = ', '.join(entry['Azymuts']) if isinstance(entry['Azymuts'], list) else entry['Azymuts']
            writer.writerow([entry['Station ID'], entry['PDF File'], azimuths])
    logging.info("Exported data to %s", filename)