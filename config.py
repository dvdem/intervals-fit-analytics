"""
Módulo de Configuración Central para intervals_fit_analytics.
Carga variables de entorno, gestiona rutas y define constantes físicas y de conexión.
"""

import os
import sys
from pathlib import Path
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


def cargar_roster(ruta_csv: Path | str = None) -> pd.DataFrame:
    """
    Carga el archivo CSV de metadatos de los ciclistas (ej. burgos.csv).
    Garantiza columnas estándar: Name, intervals_id, weight, FTP, carrera.
    """
    if ruta_csv is None:
        ruta_csv = DEFAULT_ROSTER_PATH
    
    ruta = Path(ruta_csv)
    if not ruta.exists():
        # Retornar dataframe vacío si no existe
        return pd.DataFrame(columns=["Name", "intervals_id", "weight", "FTP", "carrera"])
    
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
        
    return df
