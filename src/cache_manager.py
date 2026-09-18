"""
Módulo de Gestión y Limpieza de Caché de Cálculos para intervals_fit_analytics.
Permite inspeccionar el estado y tamaño de los archivos temporales y de caché,
así como purgarlos de manera segura sin comprometer la base de datos histórica
ni los archivos de configuración del equipo.
"""

import os
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from config import DATA_DIR, BASE_DIR
except (ImportError, ValueError):
    from ..config import DATA_DIR, BASE_DIR

logger = logging.getLogger(__name__)

# Rutas estándar de almacenamiento de caché de cálculo
TODAY_RACE_DIR = DATA_DIR / "today_race"
YESTERDAY_RACE_DIR = DATA_DIR / "yesterday_race"
WEATHER_CACHE_DIR = DATA_DIR / "weather_cache"
HISTORICAL_PEAKS_CACHE_FILE = DATA_DIR / "cache" / "historical_peaks_cache.json"
SCRATCH_DIR = BASE_DIR / "scratch"


def formatear_bytes(num_bytes: int) -> str:
    """Convierte una cantidad de bytes a una representación legible (B, KB, MB, GB)."""
    if num_bytes < 1024:
        return f"{num_bytes} B"
    elif num_bytes < 1024 * 1024:
        return f"{num_bytes / 1024:.1f} KB"
    elif num_bytes < 1024 * 1024 * 1024:
        return f"{num_bytes / (1024 * 1024):.2f} MB"
    return f"{num_bytes / (1024 * 1024 * 1024):.2f} GB"


def obtener_estado_cache() -> Dict[str, Any]:
    """
    Inspecciona todas las rutas de caché de cálculos y devuelve métricas
    detalladas de recuento de ficheros y espacio consumido en disco.
    """
    # 1. Archivos FIT en today_race y yesterday_race
    fits_files: List[Path] = []
    fits_bytes = 0
    vistos_fits = set()
    for folder in [TODAY_RACE_DIR, YESTERDAY_RACE_DIR]:
        if folder.exists() and folder.is_dir():
            for p in folder.iterdir():
                if p.is_file() and p.suffix.lower() == ".fit":
                    res_p = str(p.resolve()).lower()
                    if res_p not in vistos_fits:
                        vistos_fits.add(res_p)
                        fits_files.append(p)
                        try:
                            fits_bytes += p.stat().st_size
                        except OSError:
                            pass

    # 2. Caché meteorológica (Open-Meteo)
    weather_files: List[Path] = []
    weather_bytes = 0
    if WEATHER_CACHE_DIR.exists() and WEATHER_CACHE_DIR.is_dir():
        for p in WEATHER_CACHE_DIR.iterdir():
            if p.is_file() and p.suffix.lower() == ".json":
                weather_files.append(p)
                try:
                    weather_bytes += p.stat().st_size
                except OSError:
                    pass

    # 3. Caché de picos históricos y fatiga previa (historical_peaks_cache.json)
    peaks_bytes = 0
    peaks_actividades = 0
    peaks_activo = False
    if HISTORICAL_PEAKS_CACHE_FILE.exists() and HISTORICAL_PEAKS_CACHE_FILE.is_file():
        try:
            peaks_bytes = HISTORICAL_PEAKS_CACHE_FILE.stat().st_size
            with open(HISTORICAL_PEAKS_CACHE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    peaks_actividades = len(data)
                    peaks_activo = peaks_actividades > 0
        except Exception as e:
            logger.warning(f"Error leyendo historical_peaks_cache.json: {e}")

    # 4. Archivos temporales de pruebas y desarrollo en scratch/
    scratch_files: List[Path] = []
    scratch_bytes = 0
    if SCRATCH_DIR.exists() and SCRATCH_DIR.is_dir():
        for p in SCRATCH_DIR.iterdir():
            if p.is_file() and p.suffix.lower() in [".pkl", ".fit", ".png"]:
                scratch_files.append(p)
                try:
                    scratch_bytes += p.stat().st_size
                except OSError:
                    pass

    total_bytes = fits_bytes + weather_bytes + peaks_bytes + scratch_bytes
    total_archivos = len(fits_files) + len(weather_files) + (1 if peaks_activo else 0) + len(scratch_files)

    return {
        "total_archivos": total_archivos,
        "total_bytes": total_bytes,
        "total_tamano_kb": round(total_bytes / 1024, 1),
        "total_tamano_mb": round(total_bytes / (1024 * 1024), 2),
        "total_tamano_str": formatear_bytes(total_bytes),
        "categorias": {
            "fits": {
                "nombre": "Telemetría FIT local (today_race)",
                "num_archivos": len(fits_files),
                "bytes": fits_bytes,
                "tamano_str": formatear_bytes(fits_bytes)
            },
            "clima": {
                "nombre": "Caché meteorológica (Open-Meteo)",
                "num_archivos": len(weather_files),
                "bytes": weather_bytes,
                "tamano_str": formatear_bytes(weather_bytes)
            },
            "picos": {
                "nombre": "Picos de potencia y fatiga (kJ)",
                "num_actividades": peaks_actividades,
                "bytes": peaks_bytes,
                "tamano_str": formatear_bytes(peaks_bytes),
                "activo": peaks_activo
            },
            "scratch": {
                "nombre": "Archivos temporales (scratch)",
                "num_archivos": len(scratch_files),
                "bytes": scratch_bytes,
                "tamano_str": formatear_bytes(scratch_bytes)
            }
        }
    }


def limpiar_cache_calculos(
    limpiar_fits: bool = True,
    limpiar_clima: bool = True,
    limpiar_picos: bool = True,
    limpiar_scratch: bool = True
) -> Dict[str, Any]:
    """
    Elimina los archivos de caché utilizados en cálculos numéricos.
    Devuelve un reporte con la cantidad de elementos eliminados y bytes liberados.
    """
    eliminados = 0
    bytes_liberados = 0
    detalles: Dict[str, Any] = {
        "fits_eliminados": 0,
        "clima_eliminados": 0,
        "picos_reseteados": False,
        "scratch_eliminados": 0
    }

    # 1. Limpiar .fit en today_race y yesterday_race
    if limpiar_fits:
        vistos_fits = set()
        for folder in [TODAY_RACE_DIR, YESTERDAY_RACE_DIR]:
            if folder.exists() and folder.is_dir():
                for p in folder.iterdir():
                    if p.is_file() and p.suffix.lower() == ".fit":
                        res_p = str(p.resolve()).lower()
                        if res_p not in vistos_fits:
                            vistos_fits.add(res_p)
                            try:
                                tam = p.stat().st_size
                                p.unlink()
                                eliminados += 1
                                bytes_liberados += tam
                                detalles["fits_eliminados"] += 1
                            except OSError as e:
                                logger.warning(f"No se pudo eliminar archivo FIT {p}: {e}")

    # 2. Limpiar JSONs de clima
    if limpiar_clima:
        if WEATHER_CACHE_DIR.exists() and WEATHER_CACHE_DIR.is_dir():
            for p in WEATHER_CACHE_DIR.iterdir():
                if p.is_file() and p.suffix.lower() == ".json":
                    try:
                        tam = p.stat().st_size
                        p.unlink()
                        eliminados += 1
                        bytes_liberados += tam
                        detalles["clima_eliminados"] += 1
                    except OSError as e:
                        logger.warning(f"No se pudo eliminar caché clima {p}: {e}")

    # 3. Resetear historical_peaks_cache.json a {}
    if limpiar_picos:
        if HISTORICAL_PEAKS_CACHE_FILE.exists() and HISTORICAL_PEAKS_CACHE_FILE.is_file():
            try:
                tam = HISTORICAL_PEAKS_CACHE_FILE.stat().st_size
                HISTORICAL_PEAKS_CACHE_FILE.write_text("{}", encoding="utf-8")
                bytes_liberados += max(0, tam - 2)
                detalles["picos_reseteados"] = True
                eliminados += 1
            except OSError as e:
                logger.warning(f"No se pudo resetear {HISTORICAL_PEAKS_CACHE_FILE}: {e}")

    # 4. Limpiar temporales en scratch
    if limpiar_scratch:
        if SCRATCH_DIR.exists() and SCRATCH_DIR.is_dir():
            for p in SCRATCH_DIR.iterdir():
                if p.is_file() and p.suffix.lower() in [".pkl", ".fit", ".png"]:
                    try:
                        tam = p.stat().st_size
                        p.unlink()
                        eliminados += 1
                        bytes_liberados += tam
                        detalles["scratch_eliminados"] += 1
                    except OSError as e:
                        logger.warning(f"No se pudo eliminar temporal {p}: {e}")

    return {
        "status": "ok",
        "mensaje": f"Caché limpiada con éxito: {eliminados} archivos procesados, {formatear_bytes(bytes_liberados)} liberados.",
        "archivos_eliminados": eliminados,
        "bytes_liberados": bytes_liberados,
        "bytes_liberados_str": formatear_bytes(bytes_liberados),
        "detalles": detalles
    }
