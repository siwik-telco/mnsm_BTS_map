import logging

import pandas as pd
from PyQt5.QtCore import QThread, pyqtSignal
from geopy.distance import geodesic

from mnsm.config import DATABASE_PATH, WOJEWODZTW_MAP


class DataWorker(QThread):
    progress = pyqtSignal(int)
    result = pyqtSignal(pd.DataFrame)

    def __init__(self, location: tuple, wojewodztwo: str, radius: int):
        super().__init__()
        self.location = location
        self.wojewodztwo = wojewodztwo
        self.radius_km = radius
        self.filtered_df = pd.DataFrame()

    def run(self) -> None:
        try:
            df = pd.read_csv(
                DATABASE_PATH,
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
                    'standard': str,
                },
            )
            logging.info("CSV columns: %s", df.columns.tolist())
            mapped = WOJEWODZTW_MAP.get(self.wojewodztwo, self.wojewodztwo)
            df = df[df['wojewodztwo_id'] == mapped]
            self.filtered_df = self._filter_by_location(df)
            self.result.emit(self.filtered_df)
        except Exception as exc:
            logging.error("DataWorker error: %s", exc)
            self.result.emit(pd.DataFrame())

    def _filter_by_location(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df['distance'] = df.apply(
            lambda row: geodesic(self.location, (row['LATIuke'], row['LONGuke'])).km,
            axis=1,
        )
        filtered = df[df['distance'] <= self.radius_km].drop(columns=['distance'])
        for step in range(0, 101, 10):
            self.progress.emit(step)
        return filtered