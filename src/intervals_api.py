"""
Cliente oficial y modular para la API de Intervals.icu.
Proporciona métodos completos para atletas, actividades, curvas de potencia,
datos de bienestar (wellness/HRV) y descarga de archivos de actividades.
"""

import sys
from pathlib import Path

# Permitir ejecución directa del script o importación modular
_ROOT_DIR = Path(__file__).resolve().parent.parent
if str(_ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(_ROOT_DIR))

import time
from datetime import datetime, timedelta
from io import StringIO
from typing import Any, Dict, List, Optional, Tuple, Union
import requests
from requests.auth import HTTPBasicAuth
import pandas as pd

try:
    from config import (
        INTERVALS_API_KEY,
        INTERVALS_BASE_URL,
        INTERVALS_LOGIN_EMAIL,
        INTERVALS_LOGIN_PASSWORD,
        INTERVALS_SESSION_COOKIE
    )
except (ImportError, ValueError):
    from ..config import (
        INTERVALS_API_KEY,
        INTERVALS_BASE_URL,
        INTERVALS_LOGIN_EMAIL,
        INTERVALS_LOGIN_PASSWORD,
        INTERVALS_SESSION_COOKIE
    )


class IntervalsClient:
    """Cliente para interactuar con la API REST de Intervals.icu."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: int = 25,
        max_retries: int = 3,
        backoff_factor: float = 1.0,
    ):
        self.api_key = api_key or INTERVALS_API_KEY
        if not self.api_key:
            raise ValueError(
                "No se ha especificado INTERVALS_API_KEY. "
                "Define la variable en tu archivo .env o pásala al constructor."
            )
        self.base_url = (base_url or INTERVALS_BASE_URL).rstrip("/")
        self.auth = HTTPBasicAuth("API_KEY", self.api_key)
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff_factor = backoff_factor
        self.session = requests.Session()
        self.session.auth = self.auth

    def _request(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        json_data: Optional[Dict[str, Any]] = None,
        stream: bool = False,
    ) -> requests.Response:
        """Realiza una petición HTTP con reintentos y retroceso exponencial."""
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        ultimo_error = None

        for intento in range(1, self.max_retries + 1):
            try:
                response = self.session.request(
                    method=method,
                    url=url,
                    params=params,
                    json=json_data,
                    timeout=self.timeout,
                    stream=stream,
                )
                if response.status_code == 429:
                    # Rate limit alcanzado
                    wait_time = self.backoff_factor * (2 ** (intento - 1))
                    time.sleep(wait_time)
                    continue

                return response
            except requests.RequestException as e:
                ultimo_error = e
                if intento == self.max_retries:
                    raise RuntimeError(
                        f"Error al conectar con Intervals.icu ({url}) tras {self.max_retries} intentos: {e}"
                    ) from e
                time.sleep(self.backoff_factor * (2 ** (intento - 1)))

        if ultimo_error:
            raise ultimo_error
        raise RuntimeError(f"Fallo de petición inesperado a {url}")

    # =========================================================================
    # Atletas y Resumen
    # =========================================================================

    def get_athlete_summary(self, athlete_id: str = "0") -> List[Dict[str, Any]]:
        """
        Obtiene el resumen del atleta (o la lista de atletas accesibles por el usuario actual '0').
        """
        resp = self._request("GET", f"athlete/{athlete_id}/athlete-summary")
        if resp.status_code == 200:
            data = resp.json()
            return data if isinstance(data, list) else [data]
        raise RuntimeError(f"Error al obtener athlete-summary ({resp.status_code}): {resp.text}")

    def get_athletes_list(self, roster_df: Optional[pd.DataFrame] = None, solo_carrera: bool = False) -> List[Dict[str, Any]]:
        """
        Obtiene la lista consolidada de atletas y cruza los nombres con el roster local si se proporciona.
        Enriquece cada atleta con su número de carrera del roster (campo 'carrera').
        """
        atletas = self.get_athlete_summary("0")
        # Quitar duplicados
        atletas_unicos = list({(a.get('athlete_id'), a.get('athlete_name')): a for a in atletas}.values())

        if roster_df is not None and not roster_df.empty:
            df = roster_df.copy()
            df['intervals_id'] = df['intervals_id'].astype(str).str.strip()
            nombres_map = dict(zip(df['intervals_id'], df['Name']))
            carrera_map = dict(zip(df['intervals_id'], df['carrera'].astype(int))) if 'carrera' in df.columns else {}

            for atleta in atletas_unicos:
                aid = str(atleta.get('athlete_id', '')).strip()
                if aid in nombres_map:
                    atleta['athlete_name'] = nombres_map[aid]
                # Anotar el número de carrera en el dict del atleta
                atleta['carrera'] = carrera_map.get(aid, 0)

            if solo_carrera and 'carrera' in df.columns:
                # Incluir todos con carrera > 0 (cualquier grupo de competición)
                ids_carrera = set(df.loc[df['carrera'] > 0, 'intervals_id'].astype(str))
                atletas_unicos = [a for a in atletas_unicos if str(a.get('athlete_id', '')).strip() in ids_carrera]

        return atletas_unicos

    def get_athlete_profile(self, athlete_id: str) -> Dict[str, Any]:
        """Obtiene la información de perfil y configuración de un atleta."""
        resp = self._request("GET", f"athlete/{athlete_id}/profile")
        if resp.status_code == 200:
            return resp.json()
        raise RuntimeError(f"Error al obtener perfil del atleta {athlete_id} ({resp.status_code}): {resp.text}")

    # =========================================================================
    # Actividades
    # =========================================================================

    def get_activities(
        self,
        athlete_id: str,
        oldest: Optional[Union[str, datetime]] = None,
        newest: Optional[Union[str, datetime]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Obtiene la lista de actividades de un atleta dentro de un rango de fechas.
        Formato de fechas: 'YYYY-MM-DD' o datetime.
        """
        params = {}
        if oldest:
            params['oldest'] = oldest.strftime('%Y-%m-%d') if isinstance(oldest, datetime) else str(oldest)
        if newest:
            params['newest'] = newest.strftime('%Y-%m-%d') if isinstance(newest, datetime) else str(newest)

        resp = self._request("GET", f"athlete/{athlete_id}/activities", params=params)
        if resp.status_code == 200:
            data = resp.json()
            return data if isinstance(data, list) else []
        return []

    def get_activity_details(self, activity_id: Union[str, int]) -> Dict[str, Any]:
        """Obtiene el detalle completo de una actividad específica."""
        resp = self._request("GET", f"activity/{activity_id}")
        if resp.status_code == 200:
            return resp.json()
        raise RuntimeError(f"Error al obtener actividad {activity_id} ({resp.status_code}): {resp.text}")

    def get_activity_power_curve_csv(self, activity_id: Union[str, int]) -> Optional[pd.DataFrame]:
        """Descarga y devuelve el DataFrame de la curva de potencia de una actividad."""
        resp = self._request("GET", f"activity/{activity_id}/power-curve.csv")
        if resp.status_code != 200:
            return None

        try:
            df = pd.read_csv(StringIO(resp.text))
            cols = {c.lower(): c for c in df.columns}
            sec_col = next((cols[c] for c in cols if 'sec' in c), None)
            watts_col = next((cols[c] for c in cols if 'watt' in c or c == 'w'), None)
            if sec_col and watts_col:
                df[sec_col] = pd.to_numeric(df[sec_col], errors='coerce')
                df[watts_col] = pd.to_numeric(df[watts_col], errors='coerce')
                return df.dropna(subset=[sec_col, watts_col])
        except Exception:
            pass
        return None

    def get_activity_power_curve_json(self, activity_id: Union[str, int]) -> Optional[Dict[str, Any]]:
        """
        Descarga la curva de potencia en JSON de una actividad, incluyendo
        los vectores de secs, watts, start_index y end_index.
        """
        try:
            resp = self._request("GET", f"activity/{activity_id}/power-curve.json")
            if resp.status_code == 200:
                return resp.json()
        except Exception:
            pass
        return None

    def get_activity_streams(
        self,
        activity_id: Union[str, int],
        start_date: Optional[Union[str, datetime]] = None
    ) -> Optional[pd.DataFrame]:
        """
        Descarga los flujos (streams) de telemetría segundo a segundo directamente de Intervals.icu.
        Intervals.icu ya entrega estos datos con los periodos de parada eliminados (tiempo en movimiento).
        Devuelve un DataFrame estandarizado con lat, lon, potencia, velocidad, altitud, cadencia, fc,
        distancia, timestamp, elapsed_seconds y moving_time.
        """
        try:
            resp = self._request("GET", f"activity/{activity_id}/streams")
            if resp.status_code != 200:
                return None

            streams = resp.json()
            if not isinstance(streams, list) or not streams:
                return None

            data_dict = {}
            for s in streams:
                if not isinstance(s, dict):
                    continue
                stype = s.get('type')
                sdata = s.get('data')
                if stype == 'latlng':
                    data_dict['lat'] = sdata
                    data_dict['lon'] = s.get('data2')
                elif stype == 'time':
                    data_dict['elapsed_seconds'] = sdata
                elif stype == 'watts':
                    data_dict['potencia'] = sdata
                elif stype == 'velocity_smooth':
                    data_dict['velocidad'] = sdata
                elif stype == 'cadence':
                    data_dict['cadencia'] = sdata
                elif stype == 'heartrate':
                    data_dict['fc'] = sdata
                elif stype == 'distance':
                    data_dict['distancia'] = sdata
                elif stype == 'altitude':
                    data_dict['altitud'] = sdata
                elif stype == 'temp':
                    data_dict['temperatura'] = sdata

            if not data_dict:
                return None

            df = pd.DataFrame(data_dict)
            if df.empty:
                return None

            # Si no se pasó start_date, intentar obtenerla de los detalles de la actividad
            if start_date is None:
                try:
                    act_meta = self.get_activity_details(activity_id)
                    start_date = act_meta.get('start_date_local') or act_meta.get('start_date')
                except Exception:
                    pass

            if start_date:
                t0 = pd.to_datetime(start_date)
                if 'elapsed_seconds' in df.columns:
                    df['timestamp'] = t0 + pd.to_timedelta(df['elapsed_seconds'], unit='s')
                else:
                    df['timestamp'] = [t0 + timedelta(seconds=i) for i in range(len(df))]
            else:
                t_base = datetime.now()
                if 'elapsed_seconds' in df.columns:
                    df['timestamp'] = t_base + pd.to_timedelta(df['elapsed_seconds'], unit='s')
                else:
                    df['timestamp'] = [t_base + timedelta(seconds=i) for i in range(len(df))]

            ts_series = pd.to_datetime(df['timestamp'])
            if ts_series.dt.tz is not None:
                ts_series = ts_series.dt.tz_convert('UTC').dt.tz_localize(None)
            df['timestamp'] = ts_series

            # Columna de tiempo en movimiento acumulado (1 segundo de movimiento por fila limpia)
            df['moving_time'] = range(1, len(df) + 1)

            # Limpieza básica de tipos
            for col in ['potencia', 'velocidad', 'altitud', 'distancia', 'lat', 'lon']:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors='coerce')

            return df
        except Exception as e:
            print(f"⚠️ Error al obtener streams para la actividad {activity_id}: {e}")
            return None

    def download_activity_file(self, activity_id: Union[str, int], output_path: str) -> bool:
        """
        Descarga el archivo original (.fit / .gpx / .tcx) de una actividad.
        """
        resp = self._request("GET", f"activity/{activity_id}/file", stream=True)
        if resp.status_code == 200:
            with open(output_path, 'wb') as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
            return True
        return False

    def download_activity_fit_via_web_session(
        self,
        activity_id: Union[str, int],
        output_path: Union[str, Path],
        email: Optional[str] = None,
        password: Optional[str] = None,
        session_cookie: Optional[str] = None
    ) -> bool:
        """
        Descarga el archivo FIT generado por Intervals.icu simulando una sesión web autenticada
        (mediante Cookie de sesión o Login con email/password), permitiendo obtener el .fit de actividades
        cuyo origen sea STRAVA (evitando el bloqueo 422 de la API_KEY).
        """
        email = email or INTERVALS_LOGIN_EMAIL
        password = password or INTERVALS_LOGIN_PASSWORD
        session_cookie = session_cookie or INTERVALS_SESSION_COOKIE

        if not session_cookie and not (email and password):
            return False

        if not hasattr(self, '_web_session') or self._web_session is None:
            self._web_session = requests.Session()
            self._web_session.headers.update({
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
                'Accept': 'application/octet-stream, */*',
                'Referer': f"https://intervals.icu/activities/{activity_id}"
            })

            if session_cookie:
                self._web_session.headers['Cookie'] = session_cookie
            elif email and password:
                login_url = f"{self.base_url.replace('/api/v1', '')}/api/login"
                try:
                    login_resp = self._web_session.post(
                        login_url,
                        data={'email': email, 'password': password, 'deviceClass': 'DESKTOP'},
                        timeout=self.timeout
                    )
                    if login_resp.status_code != 200:
                        print(f"⚠️ Fallo al iniciar sesión web en Intervals.icu ({login_resp.status_code}): {login_resp.text}")
                        self._web_session = None
                        return False
                except Exception as e:
                    print(f"⚠️ Error al conectar con login web de Intervals: {e}")
                    self._web_session = None
                    return False

        base_web = self.base_url.replace('/api/v1', '/api')
        fit_url = f"{base_web}/activity/{activity_id}/fit-file?power=true&hr=true"
        try:
            resp = self._web_session.get(fit_url, timeout=self.timeout, stream=True)
            if resp.status_code == 200 and len(resp.content) > 100:
                with open(output_path, 'wb') as f:
                    f.write(resp.content)
                return True
            else:
                self._web_session = None
                return False
        except Exception:
            self._web_session = None
            return False

    # =========================================================================
    # Curvas de Potencia (Power Curves)
    # =========================================================================

    def get_athlete_power_curves(
        self,
        athlete_id: str,
        date_curves: str = "r.2023-01-01.2026-12-31",
        activity_type: str = "Ride",
    ) -> Dict[str, Any]:
        """
        Consulta el endpoint /athlete/{id}/power-curves para obtener las curvas de potencia consolidadas.
        """
        params = {
            "type": activity_type,
            "includeRanks": "true",
            "curves": date_curves
        }
        resp = self._request("GET", f"athlete/{athlete_id}/power-curves", params=params)
        if resp.status_code == 200:
            return resp.json()
        return {}

    # =========================================================================
    # Datos de Bienestar y HRV (Wellness)
    # =========================================================================

    def get_wellness(
        self,
        athlete_id: str,
        oldest: Optional[Union[str, datetime]] = None,
        newest: Optional[Union[str, datetime]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Obtiene los registros diarios de bienestar (HRV RMSSD, SDNN, peso, pulso en reposo, sueño, etc.).
        """
        params = {}
        if oldest:
            params['oldest'] = oldest.strftime('%Y-%m-%d') if isinstance(oldest, datetime) else str(oldest)
        if newest:
            params['newest'] = newest.strftime('%Y-%m-%d') if isinstance(newest, datetime) else str(newest)

        resp = self._request("GET", f"athlete/{athlete_id}/wellness", params=params)
        if resp.status_code == 200:
            data = resp.json()
            return data if isinstance(data, list) else [data]
        return []


if __name__ == '__main__':
    client = IntervalsClient()
    print("🔌 Conectando a Intervals.icu...")
    atletas = client.get_athlete_summary("0")
    print(f"✅ Conexión exitosa. Se encontraron {len(atletas)} atletas.")

