"""
Módulo de Configuración Central para intervals_fit_analytics.
Carga variables de entorno, gestiona rutas y define constantes físicas y de conexión.
"""

import os
import sys
from pathlib import Path
from typing import Any, Optional, Union
import pandas as pd
from dotenv import load_dotenv

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

# Directorio raíz del proyecto
BASE_DIR = Path(__file__).resolve().parent

# Cargar variables de entorno desde .env si existe
env_path = BASE_DIR / ".env"
if env_path.exists():
    load_dotenv(dotenv_path=env_path)

# Configuración de Intervals.icu API
INTERVALS_API_KEY = os.getenv("INTERVALS_API_KEY", "1347lyp9p4meza7lyd3sar4qu")
INTERVALS_ATHLETE_ID = os.getenv("INTERVALS_ATHLETE_ID", "0")
INTERVALS_BASE_URL = os.getenv("INTERVALS_BASE_URL", "https://intervals.icu/api/v1")

# Credenciales web opcionales para descarga de actividades Strava vía sesión
INTERVALS_LOGIN_EMAIL = os.getenv("INTERVALS_LOGIN_EMAIL", "echavarri.david@gmail.com")
INTERVALS_LOGIN_PASSWORD = os.getenv("INTERVALS_LOGIN_PASSWORD", "Ciclomotor.01")
INTERVALS_SESSION_COOKIE = os.getenv("INTERVALS_SESSION_COOKIE", "")

# Rutas estándar del proyecto
DATA_DIR = BASE_DIR / "data"
OUTPUT_DIR = BASE_DIR / "output"
ASSETS_DIR = BASE_DIR / "assets"
NOTEBOOKS_DIR = BASE_DIR / "notebooks"

DEFAULT_ROSTER_PATH = DATA_DIR / "burgos.csv"
DEFAULT_LOGO_PATH = ASSETS_DIR / "LOGO.svg" if (ASSETS_DIR / "LOGO.svg").exists() else (ASSETS_DIR / "LOGO.png")

# Asegurar que los directorios existan
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
DATA_DIR.mkdir(parents=True, exist_ok=True)
ASSETS_DIR.mkdir(parents=True, exist_ok=True)

# Constantes físicas por defecto para modelado de potencia
DEFAULT_AIR_DENSITY = 1.15      # rho en kg/m³ (aprox. a cierta altitud / temperatura templada)
DEFAULT_GRAVITY = 9.81          # g en m/s²
DEFAULT_DRIVETRAIN_EFF = 0.97   # Eficiencia transmisión (97%)
DEFAULT_BIKE_WEIGHT = 8.0       # Peso estándar de la bicicleta en kg
DEFAULT_RIDER_WEIGHT = 70.0     # Peso estándar del ciclista si no hay dato

# Duraciones estándar para picos de potencia
DEFAULT_PEAK_DURATIONS = {
    5: "5s",
    30: "30s",
    60: "1m",
    300: "5m",
    600: "10m",
    1200: "20m"
}

# Constantes para análisis biomecánico y de torque
DEFAULT_CRANK_LENGTH = 0.1700               # Longitud de biela estándar en metros (170 mm)
DEFAULT_QUADRANT_CADENCE_THRESH = 85.0       # Cadencia umbral para análisis de cuadrantes (rpm)
DEFAULT_TORQUE_PEAK_DURATIONS = {
    1: "1s",
    5: "5s",
    10: "10s",
    30: "30s",
    60: "1m",
    300: "5m",
    1200: "20m"
}

# Duraciones estándar para la Curva de Potencia completa (Power Duration Curve / MMP)
DEFAULT_POWER_DURATION_CURVE_DURATIONS = {
    1: "1s",
    5: "5s",
    10: "10s",
    15: "15s",
    30: "30s",
    60: "1m",
    120: "2m",
    180: "3m",
    300: "5m",
    600: "10m",
    1200: "20m",
    1800: "30m",
    3600: "60m"
}


def normalizar_crank_length_m(val: Any) -> float:
    """
    Convierte una longitud de biela (en mm o metros) a metros (float).
    Si no tiene valor o es inválido, devuelve DEFAULT_CRANK_LENGTH.
    Ejemplos: 165 -> 0.165, 170 -> 0.170, 172.5 -> 0.1725, 175 -> 0.175, 0.17 -> 0.17.
    """
    try:
        if val is None:
            return DEFAULT_CRANK_LENGTH
        v = float(val)
        if pd.isna(v) or v <= 0:
            return DEFAULT_CRANK_LENGTH
        if v > 10.0:  # Expresada en milímetros (ej. 165, 170, 172.5, 175)
            return round(v / 1000.0, 4)
        return round(v, 4)  # Ya expresada en metros (ej. 0.170)
    except (ValueError, TypeError):
        return DEFAULT_CRANK_LENGTH


def cargar_roster(ruta_csv: Path | str = None) -> pd.DataFrame:
    """
    Carga el archivo CSV de metadatos de los ciclistas (ej. burgos.csv).
    Garantiza columnas estándar: Name, intervals_id, weight, FTP, carrera, biela, crank_length_m.
    """
    if ruta_csv is None:
        ruta_csv = DEFAULT_ROSTER_PATH
    
    ruta = Path(ruta_csv)
    if not ruta.exists():
        # Retornar dataframe vacío si no existe
        return pd.DataFrame(columns=["Name", "intervals_id", "weight", "FTP", "carrera", "biela", "crank_length_m"])
    
    try:
        # Detectar delimitador (; o ,)
        df = pd.read_csv(ruta, sep=None, engine='python')
    except Exception:
        df = pd.read_csv(ruta, sep=';')
        
    if 'intervals_id' in df.columns:
        df['intervals_id'] = df['intervals_id'].astype(str).str.strip()
    if 'Name' in df.columns:
        df['Name'] = df['Name'].astype(str).str.strip()
    if 'weight' in df.columns:
        df['weight'] = pd.to_numeric(df['weight'], errors='coerce')
    if 'FTP' in df.columns:
        df['FTP'] = pd.to_numeric(df['FTP'], errors='coerce')
    if 'carrera' in df.columns:
        df['carrera'] = pd.to_numeric(df['carrera'], errors='coerce').fillna(0).astype(int)

    # Buscar columna de bielas / biela (en mm)
    col_biela = None
    for cand in ['bielas', 'biela', 'crank_length', 'crank_length_mm', 'crank']:
        if cand in df.columns:
            col_biela = cand
            break
        cand_lower = cand.lower()
        for col in df.columns:
            if str(col).strip().lower() == cand_lower:
                col_biela = col
                break
        if col_biela:
            break

    if col_biela:
        df['crank_length_m'] = df[col_biela].apply(normalizar_crank_length_m)
        df['biela'] = pd.to_numeric(df[col_biela], errors='coerce').fillna(round(df['crank_length_m'] * 1000.0, 1))
    else:
        df['crank_length_m'] = DEFAULT_CRANK_LENGTH
        df['biela'] = round(DEFAULT_CRANK_LENGTH * 1000.0, 1)

    return df


def obtener_crank_length_ciclista(
    identificador: Optional[Union[str, int]] = None,
    roster_df: Optional[pd.DataFrame] = None
) -> float:
    """
    Obtiene la longitud de biela en metros (crank_length_m) para un ciclista a partir de burgos.csv.
    Puede buscar por 'intervals_id' o por 'Name'.
    Si no tiene valor o no se encuentra, retorna DEFAULT_CRANK_LENGTH.
    """
    if identificador is None:
        return DEFAULT_CRANK_LENGTH

    if roster_df is None:
        roster_df = cargar_roster()

    if roster_df.empty:
        return DEFAULT_CRANK_LENGTH

    ident_str = str(identificador).strip().lower()

    # Buscar por intervals_id
    if 'intervals_id' in roster_df.columns:
        match = roster_df[roster_df['intervals_id'].astype(str).str.strip().str.lower() == ident_str]
        if not match.empty and 'crank_length_m' in match.columns:
            val = match.iloc[0]['crank_length_m']
            if pd.notna(val) and float(val) > 0:
                return float(val)

    # Buscar por Name
    if 'Name' in roster_df.columns:
        match = roster_df[roster_df['Name'].astype(str).str.strip().str.lower() == ident_str]
        if not match.empty and 'crank_length_m' in match.columns:
            val = match.iloc[0]['crank_length_m']
            if pd.notna(val) and float(val) > 0:
                return float(val)

    return DEFAULT_CRANK_LENGTH
