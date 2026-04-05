import logging
import requests


def get_location_from_opencage(address: str, api_key: str):
    url = f'https://api.opencagedata.com/geocode/v1/json?q={address}&key={api_key}'
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
        if data and data['results']:
            result = data['results'][0]
            lat = float(result['geometry']['lat'])
            lon = float(result['geometry']['lng'])
            wojewodztwo = result['components'].get('state')
            logging.info("Geocoded '%s' -> (%s, %s), voivodeship: %s", address, lat, lon, wojewodztwo)
            return (lat, lon), wojewodztwo
        logging.warning("No geocoding results for: %s", address)
        return None, None
    except requests.RequestException as exc:
        logging.error("Geocoding error for '%s': %s", address, exc)
        return None, None