"""
Módulo de Análisis de Archivos FIT y Modelado Físico / Aerodinámico.
Permite leer archivos .fit de potenciómetros/GPS, preprocesar telemetría,
y estimar parámetros aerodinámicos (CdA) y resistencia a la rodadura (Crr).
"""

import sys
from pathlib import Path

# Permitir ejecución directa del script o importación modular
_ROOT_DIR = Path(__file__).resolve().parent.parent
if str(_ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(_ROOT_DIR))

from typing import Dict, Optional, Tuple, Union, Any
import numpy as np
import pandas as pd
from scipy.optimize import minimize
import matplotlib.pyplot as plt
import fitdecode

try:
    from config import (
        DEFAULT_AIR_DENSITY,
        DEFAULT_GRAVITY,
        DEFAULT_DRIVETRAIN_EFF,
        DEFAULT_BIKE_WEIGHT,
        DEFAULT_RIDER_WEIGHT,
        DEFAULT_CRANK_LENGTH
    )
except (ImportError, ValueError):
    from ..config import (
        DEFAULT_AIR_DENSITY,
        DEFAULT_GRAVITY,
        DEFAULT_DRIVETRAIN_EFF,
        DEFAULT_BIKE_WEIGHT,
        DEFAULT_RIDER_WEIGHT,
        DEFAULT_CRANK_LENGTH
    )


def cargar_fit(ruta_archivo: Union[str, Path], permitir_vacio: bool = False) -> pd.DataFrame:
    """
    Lee un archivo .fit y extrae los mensajes 'record' con timestamp, potencia,
    velocidad, altitud, cadencia, frecuencia cardíaca y coordenadas GPS si están presentes.
    Si permitir_vacio=True y el archivo no contiene registros válidos, devuelve un DataFrame vacío.
    """
    ruta = Path(ruta_archivo)
    columnas_estandar = ['timestamp', 'potencia', 'velocidad', 'altitud', 'cadencia', 'fc', 'distancia', 'lat', 'lon', 'temperatura', 'torque', 'aepf']

    if not ruta.exists():
        if permitir_vacio:
            return pd.DataFrame(columns=columnas_estandar)
        raise FileNotFoundError(f"No se encontró el archivo FIT en: {ruta.resolve()}")

    if ruta.stat().st_size < 100:
        if permitir_vacio:
            return pd.DataFrame(columns=columnas_estandar)
        raise ValueError(f"El archivo {ruta.name} está corrupto o incompleto ({ruta.stat().st_size} bytes)")

    registros = []
    try:
        with fitdecode.FitReader(str(ruta)) as fit:
            for frame in fit:
                if isinstance(frame, fitdecode.FitDataMessage) and frame.name == 'record':
                    campos = {campo.name: campo.value for campo in frame.fields}

                    p = campos.get('power', campos.get('enhanced_power'))
                    v = campos.get('enhanced_speed', campos.get('speed'))
                    h = campos.get('enhanced_altitude', campos.get('altitude'))
                    t = campos.get('timestamp')
                    cad = campos.get('cadence')
                    hr = campos.get('heart_rate')
                    dist = campos.get('distance')
                    temp = campos.get('temperature')
                    trq_raw = campos.get('torque', campos.get('crank_torque'))
                    te_l = campos.get('left_torque_effectiveness')
                    te_r = campos.get('right_torque_effectiveness')
                    ps_l = campos.get('left_pedal_smoothness')
                    ps_r = campos.get('right_pedal_smoothness')

                    lat_raw = campos.get('position_lat')
                    lon_raw = campos.get('position_long')
                    # Conversión de semicírculos a grados decimales estándar
                    lat = float(lat_raw) * (180.0 / (2**31)) if (lat_raw is not None and abs(float(lat_raw)) > 180) else (float(lat_raw) if lat_raw is not None else np.nan)
                    lon = float(lon_raw) * (180.0 / (2**31)) if (lon_raw is not None and abs(float(lon_raw)) > 180) else (float(lon_raw) if lon_raw is not None else np.nan)

                    # Guardamos los registros que cuenten al menos con timestamp
                    if t is not None:
                        reg = {
                            'timestamp': pd.to_datetime(t),
                            'potencia': float(p) if p is not None else np.nan,
                            'velocidad': float(v) if v is not None else np.nan,
                            'altitud': float(h) if h is not None else np.nan,
                            'cadencia': float(cad) if cad is not None else np.nan,
                            'fc': float(hr) if hr is not None else np.nan,
                            'distancia': float(dist) if dist is not None else np.nan,
                            'lat': lat,
                            'lon': lon,
                            'temperatura': float(temp) if temp is not None else np.nan,
                        }
                        if trq_raw is not None:
                            reg['torque'] = float(trq_raw)
                        if te_l is not None:
                            reg['left_torque_effectiveness'] = float(te_l)
                        if te_r is not None:
                            reg['right_torque_effectiveness'] = float(te_r)
                        if ps_l is not None:
                            reg['left_pedal_smoothness'] = float(ps_l)
                        if ps_r is not None:
                            reg['right_pedal_smoothness'] = float(ps_r)
                        registros.append(reg)
    except Exception as e:
        if permitir_vacio:
            return pd.DataFrame(columns=columnas_estandar)
        raise ValueError(f"Error al decodificar archivo FIT {ruta.name}: {e}")

    if not registros:
        if permitir_vacio:
            return pd.DataFrame(columns=columnas_estandar)
        raise ValueError(f"No se encontraron registros de telemetría válidos en {ruta.name}")

    df = pd.DataFrame(registros)
    ts_series = pd.to_datetime(df['timestamp'])
    if ts_series.dt.tz is not None:
        ts_series = ts_series.dt.tz_convert('UTC').dt.tz_localize(None)
    df['timestamp'] = ts_series

    # Derivación matemática segura de Torque (N*m) y Fuerza Efectiva (AEPF, N)
    p_vals = df['potencia'].fillna(0.0).values
    c_vals = df['cadencia'].fillna(0.0).values
    omega = c_vals * (2.0 * np.pi / 60.0)

    with np.errstate(divide='ignore', invalid='ignore'):
        trq_calc = np.where(c_vals >= 15.0, p_vals / omega, 0.0)
        trq_calc = np.nan_to_num(trq_calc, nan=0.0, posinf=0.0, neginf=0.0)
        trq_calc = np.clip(trq_calc, 0.0, 250.0)

    if 'torque' not in df.columns:
        df['torque'] = trq_calc
    else:
        df['torque'] = df['torque'].fillna(pd.Series(trq_calc, index=df.index))

    df['aepf'] = df['torque'] / DEFAULT_CRANK_LENGTH

    return df.sort_values('timestamp').reset_index(drop=True)


def cargar_fit_con_tiempo_movimiento(
    ruta_archivo: Union[str, Path],
    solo_movimiento: bool = True,
    v_umbral_ms: float = 0.5,
    p_min_w: float = 15.0
) -> pd.DataFrame:
    """
    Lee un archivo .fit y detecta los periodos en los que el ciclista está detenido (Opción 2).
    Si solo_movimiento=True, elimina los registros estáticos y genera las columnas
    'is_moving', 'elapsed_seconds' y 'moving_time' con la telemetría activa limpia.
    """
    df = cargar_fit(ruta_archivo, permitir_vacio=True)
    if df.empty or 'timestamp' not in df.columns or len(df) == 0:
        return pd.DataFrame()

    # Tiempo de reloj transcurrido (elapsed_seconds)
    t0 = df['timestamp'].iloc[0]
    df['elapsed_seconds'] = (df['timestamp'] - t0).dt.total_seconds()
    df['delta_t'] = df['timestamp'].diff().dt.total_seconds().fillna(1.0).clip(lower=0.0)

    # Identificación de registros estáticos / paradas
    speed = df['velocidad'].fillna(0.0)
    power = df['potencia'].fillna(0.0) if 'potencia' in df.columns else pd.Series(0.0, index=df.index)
    cadence = df['cadencia'].fillna(0.0) if 'cadencia' in df.columns else pd.Series(0.0, index=df.index)

    # Parado si: velocidad muy baja y no pedalea (cadencia 0 y potencia menor a p_min) o velocidad nula
    esta_parado = (speed < v_umbral_ms) & (cadence == 0) & (power < p_min_w)
    esta_parado = esta_parado | (speed == 0.0)

    df['is_moving'] = ~esta_parado

    if solo_movimiento:
        df = df[df['is_moving']].copy().reset_index(drop=True)
        if df.empty:
            return pd.DataFrame()
        df['delta_t'] = df['timestamp'].diff().dt.total_seconds().fillna(1.0).clip(lower=0.0)

    if 'torque' in df.columns:
        df['torque'] = df['torque'].fillna(0.0).astype(float)
    if 'aepf' in df.columns:
        df['aepf'] = df['aepf'].fillna(0.0).astype(float)

    df['moving_time'] = range(1, len(df) + 1)
    return df


def preprocesar_datos(
    df: pd.DataFrame,
    min_speed_ms: float = 3.0,
    min_power_w: float = 30.0,
    max_dt_sec: float = 5.0
) -> pd.DataFrame:
    """
    Calcula derivadas físicas (aceleración, pendiente, distancia delta)
    y filtra tramos sin señal fiable (paradas, descensos sin pedalear, pausas).
    """
    df = df.copy()

    # Rellenar / interpolar altitud
    if 'altitud' in df.columns:
        df['altitud'] = df['altitud'].interpolate(limit_direction='both').ffill().bfill()
    else:
        df['altitud'] = 0.0

    # Diferenciales temporales y cinemáticos
    df['delta_t'] = df['timestamp'].diff().dt.total_seconds()
    df['delta_v'] = df['velocidad'].diff()
    df['delta_h'] = df['altitud'].diff()

    # Descartar primera fila tras el diff
    df = df.iloc[1:].copy()

    # Filtro de calidad
    df = df[
        (df['velocidad'] >= min_speed_ms) &
        (df['potencia'] >= min_power_w) &
        (df['delta_t'] > 0) &
        (df['delta_t'] <= max_dt_sec)
    ].copy()

    if df.empty:
        raise ValueError("El DataFrame quedó vacío tras aplicar los filtros de velocidad y potencia mínima.")

    # Aceleración y distancia de segmento
    df['aceleracion'] = df['delta_v'] / df['delta_t']
    df['distancia_segmento'] = df['velocidad'] * df['delta_t']

    # Cálculo de la pendiente (ángulo theta en radianes)
    ratio = np.divide(
        df['delta_h'].fillna(0.0),
        df['distancia_segmento'].replace(0, np.nan),
        out=np.zeros(len(df), dtype=float),
        where=df['distancia_segmento'].replace(0, np.nan).notna()
    )
    df['pendiente'] = np.arcsin(np.clip(ratio, -0.5, 0.5))

    return df.reset_index(drop=True)


def modelo_potencia(
    params: Tuple[float, float],
    df: pd.DataFrame,
    masa_ciclista: float = DEFAULT_RIDER_WEIGHT,
    masa_bici: float = DEFAULT_BIKE_WEIGHT,
    g: float = DEFAULT_GRAVITY,
    rho: float = DEFAULT_AIR_DENSITY,
    eficiencia: float = DEFAULT_DRIVETRAIN_EFF
) -> np.ndarray:
    """
    Calcula la potencia teórica demandada (Watts) según el modelo físico clásico de ciclismo:
    P = (F_aero + F_gravedad + F_rodadura + F_inercia) * v / eficiencia
    """
    cda, crr = params
    masa_total = masa_ciclista + masa_bici

    v = df['velocidad'].values
    a = df['aceleracion'].values
    sin_theta = np.sin(df['pendiente'].values)
    cos_theta = np.cos(df['pendiente'].values)

    # Componentes de fuerza (Newtons)
    f_aero = 0.5 * rho * cda * (v ** 2)
    f_gravedad = masa_total * g * sin_theta
    f_rodadura = masa_total * g * crr * cos_theta
    f_inercia = masa_total * a

    # Potencia requerida en pedales
    pot_teorica = (f_aero + f_gravedad + f_rodadura + f_inercia) * v / eficiencia
    return pot_teorica


def estimar_cda(
    df: pd.DataFrame,
    masa_total: float = 83.0,
    masa_bici: float = DEFAULT_BIKE_WEIGHT,
    rho: float = DEFAULT_AIR_DENSITY,
    eficiencia: float = DEFAULT_DRIVETRAIN_EFF,
    g: float = DEFAULT_GRAVITY,
    bounds_cda: Tuple[float, float] = (0.15, 0.60),
    bounds_crr: Tuple[float, float] = (0.002, 0.015),
    x0: Tuple[float, float] = (0.300, 0.005)
) -> Dict[str, Any]:
    """
    Ajusta los coeficientes CdA y Crr minimizando el Error Cuadrático Medio (MSE)
    entre la potencia medida real del potenciómetro y la potencia del modelo físico.
    """
    pot_real = df['potencia'].values
    masa_ciclista = max(10.0, masa_total - masa_bici)

    def funcion_objetivo(params):
        pot_pred = modelo_potencia(
            params, df,
            masa_ciclista=masa_ciclista,
            masa_bici=masa_bici,
            g=g, rho=rho, eficiencia=eficiencia
        )
        return np.mean((pot_real - pot_pred) ** 2)

    bounds = [bounds_cda, bounds_crr]
    resultado = minimize(funcion_objetivo, x0, bounds=bounds, method='L-BFGS-B')

    cda_opt, crr_opt = resultado.x
    mse_final = float(resultado.fun)
    rmse_final = float(np.sqrt(mse_final))

    pot_modelo = modelo_potencia(
        (cda_opt, crr_opt), df,
        masa_ciclista=masa_ciclista,
        masa_bici=masa_bici,
        g=g, rho=rho, eficiencia=eficiencia
    )

    return {
        'cda': round(float(cda_opt), 4),
        'crr': round(float(crr_opt), 5),
        'mse': round(mse_final, 2),
        'rmse': round(rmse_final, 2),
        'pot_real': pot_real,
        'pot_modelo': pot_modelo,
        'success': bool(resultado.success),
        'message': str(resultado.message),
        'masa_total': masa_total,
        'num_registros': len(df)
    }


def graficar_analisis_fit(
    df: pd.DataFrame,
    resultado_opt: Dict[str, Any],
    guardar_ruta: Optional[Union[str, Path]] = None,
    mostrar: bool = True
):
    """
    Genera un panel completo de gráficos que validan el ajuste del modelo
    y el comportamiento aerodinámico obtenido.
    """
    cda = resultado_opt['cda']
    crr = resultado_opt['crr']
    pot_real = resultado_opt['pot_real']
    pot_modelo = resultado_opt['pot_modelo']

    fig, axes = plt.subplots(3, 1, figsize=(14, 12))
    fig.patch.set_facecolor('#f8fafc')

    # Panel 1: Potencia Real vs Modelo en el tiempo
    axes[0].plot(df['timestamp'], pot_real, color='#94a3b8', alpha=0.6, label='Potencia Medida')
    axes[0].plot(df['timestamp'], pot_modelo, color='#ef4444', linewidth=1.8, label=f'Potencia Modelo (CdA={cda:.3f}, Crr={crr:.4f})')
    axes[0].set_title(f'Validación de Telemetría | CdA Estimado: {cda:.3f} m² | RMSE: {resultado_opt["rmse"]:.1f} W', fontsize=12, fontweight='bold')
    axes[0].set_ylabel('Potencia (W)')
    axes[0].grid(True, alpha=0.3)
    axes[0].legend(loc='upper right')

    # Panel 2: Potencia vs Velocidad (Scatter y curva de ajuste)
    vel_kmh = df['velocidad'] * 3.6
    axes[1].scatter(vel_kmh, pot_real, alpha=0.25, s=8, color='#0284c7', label='Datos reales')
    df_sorted = df.sort_values('velocidad')
    v_kmh_sorted = df_sorted['velocidad'] * 3.6
    pot_mod_sorted = pot_modelo[np.argsort(df['velocidad'].values)]
    axes[1].plot(v_kmh_sorted, pot_mod_sorted, color='#dc2626', linewidth=2.5, label='Ajuste Modelo')
    axes[1].set_title('Relación Potencia - Velocidad', fontsize=12, fontweight='bold')
    axes[1].set_xlabel('Velocidad (km/h)')
    axes[1].set_ylabel('Potencia (W)')
    axes[1].grid(True, alpha=0.3)
    axes[1].legend()

    # Panel 3: Componente pura de resistencia aerodinámica vs velocidad
    v_seq = np.linspace(5, 70, 100) / 3.6  # 5 a 70 km/h en m/s
    pot_aero_pura = 0.5 * DEFAULT_AIR_DENSITY * cda * (v_seq ** 3) / DEFAULT_DRIVETRAIN_EFF
    axes[2].plot(v_seq * 3.6, pot_aero_pura, color='#7c3aed', linewidth=2.5, label=f'Potencia Aerodinámica (CdA = {cda:.3f} m²)')
    axes[2].set_title('Demanda de Potencia Aerodinámica pura en llano', fontsize=12, fontweight='bold')
    axes[2].set_xlabel('Velocidad (km/h)')
    axes[2].set_ylabel('Potencia Aerodinámica (W)')
    axes[2].grid(True, alpha=0.3)
    axes[2].legend()

    plt.tight_layout()

    if guardar_ruta:
        ruta_p = Path(guardar_ruta)
        ruta_p.parent.mkdir(parents=True, exist_ok=True)
        plt.savefig(ruta_p, dpi=200, bbox_inches='tight')

    if mostrar:
        plt.show()
    else:
        plt.close(fig)


if __name__ == '__main__':
    fit_samples = list(Path("data").glob("*.fit"))
    if fit_samples:
        muestra = fit_samples[0]
        print(f"🚀 Ejecutando análisis de prueba en: {muestra.name}")
        df_raw = cargar_fit(muestra)
        print(f"   -> {len(df_raw)} registros cargados (GPS disponibles: {df_raw['lat'].notna().sum()}).")
        df_proc = preprocesar_datos(df_raw)
        res = estimar_cda(df_proc, masa_total=75.0)
        print(f"   • CdA Estimado: {res['cda']} m² | Crr: {res['crr']} | RMSE: {res['rmse']} W")
    else:
        print("ℹ️ No se encontraron archivos FIT en data/ para la prueba.")

