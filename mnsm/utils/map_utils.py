import csv
import io
import logging
import os
from math import cos, sin, radians

import folium
import pandas as pd

from mnsm.config import OPERATOR_COLORS_DISPLAY


def create_svg_icon(operators: list, operator_colors: dict, size: int = 30) -> folium.DivIcon:
    cx = cy = size / 2
    r = size / 2 - 1

    if len(operators) == 1:
        color = operator_colors.get(operators[0], 'gray')
        svg = (
            f'<svg width="{size}" height="{size}" xmlns="http://www.w3.org/2000/svg">'
            f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="{color}" stroke="black" stroke-width="1"/>'
            f'</svg>'
        )
    else:
        svg = (
            f'<svg width="{size}" height="{size}" xmlns="http://www.w3.org/2000/svg">'
            f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="white" stroke="black" stroke-width="1"/>'
        )
        angle_step = 360 / len(operators)
        for i, operator in enumerate(operators):
            color = operator_colors.get(operator, 'gray')
            start_rad = radians(i * angle_step)
            end_rad = radians((i + 1) * angle_step)
            x1 = cx + r * cos(start_rad)
            y1 = cy + r * sin(start_rad)
            x2 = cx + r * cos(end_rad)
            y2 = cy + r * sin(end_rad)
            large_arc = 1 if angle_step > 180 else 0
            svg += (
                f'<path d="M {cx},{cy} L {x1},{y1} A {r},{r} 0 {large_arc},1 {x2},{y2} Z" '
                f'fill="{color}" stroke="black" stroke-width="1"/>'
            )
        svg += '</svg>'

    return folium.DivIcon(html=svg)


def load_azimuth_data(station_id: str) -> list:
    station_id = str(station_id)
    csv_file = f'antenna_data_{station_id}.csv'
    if not os.path.exists(csv_file):
        logging.warning("No azimuth CSV found for StationId %s", station_id)
        return []

    azimuths = []
    try:
        with open(csv_file, encoding='utf-8') as fh:
            for row in csv.DictReader(fh):
                for az in row.get('Azymuts', '').split(','):
                    az = az.strip()
                    if not az:
                        continue
                    try:
                        value = float(az.replace('°', ''))
                        if 0 <= value <= 360:
                            azimuths.append(value)
                    except ValueError:
                        logging.warning("Invalid azimuth '%s' in %s", az, csv_file)
    except Exception as exc:
        logging.error("Error reading %s: %s", csv_file, exc)

    logging.info("Loaded %d azimuths for StationId %s", len(azimuths), station_id)
    return azimuths


def build_map(user_location: tuple, filtered_df: pd.DataFrame, radius_km: int) -> str:
    user_lat, user_lon = user_location
    map_ = folium.Map(location=[user_lat, user_lon], zoom_start=12, tiles='CartoDB positron')

    folium.Marker(
        [user_lat, user_lon],
        tooltip="Podany adres",
        icon=folium.Icon(color="blue", icon="info-sign"),
    ).add_to(map_)

    operator_colors = OPERATOR_COLORS_DISPLAY
    length = 0.01 * (radius_km / 2)

    for (lat, lon), group in filtered_df.groupby(['LATIuke', 'LONGuke']):
        station_ids = group['StationId'].unique()
        if not len(station_ids):
            continue
        station_id = station_ids[0]
        operators = group['siec_id'].unique()

        operator_info = []
        color_blocks = []
        for operator, sub_group in group.groupby('siec_id'):
            bands = sub_group.groupby('pasmo')['standard'].apply(lambda x: ', '.join(x.unique()))
            details = [f"{pasmo} ({tech})" for pasmo, tech in bands.items()]
            operator_info.append(f"{operator}: " + '; '.join(details))
            color = operator_colors.get(operator, 'blue')
            color_blocks.append(f'<div style="flex:1;background-color:{color};"></div>')

        icon_html = (
            f'<div style="width:30px;height:30px;display:flex;'
            f'border-radius:50%;border:2px solid #000;">{"".join(color_blocks)}</div>'
        )
        folium.Marker(
            [lat, lon],
            tooltip='<br>'.join(operator_info),
            icon=folium.DivIcon(html=icon_html),
        ).add_to(map_)

        azimuths = load_azimuth_data(station_id)
        if not azimuths:
            continue

        for i, operator in enumerate(operators):
            line_color = operator_colors.get(operator, 'red')
            offset = (i - len(operators) / 2) * 0.00005
            for azimuth in azimuths:
                start_lat = lat + offset * cos(radians(azimuth + 90))
                start_lon = lon + offset * sin(radians(azimuth + 90))
                end_lat = start_lat + length * cos(radians(azimuth))
                end_lon = start_lon + length * sin(radians(azimuth))
                coords = [[start_lat, start_lon], [end_lat, end_lon]]
                tip = f'Operator: {operator}, Azymut: {azimuth}°'
                folium.PolyLine(coords, weight=4, color='black', opacity=0.8, tooltip=tip).add_to(map_)
                folium.PolyLine(coords, weight=2, color=line_color, opacity=0.8, tooltip=tip).add_to(map_)

    buf = io.BytesIO()
    map_.save(buf, close_file=False)
    return buf.getvalue().decode()