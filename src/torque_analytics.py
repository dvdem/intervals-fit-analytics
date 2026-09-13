"""
Módulo de Análisis Biomecánico y Dinámica de Pedaleo (Torque & Force Analytics).
Permite calcular métricas de par en bielas (N·m), fuerza media efectiva en los pedales (AEPF en N y kgf),
curvas de picos de torque (Mean Maximal Torque - MMT), Análisis de Cuadrantes (Quadrant Analysis de Coggan),
perfil de Fuerza-Velocidad (F-v) y degradación de torque por fatiga acumulada.
"""

import sys
from pathlib import Path

# Permitir ejecución directa del script o importación modular
_ROOT_DIR = Path(__file__).resolve().parent.parent
if str(_ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(_ROOT_DIR))

from typing import Dict, List, Optional, Tuple, Union, Any
import numpy as np
import pandas as pd

try:
    from config import (
        DEFAULT_CRANK_LENGTH,
        DEFAULT_QUADRANT_CADENCE_THRESH,
        DEFAULT_TORQUE_PEAK_DURATIONS
    )
except (ImportError, ValueError):
    from ..config import (
        DEFAULT_CRANK_LENGTH,
        DEFAULT_QUADRANT_CADENCE_THRESH,
        DEFAULT_TORQUE_PEAK_DURATIONS
    )


def calcular_torque_seguro(
    potencia: Union[np.ndarray, pd.Series, List[float]],
    cadencia: Union[np.ndarray, pd.Series, List[float]],
    crank_length_m: float = DEFAULT_CRANK_LENGTH,
    cad_min_rpm: float = 15.0,
    torque_max_clip: float = 250.0
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Calcula de forma vectorial el torque instantáneo (N·m) y la fuerza efectiva media en el pedal (AEPF, N).
    Aplica filtros de seguridad:
    - Para cadencia < cad_min_rpm (rueda libre o arranque sin enganche), asigna 0.0 N·m.
    - Limita picos numéricos anómalos a torque_max_clip (250 N·m por defecto).
    """
    p = np.asarray(potencia, dtype=float)
    c = np.asarray(cadencia, dtype=float)

    # Velocidad angular: omega = cadencia * 2 * pi / 60
    omega = c * (2.0 * np.pi / 60.0)

    with np.errstate(divide='ignore', invalid='ignore'):
        trq = np.where(c >= cad_min_rpm, p / omega, 0.0)
        trq = np.nan_to_num(trq, nan=0.0, posinf=0.0, neginf=0.0)
        trq = np.clip(trq, 0.0, torque_max_clip)

    aepf = trq / max(0.1, crank_length_m)
    return trq, aepf


def calcular_picos_torque(
    torque_series: Union[pd.Series, np.ndarray],
    duraciones: Optional[Dict[int, str]] = None
) -> Dict[int, float]:
    """
    Calcula los picos de Mean Maximal Torque (MMT) para duraciones estándar (1s, 5s, 10s, 30s, 1m, 5m).
    Devuelve un diccionario {segundos: max_torque_nm}.
    """
    if duraciones is None:
        duraciones = DEFAULT_TORQUE_PEAK_DURATIONS

    s = pd.Series(torque_series).fillna(0.0)
    picos = {}
    n = len(s)

    for seg in sorted(duraciones.keys()):
        if n >= seg and seg > 0:
            val = float(s.rolling(window=seg, min_periods=seg).mean().max())
            picos[seg] = round(val, 1) if not np.isnan(val) else 0.0
        elif n > 0 and seg > 0:
            # Si la serie es más corta que la ventana, tomar la media de toda la serie
            val = float(s.mean())
            picos[seg] = round(val, 1) if not np.isnan(val) else 0.0
        else:
            picos[seg] = 0.0

    return picos


def calcular_analisis_cuadrantes(
    df: pd.DataFrame,
    ftp: float = 380.0,
    cad_thresh: float = DEFAULT_QUADRANT_CADENCE_THRESH,
    crank_length_m: float = DEFAULT_CRANK_LENGTH,
    max_scatter_points: int = 1500
) -> Dict[str, Any]:
    """
    Realiza el Análisis de Cuadrantes (Quadrant Analysis de Coggan & Allen).
    Divide la actividad según:
    - Umbral de Cadencia (por defecto 85 rpm o cadencia media en pedaleo).
    - Umbral de Torque en FTP: tau_thresh = FTP / (cad_thresh * 2pi/60).

    Cuadrantes:
    - QI  (Alta Cad, Alto Trq): Sprints, ataques, aceleraciones.
    - QII (Baja Cad, Alto Trq): Subidas empinadas, fuerza en pendientes duras.
    - QIII(Baja Cad, Bajo Trq): Recuperación, pedaleo suave, bajadas.
    - QIV (Alta Cad, Bajo Trq): Rodar protegido en pelotón a alta velocidad.
    """
    if df.empty or 'cadencia' not in df.columns or 'potencia' not in df.columns:
        return {
            'disponible': False,
            'cad_thresh': cad_thresh,
            'trq_thresh': 0.0,
            'aepf_thresh': 0.0,
            'cuadrantes': {'q1_pct': 0.0, 'q2_pct': 0.0, 'q3_pct': 0.0, 'q4_pct': 0.0},
            'puntos': []
        }

    ftp_val = max(100.0, float(ftp) if ftp and ftp > 0 else 380.0)
    cad_th = float(cad_thresh) if cad_thresh and cad_thresh > 0 else 85.0
    omega_th = cad_th * (2.0 * np.pi / 60.0)
    trq_th = round(float(ftp_val / omega_th), 2)
    aepf_th = round(float(trq_th / crank_length_m), 1)

    c = df['cadencia'].fillna(0.0).values
    p = df['potencia'].fillna(0.0).values

    if 'torque' in df.columns:
        trq = df['torque'].fillna(0.0).values
    else:
        trq, _ = calcular_torque_seguro(p, c, crank_length_m=crank_length_m)

    # Filtrar únicamente cuando el ciclista está pedaleando activamente (cadencia >= 20 rpm)
    mask_ped = (c >= 20.0) & (p > 5.0)
    c_ped = c[mask_ped]
    trq_ped = trq[mask_ped]
    p_ped = p[mask_ped]
    total_ped_sec = int(np.sum(mask_ped))

    if total_ped_sec == 0:
        return {
            'disponible': False,
            'cad_thresh': cad_th,
            'trq_thresh': trq_th,
            'aepf_thresh': aepf_th,
            'tiempo_pedaleo_seg': 0,
            'cuadrantes': {
                'q1_sec': 0, 'q1_pct': 0.0,
                'q2_sec': 0, 'q2_pct': 0.0,
                'q3_sec': 0, 'q3_pct': 0.0,
                'q4_sec': 0, 'q4_pct': 0.0
            },
            'puntos': [],
            'iso_curvas': {}
        }

    q1_mask = (c_ped >= cad_th) & (trq_ped >= trq_th)
    q2_mask = (c_ped < cad_th) & (trq_ped >= trq_th)
    q3_mask = (c_ped < cad_th) & (trq_ped < trq_th)
    q4_mask = (c_ped >= cad_th) & (trq_ped < trq_th)

    q1_sec = int(np.sum(q1_mask))
    q2_sec = int(np.sum(q2_mask))
    q3_sec = int(np.sum(q3_mask))
    q4_sec = int(np.sum(q4_mask))

    q1_pct = round((q1_sec / total_ped_sec) * 100.0, 1)
    q2_pct = round((q2_sec / total_ped_sec) * 100.0, 1)
    q3_pct = round((q3_sec / total_ped_sec) * 100.0, 1)
    q4_pct = round((q4_sec / total_ped_sec) * 100.0, 1)

    # Submuestreo uniforme para renderizado web ágil en Scatter Plot
    puntos_scatter = []
    num_pts = len(c_ped)
    if num_pts > 0:
        step = max(1, num_pts // max_scatter_points)
        indices = np.arange(0, num_pts, step)
        for idx in indices:
            cad_i = round(float(c_ped[idx]), 1)
            trq_i = round(float(trq_ped[idx]), 1)
            pwr_i = int(round(float(p_ped[idx])))
            aepf_i = round(float(trq_i / crank_length_m), 1)

            # Asignación de cuadrante
            if cad_i >= cad_th and trq_i >= trq_th:
                q_id = 1
            elif cad_i < cad_th and trq_i >= trq_th:
                q_id = 2
            elif cad_i < cad_th and trq_i < trq_th:
                q_id = 3
            else:
                q_id = 4

            puntos_scatter.append({
                'cad': cad_i,
                'trq': trq_i,
                'aepf': aepf_i,
                'pwr': pwr_i,
                'q': q_id
            })

    # Isolíneas de potencia para referencia visual (P = 200W, 300W, 400W, FTP)
    cad_seq = np.linspace(30.0, 130.0, 50)
    iso_curvas = {}
    niveles_pot = [200.0, 300.0, 400.0, ftp_val]
    for pot_val in niveles_pot:
        trq_line = [round(float(pot_val / (cd * (2.0 * np.pi / 60.0))), 1) for cd in cad_seq]
        label = f"{int(pot_val)}W" if pot_val != ftp_val else f"FTP ({int(ftp_val)}W)"
        iso_curvas[label] = {
            'cad': [round(float(cd), 1) for cd in cad_seq],
            'trq': trq_line
        }

    return {
        'disponible': True,
        'cad_thresh': cad_th,
        'trq_thresh': trq_th,
        'aepf_thresh': aepf_th,
        'tiempo_pedaleo_seg': total_ped_sec,
        'cuadrantes': {
            'q1_sec': q1_sec,
            'q1_pct': q1_pct,
            'q2_sec': q2_sec,
            'q2_pct': q2_pct,
            'q3_sec': q3_sec,
            'q3_pct': q3_pct,
            'q4_sec': q4_sec,
            'q4_pct': q4_pct,
        },
        'puntos': puntos_scatter,
        'iso_curvas': iso_curvas
    }


def calcular_zonas_torque(
    df: pd.DataFrame,
    ftp: float = 380.0,
    cad_thresh: float = DEFAULT_QUADRANT_CADENCE_THRESH,
    crank_length_m: float = DEFAULT_CRANK_LENGTH
) -> Dict[str, Any]:
    """
    Calcula la distribución del tiempo en 6 zonas de torque biomecánico basadas en el Torque de FTP:
    - Z1 (< 50% tau_FTP): Spin Ligero
    - Z2 (50-75% tau_FTP): Fuerza Aeróbica Base
    - Z3 (75-95% tau_FTP): Tensión Media / Tempo
    - Z4 (95-115% tau_FTP): Umbral de Torque
    - Z5 (115-145% tau_FTP): Supra-Umbral / Fuerza Alta
    - Z6 (> 145% tau_FTP): Neuromuscular Máximo
    """
    if df.empty or 'cadencia' not in df.columns or 'potencia' not in df.columns:
        return {}

    ftp_val = max(100.0, float(ftp) if ftp and ftp > 0 else 380.0)
    cad_th = float(cad_thresh) if cad_thresh and cad_thresh > 0 else 85.0
    trq_ftp = (ftp_val * 60.0) / (2.0 * np.pi * cad_th)

    c = df['cadencia'].fillna(0.0).values
    p = df['potencia'].fillna(0.0).values

    if 'torque' in df.columns:
        trq = df['torque'].fillna(0.0).values
    else:
        trq, _ = calcular_torque_seguro(p, c, crank_length_m=crank_length_m)

    # Filtrar cuando pedalea (cadencia >= 20 rpm)
    mask = c >= 20.0
    trq_ped = trq[mask]
    total_sec = len(trq_ped)

    limites = [
        (0.0, 0.50 * trq_ftp, "Z1 - Spin Ligero (<50%)"),
        (0.50 * trq_ftp, 0.75 * trq_ftp, "Z2 - Base Aeróbica (50-75%)"),
        (0.75 * trq_ftp, 0.95 * trq_ftp, "Z3 - Tempo (75-95%)"),
        (0.95 * trq_ftp, 1.15 * trq_ftp, "Z4 - Umbral (95-115%)"),
        (1.15 * trq_ftp, 1.45 * trq_ftp, "Z5 - Supra-Umbral (115-145%)"),
        (1.45 * trq_ftp, 999.0, "Z6 - Neuromuscular (>145%)")
    ]

    zonas = []
    trq_max_ped = float(trq_ped.max()) if len(trq_ped) > 0 else round(float(trq_ftp * 1.5), 1)
    for z_idx, (b_inf, b_sup, label) in enumerate(limites):
        if total_sec > 0:
            z_mask = (trq_ped >= b_inf) & (trq_ped < b_sup)
            z_sec = int(np.sum(z_mask))
            z_pct = round((z_sec / total_sec) * 100.0, 1)
        else:
            z_sec = 0
            z_pct = 0.0
        zonas.append({
            'zona': f"Z{z_idx + 1}",
            'nombre': label,
            'segundos': z_sec,
            'porcentaje': z_pct,
            'trq_min_nm': round(float(b_inf), 1),
            'trq_max_nm': round(float(b_sup if b_sup < 900 else trq_max_ped), 1)
        })

    return {
        'trq_ftp_nm': round(float(trq_ftp), 1),
        'zonas': zonas
    }


def calcular_perfil_fuerza_velocidad(
    df: pd.DataFrame,
    crank_length_m: float = DEFAULT_CRANK_LENGTH,
    cad_bin_size: float = 5.0,
    min_pts_por_bin: int = 5
) -> Dict[str, Any]:
    """
    Calcula el perfil Fuerza-Velocidad (F-v) a partir de la envolvente de torque máximo por tramos de cadencia.
    Ajusta una regresión lineal: tau_max = T0 * (1 - cad / cad0).
    Estima:
    - T0: Torque isométrico teórico a 0 rpm (N·m).
    - cad0: Cadencia máxima teórica con carga nula (rpm).
    - cad_opt: Cadencia óptima de sprint para máxima potencia (cad0 / 2).
    - Pmax: Potencia pico teórica máxima (W).
    """
    if df.empty or 'cadencia' not in df.columns or 'potencia' not in df.columns:
        return {'disponible': False}

    c = df['cadencia'].fillna(0.0).values
    p = df['potencia'].fillna(0.0).values

    if 'torque' in df.columns:
        trq = df['torque'].fillna(0.0).values
    else:
        trq, _ = calcular_torque_seguro(p, c, crank_length_m=crank_length_m)

    df_tmp = pd.DataFrame({'cad': c, 'trq': trq, 'pwr': p})
    # Filtrar cadencias útiles para el análisis dinámico (entre 35 y 135 rpm)
    df_tmp = df_tmp[(df_tmp['cad'] >= 35.0) & (df_tmp['cad'] <= 135.0) & (df_tmp['trq'] > 10.0)]

    if len(df_tmp) < 20:
        return {'disponible': False}

    bins = np.arange(35.0, 140.0, cad_bin_size)
    df_tmp['bin'] = pd.cut(df_tmp['cad'], bins=bins)

    envolvente = df_tmp.groupby('bin', observed=False).agg(
        cad_mean=('cad', 'mean'),
        trq_max=('trq', 'max'),
        pwr_max=('pwr', 'max'),
        count=('trq', 'count')
    ).dropna()

    envolvente = envolvente[envolvente['count'] >= min_pts_por_bin]
    if len(envolvente) < 3:
        return {'disponible': False}

    cad_x = envolvente['cad_mean'].values
    trq_y = envolvente['trq_max'].values

    # Ajuste por mínimos cuadrados: trq = m * cad + b
    # Como m < 0: T0 = b, cad0 = -b / m
    try:
        slope, intercept = np.polyfit(cad_x, trq_y, 1)
        if slope >= 0:
            # Si la pendiente es positiva (ruido o sprint no registrado), no es fisiológico
            return {'disponible': False}

        t0 = float(intercept)
        cad0 = float(-intercept / slope)
        cad_opt = float(cad0 / 2.0)
        # Pmax = T0 * (cad0 * 2pi/60) / 4
        omega_opt = cad_opt * (2.0 * np.pi / 60.0)
        pmax = float((t0 / 2.0) * omega_opt)

        # Coeficiente de determinación R^2
        y_pred = slope * cad_x + intercept
        ss_res = np.sum((trq_y - y_pred) ** 2)
        ss_tot = np.sum((trq_y - np.mean(trq_y)) ** 2)
        r2 = float(1.0 - (ss_res / max(1e-5, ss_tot)))

        return {
            'disponible': True,
            't0_nm': round(t0, 1),
            'cad0_rpm': round(cad0, 1),
            'cad_opt_rpm': round(cad_opt, 1),
            'pmax_teorico_w': int(round(pmax)),
            'r2': round(max(0.0, r2), 3),
            'puntos_envolvente': [
                {'cad': round(float(cx), 1), 'trq_max': round(float(ty), 1)}
                for cx, ty in zip(cad_x, trq_y)
            ]
        }
    except Exception:
        return {'disponible': False}


def calcular_degradacion_fatiga_torque(
    df: pd.DataFrame,
    umbral_kj: float = 2000.0,
    crank_length_m: float = DEFAULT_CRANK_LENGTH
) -> Dict[str, Any]:
    """
    Compara el rendimiento de torque entre la fase inicial (fresca) y la fase fatigada
    tras haber acumulado un umbral de trabajo mecánico (por defecto 2000 kJ).
    Permite evaluar la retención neuromuscular de arrancada y pedaleo en el final de etapa.
    """
    if df.empty or 'potencia' not in df.columns:
        return {'disponible': False}

    p = df['potencia'].fillna(0.0).values
    c = df['cadencia'].fillna(0.0).values if 'cadencia' in df.columns else np.zeros_like(p)

    if 'torque' in df.columns:
        trq = df['torque'].fillna(0.0).values
    else:
        trq, _ = calcular_torque_seguro(p, c, crank_length_m=crank_length_m)

    # Trabajo acumulado en kJ
    if 'kilojulios_acum' in df.columns:
        kj_acum = df['kilojulios_acum'].values
    else:
        kj_acum = np.cumsum(p) / 1000.0

    total_kj = float(kj_acum[-1]) if len(kj_acum) > 0 else 0.0

    # Si la etapa no supera el umbral de kJ, dividir por la mitad de la actividad
    if total_kj < (umbral_kj * 1.1):
        corte_kj = total_kj / 2.0
        label_fresco = f"1ª Mitad (<{int(corte_kj)} kJ)"
        label_fatiga = f"2ª Mitad (>{int(corte_kj)} kJ)"
    else:
        corte_kj = umbral_kj
        label_fresco = f"Fase Fresca (<{int(corte_kj)} kJ)"
        label_fatiga = f"Fase Fatigada (>{int(corte_kj)} kJ)"

    mask_fresco = (kj_acum < corte_kj) & (c >= 20.0)
    mask_fatiga = (kj_acum >= corte_kj) & (c >= 20.0)

    trq_fresco = trq[mask_fresco]
    trq_fatiga = trq[mask_fatiga]
    p_fresco = p[mask_fresco]
    p_fatiga = p[mask_fatiga]

    if len(trq_fresco) == 0 or len(trq_fatiga) == 0:
        return {'disponible': False}

    # Picos móviles de 5s en fresco vs fatigado
    s_trq = pd.Series(trq)
    roll_5s = s_trq.rolling(5, min_periods=5).mean().values

    fresco_mask_5s = (kj_acum < corte_kj) & ~np.isnan(roll_5s)
    fatiga_mask_5s = (kj_acum >= corte_kj) & ~np.isnan(roll_5s)

    pico_5s_fresco = float(np.max(roll_5s[fresco_mask_5s])) if np.any(fresco_mask_5s) else 0.0
    pico_5s_fatiga = float(np.max(roll_5s[fatiga_mask_5s])) if np.any(fatiga_mask_5s) else 0.0

    trq_med_fresco = float(np.mean(trq_fresco))
    trq_med_fatiga = float(np.mean(trq_fatiga))

    delta_pct_pico = round(((pico_5s_fatiga - pico_5s_fresco) / max(1.0, pico_5s_fresco)) * 100.0, 1)
    delta_pct_media = round(((trq_med_fatiga - trq_med_fresco) / max(1.0, trq_med_fresco)) * 100.0, 1)

    return {
        'disponible': True,
        'corte_kj': int(round(corte_kj)),
        'total_kj': int(round(total_kj)),
        'label_fresco': label_fresco,
        'label_fatiga': label_fatiga,
        'fresco': {
            'trq_media_nm': round(trq_med_fresco, 1),
            'trq_p95_nm': round(float(np.percentile(trq_fresco, 95)), 1),
            'trq_pico_5s_nm': round(pico_5s_fresco, 1),
            'pot_media_w': int(round(float(np.mean(p_fresco))))
        },
        'fatigado': {
            'trq_media_nm': round(trq_med_fatiga, 1),
            'trq_p95_nm': round(float(np.percentile(trq_fatiga, 95)), 1),
            'trq_pico_5s_nm': round(pico_5s_fatiga, 1),
            'pot_media_w': int(round(float(np.mean(p_fatiga))))
        },
        'delta_pct_pico_5s': delta_pct_pico,
        'delta_pct_media': delta_pct_media
    }


def calcular_metricas_torque_completas(
    df: pd.DataFrame,
    ftp: float = 380.0,
    crank_length_m: float = DEFAULT_CRANK_LENGTH,
    cad_thresh: float = DEFAULT_QUADRANT_CADENCE_THRESH,
    duraciones_mmt: Optional[Dict[int, str]] = None
) -> Dict[str, Any]:
    """
    Función de integración principal: calcula todas las estadísticas de torque, AEPF,
    picos MMT, Análisis de Cuadrantes, Zonas y degradación de fatiga para un ciclista.
    """
    if df.empty or 'cadencia' not in df.columns or 'potencia' not in df.columns:
        return {'disponible': False}

    c = df['cadencia'].fillna(0.0).values
    p = df['potencia'].fillna(0.0).values

    if 'torque' in df.columns and 'aepf' in df.columns:
        trq = df['torque'].fillna(0.0).values
        aepf = df['aepf'].fillna(0.0).values
    else:
        trq, aepf = calcular_torque_seguro(p, c, crank_length_m=crank_length_m)

    # Filtrar periodos activos de pedaleo (cadencia >= 20 rpm)
    mask_ped = c >= 20.0
    trq_ped = trq[mask_ped]
    aepf_ped = aepf[mask_ped]

    if len(trq_ped) == 0:
        trq_ped = np.array([0.0])
        aepf_ped = np.array([0.0])

    trq_media = round(float(np.mean(trq_ped)), 1)
    trq_mediana = round(float(np.median(trq_ped)), 1)
    trq_p95 = round(float(np.percentile(trq_ped, 95)), 1)
    trq_max = round(float(np.max(trq)), 1) if len(trq) > 0 else 0.0

    aepf_media = round(float(np.mean(aepf_ped)), 1)
    aepf_p95 = round(float(np.percentile(aepf_ped, 95)), 1)
    aepf_max = round(float(np.max(aepf)), 1) if len(aepf) > 0 else 0.0

    # Fuerza equivalente en kilogramos-fuerza
    kgf_media = round(float(aepf_media / 9.80665), 1)
    kgf_max = round(float(aepf_max / 9.80665), 1)

    # Curva MMT (Mean Maximal Torque)
    mmt = calcular_picos_torque(trq, duraciones=duraciones_mmt)

    # Análisis de Cuadrantes
    cuadrantes = calcular_analisis_cuadrantes(
        df,
        ftp=ftp,
        cad_thresh=cad_thresh,
        crank_length_m=crank_length_m
    )

    # Zonas de Torque
    zonas = calcular_zonas_torque(
        df,
        ftp=ftp,
        cad_thresh=cad_thresh,
        crank_length_m=crank_length_m
    )

    # Perfil Fuerza-Velocidad
    perfil_fv = calcular_perfil_fuerza_velocidad(
        df,
        crank_length_m=crank_length_m
    )

    # Degradación por fatiga
    fatiga = calcular_degradacion_fatiga_torque(
        df,
        crank_length_m=crank_length_m
    )

    # Detección de dinámicas nativas si existen
    nativas = {}
    if 'left_torque_effectiveness' in df.columns and df['left_torque_effectiveness'].notna().any():
        nativas['te_left_media'] = round(float(df['left_torque_effectiveness'].dropna().mean()), 1)
    if 'right_torque_effectiveness' in df.columns and df['right_torque_effectiveness'].notna().any():
        nativas['te_right_media'] = round(float(df['right_torque_effectiveness'].dropna().mean()), 1)
    if 'left_pedal_smoothness' in df.columns and df['left_pedal_smoothness'].notna().any():
        nativas['ps_left_media'] = round(float(df['left_pedal_smoothness'].dropna().mean()), 1)
    if 'right_pedal_smoothness' in df.columns and df['right_pedal_smoothness'].notna().any():
        nativas['ps_right_media'] = round(float(df['right_pedal_smoothness'].dropna().mean()), 1)

    return {
        'disponible': True,
        'trq_media_nm': trq_media,
        'trq_mediana_nm': trq_mediana,
        'trq_p95_nm': trq_p95,
        'trq_max_nm': trq_max,
        'aepf_media_n': aepf_media,
        'aepf_p95_n': aepf_p95,
        'aepf_max_n': aepf_max,
        'kgf_media': kgf_media,
        'kgf_max': kgf_max,
        'crank_length_mm': round(crank_length_m * 1000.0, 1),
        'mmt': mmt,
        'cuadrantes': cuadrantes,
        'zonas': zonas,
        'perfil_fv': perfil_fv,
        'fatiga': fatiga,
        'dinamicas_nativas': nativas
    }
