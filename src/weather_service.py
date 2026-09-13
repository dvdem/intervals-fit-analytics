"""
Módulo de Servicios Meteorológicos y Aerodinámica Ambiental para intervals_fit_analytics.
Proporciona:
1. Cálculo riguroso de densidad del aire (ρ) basado en temperatura, altitud/presión y humedad (Buck equation).
2. Estimación del rumbo (bearing/azimut) del ciclista a partir de coordenadas GPS.
3. Descarga y caché de meteorología histórica y en tiempo real desde Open-Meteo API.
4. Modelado vectorial del viento relativo: viento efectivo frontal/cola (headwind/tailwind), lateral (crosswind),
   ángulo de guiñada aparente (yaw angle) y velocidad aparente del aire (v_air).
"""

import json
import logging
import math
import urllib.request
import urllib.error
from datetime import datetime, date
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np
import pandas as pd

from config import DATA_DIR

logger = logging.getLogger(__name__)

WEATHER_CACHE_DIR = DATA_DIR / "weather_cache"
WEATHER_CACHE_DIR.mkdir(parents=True, exist_ok=True)

# Constantes físicas termodinámicas
R_DRY_AIR = 287.058     # Constante del gas para aire seco (J / (kg · K))
R_VAPOR = 461.495       # Constante del gas para vapor de agua (J / (kg · K))
P0_SEA_LEVEL = 101325.0 # Presión estándar a nivel del mar (Pa)
ISA_EXP = 5.25588       # Exponente barométrico troposférico ISA
ISA_RATE = 0.0000225577 # Gradiente barométrico ISA (1/m)

# Direcciones cardinales estándar
CARDINAL_DIRS = [
    "N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
    "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"
]


def deg_to_cardinal(degrees: float) -> str:
    """Convierte un ángulo en grados (0-360°) a su dirección cardinal (e.g., 'N', 'NE', 'SW')."""
    if degrees is None or math.isnan(degrees):
        return "--"
    idx = int((degrees + 11.25) / 22.5) % 16
    return CARDINAL_DIRS[idx]


def estimar_presion_isa(altitud_m: Union[float, np.ndarray, pd.Series]) -> Union[float, np.ndarray, pd.Series]:
    """
    Estima la presión barométrica (en Pa) en función de la altitud (en metros)
    utilizando el modelo de la Atmósfera Estándar Internacional (ISA).
    """
    if isinstance(altitud_m, (pd.Series, np.ndarray)):
        alt_clean = np.maximum(0.0, altitud_m)
        return P0_SEA_LEVEL * (1.0 - ISA_RATE * alt_clean) ** ISA_EXP
    alt_clean = max(0.0, float(altitud_m))
    return P0_SEA_LEVEL * (1.0 - ISA_RATE * alt_clean) ** ISA_EXP


def calcular_rho_preciso(
    temperatura_c: Union[float, np.ndarray, pd.Series],
    altitud_m: Union[float, np.ndarray, pd.Series],
    humedad_rel_pct: Union[float, np.ndarray, pd.Series] = 50.0,
    presion_pa: Optional[Union[float, np.ndarray, pd.Series]] = None
) -> Union[float, np.ndarray, pd.Series]:
    """
    Calcula la densidad real del aire (ρ en kg/m³) mediante la formulación termodinámica de dos componentes
    (aire seco + vapor de agua) y la ecuación de Buck para la presión de vapor saturado:
    
      P_sat(T) = 611.21 · exp((18.678 - T / 234.4) · (T / (257.14 + T)))  [Pa]
      P_v = (HR / 100) · P_sat
      P_d = P_total - P_v
      ρ = (P_d / (R_d · T_K)) + (P_v / (R_v · T_K))
    """
    t_c = temperatura_c
    t_k = t_c + 273.15

    # Si no se proporciona presión medida de superficie, estimar barométricamente por altitud
    if presion_pa is None:
        p_total = estimar_presion_isa(altitud_m)
    else:
        p_total = presion_pa

    # Presión de vapor de saturación de Buck en Pa
    if isinstance(t_c, (pd.Series, np.ndarray)):
        p_sat = 611.21 * np.exp((18.678 - t_c / 234.4) * (t_c / (257.14 + t_c)))
        hr_frac = np.clip(humedad_rel_pct / 100.0, 0.0, 1.0)
    else:
        p_sat = 611.21 * math.exp((18.678 - t_c / 234.4) * (t_c / (257.14 + t_c)))
        hr_frac = min(1.0, max(0.0, humedad_rel_pct / 100.0))

    p_v = hr_frac * p_sat
    p_d = p_total - p_v

    rho = (p_d / (R_DRY_AIR * t_k)) + (p_v / (R_VAPOR * t_k))
    return rho


def calcular_bearing_ciclista(lat: np.ndarray, lon: np.ndarray) -> np.ndarray:
    """
    Calcula el rumbo (heading/bearing en grados [0, 360)) del ciclista entre puntos GPS sucesivos.
    Aplica suavizado angular para reducir el ruido por fluctuaciones de GPS.
    """
    n = len(lat)
    if n < 2:
        return np.zeros(n, dtype=float)

    lat_rad = np.radians(lat)
    lon_rad = np.radians(lon)

    dlon = np.zeros(n, dtype=float)
    dlon[:-1] = lon_rad[1:] - lon_rad[:-1]
    dlon[-1] = dlon[-2] if n > 1 else 0.0

    lat_next = np.zeros(n, dtype=float)
    lat_next[:-1] = lat_rad[1:]
    lat_next[-1] = lat_rad[-1]

    y = np.sin(dlon) * np.cos(lat_next)
    x = np.cos(lat_rad) * np.sin(lat_next) - np.sin(lat_rad) * np.cos(lat_next) * np.cos(dlon)

    bearing_rad = np.arctan2(y, x)
    bearing_deg = (np.degrees(bearing_rad) + 360.0) % 360.0

    # Suavizado angular de rumbos consecutivos (vector sum smoothing)
    # Evita saltos de 359° a 1°
    window = min(15, max(3, n // 50))
    sin_b = pd.Series(np.sin(np.radians(bearing_deg))).rolling(window=window, min_periods=1, center=True).mean().values
    cos_b = pd.Series(np.cos(np.radians(bearing_deg))).rolling(window=window, min_periods=1, center=True).mean().values
    bearing_smooth = (np.degrees(np.arctan2(sin_b, cos_b)) + 360.0) % 360.0

    return bearing_smooth


def calcular_viento_efectivo(
    v_bici_ms: np.ndarray,
    bearing_ciclista_deg: np.ndarray,
    wind_speed_ms: Union[float, np.ndarray],
    wind_direction_deg: Union[float, np.ndarray]
) -> Dict[str, np.ndarray]:
    """
    Proyecta el vector del viento sobre el avance del ciclista:
    
    1. Ángulo relativo β: dirección desde donde sopla el viento vs rumbo del ciclista.
       β = 0°  -> Viento frontal directo (headwind en contra pura).
       β = 180° -> Viento de cola directo (tailwind a favor pura).
       β = 90° / 270° -> Viento lateral perpendicular puro (crosswind).
    
    2. Headwind / Tailwind:
       v_headwind = wind_speed · cos(rad(β))   (Positivo = en contra, Negativo = a favor)
    
    3. Crosswind (Viento lateral):
       v_crosswind = wind_speed · sin(rad(β))
    
    4. Velocidad aparente del aire (v_air):
       v_air = sqrt((v_bici + v_headwind)^2 + v_crosswind^2)
    
    5. Ángulo de guiñada aparente (Yaw angle ψ):
       ψ = arctan2(v_crosswind, v_bici + v_headwind)
    """
    beta_rad = np.radians((wind_direction_deg - bearing_ciclista_deg) % 360.0)

    # Componente longitudinal en la dirección de la marcha (+ = headwind / contra, - = tailwind / favor)
    v_headwind = wind_speed_ms * np.cos(beta_rad)
    # Componente lateral perpendicular
    v_crosswind = wind_speed_ms * np.sin(beta_rad)

    # Velocidad longitudinal aparente hacia el ciclista
    v_longitudinal_aparente = np.maximum(0.0, v_bici_ms + v_headwind)

    # Magnitud total de la corriente de aire aparente
    v_air = np.sqrt(v_longitudinal_aparente ** 2 + v_crosswind ** 2)

    # Ángulo de guiñada aparente en grados
    yaw_deg = np.degrees(np.arctan2(np.abs(v_crosswind), np.maximum(0.1, v_longitudinal_aparente)))

    return {
        'v_headwind_ms': v_headwind,
        'v_crosswind_ms': v_crosswind,
        'v_air_ms': v_air,
        'yaw_deg': yaw_deg,
    }


def obtener_clima_open_meteo(
    lat: float,
    lon: float,
    fecha: Union[str, date, datetime],
    cache_dir: Optional[Path] = None
) -> Optional[Dict[str, Any]]:
    """
    Descarga información meteorológica horaria desde Open-Meteo API.
    Aplica caché local para evitar consultas repetidas sobre las mismas coordenadas y fechas.
    
    Parámetros obtenidos:
    - temperature_2m (°C)
    - relative_humidity_2m (%)
    - surface_pressure (hPa)
    - wind_speed_10m (m/s)
    - wind_direction_10m (grados)
    - wind_gusts_10m (m/s)
    """
    if cache_dir is None:
        cache_dir = WEATHER_CACHE_DIR

    # Formatear fecha a YYYY-MM-DD
    if isinstance(fecha, datetime):
        fecha_str = fecha.strftime("%Y-%m-%d")
        fecha_obj = fecha.date()
    elif isinstance(fecha, date):
        fecha_str = fecha.strftime("%Y-%m-%d")
        fecha_obj = fecha
    elif isinstance(fecha, str):
        fecha_str = fecha[:10]
        try:
            fecha_obj = datetime.strptime(fecha_str, "%Y-%m-%d").date()
        except ValueError:
            logger.warning(f"Formato de fecha inválido para Open-Meteo: {fecha}")
            return None
    else:
        return None

    # Redondear coordenadas a 2 decimales (~1.1 km) para optimizar el acierto en caché
    lat_r = round(lat, 2)
    lon_r = round(lon, 2)
    cache_file = cache_dir / f"weather_{fecha_str}_{lat_r}_{lon_r}.json"

    if cache_file.exists():
        try:
            with open(cache_file, "r", encoding="utf-8") as f:
                cached_data = json.load(f)
                return cached_data
        except Exception as e:
            logger.warning(f"Error leyendo caché de clima {cache_file}: {e}")

    # Determinar si usar Archive API o Forecast API
    hoy = date.today()
    hourly_vars = "temperature_2m,relative_humidity_2m,surface_pressure,wind_speed_10m,wind_direction_10m,wind_gusts_10m"

    if fecha_obj < hoy:
        url = (
            f"https://archive-api.open-meteo.com/v1/archive?"
            f"latitude={lat_r}&longitude={lon_r}&start_date={fecha_str}&end_date={fecha_str}"
            f"&hourly={hourly_vars}&wind_speed_unit=ms&timezone=auto"
        )
    else:
        url = (
            f"https://api.open-meteo.com/v1/forecast?"
            f"latitude={lat_r}&longitude={lon_r}&hourly={hourly_vars}"
            f"&wind_speed_unit=ms&past_days=2&forecast_days=2&timezone=auto"
        )

    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'IntervalsFitAnalytics/1.0'})
        with urllib.request.urlopen(req, timeout=8) as response:
            if response.status == 200:
                raw_json = json.loads(response.read().decode('utf-8'))
                hourly = raw_json.get("hourly", {})
                if not hourly or "time" not in hourly:
                    return None

                # Extraer y calcular resumen del día
                times = hourly.get("time", [])
                temps = [t for t in hourly.get("temperature_2m", []) if t is not None]
                humeds = [h for h in hourly.get("relative_humidity_2m", []) if h is not None]
                pressures = [p for p in hourly.get("surface_pressure", []) if p is not None]
                winds = [w for w in hourly.get("wind_speed_10m", []) if w is not None]
                wind_dirs = [d for d in hourly.get("wind_direction_10m", []) if d is not None]
                gusts = [g for g in hourly.get("wind_gusts_10m", []) if g is not None]

                media_wind_ms = float(np.mean(winds)) if winds else 0.0
                media_wind_kmh = round(media_wind_ms * 3.6, 1)
                max_gust_kmh = round(float(np.max(gusts)) * 3.6, 1) if gusts else media_wind_kmh
                media_temp = round(float(np.mean(temps)), 1) if temps else 20.0
                media_hum = round(float(np.mean(humeds)), 1) if humeds else 50.0
                media_press = round(float(np.mean(pressures)), 1) if pressures else 1013.25

                # Dirección media del viento mediante media circular
                if wind_dirs:
                    sin_sum = sum(math.sin(math.radians(d)) for d in wind_dirs)
                    cos_sum = sum(math.cos(math.radians(d)) for d in wind_dirs)
                    media_dir_deg = round((math.degrees(math.atan2(sin_sum, cos_sum)) + 360.0) % 360.0, 1)
                else:
                    media_dir_deg = 0.0

                processed = {
                    'fuente': 'Open-Meteo',
                    'fecha': fecha_str,
                    'lat': lat_r,
                    'lon': lon_r,
                    'temp_media_c': media_temp,
                    'humedad_media_pct': media_hum,
                    'presion_media_hpa': media_press,
                    'viento_media_ms': round(media_wind_ms, 2),
                    'viento_media_kmh': media_wind_kmh,
                    'viento_dir_deg': media_dir_deg,
                    'viento_cardinal': deg_to_cardinal(media_dir_deg),
                    'viento_rafagas_max_kmh': max_gust_kmh,
                    'hourly': hourly
                }

                # Guardar en caché
                try:
                    with open(cache_file, "w", encoding="utf-8") as f:
                        json.dump(processed, f, indent=2, ensure_ascii=False)
                except Exception as e:
                    logger.warning(f"No se pudo guardar la caché de clima: {e}")

                return processed

    except Exception as e:
        logger.warning(f"No se pudo descargar información climática de Open-Meteo ({url}): {e}")
        return None

    return None
