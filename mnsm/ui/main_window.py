import logging

import pandas as pd
from PyQt5.QtGui import QIcon
from PyQt5.QtWebEngineWidgets import QWebEngineView
from PyQt5.QtWidgets import (
    QLabel, QLineEdit, QMainWindow, QMessageBox,
    QProgressBar, QPushButton, QSpinBox, QVBoxLayout, QWidget,
)

from mnsm.utils.geo import get_location_from_opencage
from mnsm.utils.map_utils import build_map
from mnsm.workers.data_worker import DataWorker
from mnsm.workers.pdf_worker import PdfWorker


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("MNSM by siwik-telco")
        self.setGeometry(100, 100, 800, 800)
        self.setWindowIcon(QIcon("ikona.ico"))
        self._worker = None
        self._pdf_worker = None
        self._build_ui()

    def _build_ui(self) -> None:
        container = QWidget()
        self.setCentralWidget(container)
        layout = QVBoxLayout(container)

        self.address_input = QLineEdit()
        self.address_input.setPlaceholderText("Podaj adres: ")
        layout.addWidget(self.address_input)

        self.api_key_input = QLineEdit()
        self.api_key_input.setPlaceholderText("Podaj klucz API (OpenCage)")
        layout.addWidget(self.api_key_input)

        self.radius_spinbox = QSpinBox()
        self.radius_spinbox.setRange(1, 10)
        self.radius_spinbox.setValue(1)
        self.radius_spinbox.setPrefix("Promień[km]: ")
        layout.addWidget(self.radius_spinbox)

        btn_show = QPushButton("Wyświetl mapę")
        btn_show.clicked.connect(self._on_show_map)
        layout.addWidget(btn_show)

        btn_pdf = QPushButton("Pobierz dane azymutów anten")
        btn_pdf.clicked.connect(self._on_download_pdf)
        layout.addWidget(btn_pdf)

        btn_clear = QPushButton("Wyczyść mapę")
        btn_clear.clicked.connect(self._on_clear_map)
        layout.addWidget(btn_clear)

        self.map_view = QWebEngineView()
        layout.addWidget(self.map_view, stretch=3)

        self.progress_bar = QProgressBar()
        layout.addWidget(self.progress_bar)

        self.pdf_progress_bar = QProgressBar()
        self.pdf_progress_bar.setVisible(False)
        layout.addWidget(self.pdf_progress_bar)

        self.status_label = QLabel()
        layout.addWidget(self.status_label)

    def _on_show_map(self) -> None:
        address = self.address_input.text()
        api_key = self.api_key_input.text()
        if not api_key:
            self.status_label.setText("Klucz API, który został podany jest niepoprawny.")
            return
        location, wojewodztwo = get_location_from_opencage(address, api_key)
        if location and wojewodztwo:
            self._start_data_worker(location, wojewodztwo, self.radius_spinbox.value())
        else:
            self.status_label.setText("Nie udało się pobrać lokalizacji.")

    def _start_data_worker(self, location, wojewodztwo, radius) -> None:
        self._worker = DataWorker(location, wojewodztwo, radius)
        self._worker.progress.connect(self.progress_bar.setValue)
        self._worker.result.connect(self._on_data_ready)
        self._worker.start()

    def _on_data_ready(self, filtered_df: pd.DataFrame) -> None:
        self.progress_bar.setValue(100)
        if filtered_df.empty:
            self.status_label.setText("Brak danych, spróbuj ponownie później.")
            return
        html = build_map(self._worker.location, filtered_df, self.radius_spinbox.value())
        self.map_view.setHtml(html)
        self.progress_bar.setValue(0)
        self.status_label.setText("Mapa z azymutami została wygenerowana.")

    def _on_download_pdf(self) -> None:
        if self._worker is None:
            self.status_label.setText("Najpierw wyświetl mapę, aby wybrać nadajniki.")
            return
        filtered_df = getattr(self._worker, 'filtered_df', pd.DataFrame())
        if filtered_df.empty:
            self.status_label.setText("Brak nadajników do pobrania PDF.")
            return
        station_ids = filtered_df['StationId'].unique()
        self.pdf_progress_bar.setVisible(True)
        self.pdf_progress_bar.setValue(0)
        self._pdf_worker = PdfWorker(station_ids)
        self._pdf_worker.progress.connect(self.pdf_progress_bar.setValue)
        self._pdf_worker.result.connect(self._on_pdf_done)
        self._pdf_worker.result.connect(lambda _: self._on_show_map())
        self._pdf_worker.start()

    def _on_pdf_done(self, extracted_data: list) -> None:
        self.pdf_progress_bar.setValue(100)
        self.pdf_progress_bar.setVisible(False)
        if not extracted_data:
            self.status_label.setText("Nie udało się pobrać lub przetworzyć PDF-ów.")
            return
        self.status_label.setText("PDF-y zostały pobrane i przetworzone pomyślnie.")
        QMessageBox.information(self, "Sukces",
            "PDF-y zostały pobrane i przetworzone.\nDane zostały zapisane do plików CSV.")

    def _on_clear_map(self) -> None:
        self.map_view.setHtml("")
        self.progress_bar.setValue(0)
        self.pdf_progress_bar.setValue(0)
        self.status_label.setText("Mapa została wyczyszczona.")
        self._worker = None
        logging.info("Map and state cleared.")