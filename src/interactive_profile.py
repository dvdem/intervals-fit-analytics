"""
Módulo para la Generación de Perfiles Interactivos de Etapa y Análisis Multiatleta.
Procesa telemetría GPS/FIT de múltiples ciclistas, sincroniza sus datos espaciales y temporales
desde el primer punto común, y genera un panel HTML/CSS/JavaScript moderno e interactivo
con mapa satelital, perfil de elevación sincronizado por posición (km) y tiempo, y HUD en vivo.
"""

import os
import sys
import re
import json
import math
import unicodedata
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Tuple, Union

# Asegurar importación de config y módulos hermanos
_ROOT_DIR = Path(__file__).resolve().parent.parent
if str(_ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(_ROOT_DIR))

import numpy as np
import pandas as pd

from config import (
    cargar_roster,
    OUTPUT_DIR,
    DEFAULT_RIDER_WEIGHT,
    DEFAULT_BIKE_WEIGHT,
)
from src.intervals_api import IntervalsClient
from src.fit_analyzer import cargar_fit, cargar_fit_con_tiempo_movimiento
from src.pdf_reports import generar_informe_etapa_pdf

# Paleta de colores distintiva para ciclistas (estilo Pro Cycling)
COLORES_CICLISTAS = [
    {"primary": "#38bdf8", "secondary": "#0284c7", "glow": "rgba(56, 189, 248, 0.45)", "badge": "bg-sky"},      # Cyan / Sky
    {"primary": "#10b981", "secondary": "#059669", "glow": "rgba(16, 185, 129, 0.45)", "badge": "bg-emerald"},  # Emerald Green
    {"primary": "#f59e0b", "secondary": "#d97706", "glow": "rgba(245, 158, 11, 0.45)", "badge": "bg-amber"},    # Amber / Gold
    {"primary": "#ec4899", "secondary": "#db2777", "glow": "rgba(236, 72, 153, 0.45)", "badge": "bg-pink"},     # Pink / Magenta
    {"primary": "#a855f7", "secondary": "#7e22ce", "glow": "rgba(168, 85, 247, 0.45)", "badge": "bg-purple"},   # Purple
    {"primary": "#f97316", "secondary": "#ea580c", "glow": "rgba(249, 115, 22, 0.45)", "badge": "bg-orange"},   # Orange
    {"primary": "#06b6d4", "secondary": "#0891b2", "glow": "rgba(6, 182, 212, 0.45)", "badge": "bg-cyan"},      # Cyan
    {"primary": "#84cc16", "secondary": "#65a30d", "glow": "rgba(132, 204, 22, 0.45)", "badge": "bg-lime"},     # Lime
]


def _haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calcula la distancia geodésica en metros entre dos puntos (lat/lon en grados)."""
    if pd.isna(lat1) or pd.isna(lon1) or pd.isna(lat2) or pd.isna(lon2):
        return float('inf')
    R = 6371000.0  # Radio medio de la Tierra en metros
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2.0) ** 2
    return 2.0 * R * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))


def calcular_potencia_normalizada(potencias: np.ndarray) -> float:
    """Calcula la Potencia Normalizada (NP) a partir de una serie de potencia en vatios."""
    if len(potencias) < 30:
        return float(np.nanmean(potencias)) if len(potencias) > 0 else 0.0
    s = pd.Series(potencias).fillna(0)
    rolling_avg = s.rolling(window=30, min_periods=1).mean()
    np_val = (np.mean(rolling_avg ** 4)) ** 0.25
    return float(np_val) if not np.isnan(np_val) else float(np.mean(potencias))


def procesar_telemetria_ciclista(
    df: pd.DataFrame,
    nombre: str,
    peso: float,
    color_cfg: Dict[str, str],
    atleta_id: str = "",
    ftp: float = 380.0,
    num_grid_points: int = 1000,
    dist_referencia_km: Optional[float] = None
) -> Dict[str, Any]:
    """
    Procesa y limpia la telemetría de un ciclista, calculando métricas acumuladas,
    medias y generando arrays de muestreo de alta resolución tanto por distancia uniforme
    como por tiempo uniforme (incluyendo NP, IF, TSS y TSS/h).

    Si se proporciona `dist_referencia_km`, el grid de distancias de muestreo se extiende
    hasta ese valor (en lugar de la distancia propia del ciclista), permitiendo que todos
    los ciclistas compartan el mismo eje X en los gráficos y que en el step final los
    marcadores coincidan en la meta de la etapa.
    """
    # Filtrar paradas para trabajar exclusivamente con tiempo y telemetría en movimiento
    if 'is_moving' in df.columns:
        df_clean = df[df['is_moving']].copy()
    else:
        v_tmp = df['velocidad'].fillna(0.0) if 'velocidad' in df.columns else pd.Series(0.0, index=df.index)
        p_tmp = df['potencia'].fillna(0.0) if 'potencia' in df.columns else pd.Series(0.0, index=df.index)
        c_tmp = df['cadencia'].fillna(0.0) if 'cadencia' in df.columns else pd.Series(0.0, index=df.index)
        # Parado si: velocidad < 0.5 m/s (1.8 km/h) y sin pedaleo (cadencia 0 y potencia < 15W) o velocidad 0
        esta_parado = ((v_tmp < 0.5) & (c_tmp == 0) & (p_tmp < 15.0)) | (v_tmp == 0.0)
        df_clean = df[~esta_parado].copy()

    df_gps = df_clean.dropna(subset=['lat', 'lon']).copy().reset_index(drop=True)
    if len(df_gps) < 10:
        # Fallback de tolerancia si el filtrado fue excesivo
        df_gps = df.dropna(subset=['lat', 'lon']).copy().reset_index(drop=True)

    if len(df_gps) < 10:
        raise ValueError(f"El archivo para {nombre} no contiene suficientes puntos GPS válidos ({len(df_gps)}).")

    # Asegurar columnas numéricas básicas
    if 'potencia' not in df_gps.columns:
        df_gps['potencia'] = 0.0
    if 'velocidad' not in df_gps.columns:
        df_gps['velocidad'] = 0.0
    if 'altitud' not in df_gps.columns:
        df_gps['altitud'] = 0.0
    if 'frecuencia_cardiaca' in df_gps.columns:
        df_gps['fc'] = df_gps['frecuencia_cardiaca']
    elif 'fc' not in df_gps.columns:
        df_gps['fc'] = 0
    if 'cadencia' not in df_gps.columns:
        df_gps['cadencia'] = 0

    df_gps['potencia'] = df_gps['potencia'].fillna(0).astype(float)
    df_gps['velocidad_kmh'] = (df_gps['velocidad'].fillna(0) * 3.6).astype(float)
    df_gps['altitud'] = df_gps['altitud'].ffill().fillna(0).astype(float)
    df_gps['fc'] = df_gps['fc'].fillna(0).astype(int)
    df_gps['cadencia'] = df_gps['cadencia'].fillna(0).astype(int)

    # Distancia acumulada (recalculada en movimiento para evitar derivas GPS estáticas)
    if 'distancia' not in df_gps.columns or df_gps['distancia'].isna().all() or df_gps['distancia'].max() == 0:
        dists = [0.0]
        for i in range(1, len(df_gps)):
            d = _haversine_distance(
                df_gps['lat'].iloc[i-1], df_gps['lon'].iloc[i-1],
                df_gps['lat'].iloc[i], df_gps['lon'].iloc[i]
            )
            dists.append(dists[-1] + d)
        df_gps['distancia'] = dists
    else:
        df_gps['distancia'] = (df_gps['distancia'] - df_gps['distancia'].iloc[0]).clip(lower=0.0)

    # Pendiente en % y W/kg
    df_gps['w_kg'] = (df_gps['potencia'] / max(30.0, peso)).round(2)
    
    # Suavizado de altitud y cálculo de pendiente y desnivel
    alt_smooth = df_gps['altitud'].rolling(window=11, min_periods=1, center=True).mean()
    dist_diff = df_gps['distancia'].diff().replace(0, np.nan)
    alt_diff = alt_smooth.diff()
    df_gps['pendiente'] = ((alt_diff / dist_diff) * 100.0).fillna(0).clip(-25.0, 25.0)

    desnivel_pos = float(alt_diff[alt_diff > 0].sum())

    # Tiempos: Tiempo oficial de carrera = Tiempo en Movimiento (Moving Time)
    t_inicio = df['timestamp'].iloc[0] if 'timestamp' in df.columns and len(df) > 0 and pd.notna(df['timestamp'].iloc[0]) else df_gps['timestamp'].iloc[0]
    t_fin = df['timestamp'].iloc[-1] if 'timestamp' in df.columns and len(df) > 0 and pd.notna(df['timestamp'].iloc[-1]) else df_gps['timestamp'].iloc[-1]
    duracion_bruta_seg = float((t_fin - t_inicio).total_seconds()) if pd.notna(t_inicio) and pd.notna(t_fin) else float(len(df_gps))

    # Cada fila de la telemetría limpia representa 1 segundo de movimiento activo
    tiempo_mov_seg = float(len(df_gps))
    horas_mov = max(0.01, tiempo_mov_seg / 3600.0)
    duracion_seg = int(tiempo_mov_seg)

    # Trabajo acumulado en Kilojulios (kJ = Potencia * 1s / 1000)
    df_gps['kilojulios_acum'] = (df_gps['potencia'] * 1.0).cumsum() / 1000.0
    total_kj = float(df_gps['kilojulios_acum'].iloc[-1]) if not df_gps.empty else 0.0
    peso_val = max(30.0, peso)

    # Resumen de estadísticas 100% en movimiento
    distancia_total_km = float(df_gps['distancia'].max() / 1000.0)
    vel_media = round(distancia_total_km / horas_mov, 1)
    vel_max = float(df_gps['velocidad_kmh'].max())

    pot_media = float(df_gps['potencia'].mean())
    pot_max = float(df_gps['potencia'].max())
    
    # NP calculada sobre la serie en movimiento
    np_pot = calcular_potencia_normalizada(df_gps['potencia'].values)

    # FC y Cadencia medias en movimiento
    fc_valid = df_gps.loc[df_gps['fc'] > 40, 'fc']
    fc_media = float(fc_valid.mean()) if not fc_valid.empty else 0.0
    fc_max = float(df_gps['fc'].max())

    cad_valid = df_gps.loc[df_gps['cadencia'] > 10, 'cadencia']
    cad_media = float(cad_valid.mean()) if not cad_valid.empty else 0.0

    # Métricas de Umbral y Estrés (FTP, IF, TSS, TSS/h)
    ftp_val = float(ftp) if ftp and ftp > 0 else 380.0
    if_val = round(np_pot / ftp_val, 2) if ftp_val > 0 else 0.0
    # TSS clásico de Coggan sobre tiempo en movimiento: (t_mov_seg * NP * IF) / (FTP * 3600) * 100
    tss_val = round((tiempo_mov_seg * np_pot * (np_pot / ftp_val)) / (ftp_val * 36.0), 1) if ftp_val > 0 else 0.0
    tss_hora = round(tss_val / horas_mov, 1) if horas_mov > 0 else 0.0

    # Tasas de trabajo metabólico / energético específico
    kj_kg_total = round(total_kj / peso_val, 1)
    kj_kg_hora = round(kj_kg_total / horas_mov, 1) if horas_mov > 0 else round((pot_media / peso_val) * 3.6, 1)
    np_kj_kg_hora = round((np_pot / peso_val) * 3.6, 1) if peso_val > 0 else 0.0
    kcal_estimadas = int(round(total_kj))
    kcal_hora_estimada = int(round(kj_kg_hora * peso_val))

    tiempo_mov_str = str(timedelta(seconds=int(tiempo_mov_seg)))
    tiempo_bruto_str = str(timedelta(seconds=int(duracion_bruta_seg)))

    stats = {
        'nombre': nombre,
        'atleta_id': atleta_id,
        'peso_kg': peso,
        'ftp_w': int(round(ftp_val)),
        'if_val': if_val,
        'tss_total': int(round(tss_val)),
        'tss_hora': tss_hora,
        'distancia_km': round(distancia_total_km, 2),
        'desnivel_pos_m': int(round(desnivel_pos)),
        'altitud_min': int(round(df_gps['altitud'].min())),
        'altitud_max': int(round(df_gps['altitud'].max())),
        'tiempo_total_str': tiempo_mov_str,  # El tiempo mostrado como oficial es el tiempo en movimiento
        'tiempo_mov_str': tiempo_mov_str,
        'tiempo_bruto_str': tiempo_bruto_str,
        'duracion_seg': int(tiempo_mov_seg),
        'tiempo_mov_seg': int(tiempo_mov_seg),
        'duracion_bruta_seg': int(duracion_bruta_seg),
        'vel_media_kmh': round(vel_media, 1),
        'vel_max_kmh': round(vel_max, 1),
        'pot_media_w': int(round(pot_media)),
        'pot_max_w': int(round(pot_max)),
        'np_w': int(round(np_pot)),
        'w_kg_media': round(pot_media / peso_val, 2),
        'kilojulios_total': int(round(total_kj)),
        'kj_kg': kj_kg_total,
        'kj_kg_hora': kj_kg_hora,
        'np_kj_kg_hora': np_kj_kg_hora,
        'kcal_estimadas': kcal_estimadas,
        'kcal_hora_estimada': kcal_hora_estimada,
        'fc_media_bpm': int(round(fc_media)),
        'fc_max_bpm': int(round(fc_max)),
        'cadencia_media_rpm': int(round(cad_media)),
        'color': color_cfg['primary'],
        'color_sec': color_cfg['secondary'],
        'glow': color_cfg['glow'],
        'badge': color_cfg['badge'],
        'num_puntos': len(df_gps),
    }

    # Desglose horario de gasto energético y ritmo sobre tiempo en movimiento (Hourly Energy Breakdown)
    desglose_horas = []
    duracion_horas_total = max(1, math.ceil(tiempo_mov_seg / 3600.0))
    t_mov_sec_arr = np.arange(len(df_gps), dtype=float)

    for h_idx in range(duracion_horas_total):
        t_h_inicio = h_idx * 3600.0
        t_h_fin = min((h_idx + 1) * 3600.0, tiempo_mov_seg)
        if t_h_fin <= t_h_inicio:
            continue

        h_mask = (t_mov_sec_arr >= t_h_inicio) & (t_mov_sec_arr < t_h_fin)
        if not h_mask.any():
            continue

        df_h = df_gps.loc[h_mask]
        t_mov_h_seg = float(len(df_h))
        t_mov_h_hr = max(0.01, t_mov_h_seg / 3600.0)

        # Delta de kJ en esta franja horaria
        kj_acum_h = df_gps['kilojulios_acum'].loc[h_mask]
        kj_h = float(kj_acum_h.iloc[-1] - kj_acum_h.iloc[0]) if len(kj_acum_h) > 1 else float(kj_acum_h.iloc[0]) if len(kj_acum_h) == 1 else 0.0
        kj_h = max(0.0, kj_h)

        dist_h_series = df_gps['distancia'].loc[h_mask] / 1000.0
        dist_h = float(dist_h_series.iloc[-1] - dist_h_series.iloc[0]) if len(dist_h_series) > 1 else 0.0

        alt_diff_h = alt_diff.loc[h_mask]
        desn_h = float(alt_diff_h[alt_diff_h > 0].sum()) if (alt_diff_h > 0).any() else 0.0

        # Potencia y NP en movimiento de la hora
        pwr_h_media = float(df_h['potencia'].mean()) if not df_h.empty else 0.0
        pot_h_mov_vals = df_h['potencia'].values
        np_h = calcular_potencia_normalizada(pot_h_mov_vals) if len(pot_h_mov_vals) > 0 else 0.0
        wkg_h = round(pwr_h_media / peso_val, 2)
        kj_kg_h_val = round(kj_h / peso_val, 1)
        tasa_kj_kg_h = round(kj_kg_h_val / t_mov_h_hr, 1) if t_mov_h_hr > 0 else round(wkg_h * 3.6, 1)
        
        fc_h_mov = df_h.loc[df_h['fc'] > 40, 'fc'] if 'fc' in df_h.columns else pd.Series()
        fc_h_media = float(fc_h_mov.mean()) if not fc_h_mov.empty else 0.0

        desglose_horas.append({
            'hora_num': h_idx + 1,
            'label': f"Hora {h_idx + 1}",
            'duracion_min': round(t_mov_h_seg / 60.0, 1),
            'tiempo_mov_min': round(t_mov_h_seg / 60.0, 1),
            'distancia_km': round(max(0.0, dist_h), 1),
            'desnivel_m': int(round(desn_h)),
            'pot_media_w': int(round(pwr_h_media)),
            'np_w': int(round(np_h)),
            'w_kg': wkg_h,
            'kj_total': int(round(kj_h)),
            'kj_kg': kj_kg_h_val,
            'kj_kg_h': tasa_kj_kg_h,
            'fc_media': int(round(fc_h_media)),
        })

    # Suavizado de telemetría agrupada a 60 muestras de movimiento (60s rolling average)
    df_gps['potencia_smooth_60s'] = df_gps['potencia'].rolling(window=60, min_periods=1, center=True).mean()
    df_gps['fc_smooth_60s'] = df_gps['fc'].astype(float).rolling(window=60, min_periods=1, center=True).mean()
    df_gps['velocidad_smooth_60s'] = df_gps['velocidad_kmh'].astype(float).rolling(window=60, min_periods=1, center=True).mean()

    # Interpolación en rejilla uniforme de distancia (Sincronización espacial)
    dists_km_arr = (df_gps['distancia'].values / 1000.0).clip(min=0.0)

    grid_max = dist_referencia_km if (dist_referencia_km is not None and dist_referencia_km > distancia_total_km * 0.95) else distancia_total_km
    grid_dist = np.linspace(0.0, grid_max, num_grid_points)

    lat_by_dist = np.interp(grid_dist, dists_km_arr, df_gps['lat'].values)
    lon_by_dist = np.interp(grid_dist, dists_km_arr, df_gps['lon'].values)
    alt_by_dist = np.interp(grid_dist, dists_km_arr, df_gps['altitud'].values)
    pwr_by_dist = np.interp(grid_dist, dists_km_arr, df_gps['potencia_smooth_60s'].values)
    kj_by_dist = np.interp(grid_dist, dists_km_arr, df_gps['kilojulios_acum'].values)
    spd_by_dist = np.interp(grid_dist, dists_km_arr, df_gps['velocidad_smooth_60s'].values)
    hr_by_dist = np.interp(grid_dist, dists_km_arr, df_gps['fc_smooth_60s'].values)
    cad_by_dist = np.interp(grid_dist, dists_km_arr, df_gps['cadencia'].values)
    grad_by_dist = np.interp(grid_dist, dists_km_arr, df_gps['pendiente'].values)
    t_by_dist = np.interp(grid_dist, dists_km_arr, t_mov_sec_arr)

    samples_by_dist = []
    for i in range(num_grid_points):
        d_val = round(float(grid_dist[i]), 2)
        t_val = int(round(float(t_by_dist[i])))
        tss_cum = round((t_val / 3600.0) * (if_val ** 2) * 100.0, 1) if ftp_val > 0 else 0.0
        wkg_val = round(float(pwr_by_dist[i] / peso_val), 2)
        samples_by_dist.append({
            'd_km': d_val,
            'alt': round(float(alt_by_dist[i]), 1),
            'lat': round(float(lat_by_dist[i]), 6),
            'lon': round(float(lon_by_dist[i]), 6),
            'pwr': int(round(float(pwr_by_dist[i]))),
            'wkg': wkg_val,
            'tss': tss_cum,
            'kj': int(round(float(kj_by_dist[i]))),
            'kj_kg': round(float(kj_by_dist[i] / peso_val), 1),
            'kjkg_h': round(float(wkg_val * 3.6), 1),
            'spd': round(float(spd_by_dist[i]), 1),
            'hr': int(round(float(hr_by_dist[i]))),
            'cad': int(round(float(cad_by_dist[i]))),
            'grad': round(float(grad_by_dist[i]), 1),
            't_sec': t_val,
            't_str': str(timedelta(seconds=t_val))
        })

    # Interpolación en rejilla uniforme de tiempo en movimiento (Sincronización temporal)
    grid_time_mov = np.linspace(0.0, max(1.0, tiempo_mov_seg), num_grid_points)
    d_by_time = np.interp(grid_time_mov, t_mov_sec_arr, dists_km_arr)
    lat_by_time = np.interp(grid_time_mov, t_mov_sec_arr, df_gps['lat'].values)
    lon_by_time = np.interp(grid_time_mov, t_mov_sec_arr, df_gps['lon'].values)
    alt_by_time = np.interp(grid_time_mov, t_mov_sec_arr, df_gps['altitud'].values)
    pwr_by_time = np.interp(grid_time_mov, t_mov_sec_arr, df_gps['potencia_smooth_60s'].values)
    kj_by_time = np.interp(grid_time_mov, t_mov_sec_arr, df_gps['kilojulios_acum'].values)
    spd_by_time = np.interp(grid_time_mov, t_mov_sec_arr, df_gps['velocidad_smooth_60s'].values)
    hr_by_time = np.interp(grid_time_mov, t_mov_sec_arr, df_gps['fc_smooth_60s'].values)
    cad_by_time = np.interp(grid_time_mov, t_mov_sec_arr, df_gps['cadencia'].values)
    grad_by_time = np.interp(grid_time_mov, t_mov_sec_arr, df_gps['pendiente'].values)

    samples_by_time = []
    for i in range(num_grid_points):
        t_val = int(round(float(grid_time_mov[i])))
        d_val = round(float(d_by_time[i]), 2)
        tss_cum = round((t_val / 3600.0) * (if_val ** 2) * 100.0, 1) if ftp_val > 0 else 0.0
        wkg_val = round(float(pwr_by_time[i] / peso_val), 2)
        samples_by_time.append({
            't_sec': t_val,
            't_str': str(timedelta(seconds=t_val)),
            'd_km': d_val,
            'alt': round(float(alt_by_time[i]), 1),
            'lat': round(float(lat_by_time[i]), 6),
            'lon': round(float(lon_by_time[i]), 6),
            'pwr': int(round(float(pwr_by_time[i]))),
            'wkg': wkg_val,
            'tss': tss_cum,
            'kj': int(round(float(kj_by_time[i]))),
            'kj_kg': round(float(kj_by_time[i] / peso_val), 1),
            'kjkg_h': round(float(wkg_val * 3.6), 1),
            'spd': round(float(spd_by_time[i]), 1),
            'hr': int(round(float(hr_by_time[i]))),
            'cad': int(round(float(cad_by_time[i]))),
            'grad': round(float(grad_by_time[i]), 1),
        })

    return {
        'stats': stats,
        'samples_by_dist': samples_by_dist,
        'samples_by_time': samples_by_time,
        'desglose_horas': desglose_horas,
        'df_gps': df_gps,
    }


def detectar_tramos_etapa(perfil_altimetria: List[Dict[str, Any]], distancia_total_km: float) -> List[Dict[str, Any]]:
    """
    Detecta automáticamente ascensiones significativas (puertos, cotas) y tramos clave estándar
    de la etapa a partir del perfil altimétrico de referencia.
    """
    tramos = []

    # 1. Preset: Etapa Completa
    tramos.append({
        'id': 'full_stage',
        'tipo': 'general',
        'nombre': 'Etapa Completa',
        'km_inicio': 0.0,
        'km_fin': round(float(distancia_total_km), 2),
        'distancia_km': round(float(distancia_total_km), 2),
        'icono': 'flag',
        'badge': 'General',
        'color': '#7c3aed'
    })

    # 2. Algoritmo de detección de puertos / ascensiones en el perfil
    if perfil_altimetria and len(perfil_altimetria) >= 10:
        dists = np.array([p['x'] for p in perfil_altimetria])
        alts = np.array([p['y'] for p in perfil_altimetria])

        # Suavizado de altitud para detección robusta de cotas y cumbres
        window = max(5, int(len(alts) * 0.015))
        if window % 2 == 0:
            window += 1
        alt_s = pd.Series(alts).rolling(window=window, min_periods=1, center=True).mean().values

        puertos_candidatos = []
        i = 0
        n = len(alt_s)
        while i < n - 5:
            # Buscar inicio de subida: pendiente positiva continuada
            if i + 5 < n and (alt_s[i+5] - alt_s[i]) > 3.0:
                start_idx = i
                max_alt_local = alt_s[start_idx]
                max_idx_local = start_idx
                j = start_idx + 1
                while j < n:
                    if alt_s[j] > max_alt_local:
                        max_alt_local = alt_s[j]
                        max_idx_local = j
                    elif (max_alt_local - alt_s[j]) > 30.0 or (dists[j] - dists[max_idx_local]) > 3.0:
                        break
                    j += 1

                if max_idx_local > start_idx:
                    d_subida = dists[max_idx_local] - dists[start_idx]
                    desn_subida = max_alt_local - alt_s[start_idx]
                    if d_subida >= 1.0 and desn_subida >= 40.0:
                        pend_media = (desn_subida / (d_subida * 1000.0)) * 100.0
                        if pend_media >= 1.8:
                            puertos_candidatos.append({
                                'start_idx': start_idx,
                                'end_idx': max_idx_local,
                                'km_ini': round(float(dists[start_idx]), 1),
                                'km_fin': round(float(dists[max_idx_local]), 1),
                                'dist_km': round(float(d_subida), 1),
                                'desnivel_m': int(round(desn_subida)),
                                'pend_media': round(float(pend_media), 1),
                                'alt_max': int(round(max_alt_local))
                            })
                i = max(i + 1, max_idx_local + 5)
            else:
                i += 1

        # Filtrar solapamientos
        puertos_filtrados = []
        for p in sorted(puertos_candidatos, key=lambda x: x['desnivel_m'], reverse=True):
            solapado = False
            for pf in puertos_filtrados:
                if max(p['km_ini'], pf['km_ini']) < min(p['km_fin'], pf['km_fin']):
                    solapado = True
                    break
            if not solapado:
                puertos_filtrados.append(p)

        puertos_filtrados.sort(key=lambda x: x['km_ini'])

        for p_idx, p in enumerate(puertos_filtrados, 1):
            desn = p['desnivel_m']
            pend = p['pend_media']
            d_km = p['dist_km']
            score_apm = desn * pend
            if desn >= 650 or score_apm >= 4000:
                cat = "1ª Cat"
                cat_color = "#ef4444"
                cat_tag = "Puerto 1ª Cat"
            elif desn >= 350 or score_apm >= 2000:
                cat = "2ª Cat"
                cat_color = "#f97316"
                cat_tag = "Puerto 2ª Cat"
            elif desn >= 150 or score_apm >= 900:
                cat = "3ª Cat"
                cat_color = "#eab308"
                cat_tag = "Puerto 3ª Cat"
            else:
                cat = "Cota"
                cat_color = "#10b981"
                cat_tag = "Cota / Subida"

            tramos.append({
                'id': f"climb_{p_idx}",
                'tipo': 'puerto',
                'nombre': f"{cat_tag} (Km {p['km_ini']} → {p['km_fin']})",
                'km_inicio': p['km_ini'],
                'km_fin': p['km_fin'],
                'distancia_km': d_km,
                'desnivel_m': desn,
                'pendiente_media': pend,
                'altitud_max': p['alt_max'],
                'categoria': cat,
                'icono': 'mountain',
                'badge': f"+{desn}m @ {pend}%",
                'color': cat_color
            })

    # 3. Presets Estándar de Carrera
    dist_tot = float(distancia_total_km)
    if dist_tot > 60.0:
        tramos.append({
            'id': 'first_50km',
            'tipo': 'carrera',
            'nombre': '🚩 Primeros 50 km',
            'km_inicio': 0.0,
            'km_fin': 50.0,
            'distancia_km': 50.0,
            'icono': 'chevrons-right',
            'badge': 'Km 0 - 50',
            'color': '#38bdf8'
        })

    if dist_tot > 55.0:
        k_ini = round(max(0.0, dist_tot - 50.0), 1)
        tramos.append({
            'id': 'last_50km',
            'tipo': 'carrera',
            'nombre': '🏁 Últimos 50 km',
            'km_inicio': k_ini,
            'km_fin': round(dist_tot, 1),
            'distancia_km': round(dist_tot - k_ini, 1),
            'icono': 'flag',
            'badge': f"Km {k_ini} - {round(dist_tot, 1)}",
            'color': '#a855f7'
        })

    if dist_tot > 25.0:
        k_ini = round(max(0.0, dist_tot - 20.0), 1)
        tramos.append({
            'id': 'last_20km',
            'tipo': 'carrera',
            'nombre': '⚡ Últimos 20 km (Final)',
            'km_inicio': k_ini,
            'km_fin': round(dist_tot, 1),
            'distancia_km': round(dist_tot - k_ini, 1),
            'icono': 'zap',
            'badge': f"Km {k_ini} - {round(dist_tot, 1)}",
            'color': '#ec4899'
        })

    if dist_tot > 12.0:
        k_ini = round(max(0.0, dist_tot - 10.0), 1)
        tramos.append({
            'id': 'last_10km',
            'tipo': 'carrera',
            'nombre': '🔥 Últimos 10 km',
            'km_inicio': k_ini,
            'km_fin': round(dist_tot, 1),
            'distancia_km': round(dist_tot - k_ini, 1),
            'icono': 'flame',
            'badge': f"Km {k_ini} - {round(dist_tot, 1)}",
            'color': '#f97316'
        })

    if dist_tot > 6.0:
        k_ini = round(max(0.0, dist_tot - 5.0), 1)
        tramos.append({
            'id': 'last_5km',
            'tipo': 'carrera',
            'nombre': '🎯 Últimos 5 km (Sprint / Meta)',
            'km_inicio': k_ini,
            'km_fin': round(dist_tot, 1),
            'distancia_km': round(dist_tot - k_ini, 1),
            'icono': 'target',
            'badge': f"Km {k_ini} - {round(dist_tot, 1)}",
            'color': '#ef4444'
        })

    return tramos


def construir_perfil_etapa_referencia(ciclistas_proc: List[Dict[str, Any]], num_points: int = 1000) -> Dict[str, Any]:
    """
    Construye el perfil de altimetría de referencia unificado a partir del ciclista
    que completó la ruta más extensa.
    """
    ciclista_ref = max(ciclistas_proc, key=lambda c: c['stats']['distancia_km'])
    muestras_dist = ciclista_ref['samples_by_dist']

    coordenadas_track = [[m['lat'], m['lon']] for m in muestras_dist]
    
    perfil_altimetria = [
        {
            'x': m['d_km'],
            'y': m['alt'],
            'lat': m['lat'],
            'lon': m['lon'],
            'grad': m['grad'],
        }
        for m in muestras_dist
    ]

    alts = np.array([m['alt'] for m in muestras_dist])
    dists = np.array([m['d_km'] for m in muestras_dist])
    
    cumbres = []
    idx_max = int(np.argmax(alts))
    cumbres.append({
        'nombre': f"Cumbre Etapa ({int(alts[idx_max])}m)",
        'dist_km': round(float(dists[idx_max]), 1),
        'altitud': int(alts[idx_max]),
        'lat': muestras_dist[idx_max]['lat'],
        'lon': muestras_dist[idx_max]['lon'],
    })

    lats = [c[0] for c in coordenadas_track]
    lons = [c[1] for c in coordenadas_track]
    centro_mapa = [round(float(np.mean(lats)), 5), round(float(np.mean(lons)), 5)]

    bounds = [
        [round(float(np.min(lats)), 5), round(float(np.min(lons)), 5)],
        [round(float(np.max(lats)), 5), round(float(np.max(lons)), 5)]
    ]

    dist_total = ciclista_ref['stats']['distancia_km']
    segmentos_sugeridos = detectar_tramos_etapa(perfil_altimetria, dist_total)

    return {
        'ciclista_referencia': ciclista_ref['stats']['nombre'],
        'distancia_total_km': dist_total,
        'desnivel_pos_m': ciclista_ref['stats']['desnivel_pos_m'],
        'altitud_min': ciclista_ref['stats']['altitud_min'],
        'altitud_max': ciclista_ref['stats']['altitud_max'],
        'coordenadas_track': coordenadas_track,
        'perfil_altimetria': perfil_altimetria,
        'cumbres': cumbres,
        'centro_mapa': centro_mapa,
        'bounds': bounds,
        'segmentos_sugeridos': segmentos_sugeridos,
    }


def _obtener_logo_base64(preferencia: str = "negro", logo_path: Optional[Union[str, Path]] = None) -> str:
    """
    Busca LOGO.svg en assets/ (o logonegro.png / logoblanco.png en src/ o assets/) y lo devuelve como data URI base64.
    Prioriza el archivo LOGO.svg en la carpeta assets/.
    """
    import base64
    import io
    from pathlib import Path

    # 1. Si se proporciona una ruta explícita y existe
    if logo_path and Path(logo_path).exists() and Path(logo_path).is_file():
        p = Path(logo_path)
        if p.suffix.lower() == '.svg':
            try:
                raw_bytes = p.read_bytes()
                if raw_bytes:
                    b64 = base64.b64encode(raw_bytes).decode('utf-8')
                    return f"data:image/svg+xml;base64,{b64}"
            except Exception:
                pass
        else:
            try:
                b64 = base64.b64encode(p.read_bytes()).decode('utf-8')
                return f"data:image/png;base64,{b64}"
            except Exception:
                pass

    # 2. Prioridad máxima: assets/LOGO.svg o assets/logo.svg
    candidatos_svg = [
        Path(__file__).resolve().parent.parent / "assets" / "LOGO.svg",
        Path(__file__).resolve().parent.parent / "assets" / "logo.svg",
        Path(__file__).resolve().parent / "assets" / "LOGO.svg",
        Path(__file__).resolve().parent / "assets" / "logo.svg",
        _ROOT_DIR / "assets" / "LOGO.svg",
        _ROOT_DIR / "assets" / "logo.svg",
        Path("assets/LOGO.svg"),
        Path("assets/logo.svg"),
    ]

    for p in candidatos_svg:
        if p.exists() and p.is_file():
            try:
                raw_bytes = p.read_bytes()
                if raw_bytes:
                    b64 = base64.b64encode(raw_bytes).decode('utf-8')
                    return f"data:image/svg+xml;base64,{b64}"
            except Exception:
                pass

    # 3. Fallback a imágenes ráster en assets/ o src/
    if preferencia == "negro":
        archivos = ["LOGO.png", "logo.png", "logonegro.png", "logoblanco.png"]
    else:
        archivos = ["logoblanco.png", "logo.png", "LOGO.png", "logonegro.png"]

    directorios = [
        Path(__file__).resolve().parent.parent / "assets",
        Path(__file__).resolve().parent.parent / "src",
        Path(__file__).resolve().parent,
        _ROOT_DIR / "assets",
        _ROOT_DIR / "src",
    ]

    for d in directorios:
        for arch in archivos:
            p = d / arch
            if p.exists() and p.is_file():
                if p.suffix.lower() == '.svg':
                    try:
                        raw_bytes = p.read_bytes()
                        b64 = base64.b64encode(raw_bytes).decode('utf-8')
                        return f"data:image/svg+xml;base64,{b64}"
                    except Exception:
                        pass
                else:
                    try:
                        import numpy as np
                        from PIL import Image

                        img = Image.open(p).convert('RGBA')
                        arr = np.array(img)
                        
                        # Convertir fondo casi blanco (> 225 en RGB) a transparente
                        mask_blanco = (arr[:, :, 0] > 225) & (arr[:, :, 1] > 225) & (arr[:, :, 2] > 225)
                        arr[mask_blanco, 3] = 0
                        
                        img_trans = Image.fromarray(arr)
                        bbox = img_trans.getbbox()
                        if bbox:
                            img_cropped = img_trans.crop(bbox)
                        else:
                            img_cropped = img_trans

                        img_cropped.thumbnail((450, 180), Image.Resampling.LANCZOS)
                        buf = io.BytesIO()
                        img_cropped.save(buf, format="PNG", optimize=True)
                        b64 = base64.b64encode(buf.getvalue()).decode('utf-8')
                        return f"data:image/png;base64,{b64}"
                    except Exception:
                        try:
                            b64 = base64.b64encode(p.read_bytes()).decode('utf-8')
                            return f"data:image/png;base64,{b64}"
                        except Exception:
                            pass
    return ""



HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>__TITULO_ETAPA__ | Intervals & FIT Analytics</title>
    
    <!-- Fuentes modernas -->
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800;900&family=Outfit:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500;700&display=swap" rel="stylesheet">
    
    <!-- Leaflet CSS para Mapas -->
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" integrity="sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY=" crossorigin=""/>
    
    <!-- Chart.js para gráficos de altimetría y telemetría sincronizada -->
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
    <!-- Leaflet JS -->
    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js" integrity="sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo=" crossorigin=""></script>
    <!-- Lucide Icons -->
    <script src="https://unpkg.com/lucide@latest"></script>

    <style>
        :root {
            /* Paleta Burgos Burpellet BH — Light Theme (Default) */
            --bg-base: #f8f6fc;
            --bg-card: rgba(255, 255, 255, 0.96);
            --bg-card-hover: #ffffff;
            --border-card: rgba(124, 58, 237, 0.12);
            --border-glow: rgba(124, 58, 237, 0.25);
            --border-subtle: rgba(124, 58, 237, 0.08);
            --text-main: #1e152d;
            --text-muted: #645a78;
            --text-accent: #7c3aed;
            
            --bg-panel: #ffffff;
            --bg-panel-solid: #f3eff9;
            --bg-btn: #ffffff;
            --bg-btn-hover: #f1ecf9;
            --bg-metric: #f5f1fb;
            --bg-map: #eef0f6;
            --bg-bio: #ffffff;
            --bg-table-th: #f3eff9;
            --border-btn: rgba(124, 58, 237, 0.18);
            --header-gradient: linear-gradient(135deg, #1e152d 0%, #7c3aed 100%);
            --card-shadow: 0 4px 20px rgba(124, 58, 237, 0.06), 0 1px 3px rgba(0, 0, 0, 0.03);
            --card-shadow-hover: 0 8px 30px rgba(124, 58, 237, 0.12), 0 2px 6px rgba(0, 0, 0, 0.04);
            --text-inverted: #ffffff;
            
            --color-primary: #7c3aed;
            --color-accent: #e035a1;
            --color-jersey-start: #6d28d9;
            --color-jersey-mid: #e035a1;
            --color-jersey-end: #f472b6;
            --font-display: 'Inter', sans-serif;
            --font-body: 'Outfit', sans-serif;
            --font-mono: 'JetBrains Mono', monospace;
        }

        [data-theme="dark"] {
            /* Paleta Burgos Burpellet BH — Dark Theme */
            --bg-base: #0a0515;
            --bg-card: rgba(18, 10, 32, 0.92);
            --bg-card-hover: rgba(28, 16, 50, 0.98);
            --border-card: rgba(124, 58, 237, 0.15);
            --border-glow: rgba(124, 58, 237, 0.35);
            --border-subtle: rgba(255, 255, 255, 0.05);
            --text-main: #f8fafc;
            --text-muted: #a89ec4;
            --text-accent: #a855f7;
            
            --bg-panel: rgba(18, 10, 32, 0.9);
            --bg-panel-solid: #130a24;
            --bg-btn: #1b1130;
            --bg-btn-hover: #2a1b47;
            --bg-metric: rgba(28, 16, 50, 0.7);
            --bg-map: #0f172a;
            --bg-bio: rgba(28, 16, 50, 0.6);
            --bg-table-th: #160c2b;
            --border-btn: rgba(124, 58, 237, 0.3);
            --header-gradient: linear-gradient(135deg, #ffffff 0%, #c4b5fd 100%);
            --card-shadow: 0 4px 20px rgba(0, 0, 0, 0.4);
            --card-shadow-hover: 0 8px 30px rgba(0, 0, 0, 0.6);
            --text-inverted: #090d16;
        }

        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        body {
            background: var(--bg-base);
            background-image: 
                radial-gradient(at 0% 0%, rgba(124, 58, 237, 0.07) 0px, transparent 50%),
                radial-gradient(at 100% 100%, rgba(224, 53, 161, 0.05) 0px, transparent 50%),
                radial-gradient(at 50% 50%, rgba(91, 33, 182, 0.03) 0px, transparent 60%);
            color: var(--text-main);
            font-family: var(--font-body);
            min-height: 100vh;
            padding: 24px;
            overflow-x: hidden;
            transition: background 0.3s ease, color 0.3s ease;
        }

        /* Header Principal */
        .header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 20px;
            margin-bottom: 24px;
            padding-bottom: 20px;
            border-bottom: 1px solid var(--border-card);
        }

        .header-title-group h1 {
            font-family: var(--font-display);
            font-size: 1.85rem;
            font-weight: 800;
            letter-spacing: -0.01em;
            background: var(--header-gradient);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            display: flex;
            align-items: center;
            gap: 12px;
        }

        .header-title-group p {
            color: var(--text-muted);
            font-size: 0.95rem;
            margin-top: 4px;
        }

        .header-badges {
            display: flex;
            gap: 10px;
            flex-wrap: wrap;
            align-items: center;
        }

        .badge {
            background: var(--bg-panel);
            border: 1px solid var(--border-card);
            padding: 8px 14px;
            border-radius: 12px;
            font-family: var(--font-mono);
            font-size: 0.85rem;
            display: flex;
            align-items: center;
            gap: 6px;
            color: var(--text-main);
            box-shadow: var(--card-shadow);
        }

        .badge.highlight {
            border-color: rgba(124, 58, 237, 0.3);
            background: rgba(124, 58, 237, 0.08);
            color: var(--text-accent);
            font-weight: 600;
        }

        .theme-toggle-btn {
            background: var(--bg-panel);
            border: 1px solid var(--border-card);
            padding: 8px 12px;
            border-radius: 12px;
            cursor: pointer;
            display: flex;
            align-items: center;
            gap: 6px;
            color: var(--text-main);
            font-family: var(--font-display);
            font-size: 0.85rem;
            font-weight: 600;
            transition: all 0.2s ease;
            box-shadow: var(--card-shadow);
        }

        .theme-toggle-btn:hover {
            border-color: var(--color-primary);
            transform: translateY(-1px);
        }

        /* Tarjetas de Ciclistas (Live HUD) */
        .riders-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
            gap: 16px;
            margin-bottom: 20px;
        }

        .rider-card {
            background: var(--bg-card);
            backdrop-filter: blur(16px);
            border: 1px solid var(--border-card);
            border-radius: 18px;
            padding: 16px 18px;
            position: relative;
            overflow: hidden;
            transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1);
            box-shadow: var(--card-shadow);
        }

        .rider-card::before {
            content: '';
            position: absolute;
            top: 0;
            left: 0;
            width: 4px;
            height: 100%;
            background: var(--rider-color);
            box-shadow: 0 0 10px var(--rider-color);
        }

        .rider-card:hover {
            transform: translateY(-3px);
            border-color: var(--border-glow);
            box-shadow: var(--card-shadow-hover);
        }

        .rider-header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            margin-bottom: 12px;
        }

        .rider-avatar-name {
            display: flex;
            align-items: center;
            gap: 10px;
        }

        .rider-avatar {
            width: 38px;
            height: 38px;
            border-radius: 50%;
            background: var(--rider-color);
            color: #ffffff;
            font-weight: 800;
            font-family: var(--font-display);
            font-size: 0.95rem;
            display: flex;
            align-items: center;
            justify-content: center;
            box-shadow: 0 2px 8px rgba(0, 0, 0, 0.15);
        }

        .rider-name {
            font-family: var(--font-display);
            font-weight: 700;
            font-size: 1.05rem;
            color: var(--text-main);
        }

        .rider-rank-badge {
            font-family: var(--font-mono);
            font-size: 0.8rem;
            font-weight: 700;
            padding: 4px 8px;
            border-radius: 8px;
            background: var(--bg-panel-solid);
            border: 1px solid var(--border-card);
            color: var(--text-muted);
        }

        .rider-rank-badge.leader {
            background: rgba(245, 158, 11, 0.15);
            color: #d97706;
            border-color: rgba(245, 158, 11, 0.4);
            font-weight: 800;
        }

        .rider-metrics-grid {
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 8px;
            text-align: center;
        }

        @media (max-width: 768px) {
            .rider-metrics-grid {
                grid-template-columns: repeat(2, 1fr);
            }
        }

        .metric-mini-box {
            background: var(--bg-metric);
            border-radius: 10px;
            padding: 8px 4px;
            border: 1px solid var(--border-subtle);
        }

        .metric-mini-val {
            font-family: var(--font-mono);
            font-size: 0.95rem;
            font-weight: 700;
            color: var(--text-main);
        }

        .metric-mini-lbl {
            font-size: 0.7rem;
            color: var(--text-muted);
            margin-top: 2px;
            font-family: var(--font-display);
            text-transform: uppercase;
            letter-spacing: 0.04em;
            font-weight: 600;
        }

        /* Barra de Controles y Reproducción */
        .controls-bar {
            background: var(--bg-card);
            backdrop-filter: blur(16px);
            border: 1px solid var(--border-card);
            border-radius: 20px;
            padding: 16px 20px;
            margin-bottom: 20px;
            box-shadow: var(--card-shadow);
        }

        .controls-top-row {
            display: flex;
            align-items: center;
            justify-content: space-between;
            flex-wrap: wrap;
            gap: 14px;
        }

        .playback-buttons {
            display: flex;
            align-items: center;
            gap: 10px;
            flex-wrap: wrap;
        }

        .btn-ctrl {
            background: var(--bg-btn);
            border: 1px solid var(--border-card);
            color: var(--text-main);
            border-radius: 10px;
            padding: 8px 14px;
            font-size: 0.9rem;
            font-weight: 600;
            cursor: pointer;
            display: inline-flex;
            align-items: center;
            gap: 6px;
            transition: all 0.15s ease;
            box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05);
        }

        .btn-ctrl:hover {
            background: var(--bg-btn-hover);
            border-color: var(--border-btn);
        }

        .btn-ctrl.primary {
            background: linear-gradient(135deg, var(--color-jersey-start), var(--color-accent)) !important;
            border-color: rgba(124, 58, 237, 0.4);
            color: #ffffff !important;
            box-shadow: 0 4px 14px rgba(124, 58, 237, 0.25);
        }

        .btn-ctrl.primary * {
            color: #ffffff !important;
        }

        .btn-ctrl.primary:hover {
            background: linear-gradient(135deg, #5b21b6, #be185d) !important;
            box-shadow: 0 6px 18px rgba(124, 58, 237, 0.35);
        }

        .mode-toggle-group {
            display: flex;
            background: var(--bg-panel-solid);
            border-radius: 10px;
            padding: 4px;
            border: 1px solid var(--border-card);
            gap: 4px;
        }

        .mode-btn {
            background: transparent;
            border: none;
            color: var(--text-muted);
            padding: 6px 12px;
            border-radius: 8px;
            font-family: var(--font-display);
            font-size: 0.85rem;
            font-weight: 600;
            cursor: pointer;
            display: flex;
            align-items: center;
            gap: 6px;
            transition: all 0.15s ease;
        }

        .mode-btn.active {
            background: var(--color-primary);
            color: #ffffff !important;
            box-shadow: 0 2px 8px rgba(124, 58, 237, 0.35);
        }

        .speed-selector {
            display: flex;
            align-items: center;
            gap: 4px;
            background: var(--bg-panel-solid);
            padding: 4px;
            border-radius: 10px;
            border: 1px solid var(--border-card);
        }

        .speed-btn {
            background: transparent;
            border: none;
            color: var(--text-muted);
            padding: 4px 8px;
            border-radius: 6px;
            font-family: var(--font-mono);
            font-size: 0.8rem;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.15s ease;
        }

        .speed-btn.active {
            background: rgba(124, 58, 237, 0.15);
            color: var(--color-primary);
            font-weight: 700;
        }

        .timeline-timer {
            font-family: var(--font-mono);
            font-size: 1.15rem;
            font-weight: 700;
            color: var(--color-primary);
            background: var(--bg-panel);
            padding: 6px 14px;
            border-radius: 10px;
            border: 1px solid var(--border-card);
            box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05);
        }

        .slider-container {
            margin-top: 14px;
            display: flex;
            align-items: center;
            gap: 12px;
        }

        .custom-range {
            flex: 1;
            -webkit-appearance: none;
            appearance: none;
            height: 8px;
            border-radius: 4px;
            background: #e2e8f0;
            outline: none;
            cursor: pointer;
            transition: background 0.15s;
        }

        [data-theme="dark"] .custom-range {
            background: #2a1b47;
        }

        .custom-range::-webkit-slider-thumb {
            -webkit-appearance: none;
            appearance: none;
            width: 20px;
            height: 20px;
            border-radius: 50%;
            background: var(--color-primary);
            cursor: pointer;
            box-shadow: 0 2px 8px rgba(124, 58, 237, 0.4);
            border: 2px solid #ffffff;
            transition: transform 0.1s ease;
        }

        .custom-range::-webkit-slider-thumb:hover {
            transform: scale(1.2);
        }

        /* Grid Principal de Visualización (Mapa + Perfil) */
        .viz-grid {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 20px;
            margin-bottom: 20px;
            transition: all 0.25s ease;
        }

        .viz-grid.hidden {
            display: none !important;
        }

        @media (max-width: 1100px) {
            .viz-grid {
                grid-template-columns: 1fr;
            }
        }

        .viz-card {
            background: var(--bg-card);
            backdrop-filter: blur(16px);
            border: 1px solid var(--border-card);
            border-radius: 20px;
            padding: 20px;
            position: relative;
            box-shadow: var(--card-shadow);
            display: flex;
            flex-direction: column;
        }

        .viz-header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            margin-bottom: 14px;
            flex-wrap: wrap;
            gap: 10px;
        }

        .viz-title {
            font-family: var(--font-display);
            font-size: 1.1rem;
            font-weight: 700;
            color: var(--text-main);
            display: flex;
            align-items: center;
            gap: 8px;
        }

        #map {
            height: 380px;
            width: 100%;
            border-radius: 14px;
            border: 1px solid var(--border-card);
            background: var(--bg-map);
            z-index: 1;
        }

        .chart-wrapper {
            position: relative;
            flex: 1;
            min-height: 380px;
            width: 100%;
        }

        /* Marcadores del Mapa */
        .rider-marker-div {
            background: transparent !important;
            border: none !important;
            box-shadow: none !important;
            overflow: visible !important;
            padding: 0 !important;
        }
        .rider-map-marker {
            width: 32px;
            height: 32px;
            border-radius: 50%;
            background: var(--m-color);
            color: #ffffff;
            font-weight: 800;
            font-family: var(--font-display);
            font-size: 0.8rem;
            display: flex;
            align-items: center;
            justify-content: center;
            box-shadow: 0 2px 6px rgba(0,0,0,0.3);
            border: 2px solid #ffffff;
            transition: all 0.15s ease-out;
            position: relative;
            overflow: visible;
            cursor: pointer;
        }
        .rider-map-marker.leader {
            width: 38px;
            height: 38px;
            border: 3px solid #fbbf24;
            box-shadow: 0 0 14px rgba(251, 191, 36, 0.7), 0 3px 8px rgba(0,0,0,0.3);
            font-size: 0.85rem;
            z-index: 1000;
        }
        .rider-map-marker.leader::after {
            content: '👑';
            position: absolute;
            top: -16px;
            left: 50%;
            transform: translateX(-50%);
            font-size: 13px;
            filter: drop-shadow(0 1px 2px rgba(0,0,0,0.5));
            pointer-events: none;
        }

        /* Pestañas de Telemetría */
        .telemetry-tabs {
            display: flex;
            background: var(--bg-panel-solid);
            border-radius: 10px;
            padding: 4px;
            border: 1px solid var(--border-card);
            gap: 4px;
            flex-wrap: wrap;
        }

        .tab-btn {
            background: transparent;
            border: none;
            color: var(--text-muted);
            padding: 6px 12px;
            font-family: var(--font-display);
            font-size: 0.82rem;
            font-weight: 600;
            border-radius: 8px;
            cursor: pointer;
            transition: all 0.15s ease;
        }

        .tab-btn:hover {
            color: var(--text-main);
            background: rgba(124, 58, 237, 0.08);
        }

        .tab-btn.active {
            background: var(--bg-panel);
            color: var(--color-primary);
            border: 1px solid var(--border-card);
            box-shadow: 0 1px 4px rgba(0, 0, 0, 0.06);
            font-weight: 700;
        }

        /* Tabla Comparativa de Rendimiento */
        .summary-card {
            background: var(--bg-card);
            backdrop-filter: blur(16px);
            border: 1px solid var(--border-card);
            border-radius: 20px;
            padding: 24px;
            box-shadow: var(--card-shadow);
            margin-bottom: 20px;
            overflow-x: auto;
        }

        .styled-table {
            width: 100%;
            border-collapse: collapse;
            font-family: var(--font-body);
            text-align: left;
        }

        .styled-table th {
            background: var(--bg-table-th);
            color: var(--text-muted);
            font-size: 0.8rem;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            padding: 12px 16px;
            border-bottom: 2px solid var(--border-card);
        }

        .styled-table td {
            padding: 14px 16px;
            border-bottom: 1px solid var(--border-subtle);
            font-family: var(--font-mono);
            font-size: 0.9rem;
            color: var(--text-main);
        }

        .styled-table tr:hover td {
            background: rgba(124, 58, 237, 0.03);
        }

        .rider-tag {
            display: inline-flex;
            align-items: center;
            gap: 8px;
            font-family: var(--font-display);
            font-weight: 700;
            color: var(--text-main);
        }

        .rider-dot {
            width: 10px;
            height: 10px;
            border-radius: 50%;
            background: var(--dot-color);
            display: inline-block;
        }

        /* Insignias Térmicas de Tasa de Trabajo Energético (kJ/kg/h) */
        .rate-badge {
            display: inline-flex;
            align-items: center;
            gap: 4px;
            padding: 3px 8px;
            border-radius: 6px;
            font-size: 0.74rem;
            font-weight: 700;
            font-family: var(--font-mono);
            letter-spacing: 0.02em;
        }

        .rate-easy {
            background: rgba(16, 185, 129, 0.12);
            color: #059669;
            border: 1px solid rgba(16, 185, 129, 0.3);
        }

        .rate-moderate {
            background: rgba(14, 165, 233, 0.12);
            color: #0284c7;
            border: 1px solid rgba(14, 165, 233, 0.3);
        }

        .rate-high {
            background: rgba(245, 158, 11, 0.12);
            color: #d97706;
            border: 1px solid rgba(245, 158, 11, 0.3);
        }

        .rate-extreme {
            background: rgba(224, 53, 161, 0.14);
            color: #db2777;
            border: 1px solid rgba(224, 53, 161, 0.35);
        }

        /* Estilos de Sección de Demanda Metabólica y Gasto Energético (kJ/kg/h) */
        .metabolic-section {
            background: var(--bg-card);
            backdrop-filter: blur(16px);
            border: 1px solid var(--border-card);
            border-radius: 20px;
            padding: 24px;
            box-shadow: var(--card-shadow);
        }

        .metabolic-kpis-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
            gap: 14px;
            margin-bottom: 20px;
        }

        .metabolic-kpi-card {
            background: var(--bg-panel);
            border: 1px solid var(--border-card);
            border-radius: 14px;
            padding: 14px 16px;
            display: flex;
            align-items: center;
            gap: 14px;
            box-shadow: var(--card-shadow);
            transition: transform 0.2s ease, border-color 0.2s ease;
        }

        .metabolic-kpi-card:hover {
            transform: translateY(-2px);
            border-color: var(--border-glow);
        }

        .metabolic-kpi-icon {
            width: 42px;
            height: 42px;
            border-radius: 10px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 1.2rem;
            flex-shrink: 0;
        }

        .metabolic-kpi-info {
            display: flex;
            flex-direction: column;
            gap: 2px;
            min-width: 0;
        }

        .metabolic-kpi-val {
            font-family: var(--font-display);
            font-size: 1.25rem;
            font-weight: 800;
            line-height: 1.1;
            color: var(--text-main);
        }

        .metabolic-kpi-lbl {
            font-size: 0.75rem;
            font-weight: 600;
            color: var(--text-muted);
            text-transform: uppercase;
            letter-spacing: 0.03em;
        }

        .metabolic-kpi-sub {
            font-size: 0.7rem;
            color: var(--text-muted);
            opacity: 0.85;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }

        .metabolic-tabs {
            display: flex;
            gap: 6px;
            flex-wrap: wrap;
        }

        /* Header con Logo Corporativo */
        .header-brand {
            display: flex;
            align-items: center;
            gap: 18px;
            flex-wrap: wrap;
        }

        .logo-badge-header {
            background: #ffffff;
            padding: 6px 14px;
            border-radius: 12px;
            box-shadow: 0 2px 10px rgba(0, 0, 0, 0.08);
            display: inline-flex;
            align-items: center;
            justify-content: center;
            border: 1px solid var(--border-card);
            transition: transform 0.2s ease, box-shadow 0.2s ease;
            flex-shrink: 0;
        }

        .logo-badge-header:hover {
            transform: translateY(-1px);
            box-shadow: 0 4px 14px rgba(124, 58, 237, 0.15);
        }

        .logo-badge-header img, .logo-badge-header svg {
            height: 44px;
            max-height: 48px;
            width: auto;
            object-fit: contain;
            display: block;
        }

        /* Footer con Marca de Agua del Logo */
        .app-footer-watermark {
            margin-top: 30px;
            padding-top: 20px;
            border-top: 1px solid var(--border-card);
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 16px;
        }

        .watermark-content {
            display: flex;
            align-items: center;
            justify-content: space-between;
            width: 100%;
            flex-wrap: wrap;
            gap: 16px;
        }

        .watermark-left {
            display: flex;
            align-items: center;
            gap: 10px;
            font-size: 0.85rem;
            color: var(--text-muted);
        }

        .watermark-right {
            display: flex;
            align-items: center;
            gap: 16px;
        }

        .watermark-logo-badge {
            background: #ffffff;
            padding: 5px 12px;
            border-radius: 10px;
            box-shadow: 0 2px 8px rgba(0, 0, 0, 0.06);
            display: inline-flex;
            align-items: center;
            justify-content: center;
            border: 1px solid var(--border-card);
            width: fit-content;
            height: fit-content;
        }

        .watermark-img {
            max-height: 46px;
            width: auto;
            object-fit: contain;
            display: block;
        }

        .watermark-meta {
            display: flex;
            align-items: center;
            gap: 10px;
            font-family: var(--font-display);
            font-size: 0.85rem;
            font-weight: 700;
            color: var(--text-muted);
            text-transform: uppercase;
            letter-spacing: 0.05em;
        }

        .team-title { color: var(--text-main); }
        .app-title { color: var(--color-primary); }
        .meta-divider { color: var(--border-subtle); }

        /* =========================================================
           SECCIÓN DE SALUD, FISIOLOGÍA Y CARGA DE ENTRENAMIENTO
           ========================================================= */
        .health-load-section {
            margin-bottom: 24px;
            display: flex;
            flex-direction: column;
            gap: 16px;
        }

        .health-header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            flex-wrap: wrap;
            gap: 12px;
            padding: 4px 0;
        }

        .health-badge-status {
            display: inline-flex;
            align-items: center;
            gap: 8px;
            background: rgba(16, 185, 129, 0.12);
            border: 1px solid rgba(16, 185, 129, 0.3);
            color: #059669;
            font-size: 0.8rem;
            font-weight: 600;
            padding: 4px 12px;
            border-radius: 9999px;
            font-family: var(--font-display);
        }

        .pulse-dot {
            width: 8px;
            height: 8px;
            border-radius: 50%;
            background: #10b981;
            box-shadow: 0 0 8px #10b981;
            animation: pulse-green 2s infinite;
        }

        @keyframes pulse-green {
            0%, 100% { opacity: 1; transform: scale(1); }
            50% { opacity: 0.4; transform: scale(0.85); }
        }

        /* Grid de KPIs Globales del Equipo */
        .team-kpis-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
            gap: 12px;
        }

        .team-kpi-card {
            background: var(--bg-card);
            backdrop-filter: blur(12px);
            border: 1px solid var(--border-card);
            border-radius: 14px;
            padding: 14px 16px;
            display: flex;
            align-items: center;
            gap: 14px;
            box-shadow: var(--card-shadow);
            transition: transform 0.2s ease, border-color 0.2s ease;
        }

        .team-kpi-card:hover {
            transform: translateY(-2px);
            border-color: var(--border-glow);
        }

        .team-kpi-icon {
            width: 42px;
            height: 42px;
            border-radius: 10px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 1.2rem;
            flex-shrink: 0;
        }

        .team-kpi-info {
            display: flex;
            flex-direction: column;
            gap: 2px;
            min-width: 0;
        }

        .team-kpi-val {
            font-family: var(--font-display);
            font-size: 1.35rem;
            font-weight: 800;
            color: var(--text-main);
            line-height: 1.1;
        }

        .team-kpi-lbl {
            font-size: 0.75rem;
            color: var(--text-muted);
            text-transform: uppercase;
            letter-spacing: 0.04em;
            font-weight: 600;
        }

        .team-kpi-sub {
            font-size: 0.7rem;
            color: var(--text-muted);
            opacity: 0.85;
        }

        /* Tarjetas de Salud y Carga por Ciclista */
        .health-cards-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
            gap: 16px;
        }

        .health-card {
            background: var(--bg-card);
            backdrop-filter: blur(16px);
            border: 1px solid var(--border-card);
            border-radius: 16px;
            padding: 16px;
            display: flex;
            flex-direction: column;
            gap: 12px;
            position: relative;
            box-shadow: var(--card-shadow);
            transition: all 0.2s ease;
            border-left: 4px solid var(--rider-color, #7c3aed);
        }

        .health-card:hover {
            transform: translateY(-2px);
            box-shadow: var(--card-shadow-hover);
            border-color: var(--border-glow);
        }

        .health-card-header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 10px;
        }

        .health-rider-info {
            display: flex;
            align-items: center;
            gap: 10px;
            min-width: 0;
        }

        .health-avatar {
            width: 38px;
            height: 38px;
            border-radius: 10px;
            background: var(--rider-color, #7c3aed);
            color: #ffffff;
            font-weight: 800;
            font-family: var(--font-display);
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 0.9rem;
            flex-shrink: 0;
        }

        .health-rider-name {
            font-family: var(--font-display);
            font-size: 1rem;
            font-weight: 700;
            color: var(--text-main);
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }

        .health-rider-meta {
            font-size: 0.75rem;
            color: var(--text-muted);
        }

        /* Pill de Estado de Forma (TSB) */
        .health-form-pill {
            padding: 4px 10px;
            border-radius: 9999px;
            font-size: 0.75rem;
            font-weight: 700;
            font-family: var(--font-display);
            display: inline-flex;
            align-items: center;
            gap: 5px;
            flex-shrink: 0;
            border: 1px solid transparent;
        }

        .badge-emerald { background: rgba(16, 185, 129, 0.12); color: #059669; border-color: rgba(16, 185, 129, 0.3); }
        .badge-sky { background: rgba(14, 165, 233, 0.12); color: #0284c7; border-color: rgba(14, 165, 233, 0.3); }
        .badge-indigo { background: rgba(99, 102, 241, 0.12); color: #4f46e5; border-color: rgba(99, 102, 241, 0.3); }
        .badge-amber { background: rgba(245, 158, 11, 0.12); color: #d97706; border-color: rgba(245, 158, 11, 0.3); }
        .badge-red { background: rgba(239, 68, 68, 0.12); color: #dc2626; border-color: rgba(239, 68, 68, 0.3); }
        .badge-gray { background: rgba(100, 116, 139, 0.12); color: #475569; border-color: rgba(100, 116, 139, 0.3); }

        /* Grid interno de métricas de carga */
        .health-metrics-row {
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 8px;
            background: var(--bg-panel-solid);
            padding: 10px;
            border-radius: 12px;
            border: 1px solid var(--border-subtle);
        }

        .health-metric-box {
            display: flex;
            flex-direction: column;
            align-items: center;
            text-align: center;
            gap: 2px;
        }

        .health-box-val {
            font-family: var(--font-display);
            font-size: 1.05rem;
            font-weight: 700;
            color: var(--text-main);
            line-height: 1.1;
        }

        .health-box-lbl {
            font-size: 0.68rem;
            color: var(--text-muted);
            text-transform: uppercase;
            letter-spacing: 0.03em;
            font-weight: 600;
        }

        .health-box-sub {
            font-size: 0.65rem;
            color: var(--text-muted);
            opacity: 0.85;
        }

        /* Barra / Fila de Biometría (HRV, FC Reposo, Peso, Sueño) */
        .health-biometrics-row {
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 8px;
        }

        .health-bio-item {
            background: var(--bg-panel);
            border: 1px solid var(--border-subtle);
            border-radius: 10px;
            padding: 8px;
            display: flex;
            flex-direction: column;
            align-items: center;
            text-align: center;
            gap: 2px;
            box-shadow: 0 1px 3px rgba(0, 0, 0, 0.03);
        }

        .health-bio-val {
            font-family: var(--font-mono);
            font-size: 0.88rem;
            font-weight: 700;
            color: var(--text-main);
        }

        .health-bio-lbl {
            font-size: 0.65rem;
            color: var(--text-muted);
            text-transform: uppercase;
            font-weight: 600;
        }

        /* Controles y Selector de Gráficos de Salud */
        .health-chart-controls {
            display: flex;
            align-items: center;
            gap: 12px;
            flex-wrap: wrap;
        }

        .rider-selector-wrapper {
            display: flex;
            align-items: center;
            gap: 8px;
        }

        .custom-select {
            background: var(--bg-panel);
            color: var(--text-main);
            border: 1px solid var(--border-card);
            border-radius: 8px;
            padding: 6px 12px;
            font-family: var(--font-display);
            font-size: 0.82rem;
            font-weight: 600;
            outline: none;
            cursor: pointer;
            box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05);
            transition: border-color 0.2s ease;
        }

        .custom-select:hover, .custom-select:focus {
            border-color: var(--color-primary);
        }

        /* =========================================================
           SECCIÓN DE SELECCIÓN Y ANÁLISIS DE TRAMOS / SEGMENTOS
           ========================================================= */
        .segment-section {
            background: var(--bg-card);
            backdrop-filter: blur(16px);
            border: 1px solid var(--border-card);
            border-radius: 20px;
            padding: 24px;
            box-shadow: var(--card-shadow);
            margin-bottom: 24px;
            position: relative;
        }

        .segment-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 14px;
            margin-bottom: 18px;
        }

        .segment-title-group {
            display: flex;
            flex-direction: column;
            gap: 4px;
        }

        .segment-title {
            font-family: var(--font-display);
            font-size: 1.15rem;
            font-weight: 800;
            color: var(--text-main);
            display: flex;
            align-items: center;
            gap: 8px;
        }

        .segment-subtitle {
            font-size: 0.8rem;
            color: var(--text-muted);
        }

        .segment-actions {
            display: flex;
            align-items: center;
            gap: 8px;
            flex-wrap: wrap;
        }

        /* Presets Pills */
        .segment-presets-container {
            margin-bottom: 18px;
            padding: 12px 16px;
            background: var(--bg-panel-solid);
            border-radius: 14px;
            border: 1px solid var(--border-subtle);
        }

        .segment-presets-title {
            font-size: 0.75rem;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            color: var(--text-muted);
            margin-bottom: 10px;
            display: flex;
            align-items: center;
            gap: 6px;
        }

        .segment-presets-pills {
            display: flex;
            gap: 8px;
            overflow-x: auto;
            padding-bottom: 4px;
            scrollbar-width: thin;
        }

        .segment-preset-pill {
            background: var(--bg-panel);
            border: 1px solid var(--border-card);
            color: var(--text-main);
            padding: 7px 12px;
            border-radius: 10px;
            font-size: 0.8rem;
            font-weight: 600;
            cursor: pointer;
            white-space: nowrap;
            display: inline-flex;
            align-items: center;
            gap: 6px;
            transition: all 0.2s ease;
            box-shadow: 0 1px 3px rgba(0, 0, 0, 0.04);
        }

        .segment-preset-pill:hover {
            border-color: var(--color-primary);
            transform: translateY(-1px);
            background: var(--bg-btn-hover);
        }

        .segment-preset-pill.active {
            background: linear-gradient(135deg, var(--color-jersey-start), var(--color-accent)) !important;
            border-color: transparent !important;
            color: #ffffff !important;
            box-shadow: 0 4px 12px rgba(124, 58, 237, 0.35);
        }

        .segment-preset-pill.active * {
            color: #ffffff !important;
        }

        .preset-pill-badge {
            background: rgba(124, 58, 237, 0.12);
            color: var(--color-primary);
            font-size: 0.7rem;
            padding: 2px 6px;
            border-radius: 6px;
            font-family: var(--font-mono);
        }

        .segment-preset-pill.active .preset-pill-badge {
            background: rgba(255, 255, 255, 0.25);
            color: #ffffff;
        }

        /* Controles de Rango Doble (Sliders e Inputs Numéricos) */
        .segment-range-wrapper {
            background: var(--bg-panel);
            border: 1px solid var(--border-card);
            border-radius: 16px;
            padding: 16px 20px;
            margin-bottom: 20px;
            box-shadow: var(--card-shadow);
        }

        .segment-range-inputs {
            display: flex;
            align-items: center;
            justify-content: space-between;
            flex-wrap: wrap;
            gap: 16px;
            margin-bottom: 14px;
        }

        .segment-input-box {
            display: flex;
            align-items: center;
            gap: 8px;
        }

        .segment-input-label {
            font-size: 0.8rem;
            font-weight: 700;
            color: var(--text-muted);
            text-transform: uppercase;
        }

        .segment-num-input {
            width: 90px;
            padding: 6px 10px;
            border-radius: 8px;
            border: 1px solid var(--border-card);
            background: var(--bg-base);
            color: var(--text-main);
            font-family: var(--font-mono);
            font-size: 0.95rem;
            font-weight: 700;
            outline: none;
            text-align: center;
            transition: border-color 0.2s ease;
        }

        .segment-num-input:focus {
            border-color: var(--color-primary);
            box-shadow: 0 0 0 2px rgba(124, 58, 237, 0.2);
        }

        .segment-stats-pill {
            display: flex;
            align-items: center;
            gap: 12px;
            background: var(--bg-panel-solid);
            border: 1px solid var(--border-subtle);
            padding: 6px 14px;
            border-radius: 10px;
            font-family: var(--font-mono);
            font-size: 0.82rem;
            color: var(--text-main);
            flex-wrap: wrap;
        }

        .segment-slider-track-container {
            position: relative;
            height: 36px;
            display: flex;
            align-items: center;
        }

        .segment-slider-rail {
            position: absolute;
            width: 100%;
            height: 8px;
            background: #e2e8f0;
            border-radius: 4px;
            z-index: 1;
        }

        [data-theme="dark"] .segment-slider-rail {
            background: #2a1b47;
        }

        .segment-slider-highlight {
            position: absolute;
            height: 8px;
            background: linear-gradient(90deg, #7c3aed, #ec4899);
            border-radius: 4px;
            z-index: 2;
            transition: left 0.05s ease, width 0.05s ease;
            box-shadow: 0 0 10px rgba(236, 72, 153, 0.4);
        }

        .dual-range-input {
            position: absolute;
            width: 100%;
            pointer-events: none;
            -webkit-appearance: none;
            appearance: none;
            height: 8px;
            background: transparent;
            z-index: 3;
            outline: none;
            margin: 0;
        }

        .dual-range-input::-webkit-slider-thumb {
            pointer-events: all;
            -webkit-appearance: none;
            appearance: none;
            width: 22px;
            height: 22px;
            border-radius: 50%;
            background: #ffffff;
            border: 3px solid var(--color-primary);
            cursor: grab;
            box-shadow: 0 2px 8px rgba(0, 0, 0, 0.3);
            transition: transform 0.1s ease;
        }

        .dual-range-input::-webkit-slider-thumb:hover {
            transform: scale(1.2);
            border-color: var(--color-accent);
        }

        .dual-range-input::-webkit-slider-thumb:active {
            cursor: grabbing;
            transform: scale(1.25);
        }

        /* Banner Resumen del Tramo Seleccionado */
        .segment-banner {
            background: linear-gradient(135deg, rgba(124, 58, 237, 0.08) 0%, rgba(236, 72, 153, 0.06) 100%);
            border: 1px solid rgba(124, 58, 237, 0.2);
            border-radius: 14px;
            padding: 14px 18px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 14px;
            margin-bottom: 18px;
        }

        .segment-banner-info {
            display: flex;
            align-items: center;
            gap: 12px;
            flex-wrap: wrap;
        }

        .segment-banner-name {
            font-family: var(--font-display);
            font-size: 1.05rem;
            font-weight: 800;
            color: var(--text-main);
        }

        .segment-banner-metrics {
            display: flex;
            gap: 10px;
            flex-wrap: wrap;
        }

        .segment-banner-badge {
            background: var(--bg-panel);
            border: 1px solid var(--border-card);
            padding: 4px 10px;
            border-radius: 8px;
            font-family: var(--font-mono);
            font-size: 0.8rem;
            font-weight: 700;
            color: var(--text-main);
        }

        /* KPIs del Segmento */
        .segment-kpis-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 12px;
            margin-bottom: 20px;
        }

        .segment-kpi-card {
            background: var(--bg-panel);
            border: 1px solid var(--border-card);
            border-radius: 12px;
            padding: 12px 16px;
            display: flex;
            align-items: center;
            gap: 12px;
            box-shadow: var(--card-shadow);
            transition: transform 0.2s ease;
        }

        .segment-kpi-card:hover {
            transform: translateY(-2px);
            border-color: var(--border-glow);
        }

        .segment-kpi-icon {
            width: 38px;
            height: 38px;
            border-radius: 10px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 1.1rem;
            flex-shrink: 0;
        }

        .segment-kpi-val {
            font-family: var(--font-display);
            font-size: 1.15rem;
            font-weight: 800;
            color: var(--text-main);
            line-height: 1.1;
        }

        .segment-kpi-lbl {
            font-size: 0.7rem;
            font-weight: 600;
            color: var(--text-muted);
            text-transform: uppercase;
            letter-spacing: 0.03em;
        }

        .segment-kpi-sub {
            font-size: 0.7rem;
            color: var(--text-muted);
            font-weight: 600;
        }

        /* Mini Gráfico y Grid de Visualización de Segmento */
        .segment-chart-wrapper {
            background: var(--bg-panel);
            border: 1px solid var(--border-card);
            border-radius: 14px;
            padding: 16px;
            margin-bottom: 20px;
            box-shadow: var(--card-shadow);
        }

        .segment-chart-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 10px;
            margin-bottom: 12px;
        }
    </style>
</head>
<body>

    <!-- Header Principal -->
    <header class="header">
        <div class="header-brand" style="width: 100%; display: flex; justify-content: space-between;">
            <div style="display: flex; align-items: center; gap: 18px;">
                __HEADER_LOGO_HTML__
            </div>
            <button class="theme-toggle-btn" id="btnThemeToggle" title="Cambiar Tema Claro / Oscuro">
                <i data-lucide="moon" id="themeIcon"></i>
                <span id="themeText">Oscuro</span>
            </button>
        </div>
        <div class="header-title-group" style="width: 100%; margin-top: 10px;">
            <h1><i data-lucide="activity" style="color: #38bdf8;"></i> __TITULO_ETAPA__</h1>
            <p>__SUBTITULO_ETAPA__</p>
        </div>
        <div class="header-badges" style="width: 100%; margin-top: 8px;">
            <div class="badge highlight"><i data-lucide="map-pin"></i> __DISTANCIA_TOTAL_KM__ km</div>
            <div class="badge"><i data-lucide="trending-up"></i> +__DESNIVEL_POS_M__ m D+</div>
            <div class="badge"><i data-lucide="mountain"></i> Máx __ALTITUD_MAX__ m</div>
            <div class="badge"><i data-lucide="users"></i> __NUM_CICLISTAS__ Ciclistas</div>
        </div>
    </header>
      <!-- Tabla Resumen -->
    <section class="summary-card" style="margin-bottom: 24px;">
        <div class="viz-title" style="margin-bottom: 16px;"><i data-lucide="trophy" style="color: #ec4899;"></i> Resumen de Etapa</div>
        <table class="styled-table">
            <thead>
                <tr>
                    <th style="width: 45px; text-align: center;">Pos</th>
                    <th>Ciclista</th>
                    <th>Tiempo</th>
                    <th>Distancia</th>
                    <th>Desnivel +</th>
                    <th>Potencia Med.</th>
                    <th>W / kg</th>
                    <th>NP (IF)</th>
                    <th>TSS (TSS/h)</th>
                    <th>Trabajo</th>
                    <th>FC Media</th>
                    <th style="color: #38bdf8;">CTL (42d)</th>
                    <th style="color: #ec4899;">ATL (7d)</th>
                    <th style="color: #34d399;">TSB (Forma)</th>
                    <th style="color: #fbbf24;">FC Reposo</th>
                </tr>
            </thead>
            <tbody id="summaryTableBody">
            </tbody>
        </table>
    </section>
    <!-- Live HUD / Tarjetas de Ciclistas >
    <!--section class="riders-grid" id="ridersCardsContainer">
    </section-->

    <!-- Barra de Controles -->
    <!--section class="controls-bar">
        <div class="controls-top-row">
            <div class="playback-buttons">
                <button class="btn-ctrl primary" id="btnPlayPause">
                    <i data-lucide="play" id="iconPlay"></i>
                    <span id="txtPlay">Iniciar Simulación</span>
                </button>
                <button class="btn-ctrl" id="btnReset">
                    <i data-lucide="rotate-ccw"></i>
                    <span>Reiniciar</span>
                </button>
                <div class="mode-toggle-group">
                    <button class="mode-btn active" id="btnModeDist" data-mode="dist">Km</button>
                    <button class="mode-btn" id="btnModeTime" data-mode="time">Tiempo</button>
                </div>
                <div class="speed-selector">
                    <button class="speed-btn active" data-speed="1">1x</button>
                    <button class="speed-btn" data-speed="5">5x</button>
                    <button class="speed-btn" data-speed="15">15x</button>
                </div>
                <button class="btn-ctrl" id="btnToggleMapProfile">
                    <i data-lucide="eye" id="iconToggleMapProfile"></i>
                    <span id="txtToggleMapProfile">Mapa y Perfil</span>
                </button>
            </div>
            <div class="timeline-timer" id="lblTimer">0.0 km</div>
        </div>
        <div class="slider-container">
            <input type="range" class="custom-range" id="timelineSlider" min="0" max="999" value="0">
        </div>
    </section-->

    <!-- Visualización Mapa + Perfil -->
    <!--section class="viz-grid hidden" id="vizGridSection">
        <div class="viz-card">
            <div class="viz-header">
                <div class="viz-title"><i data-lucide="map" style="color: #38bdf8;"></i> Recorrido</div>
                <button class="btn-ctrl" id="btnRecenterMap" style="padding: 4px 10px; font-size: 0.8rem;"><i data-lucide="crosshair"></i> Recentrar</button>
            </div>
            <div id="map"></div>
        </div>
        <div class="viz-card">
            <div class="viz-header">
                <div class="viz-title"><i data-lucide="mountain-snow" style="color: #10b981;"></i> Perfil</div>
            </div>
            <div class="chart-wrapper">
                <canvas id="elevationChart"></canvas>
            </div>
        </div>
    </section-->

    <!-- Gráfico Telemetría y Comparativa -->
    <section class="viz-card" style="margin-bottom: 20px;">
        <div class="viz-header">
            <div class="viz-title"><i data-lucide="line-chart" style="color: #f59e0b;"></i> Comparativa de Telemetría</div>
            <div style="display: flex; gap: 8px; flex-wrap: wrap; align-items: center;">
                <div class="telemetry-tabs">
                    <button class="tab-btn active" data-metric="power">Potencia</button>
                    <button class="tab-btn" data-metric="wkg">W / kg</button>
                    <button class="tab-btn" data-metric="tss">TSS Acumulado</button>
                    <button class="tab-btn" data-metric="kj">Kilojulios</button>
                    <button class="tab-btn" data-metric="kjkg">kJ / kg</button>
                    <button class="tab-btn" data-metric="kjkg_h">kJ / kg / h</button>
                    <button class="tab-btn" data-metric="hr">Pulso</button>
                </div>
                <div style="display: flex; gap: 8px; flex-wrap: wrap; align-items: center;">
                    <div style="font-size: 0.78rem; color: var(--text-muted); background: var(--bg-panel-solid); padding: 5px 12px; border-radius: 8px; border: 1px solid var(--border-subtle); display: inline-flex; align-items: center; gap: 6px;">
                        <i data-lucide="mouse-pointer" style="width: 14px; height: 14px; color: #ec4899;"></i>
                        <span>Arrastra sobre el gráfico para seleccionar tramo</span>
                    </div>
                    <button class="btn-ctrl" id="btnChartZoomSeg" title="Zoom al Tramo Seleccionado" style="font-size: 0.8rem; padding: 6px 10px;">
                        <i data-lucide="zoom-in"></i> <span>Zoom Tramo</span>
                    </button>
                    <button class="btn-ctrl" id="btnChartResetZoom" title="Ver Toda la Etapa" style="font-size: 0.8rem; padding: 6px 10px;">
                        <i data-lucide="maximize-2"></i> <span>Ver Todo</span>
                    </button>
                </div>
            </div>
        </div>
        <div class="chart-wrapper" style="min-height: 380px;">
            <canvas id="telemetryChart"></canvas>
        </div>
    </section>

    <!-- SECCIÓN DE SELECCIÓN Y ANÁLISIS DE TRAMOS / SEGMENTOS -->
    <section class="summary-card segment-section" id="segmentAnalysisSection">
        <div class="segment-header">
            <div class="segment-title-group">
                <div class="segment-title">
                    <i data-lucide="split" style="color: #ec4899;"></i>
                    <span>Análisis de Tramos y Segmentos de la Etapa</span>
                </div>
                <div class="segment-subtitle">
                    Selecciona cualquier tramo
                </div>
            </div>
            <div class="segment-actions">
                <button class="btn-ctrl primary" id="btnSimulateSegment">
                    <i data-lucide="play-circle"></i>
                    <span>Simular este Tramo</span>
                </button>
                <button class="btn-ctrl" id="btnResetSegment">
                    <i data-lucide="rotate-ccw"></i>
                    <span>Etapa Completa</span>
                </button>
            </div>
        </div>

        <!-- 1. Presets Rápidos: Puertos Detectados y Secciones de Carrera -->
        <div class="segment-presets-container">
            <div class="segment-presets-title">
                <i data-lucide="bookmark" style="width: 14px; height: 14px; color: #ec4899;"></i>
                <span>Tramos Sugeridos y Puertos de Montaña</span>
            </div>
            <div class="segment-presets-pills" id="segmentPresetsContainer">
                <!-- Se llena dinámicamente con JS a partir de DATA.etapa.segmentos_sugeridos -->
            </div>
        </div>

        <!-- 2. Selector Libre de Rango por Km (Sliders e Inputs Numéricos) -->
        <div class="segment-range-wrapper">
            <div class="segment-range-inputs">
                <div style="display: flex; gap: 16px; align-items: center; flex-wrap: wrap;">
                    <div class="segment-input-box">
                        <span class="segment-input-label">Inicio (Km):</span>
                        <input type="number" id="inputSegStart" class="segment-num-input" min="0" step="0.1" value="0.0">
                    </div>
                    <div class="segment-input-box">
                        <span class="segment-input-label">Fin (Km):</span>
                        <input type="number" id="inputSegEnd" class="segment-num-input" min="0.1" step="0.1" value="0.0">
                    </div>
                </div>
                <div class="segment-stats-pill" id="segmentStatsSummary">
                    <span>📏 <strong id="lblSegDistance">0.0 km</strong></span>
                    <span>⛰️ <strong id="lblSegElevation">+0 m</strong></span>
                    <span>📈 <strong id="lblSegGradient">0.0%</strong></span>
                    <span>🏁 <strong id="lblSegFastestRider">--</strong> (<span id="lblSegFastestTime">--</span>)</span>
                </div>
            </div>

            <!-- Slider Doble de Rango -->
            <div class="segment-slider-track-container">
                <div class="segment-slider-rail"></div>
                <div class="segment-slider-highlight" id="segmentSliderHighlight" style="left: 0%; width: 100%;"></div>
                <input type="range" class="dual-range-input" id="sliderSegStart" min="0" max="1000" value="0" step="1">
                <input type="range" class="dual-range-input" id="sliderSegEnd" min="0" max="1000" value="1000" step="1">
            </div>
        </div>

        <!-- 3. Banner Informativo del Tramo Activo -->
        <div class="segment-banner" id="segmentActiveBanner">
            <div class="segment-banner-info">
                <span class="segment-banner-name" id="lblActiveSegmentName">📍 Etapa Completa (Km 0.0 → 0.0)</span>
                <div class="segment-banner-metrics">
                    <span class="segment-banner-badge" id="badgeSegKm">0.0 km</span>
                    <span class="segment-banner-badge" id="badgeSegElev" style="color: #10b981;">+0 m D+</span>
                    <span class="segment-banner-badge" id="badgeSegSlope" style="color: #f59e0b;">0.0% pend. med.</span>
                </div>
            </div>
            <div style="font-size: 0.8rem; color: var(--text-muted); font-weight: 600;" id="lblSegRidersCount">
                Analizando todos los ciclistas
            </div>
        </div>
        <!-- 4. Mini KPIs del Tramo -->
        <div class="segment-kpis-grid" id="segmentKpisGrid"></div>

        <!-- 5. Mini Gráfico Comparativo del Segmento -->
        <!--div class="segment-chart-wrapper">
            <div class="segment-chart-header">
                <div class="viz-title" style="font-size: 0.95rem;">
                    <i data-lucide="bar-chart-3" style="color: #38bdf8;"></i>
                    <span>Comparativa Visual en este Tramo</span>
                </div>
                <div class="telemetry-tabs" id="segmentChartTabs">
                    <button class="tab-btn active" data-seg-metric="wkg">W / kg</button>
                    <button class="tab-btn" data-seg-metric="power">Potencia (W)</button>
                    <button class="tab-btn" data-seg-metric="time">Tiempo (min)</button>
                    <button class="tab-btn" data-seg-metric="kjkg_h">kJ / kg / h</button>
                    <button class="tab-btn" data-seg-metric="speed">Velocidad (km/h)</button>
                </div>
            </div>
            <div class="chart-wrapper" style="min-height: 260px;">
                <canvas id="segmentBarChart"></canvas>
            </div>
        </div-->

        <!-- 6. Tabla Clasificación y Métricas del Segmento -->
        <div class="viz-title" style="font-size: 0.95rem; margin-bottom: 12px;">
            <i data-lucide="list-ordered" style="color: #ec4899;"></i>
            <span>Clasificación y Telemetría en el Tramo Seleccionado</span>
        </div>
        <div style="overflow-x: auto;">
            <table class="styled-table">
                <thead>
                    <tr>
                        <th style="width: 45px; text-align: center;">Pos</th>
                        <th>Ciclista</th>
                        <th>Tiempo Tramo</th>
                        <th>Gap Tramo</th>
                        <th>Vel. Media</th>
                        <th>Potencia Med.</th>
                        <th>W / kg</th>
                        <th>NP (IF)</th>
                        <th>TSS (TSS/h)</th>
                        <th>Trabajo Tramo</th>
                        <th>FC Media / Máx</th>
                        <th>Cadencia</th>
                    </tr>
                </thead>
                <tbody id="segmentTableBody">
                </tbody>
            </table>
        </div>
    </section>

   

    <!-- Sección de Demanda Metabólica y Gasto Energético (kJ / kg / h)-->
    <section class="summary-card metabolic-section" style="margin-bottom: 24px;" id="metabolicKjKgSection">
        <!--div class="viz-header" style="margin-bottom: 16px;">
            <div class="viz-title">
                <i data-lucide="flame" style="color: #f97316;"></i>
                Demanda Metabólica y Gasto Energético (kJ / kg / h)
            </div>
            <div style="font-size: 0.8rem; color: var(--text-muted); font-weight: 500;">
                Ritmo horario de combustión metabólica, fatiga energética relativa al peso y recomendaciones de nutrición
            </div>
        </div>-->

        <!-- Tarjetas Resumen KPIs Metabólicos del Equipo-->
        <!--div class="metabolic-kpis-grid" id="metabolicKpisContainer"></div-->

        <!-- Gráfico Interactivo de kJ / kg / h -->
        <!--div class="viz-card" style="margin-bottom: 20px; background: rgba(15, 23, 42, 0.65); border: 1px solid rgba(255, 255, 255, 0.06);">
            <div class="viz-header">
                <div class="viz-title" style="font-size: 0.95rem;">
                    <i data-lucide="bar-chart-3" style="color: #38bdf8;"></i>
                    Gráfico Comparativo de Demanda Horaria
                </div>
                <div class="health-chart-controls">
                    <div class="rider-selector-wrapper">
                        <label for="metabolicRiderSelect" style="font-size: 0.8rem; color: var(--text-muted); font-weight: 600;">Ciclista:</label>
                        <select id="metabolicRiderSelect" class="custom-select">
                            <option value="all">Todos los Ciclistas</option>
                        </select>
                    </div>
                    <div class="metabolic-tabs">
                        <button class="tab-btn active" data-metabolic-metric="kjkg_h">
                            <i data-lucide="zap" style="width: 14px; height: 14px; display: inline-block;"></i> kJ / kg / h
                        </button>
                        <button class="tab-btn" data-metabolic-metric="kj_total_h">
                            <i data-lucide="flame" style="width: 14px; height: 14px; display: inline-block;"></i> kJ / h (Absoluto)
                        </button>
                        <button class="tab-btn" data-metabolic-metric="kjkg_acum">
                            <i data-lucide="trending-up" style="width: 14px; height: 14px; display: inline-block;"></i> kJ / kg Acumulado
                        </button>
                        <button class="tab-btn" data-metabolic-metric="wkg_h">
                            <i data-lucide="gauge" style="width: 14px; height: 14px; display: inline-block;"></i> W / kg Horario
                        </button>
                    </div>
                </div>
            </div>
            <div class="chart-wrapper" style="min-height: 360px;">
                <canvas id="metabolicKjKgChart"></canvas>
            </div>
        </div-->

        <!-- Tabla de Datos Detallada de kJ / kg / h -->
        <div class="viz-title" style="font-size: 0.92rem; margin-bottom: 12px;">
            <i data-lucide="table-2" style="color: #38bdf8;"></i>
            Tabla de Desglose Horario y Pacing (kJ / kg / h)
        </div>
        <div id="hourlyBreakdownContainer"></div>
    </section>

    <!-- Sección de Salud, Fisiología y Carga de Entrenamiento -->
    <section class="health-load-section" id="healthLoadSection">
        <!--div class="health-header">
            <div class="viz-title">
                <i data-lucide="heart-pulse" style="color: #ec4899;"></i>
                Fisiología
            </div>
           
        </div-->

        <!-- KPIs Globales del Equipo -->
        <!--div class="team-kpis-grid" id="teamKpisContainer"></div-->

        <!-- Tarjetas de Salud y Carga de los Ciclistas -->
        <!--div class="health-cards-grid" id="healthCardsContainer"></div-->

        <!-- Gráfico Interactivo de Evolución de Carga y Biometría -->
        <div class="viz-card" style="margin-top: 6px;">
            <div class="viz-header">
                <div class="viz-title">
                    <i data-lucide="trending-up" style="color: #38bdf8;"></i>
                    Evolución Temporal de Carga y Biometría (30 Días)
                </div>
                <div class="health-chart-controls">
                    <div class="rider-selector-wrapper">
                        <label for="healthRiderSelect" style="font-size: 0.8rem; color: var(--text-muted); font-weight: 600;">Ciclista:</label>
                        <select id="healthRiderSelect" class="custom-select">
                            <option value="all">Todos</option>
                        </select>
                    </div>
                    <div class="health-tabs">
                        <button class="tab-btn active" data-health-metric="fitness_freshness">
                            <i data-lucide="activity" style="width: 14px; height: 14px; display: inline-block;"></i> Carga (CTL/ATL)
                        </button>
                        <button class="tab-btn" data-health-metric="atl">
                            <i data-lucide="flame" style="width: 14px; height: 14px; display: inline-block;"></i> ATL (Fatiga)
                        </button>
                        <button class="tab-btn" data-health-metric="ctl">
                            <i data-lucide="shield" style="width: 14px; height: 14px; display: inline-block;"></i> CTL (Fitness)
                        </button>
                        <button class="tab-btn" data-health-metric="tsb">
                            <i data-lucide="scale" style="width: 14px; height: 14px; display: inline-block;"></i> TSB (Forma)
                        </button>
                        <button class="tab-btn" data-health-metric="hrv_rhr">
                            <i data-lucide="heart" style="width: 14px; height: 14px; display: inline-block;"></i> RMSSD & FC Reposo
                        </button>
                        <button class="tab-btn" data-health-metric="rhr">
                            <i data-lucide="heart-pulse" style="width: 14px; height: 14px; display: inline-block;"></i> FC Reposo
                        </button>
                        <button class="tab-btn" data-health-metric="weight_sleep">
                            <i data-lucide="moon" style="width: 14px; height: 14px; display: inline-block;"></i> Peso & Sueño
                        </button>
                    </div>
                </div>
            </div>
            <div class="chart-wrapper" style="min-height: 380px;">
                <canvas id="healthLoadChart"></canvas>
            </div>
        </div>
    </section>

    <footer class="app-footer-watermark">
        <div class="watermark-content">
            <div class="watermark-left">
                <i data-lucide="shield-check" style="color: #10b981;"></i>
                <span>Telemetría  procesada vía FIT + Intervals.icu API</span>
            </div>
            <div class="watermark-right">
                <div class="watermark-meta">
                    <span class="team-title">Burgos Burpellet BH Pro Team</span>
                    <span class="meta-divider">•</span>
                    <span class="app-title">Intervals Fit Analytics</span>
                </div>
                __LOGO_WATERMARK_HTML__
            </div>
        </div>
    </footer>

    <script>
        const DATA = __PAYLOAD_JSON__;
        
        let map = null;
        let trackLayer = null;
        let riderMarkers = {};
        let elevationChart = null;
        let telemetryChart = null;
        
        let isPlaying = false;
        let playInterval = null;
        let currentStep = 0;
        let playSpeed = 1;
        let syncMode = 'dist';
        let activeMetric = 'power';
        let currentLeaderX = 0;
        let currentLeaderName = '--';
        let currentLeaderXLabel = '0.0 km';

        if (typeof lucide !== 'undefined' && lucide.createIcons) {
            lucide.createIcons();
        }

        
        // =========================================================
        // Gestión de Tema Claro / Oscuro
        // =========================================================
        function initThemeToggle() {
            const btn = document.getElementById('btnThemeToggle');
            const icon = document.getElementById('themeIcon');
            const txt = document.getElementById('themeText');
            if (!btn) return;

            const savedTheme = localStorage.getItem('profile_theme') || 'light';
            if (savedTheme === 'dark') {
                document.documentElement.setAttribute('data-theme', 'dark');
                if (icon) icon.setAttribute('data-lucide', 'sun');
                if (txt) txt.innerText = 'Claro';
            } else {
                document.documentElement.removeAttribute('data-theme');
                if (icon) icon.setAttribute('data-lucide', 'moon');
                if (txt) txt.innerText = 'Oscuro';
            }

            btn.addEventListener('click', () => {
                const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
                if (isDark) {
                    document.documentElement.removeAttribute('data-theme');
                    localStorage.setItem('profile_theme', 'light');
                    if (icon) icon.setAttribute('data-lucide', 'moon');
                    if (txt) txt.innerText = 'Oscuro';
                } else {
                    document.documentElement.setAttribute('data-theme', 'dark');
                    localStorage.setItem('profile_theme', 'dark');
                    if (icon) icon.setAttribute('data-lucide', 'sun');
                    if (txt) txt.innerText = 'Claro';
                }
                if (typeof lucide !== 'undefined' && lucide.createIcons) lucide.createIcons();
            });
        }

        function initRiderCards() {
            const container = document.getElementById('ridersCardsContainer');
            if (!container) return;
            container.innerHTML = '';
            DATA.ciclistas.forEach((c, idx) => {
                const s = c.stats;
                const initials = s.nombre.split(' ').map(n => n[0]).join('').substring(0, 2);
                const kjKg = (s.kj_kg !== undefined && s.kj_kg !== null) ? s.kj_kg : (s.kilojulios_total / Math.max(30, s.peso_kg)).toFixed(1);
                const kjKgH = (s.kj_kg_hora !== undefined && s.kj_kg_hora !== null) ? s.kj_kg_hora : (s.w_kg_media * 3.6).toFixed(1);
                
                const card = document.createElement('div');
                card.className = 'rider-card';
                card.id = `rider-card-${idx}`;
                card.style.setProperty('--rider-color', s.color);
                card.style.setProperty('--rider-glow', s.glow);
                card.innerHTML = `
                    <div class="rider-header">
                        <div class="rider-avatar-name">
                            <div class="rider-avatar">${initials}</div>
                            <div>
                                <div class="rider-name">${s.nombre}</div>
                                <div style="font-size: 0.75rem; color: var(--text-muted); margin-top: 2px;">
                                    ${s.peso_kg} kg • FTP ${s.ftp_w} W • <span style="color: #ec4899; font-weight: 600;">NP ${s.np_w} W</span> (IF ${s.if_val}) • <span style="color: #a855f7; font-weight: 600;">${s.tss_total} TSS</span> (${s.tss_hora}/h) • <span style="color: #06b6d4; font-weight: 600;">${kjKgH} kJ/kg/h</span>
                                </div>
                            </div>
                        </div>
                        <div class="rider-rank-badge" id="hud-gap-${idx}">+0:00</div>
                    </div>
                    <div class="rider-metrics-grid">
                        <div class="metric-mini-box">
                            <div class="metric-mini-val" id="hud-pwr-${idx}">${s.pot_media_w} W</div>
                            <div class="metric-mini-lbl">Potencia</div>
                        </div>
                        <div class="metric-mini-box">
                            <div class="metric-mini-val" id="hud-wkg-${idx}">${s.w_kg_media}</div>
                            <div class="metric-mini-lbl">W / kg</div>
                        </div>
                        <div class="metric-mini-box">
                            <div class="metric-mini-val" id="hud-tss-${idx}" style="color: #a855f7;">${s.tss_total} TSS</div>
                            <div class="metric-mini-lbl" id="hud-tssh-lbl-${idx}">Carga <span style="color: #c084fc; font-weight: 600;">(${s.tss_hora}/h)</span></div>
                        </div>
                        <div class="metric-mini-box">
                            <div class="metric-mini-val" id="hud-kj-${idx}">${s.kilojulios_total ? s.kilojulios_total.toLocaleString() : 0} kJ</div>
                            <div class="metric-mini-lbl" id="hud-kjkg-lbl-${idx}">Trabajo <span style="color: #38bdf8; font-weight: 600;">(${kjKg} kJ/kg • ${kjKgH}/h)</span></div>
                        </div>
                        <div class="metric-mini-box">
                            <div class="metric-mini-val" id="hud-hr-${idx}">${s.fc_media_bpm > 0 ? s.fc_media_bpm : '--'}</div>
                            <div class="metric-mini-lbl">Pulso</div>
                        </div>
                        <div class="metric-mini-box">
                            <div class="metric-mini-val" id="hud-alt-${idx}">${s.altitud_min} m</div>
                            <div class="metric-mini-lbl">Altitud</div>
                        </div>
                        <div class="metric-mini-box">
                            <div class="metric-mini-val" id="hud-dist-${idx}">0.0 km</div>
                            <div class="metric-mini-lbl">Distancia</div>
                        </div>
                    </div>
                `;
                container.appendChild(card);
            });
        }

        function initSummaryTable() {
            const tbody = document.getElementById('summaryTableBody');
            if (!tbody) return;
            tbody.innerHTML = '';
            DATA.ciclistas.forEach((c, idx) => {
                const s = c.stats;
                const w = c.wellness_load || {};
                const st = w.status || { label: 'Sin datos', tag: 'badge-gray', color: '#94a3b8' };
                const isLeader = (s.gap_lider_seg === 0);
                const kjKg = (s.kj_kg !== undefined && s.kj_kg !== null) ? s.kj_kg : (s.kilojulios_total / Math.max(30, s.peso_kg)).toFixed(1);
                const kjKgH = (s.kj_kg_hora !== undefined && s.kj_kg_hora !== null) ? s.kj_kg_hora : (s.w_kg_media * 3.6).toFixed(1);
                const npKjKgH = (s.np_kj_kg_hora !== undefined && s.np_kj_kg_hora !== null) ? s.np_kj_kg_hora : ((s.np_w / Math.max(30, s.peso_kg)) * 3.6).toFixed(1);

                const ctlTbl = w.ctl !== null && w.ctl !== undefined ? `${w.ctl}` : '-';
                const atlTbl = w.atl !== null && w.atl !== undefined ? `${w.atl}` : '-';
                const tsbTbl = w.tsb !== null && w.tsb !== undefined ? (w.tsb > 0 ? `+${w.tsb}` : `${w.tsb}`) : '-';
                const rmssdTbl = (w.hrv_rmssd !== null && w.hrv_rmssd !== undefined) ? `${w.hrv_rmssd} ms` : '-';
                const rhrTbl = (w.resting_hr !== null && w.resting_hr !== undefined) ? `${w.resting_hr} bpm` : '-';

                const tr = document.createElement('tr');
                tr.innerHTML = `
                    <td style="text-align: center; font-weight: bold; color: ${isLeader ? '#fbbf24' : 'var(--text-muted)'};">${s.posicion_str || (idx + 1) + 'º'}</td>
                    <td><div class="rider-tag"><span class="rider-dot" style="--dot-color: ${s.color};"></span> ${s.nombre}</div></td>
                    <td><strong style="color: var(--text-main);">${s.tiempo_total_str}</strong></td>
                    <td>${s.distancia_km} km</td>
                    <td>+${s.desnivel_pos_m} m</td>
                    <td><strong style="color: #38bdf8;">${s.pot_media_w} W</strong></td>
                    <td>${s.w_kg_media} W/kg</td>
                    <td><strong style="color: #ec4899;">${s.np_w} W</strong> <span style="font-size: 0.75rem; color: var(--text-muted);">(IF ${s.if_val})</span></td>
                    <td><strong style="color: #a855f7;">${s.tss_total} TSS</strong> <span style="font-size: 0.75rem; color: var(--text-muted);">(${s.tss_hora}/h)</span></td>
                    <td>
                        <strong style="color: #f59e0b;">${s.kilojulios_total ? s.kilojulios_total.toLocaleString() : 0} kJ</strong>
                        <div style="font-size: 0.72rem; color: var(--text-muted); margin-top: 2px;">
                            <span style="color: #6e6781;">${kjKg} kJ/kg</span> • <span style="color: #38bdf8; font-weight: 600;">${kjKgH} kJ/kg/h</span> <span style="color: #64748b; font-size: 0.68rem;">(NP: ${npKjKgH})</span>
                        </div>
                    </td>
                    <td>${s.fc_media_bpm > 0 ? s.fc_media_bpm + ' bpm' : '-'}</td>
                    <td><strong style="color: #38bdf8;">${ctlTbl}</strong></td>
                    <td><strong style="color: #ec4899;">${atlTbl}</strong></td>
                    <td><span class="health-form-pill ${st.tag}" style="padding: 2px 8px; font-size: 0.72rem;">${tsbTbl}</span></td>
                    <td><strong style="color: #fbbf24;">${rhrTbl}</strong></td>
                `;
                tbody.appendChild(tr);
            });
        }

        // =========================================================
        // Módulo de Demanda Metabólica y Gasto Energético (kJ/kg/h)
        // =========================================================
        let metabolicChart = null;
        let activeMetabolicMetric = 'kjkg_h';
        let selectedMetabolicRiderId = 'all';

        function initMetabolicSection() {
            renderMetabolicKPIs();
            populateMetabolicRiderSelect();
            initMetabolicChart();
            renderHourlyBreakdown();
            setupMetabolicEventListeners();
        }

        function renderMetabolicKPIs() {
            const container = document.getElementById('metabolicKpisContainer');
            if (!container) return;

            let peakKjKgH = 0;
            let peakRiderName = '--';
            let peakHour = 1;
            let sumKjKgH = 0;
            let countKjKgH = 0;
            let sumTotalKjKg = 0;
            let countRiders = 0;
            let sumTotalKj = 0;

            DATA.ciclistas.forEach(c => {
                const s = c.stats;
                const horas = c.desglose_horas || [];
                countRiders++;
                if (s.kj_kg) sumTotalKjKg += s.kj_kg;
                if (s.kilojulios) sumTotalKj += s.kilojulios;
                if (s.kj_kg_hora) {
                    sumKjKgH += parseFloat(s.kj_kg_hora);
                    countKjKgH++;
                }

                horas.forEach(h => {
                    if (h.kj_kg_h > peakKjKgH) {
                        peakKjKgH = h.kj_kg_h;
                        peakRiderName = s.nombre;
                        peakHour = h.hora_num;
                    }
                });
            });

            const avgKjKgH = countKjKgH > 0 ? (sumKjKgH / countKjKgH).toFixed(1) : '--';
            const avgTotalKjKg = countRiders > 0 ? (sumTotalKjKg / countRiders).toFixed(1) : '--';
            const avgTotalKj = countRiders > 0 ? Math.round(sumTotalKj / countRiders) : '--';

            container.innerHTML = `
                <div class="metabolic-kpi-card">
                    <div class="metabolic-kpi-icon" style="background: rgba(236, 72, 153, 0.15); color: #ec4899;">
                        <i data-lucide="zap"></i>
                    </div>
                    <div class="metabolic-kpi-info">
                        <div class="metabolic-kpi-val" style="color: #f472b6;">${peakKjKgH > 0 ? peakKjKgH + ' <span style="font-size: 0.8rem; font-weight: normal;">kJ/kg/h</span>' : '--'}</div>
                        <div class="metabolic-kpi-lbl">Pico Máximo de Equipo</div>
                        <div class="metabolic-kpi-sub">${peakKjKgH > 0 ? `${peakRiderName} (Hora ${peakHour})` : 'Sin datos'}</div>
                    </div>
                </div>
                <div class="metabolic-kpi-card">
                    <div class="metabolic-kpi-icon" style="background: rgba(56, 189, 248, 0.15); color: #38bdf8;">
                        <i data-lucide="activity"></i>
                    </div>
                    <div class="metabolic-kpi-info">
                        <div class="metabolic-kpi-val" style="color: #38bdf8;">${avgKjKgH} <span style="font-size: 0.8rem; font-weight: normal;">kJ/kg/h</span></div>
                        <div class="metabolic-kpi-lbl">Media del Equipo</div>
                        <div class="metabolic-kpi-sub">Ritmo de combustión horario</div>
                    </div>
                </div>
                <div class="metabolic-kpi-card">
                    <div class="metabolic-kpi-icon" style="background: rgba(245, 158, 11, 0.15); color: #fbbf24;">
                        <i data-lucide="flame"></i>
                    </div>
                    <div class="metabolic-kpi-info">
                        <div class="metabolic-kpi-val" style="color: #fbbf24;">${avgTotalKjKg} <span style="font-size: 0.8rem; font-weight: normal;">kJ/kg</span></div>
                        <div class="metabolic-kpi-lbl">Gasto Relativo Total</div>
                        <div class="metabolic-kpi-sub">Trabajo acumulado medio</div>
                    </div>
                </div>
                <div class="metabolic-kpi-card">
                    <div class="metabolic-kpi-icon" style="background: rgba(168, 85, 247, 0.15); color: #c084fc;">
                        <i data-lucide="gauge"></i>
                    </div>
                    <div class="metabolic-kpi-info">
                        <div class="metabolic-kpi-val" style="color: #c084fc;">${avgTotalKj} <span style="font-size: 0.8rem; font-weight: normal;">kJ</span></div>
                        <div class="metabolic-kpi-lbl">Trabajo Medio Etapa</div>
                        <div class="metabolic-kpi-sub">Energía mecánica total</div>
                    </div>
                </div>
            `;
            if (typeof lucide !== 'undefined' && lucide.createIcons) lucide.createIcons();
        }

        function populateMetabolicRiderSelect() {
            const select = document.getElementById('metabolicRiderSelect');
            if (!select) return;
            select.innerHTML = '<option value="all">Todos los Ciclistas</option>';
            DATA.ciclistas.forEach((c, idx) => {
                const opt = document.createElement('option');
                opt.value = idx;
                opt.textContent = `${c.stats.nombre} (${c.stats.peso_kg} kg)`;
                select.appendChild(opt);
            });
        }

        function getStageMaxHours() {
            let maxH = 0;
            DATA.ciclistas.forEach(c => {
                const arr = c.desglose_horas || [];
                if (arr.length > maxH) maxH = arr.length;
            });
            return maxH || 1;
        }

        function initMetabolicChart() {
            const canvasEl = document.getElementById('metabolicKjKgChart');
            if (!canvasEl) return;
            updateMetabolicChart('kjkg_h', 'all');
        }

        function updateMetabolicChart(metric, riderFilter) {
            const canvasEl = document.getElementById('metabolicKjKgChart');
            if (!canvasEl) return;
            const ctx = canvasEl.getContext('2d');

            if (metabolicChart) {
                metabolicChart.destroy();
                metabolicChart = null;
            }

            const maxHoras = getStageMaxHours();
            const labels = [];
            for (let h = 1; h <= maxHoras; h++) {
                labels.push(`Hora ${h}`);
            }

            let datasets = [];
            let chartType = 'bar';
            let yUnit = ' kJ/kg/h';
            let yTitle = 'kJ / kg / h';

            const ridersToRender = (riderFilter === 'all')
                ? DATA.ciclistas
                : [DATA.ciclistas[parseInt(riderFilter)]].filter(Boolean);

            if (metric === 'kjkg_h') {
                yUnit = ' kJ/kg/h';
                yTitle = 'Demanda Metabólica (kJ/kg/h)';
                chartType = 'bar';

                ridersToRender.forEach(c => {
                    const horas = c.desglose_horas || [];
                    const dataVals = [];
                    for (let h = 1; h <= maxHoras; h++) {
                        const hData = horas.find(item => item.hora_num === h);
                        dataVals.push(hData ? hData.kj_kg_h : 0);
                    }
                    datasets.push({
                        label: c.stats.nombre,
                        data: dataVals,
                        backgroundColor: c.stats.color + 'bb',
                        borderColor: c.stats.color,
                        borderWidth: 1.5,
                        borderRadius: 6,
                        metaData: c.desglose_horas || []
                    });
                });
            } else if (metric === 'kj_total_h') {
                yUnit = ' kJ';
                yTitle = 'Gasto Absoluto por Hora (kJ)';
                chartType = 'bar';

                ridersToRender.forEach(c => {
                    const horas = c.desglose_horas || [];
                    const dataVals = [];
                    for (let h = 1; h <= maxHoras; h++) {
                        const hData = horas.find(item => item.hora_num === h);
                        dataVals.push(hData ? hData.kj_total : 0);
                    }
                    datasets.push({
                        label: c.stats.nombre,
                        data: dataVals,
                        backgroundColor: c.stats.color + 'bb',
                        borderColor: c.stats.color,
                        borderWidth: 1.5,
                        borderRadius: 6,
                        metaData: c.desglose_horas || []
                    });
                });
            } else if (metric === 'kjkg_acum') {
                yUnit = ' kJ/kg';
                yTitle = 'Fatiga Metabólica Acumulada (kJ/kg)';
                chartType = 'line';

                ridersToRender.forEach(c => {
                    const horas = c.desglose_horas || [];
                    let acum = 0;
                    const dataVals = [];
                    for (let h = 1; h <= maxHoras; h++) {
                        const hData = horas.find(item => item.hora_num === h);
                        if (hData) {
                            acum += hData.kj_kg;
                            dataVals.push(parseFloat(acum.toFixed(1)));
                        } else {
                            dataVals.push(acum > 0 ? parseFloat(acum.toFixed(1)) : null);
                        }
                    }
                    datasets.push({
                        label: c.stats.nombre,
                        data: dataVals,
                        borderColor: c.stats.color,
                        backgroundColor: c.stats.color + '22',
                        fill: (ridersToRender.length === 1),
                        borderWidth: 2.5,
                        pointRadius: 5,
                        pointHoverRadius: 7,
                        tension: 0.25,
                        metaData: c.desglose_horas || []
                    });
                });
            } else if (metric === 'wkg_h') {
                yUnit = ' W/kg';
                yTitle = 'Potencia Media por Hora (W/kg)';
                chartType = 'bar';

                ridersToRender.forEach(c => {
                    const horas = c.desglose_horas || [];
                    const dataVals = [];
                    for (let h = 1; h <= maxHoras; h++) {
                        const hData = horas.find(item => item.hora_num === h);
                        dataVals.push(hData ? hData.w_kg : 0);
                    }
                    datasets.push({
                        label: c.stats.nombre,
                        data: dataVals,
                        backgroundColor: c.stats.color + 'bb',
                        borderColor: c.stats.color,
                        borderWidth: 1.5,
                        borderRadius: 6,
                        metaData: c.desglose_horas || []
                    });
                });
            }

            metabolicChart = new Chart(ctx, {
                type: chartType,
                data: {
                    labels: labels,
                    datasets: datasets
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    animation: { duration: 400 },
                    interaction: { mode: 'index', intersect: false },
                    scales: {
                        x: {
                            grid: { color: 'rgba(124, 58, 237, 0.07)' },
                            ticks: { color: '#645a78',
                                font: { family: 'Outfit', size: 12, weight: '600' }
                            }
                        },
                        y: {
                            beginAtZero: true,
                            grid: { color: 'rgba(124, 58, 237, 0.07)' },
                            title: { display: true, text: yTitle, color: '#645a78',
                                font: { family: 'Outfit', size: 11, weight: '600' }
                            },
                            ticks: {
                                color: '#38bdf8',
                                font: { family: 'JetBrains Mono', size: 11 },
                                callback: (v) => `${v}${yUnit}`
                            }
                        }
                    },
                    plugins: {
                        legend: {
                            position: 'top',
                            labels: { color: '#645a78',
                                font: { family: 'Outfit', size: 12 },
                                usePointStyle: true,
                                boxWidth: 8
                            }
                        },
                        tooltip: {
                            backgroundColor: 'rgba(15, 23, 42, 0.95)',
                            titleFont: { family: 'Outfit', size: 13, weight: 'bold' },
                            bodyFont: { family: 'JetBrains Mono', size: 12 },
                            borderColor: 'rgba(255,255,255,0.12)',
                            borderWidth: 1,
                            padding: 10,
                            callbacks: {
                                title: (items) => `${items[0].label}`,
                                label: (item) => {
                                    const ds = item.dataset;
                                    const val = item.raw;
                                    const hIdx = item.dataIndex;
                                    const hData = (ds.metaData || []).find(h => h.hora_num === (hIdx + 1));
                                    let line = `${ds.label}: ${val}${yUnit}`;
                                    if (hData && activeMetabolicMetric === 'kjkg_h') {
                                        return [
                                            line,
                                            `  ⚡ Potencia: ${hData.pot_media_w}W (${hData.w_kg} W/kg)`,
                                            `  🔋 Trabajo: ${hData.kj_total} kJ`,
                                            `  📈 NP: ${hData.np_w}W | ${hData.fc_media ? hData.fc_media + ' bpm' : '-'}`
                                        ];
                                    }
                                    return line;
                                }
                            }
                        }
                    }
                }
            });
        }

        function setupMetabolicEventListeners() {
            const select = document.getElementById('metabolicRiderSelect');
            if (select) {
                select.addEventListener('change', (e) => {
                    selectedMetabolicRiderId = e.target.value;
                    updateMetabolicChart(activeMetabolicMetric, selectedMetabolicRiderId);
                });
            }

            document.querySelectorAll('.metabolic-tabs .tab-btn').forEach(btn => {
                btn.addEventListener('click', (e) => {
                    document.querySelectorAll('.metabolic-tabs .tab-btn').forEach(b => b.classList.remove('active'));
                    e.currentTarget.classList.add('active');
                    activeMetabolicMetric = e.currentTarget.dataset.metabolicMetric;
                    updateMetabolicChart(activeMetabolicMetric, selectedMetabolicRiderId);
                });
            });
        }

        function renderHourlyBreakdown() {
            const container = document.getElementById('hourlyBreakdownContainer');
            if (!container) return;

            let maxHoras = getStageMaxHours();

            if (maxHoras === 0) {
                container.innerHTML = '<div style="color: var(--text-muted); font-size: 0.85rem; padding: 10px;">No hay desglose horario disponible para esta actividad.</div>';
                return;
            }

            let html = `
                <div style="overflow-x: auto;">
                    <table class="styled-table" style="font-size: 0.82rem;">
                        <thead>
                            <tr>
                                <th style="min-width: 150px;">Ciclista</th>
            `;

            for (let h = 1; h <= maxHoras; h++) {
                html += `<th style="text-align: center; min-width: 135px;"><span style="color: #38bdf8;">Hora ${h}</span></th>`;
            }

            html += `
                                <th style="text-align: center; min-width: 130px; color: #f472b6;">Pico Horario</th>
                                <th style="text-align: center; min-width: 145px; color: #fbbf24;">Media Etapa</th>
                                <th style="text-align: center; min-width: 140px; color: #34d399;">Total Etapa</th>
                            </tr>
                        </thead>
                        <tbody>
            `;

            DATA.ciclistas.forEach((c, idx) => {
                const s = c.stats;
                const horas = c.desglose_horas || [];
                const kjKgH = (s.kj_kg_hora !== undefined && s.kj_kg_hora !== null) ? s.kj_kg_hora : (s.w_kg_media * 3.6).toFixed(1);
                const npKjKgH = (s.np_kj_kg_hora !== undefined && s.np_kj_kg_hora !== null) ? s.np_kj_kg_hora : ((s.np_w / Math.max(30, s.peso_kg)) * 3.6).toFixed(1);

                let peakRate = 0;
                let peakHourNum = 1;
                horas.forEach(h => {
                    if (h.kj_kg_h > peakRate) {
                        peakRate = h.kj_kg_h;
                        peakHourNum = h.hora_num;
                    }
                });

                let peakBadgeClass = 'rate-easy';
                if (peakRate >= 34.0) peakBadgeClass = 'rate-extreme';
                else if (peakRate >= 28.0) peakBadgeClass = 'rate-high';
                else if (peakRate >= 22.0) peakBadgeClass = 'rate-moderate';

                html += `
                    <tr>
                        <td>
                            <div class="rider-tag"><span class="rider-dot" style="--dot-color: ${s.color};"></span> ${s.nombre}</div>
                            <div style="font-size: 0.72rem; color: var(--text-muted); margin-top: 2px;">${s.peso_kg} kg • FTP ${s.ftp_w}W</div>
                        </td>
                `;

                for (let h = 1; h <= maxHoras; h++) {
                    const hData = horas.find(item => item.hora_num === h);
                    if (hData) {
                        const tasa = hData.kj_kg_h;
                        let badgeClass = 'rate-easy';
                        if (tasa >= 34.0) badgeClass = 'rate-extreme';
                        else if (tasa >= 28.0) badgeClass = 'rate-high';
                        else if (tasa >= 22.0) badgeClass = 'rate-moderate';

                        html += `
                            <td style="text-align: center; vertical-align: middle;">
                                <div class="rate-badge ${badgeClass}" style="margin: 0 auto 4px auto; display: inline-flex;">
                                    ${tasa} kJ/kg/h
                                </div>
                                <div style="font-size: 0.75rem; color: var(--text-main); font-weight: 600;">
                                    ${hData.pot_media_w} W <span style="color: var(--text-muted); font-weight: normal;">(${hData.w_kg} W/kg)</span>
                                </div>
                                <div style="font-size: 0.7rem; color: var(--text-muted); margin-top: 2px;">
                                    ${hData.kj_total} kJ • <span style="color: #38bdf8;">NP ${hData.np_w} W</span>
                                </div>
                            </td>
                        `;
                    } else {
                        html += `<td style="text-align: center; color: var(--text-muted);">-</td>`;
                    }
                }

                let globalBadgeClass = 'rate-easy';
                const tasaGlobal = parseFloat(kjKgH);
                if (tasaGlobal >= 34.0) globalBadgeClass = 'rate-extreme';
                else if (tasaGlobal >= 28.0) globalBadgeClass = 'rate-high';
                else if (tasaGlobal >= 22.0) globalBadgeClass = 'rate-moderate';

                html += `
                        <td style="text-align: center; vertical-align: middle; background: rgba(236, 72, 153, 0.03);">
                            <div class="rate-badge ${peakBadgeClass}" style="margin: 0 auto 4px auto; display: inline-flex;">
                                ${peakRate} kJ/kg/h
                            </div>
                            <div style="font-size: 0.72rem; color: var(--text-muted); font-weight: 600;">
                                Hora ${peakHourNum}
                            </div>
                        </td>
                        <td style="text-align: center; vertical-align: middle; background: rgba(124, 58, 237, 0.05);">
                            <div class="rate-badge ${globalBadgeClass}" style="margin: 0 auto 4px auto; display: inline-flex;">
                                ${kjKgH} kJ/kg/h
                            </div>
                            <div style="font-size: 0.75rem; color: #ec4899; font-weight: 600;">
                                NP: ${npKjKgH} kJ/kg/h
                            </div>
                            <div style="font-size: 0.7rem; color: var(--text-muted); margin-top: 2px;">
                                ${s.w_kg_media} W/kg • ${s.tss_hora} TSS/h
                            </div>
                        </td>
                        <td style="text-align: center; vertical-align: middle; background: rgba(52, 211, 153, 0.03);">
                            <div style="font-size: 0.88rem; color: #34d399; font-weight: 700; font-family: var(--font-mono);">
                                ${s.kj_kg} kJ/kg
                            </div>
                            <div style="font-size: 0.72rem; color: var(--text-muted); margin-top: 2px;">
                                ${s.kilojulios_total ? s.kilojulios_total.toLocaleString() : 0} kJ (${s.kcal_estimadas ? s.kcal_estimadas.toLocaleString() : 0} kcal)
                            </div>
                        </td>
                    </tr>
                `;
            });

            html += `
                        </tbody>
                    </table>
                </div>
                <div style="display: flex; align-items: center; justify-content: flex-end; gap: 12px; margin-top: 12px; font-size: 0.72rem; color: var(--text-muted); flex-wrap: wrap;">
                    <span style="font-weight: 600; text-transform: uppercase;">Escala de Intensidad Horaria:</span>
                    <span class="rate-badge rate-easy">&lt; 22 kJ/kg/h (Z1/Z2 Baja)</span>
                    <span class="rate-badge rate-moderate">22 - 28 kJ/kg/h (Z2/Z3 Media)</span>
                    <span class="rate-badge rate-high">28 - 34 kJ/kg/h (Z3/Z4 Alta)</span>
                    <span class="rate-badge rate-extreme">&gt; 34 kJ/kg/h (Exigencia Extrema)</span>
                </div>
            `;

            container.innerHTML = html;
        }

        function initMap() {
            const mapEl = document.getElementById('map');
            if (!mapEl) return;
            const centro = DATA.etapa.centro_mapa || [42.5, 1.6];
            map = L.map('map', {
                center: centro,
                zoom: 11,
                zoomControl: true
            });

            L.tileLayer('https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png', {
                attribution: '&copy; <a href="https://carto.com/">CARTO</a>, OpenStreetMap',
                maxZoom: 18,
                subdomains: 'abcd'
            }).addTo(map);

            const coords = DATA.etapa.coordenadas_track;
            trackLayer = L.polyline(coords, {
                color: '#38bdf8',
                weight: 4.5,
                opacity: 0.85,
                lineJoin: 'round'
            }).addTo(map);

            if (coords.length > 0) {
                L.circleMarker(coords[0], {
                    radius: 7,
                    fillColor: '#10b981',
                    color: '#ffffff',
                    weight: 2,
                    fillOpacity: 1
                }).bindPopup("<b>🚩 Punto Común de Inicio</b>").addTo(map);

                L.circleMarker(coords[coords.length - 1], {
                    radius: 7,
                    fillColor: '#ef4444',
                    color: '#ffffff',
                    weight: 2,
                    fillOpacity: 1
                }).bindPopup("<b>🏁 Meta de la Etapa</b>").addTo(map);
            }

            if (DATA.etapa.bounds) {
                map.fitBounds(DATA.etapa.bounds, { padding: [30, 30] });
            }

            DATA.ciclistas.forEach((c, idx) => {
                const s = c.stats;
                const initials = s.nombre.split(' ').map(n => n[0]).join('').substring(0, 2).toUpperCase();
                const firstSample = c.by_dist[0] || { lat: centro[0], lon: centro[1] };

                const customIcon = L.divIcon({
                    className: 'rider-marker-div',
                    html: `<div class="rider-map-marker" style="--m-color: ${s.color}; --m-glow: ${s.glow};">${initials}</div>`,
                    iconSize: [32, 32],
                    iconAnchor: [16, 16]
                });

                const marker = L.marker([firstSample.lat, firstSample.lon], { icon: customIcon })
                    .bindPopup(`<b>${s.nombre}</b>`, { maxWidth: 220 })
                    .addTo(map);

                marker._riderInitials = initials;
                marker._riderStats = s;
                riderMarkers[idx] = marker;
            });

            const btnRecenter = document.getElementById('btnRecenterMap');
            if (btnRecenter) {
                btnRecenter.addEventListener('click', () => {
                    if (DATA.etapa.bounds) map.fitBounds(DATA.etapa.bounds, { padding: [30, 30] });
                });
            }
        }

        function initElevationChart() {
            const canvasEl = document.getElementById('elevationChart');
            if (!canvasEl) return;
            const ctx = canvasEl.getContext('2d');
            const perfil = DATA.etapa.perfil_altimetria;

            const datasets = [{
                label: 'Perfil Altimetría',
                data: perfil.map(p => ({ x: p.x, y: p.y })),
                borderColor: '#10b981',
                backgroundColor: 'rgba(16, 185, 129, 0.15)',
                borderWidth: 2.5,
                fill: true,
                tension: 0.15,
                pointRadius: 0,
                pointHoverRadius: 5,
                order: 2
            }];

            DATA.ciclistas.forEach(c => {
                const firstPt = c.by_dist[0] || { d_km: 0, alt: 0 };
                datasets.push({
                    label: c.stats.nombre,
                    data: [{ x: firstPt.d_km, y: firstPt.alt }],
                    borderColor: '#ffffff',
                    backgroundColor: c.stats.color,
                    borderWidth: 2.5,
                    pointRadius: 7,
                    pointHoverRadius: 9,
                    showLine: false,
                    order: 1
                });
            });

            elevationChart = new Chart(ctx, {
                type: 'line',
                data: { datasets: datasets },
                plugins: [segmentHighlightPlugin],
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    animation: false,
                    scales: {
                        x: {
                            type: 'linear',
                            min: 0,
                            max: DATA.etapa.distancia_total_km,
                            grid: { color: 'rgba(124, 58, 237, 0.07)' },
                            ticks: { color: '#645a78',
                                font: { family: 'JetBrains Mono', size: 11 },
                                callback: (v) => `${v.toFixed(1)} km`
                            }
                        },
                        y: {
                            grid: { color: 'rgba(124, 58, 237, 0.07)' },
                            ticks: { color: '#645a78',
                                font: { family: 'JetBrains Mono', size: 11 },
                                callback: (v) => `${v} m`
                            }
                        }
                    },
                    plugins: {
                        legend: {
                            labels: { color: '#645a78',
                                font: { family: 'Outfit', size: 12 },
                                usePointStyle: true
                            }
                        },
                        tooltip: {
                            backgroundColor: 'rgba(15, 23, 42, 0.95)',
                            titleFont: { family: 'Outfit', size: 13, weight: 'bold' },
                            bodyFont: { family: 'JetBrains Mono', size: 12 },
                            borderColor: 'rgba(255,255,255,0.1)',
                            borderWidth: 1,
                            callbacks: {
                                title: (items) => `📍 Km ${items[0].raw.x.toFixed(2)}`,
                                label: (item) => {
                                    if (item.datasetIndex === 0) {
                                        return `⛰️ Altitud Etapa: ${Math.round(item.raw.y)} m`;
                                    }
                                    // Es un marcador de ciclista (dataset index > 0)
                                    const cIdx = item.datasetIndex - 1;
                                    const series = syncMode === 'dist' ? DATA.ciclistas[cIdx]?.by_dist : DATA.ciclistas[cIdx]?.by_time;
                                    const sampleIdx = Math.min((series?.length || 1) - 1, currentStep);
                                    const samp = series?.[sampleIdx];
                                    if (!samp) return `${item.dataset.label}: ${Math.round(item.raw.y)} m`;
                                    const hh = String(Math.floor(samp.t_sec / 3600)).padStart(2, '0');
                                    const mm = String(Math.floor((samp.t_sec % 3600) / 60)).padStart(2, '0');
                                    const ss = String(Math.floor(samp.t_sec % 60)).padStart(2, '0');
                                    return `🚴 ${item.dataset.label}: ${Math.round(item.raw.y)} m | ⏱ ${hh}:${mm}:${ss} | ⚡ ${samp.pwr}W`;
                                }
                            }
                        }
                    }
                }
            });

            // Conectar selección arrastrando con el ratón sobre el perfil de elevación
            attachChartDragSelection(() => elevationChart, canvasEl);
        }

        // =========================================================
        // Módulo de Selección y Análisis de Tramos / Segmentos
        // =========================================================
        let currentSegment = {
            startKm: 0.0,
            endKm: DATA.etapa.distancia_total_km || 100.0,
            name: 'Etapa Completa',
            isPreset: true,
            isZoomed: false,
            isSimulating: false,
            simInterval: null
        };
        let segmentBarChart = null;
        let activeSegmentMetric = 'wkg';

        // Estado global de arrastre sobre los gráficos (Drag-to-Select)
        const dragState = {
            isDragging: false,
            startKm: 0.0,
            currentKm: 0.0,
            activeChart: null
        };

        // Chart.js Plugin para dibujar el sombreado del tramo seleccionado y el arrastre en vivo
        const segmentHighlightPlugin = {
            id: 'segmentHighlightPlugin',
            beforeDatasetsDraw(chart) {
                const { ctx, chartArea, scales } = chart;
                if (!chartArea || !scales || !scales.x) return;

                let startKm = 0;
                let endKm = 0;
                let isLiveDrag = false;

                if (dragState.isDragging) {
                    startKm = Math.min(dragState.startKm, dragState.currentKm);
                    endKm = Math.max(dragState.startKm, dragState.currentKm);
                    isLiveDrag = true;
                } else if (currentSegment && currentSegment.startKm !== null && currentSegment.endKm !== null) {
                    startKm = Math.min(currentSegment.startKm, currentSegment.endKm);
                    endKm = Math.max(currentSegment.startKm, currentSegment.endKm);
                    const totalKm = DATA.etapa.distancia_total_km || 100.0;
                    if (startKm <= 0.05 && endKm >= (totalKm - 0.05) && !currentSegment.isZoomed) {
                        return;
                    }
                } else {
                    return;
                }

                const startX = Math.max(chartArea.left, Math.min(chartArea.right, scales.x.getPixelForValue(startKm)));
                const endX = Math.max(chartArea.left, Math.min(chartArea.right, scales.x.getPixelForValue(endKm)));
                const width = endX - startX;
                if (Math.abs(width) < 1) return;

                ctx.save();

                // 1. Fondo translúcido con gradiente de selección
                const grad = ctx.createLinearGradient(startX, 0, endX, 0);
                if (isLiveDrag) {
                    grad.addColorStop(0, 'rgba(236, 72, 153, 0.28)');
                    grad.addColorStop(0.5, 'rgba(124, 58, 237, 0.32)');
                    grad.addColorStop(1, 'rgba(236, 72, 153, 0.28)');
                } else {
                    grad.addColorStop(0, 'rgba(124, 58, 237, 0.16)');
                    grad.addColorStop(0.5, 'rgba(236, 72, 153, 0.18)');
                    grad.addColorStop(1, 'rgba(124, 58, 237, 0.16)');
                }
                ctx.fillStyle = grad;
                ctx.fillRect(startX, chartArea.top, width, chartArea.bottom - chartArea.top);

                // 2. Líneas verticales en los bordes
                ctx.strokeStyle = isLiveDrag ? '#ec4899' : '#ec4899';
                ctx.lineWidth = isLiveDrag ? 2.5 : 2;
                ctx.setLineDash(isLiveDrag ? [3, 3] : [5, 4]);

                ctx.beginPath();
                ctx.moveTo(startX, chartArea.top);
                ctx.lineTo(startX, chartArea.bottom);
                ctx.stroke();

                ctx.beginPath();
                ctx.moveTo(endX, chartArea.top);
                ctx.lineTo(endX, chartArea.bottom);
                ctx.stroke();

                ctx.setLineDash([]);

                // 3. Etiquetas superiores (Inicio, Fin y Distancia Central)
                ctx.font = 'bold 11px Outfit, sans-serif';
                const distSpan = (endKm - startKm).toFixed(1);

                // Tag Inicio
                const tagW = Math.min(65, Math.max(48, width / 3));
                ctx.fillStyle = isLiveDrag ? 'rgba(244, 63, 94, 0.95)' : 'rgba(124, 58, 237, 0.9)';
                ctx.beginPath();
                if (ctx.roundRect) ctx.roundRect(startX, chartArea.top + 4, tagW, 18, 4);
                else ctx.rect(startX, chartArea.top + 4, tagW, 18);
                ctx.fill();
                ctx.fillStyle = '#ffffff';
                ctx.textAlign = 'center';
                ctx.fillText(`🚩 ${startKm.toFixed(1)}k`, startX + tagW / 2, chartArea.top + 17);

                // Tag Fin
                ctx.fillStyle = isLiveDrag ? 'rgba(244, 63, 94, 0.95)' : 'rgba(236, 72, 153, 0.9)';
                ctx.beginPath();
                if (ctx.roundRect) ctx.roundRect(endX - tagW, chartArea.top + 4, tagW, 18, 4);
                else ctx.rect(endX - tagW, chartArea.top + 4, tagW, 18);
                ctx.fill();
                ctx.fillStyle = '#ffffff';
                ctx.textAlign = 'center';
                ctx.fillText(`🏁 ${endKm.toFixed(1)}k`, endX - tagW / 2, chartArea.top + 17);

                // Badge Central de Longitud si hay espacio suficiente (> 120px)
                if (width > 120) {
                    const centerTagW = 82;
                    const centerX = startX + width / 2;
                    ctx.fillStyle = isLiveDrag ? 'rgba(15, 23, 42, 0.92)' : 'rgba(15, 23, 42, 0.85)';
                    ctx.beginPath();
                    if (ctx.roundRect) ctx.roundRect(centerX - centerTagW / 2, chartArea.top + 4, centerTagW, 18, 4);
                    else ctx.rect(centerX - centerTagW / 2, chartArea.top + 4, centerTagW, 18);
                    ctx.fill();
                    ctx.fillStyle = isLiveDrag ? '#38bdf8' : '#a78bfa';
                    ctx.textAlign = 'center';
                    ctx.fillText(`📏 ${distSpan} km`, centerX, chartArea.top + 17);
                }

                ctx.restore();
            }
        };

        // Función reutilizable para habilitar selección arrastrando con el ratón sobre cualquier gráfico
        function attachChartDragSelection(getChartFn, canvasEl) {
            if (!canvasEl) return;

            let isMouseDown = false;
            let startClientX = 0;
            let startKm = 0;
            let hasMoved = false;

            function getKm(clientX) {
                const chart = getChartFn();
                if (!chart || !chart.scales || !chart.scales.x) return 0;
                const rect = canvasEl.getBoundingClientRect();
                const xPos = clientX - rect.left;
                const scaleX = chart.scales.x;
                const km = scaleX.getValueForPixel(xPos);
                const totalKm = DATA.etapa.distancia_total_km || 100.0;
                return Math.max(0, Math.min(totalKm, parseFloat(km.toFixed(2))));
            }

            function isInsideArea(clientX, clientY) {
                const chart = getChartFn();
                if (!chart || !chart.chartArea) return false;
                const rect = canvasEl.getBoundingClientRect();
                const x = clientX - rect.left;
                const y = clientY - rect.top;
                const area = chart.chartArea;
                return (x >= area.left && x <= area.right && y >= area.top && y <= area.bottom);
            }

            const onStart = (e) => {
                const clientX = e.touches ? e.touches[0].clientX : e.clientX;
                const clientY = e.touches ? e.touches[0].clientY : e.clientY;
                if (!isInsideArea(clientX, clientY)) return;

                isMouseDown = true;
                hasMoved = false;
                startClientX = clientX;
                startKm = getKm(clientX);

                dragState.isDragging = false;
                dragState.startKm = startKm;
                dragState.currentKm = startKm;
                dragState.activeChart = getChartFn();
            };

            const onMove = (e) => {
                const clientX = e.touches ? e.touches[0].clientX : e.clientX;
                const clientY = e.touches ? e.touches[0].clientY : e.clientY;

                if (!isMouseDown) {
                    if (isInsideArea(clientX, clientY)) {
                        canvasEl.style.cursor = 'col-resize';
                    } else {
                        canvasEl.style.cursor = 'default';
                    }
                    return;
                }

                const diffX = Math.abs(clientX - startClientX);
                if (diffX >= 5) {
                    hasMoved = true;
                    dragState.isDragging = true;
                    dragState.currentKm = getKm(clientX);

                    if (e.cancelable && e.touches) e.preventDefault();

                    const chart = getChartFn();
                    if (chart) chart.draw();
                    if (chart === telemetryChart && elevationChart) elevationChart.draw();
                    if (chart === elevationChart && telemetryChart) telemetryChart.draw();
                }
            };

            const onEnd = (e) => {
                if (!isMouseDown) return;
                isMouseDown = false;

                if (dragState.isDragging && hasMoved) {
                    const minKm = parseFloat(Math.min(dragState.startKm, dragState.currentKm).toFixed(1));
                    const maxKm = parseFloat(Math.max(dragState.startKm, dragState.currentKm).toFixed(1));

                    if (maxKm - minKm >= 0.2) {
                        setSegment(minKm, maxKm, `Tramo Km ${minKm.toFixed(1)} → ${maxKm.toFixed(1)}`, false);
                        // Auto-zoom: aplicar zoom al rango seleccionado igual que el botón "Zoom Tramo"
                        zoomToCurrentSegment();
                    }
                }

                dragState.isDragging = false;
                dragState.activeChart = null;
                if (telemetryChart) telemetryChart.update('none');
                if (elevationChart) elevationChart.update('none');
            };

            canvasEl.addEventListener('mousedown', onStart);
            window.addEventListener('mousemove', onMove);
            window.addEventListener('mouseup', onEnd);

            canvasEl.addEventListener('touchstart', onStart, { passive: true });
            window.addEventListener('touchmove', onMove, { passive: false });
            window.addEventListener('touchend', onEnd);
        }

        function initSegmentAnalysis() {
            renderSegmentPresets();
            setupSegmentControls();
            initSegmentBarChart();

            const totalKm = DATA.etapa.distancia_total_km || 100.0;
            setSegment(0.0, totalKm, 'Etapa Completa', true);
        }

        function renderSegmentPresets() {
            const container = document.getElementById('segmentPresetsContainer');
            if (!container) return;
            container.innerHTML = '';

            const presets = DATA.etapa.segmentos_sugeridos || [];
            presets.forEach((p, idx) => {
                const pill = document.createElement('button');
                pill.className = `segment-preset-pill ${idx === 0 ? 'active' : ''}`;
                pill.id = `preset-pill-${p.id}`;
                pill.setAttribute('data-preset-id', p.id);
                pill.setAttribute('data-start-km', p.km_inicio);
                pill.setAttribute('data-end-km', p.km_fin);
                pill.setAttribute('data-name', p.nombre);

                let iconName = p.icono || (p.tipo === 'puerto' ? 'mountain' : 'flag');
                pill.innerHTML = `
                    <i data-lucide="${iconName}" style="width: 14px; height: 14px; color: ${p.color || 'var(--color-primary)'};"></i>
                    <span>${p.nombre}</span>
                    <span class="preset-pill-badge">${p.badge || (p.distancia_km + ' km')}</span>
                `;

                pill.addEventListener('click', () => {
                    setSegment(p.km_inicio, p.km_fin, p.nombre, true);
                    document.querySelectorAll('.segment-preset-pill').forEach(el => el.classList.remove('active'));
                    pill.classList.add('active');
                });

                container.appendChild(pill);
            });

            if (typeof lucide !== 'undefined' && lucide.createIcons) lucide.createIcons();
        }

        function setupSegmentControls() {
            const inputStart = document.getElementById('inputSegStart');
            const inputEnd = document.getElementById('inputSegEnd');
            const sliderStart = document.getElementById('sliderSegStart');
            const sliderEnd = document.getElementById('sliderSegEnd');
            const totalKm = DATA.etapa.distancia_total_km || 100.0;

            if (inputStart) {
                inputStart.max = totalKm;
                inputStart.addEventListener('change', () => {
                    let sVal = parseFloat(inputStart.value) || 0.0;
                    let eVal = parseFloat(inputEnd.value) || totalKm;
                    if (sVal < 0) sVal = 0.0;
                    if (sVal >= eVal) sVal = Math.max(0.0, eVal - 0.5);
                    setSegment(sVal, eVal, `Tramo Km ${sVal.toFixed(1)} → ${eVal.toFixed(1)}`, false, false, true);
                });
            }

            if (inputEnd) {
                inputEnd.max = totalKm;
                inputEnd.value = totalKm.toFixed(1);
                inputEnd.addEventListener('change', () => {
                    let sVal = parseFloat(inputStart.value) || 0.0;
                    let eVal = parseFloat(inputEnd.value) || totalKm;
                    if (eVal > totalKm) eVal = totalKm;
                    if (eVal <= sVal) eVal = Math.min(totalKm, sVal + 0.5);
                    setSegment(sVal, eVal, `Tramo Km ${sVal.toFixed(1)} → ${eVal.toFixed(1)}`, false, false, true);
                });
            }

            if (sliderStart && sliderEnd) {
                sliderStart.addEventListener('input', (e) => {
                    let sRatio = parseFloat(e.target.value) / 1000.0;
                    let sKm = parseFloat((sRatio * totalKm).toFixed(1));
                    let eKm = currentSegment.endKm;
                    if (sKm >= eKm) {
                        sKm = Math.max(0.0, eKm - 0.2);
                        sliderStart.value = Math.round((sKm / totalKm) * 1000);
                    }
                    setSegment(sKm, eKm, `Tramo Km ${sKm.toFixed(1)} → ${eKm.toFixed(1)}`, false, true);
                });

                sliderEnd.addEventListener('input', (e) => {
                    let eRatio = parseFloat(e.target.value) / 1000.0;
                    let eKm = parseFloat((eRatio * totalKm).toFixed(1));
                    let sKm = currentSegment.startKm;
                    if (eKm <= sKm) {
                        eKm = Math.min(totalKm, sKm + 0.2);
                        sliderEnd.value = Math.round((eKm / totalKm) * 1000);
                    }
                    setSegment(sKm, eKm, `Tramo Km ${sKm.toFixed(1)} → ${eKm.toFixed(1)}`, false, true);
                });
            }

            // Botones de Acción
            const btnReset = document.getElementById('btnResetSegment');
            if (btnReset) {
                btnReset.addEventListener('click', () => {
                    setSegment(0.0, totalKm, 'Etapa Completa', true);
                    const firstPill = document.querySelector('.segment-preset-pill');
                    if (firstPill) {
                        document.querySelectorAll('.segment-preset-pill').forEach(el => el.classList.remove('active'));
                        firstPill.classList.add('active');
                    }
                });
            }

            const btnZoom = document.getElementById('btnChartZoomSeg');
            if (btnZoom) {
                btnZoom.addEventListener('click', zoomToCurrentSegment);
            }

            const btnResetZoom = document.getElementById('btnChartResetZoom');
            if (btnResetZoom) {
                btnResetZoom.addEventListener('click', resetChartZoom);
            }

            const btnSim = document.getElementById('btnSimulateSegment');
            if (btnSim) {
                btnSim.addEventListener('click', playSegmentSimulation);
            }

            // Pestañas de métrica del gráfico de segmento
            document.querySelectorAll('#segmentChartTabs .tab-btn').forEach(btn => {
                btn.addEventListener('click', (e) => {
                    document.querySelectorAll('#segmentChartTabs .tab-btn').forEach(b => b.classList.remove('active'));
                    e.currentTarget.classList.add('active');
                    activeSegmentMetric = e.currentTarget.dataset.segMetric;
                    const res = calculateSegmentMetrics(currentSegment.startKm, currentSegment.endKm);
                    updateSegmentBarChart(res, activeSegmentMetric);
                });
            });
        }

        function setSegment(startKm, endKm, name, isPreset, isFromSlider, isFromInput) {
            const totalKm = DATA.etapa.distancia_total_km || 100.0;
            startKm = Math.max(0.0, Math.min(totalKm, parseFloat(startKm) || 0.0));
            endKm = Math.max(0.0, Math.min(totalKm, parseFloat(endKm) || totalKm));

            if (startKm > endKm) {
                const temp = startKm;
                startKm = endKm;
                endKm = temp;
            }

            currentSegment.startKm = parseFloat(startKm.toFixed(1));
            currentSegment.endKm = parseFloat(endKm.toFixed(1));
            currentSegment.name = name || `Tramo Km ${currentSegment.startKm} → ${currentSegment.endKm}`;
            currentSegment.isPreset = !!isPreset;

            if (!isFromInput) {
                const inputStart = document.getElementById('inputSegStart');
                const inputEnd = document.getElementById('inputSegEnd');
                if (inputStart) inputStart.value = currentSegment.startKm.toFixed(1);
                if (inputEnd) inputEnd.value = currentSegment.endKm.toFixed(1);
            }

            if (!isFromSlider) {
                const sliderStart = document.getElementById('sliderSegStart');
                const sliderEnd = document.getElementById('sliderSegEnd');
                if (sliderStart) sliderStart.value = Math.round((currentSegment.startKm / totalKm) * 1000);
                if (sliderEnd) sliderEnd.value = Math.round((currentSegment.endKm / totalKm) * 1000);
            }

            updateSegmentSliderHighlight(currentSegment.startKm, currentSegment.endKm, totalKm);

            if (!isPreset) {
                document.querySelectorAll('.segment-preset-pill').forEach(el => el.classList.remove('active'));
            }

            const segmentData = calculateSegmentMetrics(currentSegment.startKm, currentSegment.endKm);
            renderSegmentAnalysis(segmentData, currentSegment.name);

            if (telemetryChart) telemetryChart.update('none');
            if (elevationChart) elevationChart.update('none');
        }

        function updateSegmentSliderHighlight(startKm, endKm, totalKm) {
            const highlight = document.getElementById('segmentSliderHighlight');
            if (!highlight || totalKm <= 0) return;
            const leftPct = (startKm / totalKm) * 100.0;
            const widthPct = ((endKm - startKm) / totalKm) * 100.0;
            highlight.style.left = `${leftPct}%`;
            highlight.style.width = `${Math.max(0.5, widthPct)}%`;
        }

        function calculateSegmentMetrics(startKm, endKm) {
            if (startKm > endKm) {
                const tmp = startKm;
                startKm = endKm;
                endKm = tmp;
            }
            const distSegmento = Math.max(0.05, endKm - startKm);

            const perfil = DATA.etapa.perfil_altimetria || [];
            let altIni = null;
            let altFin = null;
            let desnivelPos = 0;
            let maxAlt = 0;
            let minAlt = 99999;

            for (let i = 0; i < perfil.length; i++) {
                const p = perfil[i];
                if (p.x >= startKm - 0.05 && p.x <= endKm + 0.05) {
                    if (altIni === null) altIni = p.y;
                    altFin = p.y;
                    if (p.y > maxAlt) maxAlt = p.y;
                    if (p.y < minAlt) minAlt = p.y;

                    if (i > 0 && perfil[i-1].x >= startKm - 0.05) {
                        const diff = p.y - perfil[i - 1].y;
                        if (diff > 0) desnivelPos += diff;
                    }
                }
            }

            if (altIni === null && perfil.length > 0) {
                altIni = perfil[0].y;
                altFin = perfil[perfil.length - 1].y;
            }
            if (minAlt > maxAlt) { minAlt = altIni || 0; maxAlt = altFin || 0; }

            const pendienteMedia = (((altFin || 0) - (altIni || 0)) / (distSegmento * 1000.0)) * 100.0;
            const riderResults = [];

            DATA.ciclistas.forEach((c, idx) => {
                const s = c.stats;
                const series = c.by_dist || [];
                const peso = Math.max(30.0, s.peso_kg || 70.0);
                const ftp = Math.max(150.0, s.ftp_w || 380.0);

                const samplesInSeg = series.filter(pt => pt.d_km >= startKm - 0.05 && pt.d_km <= endKm + 0.05);

                let duracionSeg = 0;
                let pwrSum = 0;
                let hrSum = 0;
                let hrCount = 0;
                let hrMax = 0;
                let cadSum = 0;
                let cadCount = 0;
                let pwrVals = [];
                let spdSum = 0;
                let kjIni = 0;
                let kjFin = 0;

                if (samplesInSeg.length >= 2) {
                    const ptStart = samplesInSeg[0];
                    const ptEnd = samplesInSeg[samplesInSeg.length - 1];
                    duracionSeg = Math.max(1, ptEnd.t_sec - ptStart.t_sec);
                    kjIni = ptStart.kj;
                    kjFin = ptEnd.kj;

                    samplesInSeg.forEach(pt => {
                        pwrSum += pt.pwr;
                        pwrVals.push(pt.pwr);
                        spdSum += (pt.spd || 0);
                        if (pt.hr > 40) {
                            hrSum += pt.hr;
                            hrCount++;
                            if (pt.hr > hrMax) hrMax = pt.hr;
                        }
                        if (pt.cad > 10) {
                            cadSum += pt.cad;
                            cadCount++;
                        }
                    });
                } else {
                    const ptIni = interpolateRiderAtKm(series, startKm);
                    const ptFin = interpolateRiderAtKm(series, endKm);
                    duracionSeg = Math.max(1, ptFin.t_sec - ptIni.t_sec);
                    kjIni = ptIni.kj;
                    kjFin = ptFin.kj;
                    pwrSum = (ptIni.pwr + ptFin.pwr);
                    pwrVals = [ptIni.pwr, ptFin.pwr];
                    spdSum = (ptIni.spd + ptFin.spd);
                    if (ptIni.hr > 40) { hrSum += ptIni.hr; hrCount++; }
                    if (ptFin.hr > 40) { hrSum += ptFin.hr; hrCount++; }
                    hrMax = Math.max(ptIni.hr, ptFin.hr);
                    if (ptIni.cad > 10) { cadSum += ptIni.cad; cadCount++; }
                    if (ptFin.cad > 10) { cadSum += ptFin.cad; cadCount++; }
                }

                const count = Math.max(1, pwrVals.length);
                const potMedia = Math.round(pwrSum / count);
                const wkgMedia = parseFloat((potMedia / peso).toFixed(2));
                const horasSeg = duracionSeg / 3600.0;
                const velMedia = parseFloat((distSegmento / Math.max(0.001, horasSeg)).toFixed(1));

                // Potencia Normalizada (NP)
                let npSeg = potMedia;
                if (pwrVals.length >= 10) {
                    let p4Sum = 0;
                    let roll = [];
                    const wSize = Math.max(1, Math.min(30, Math.floor(pwrVals.length / 4)));
                    for (let i = 0; i < pwrVals.length; i++) {
                        roll.push(pwrVals[i]);
                        if (roll.length > wSize) roll.shift();
                        const m = roll.reduce((a, b) => a + b, 0) / roll.length;
                        p4Sum += Math.pow(m, 4);
                    }
                    npSeg = Math.round(Math.pow(p4Sum / pwrVals.length, 0.25));
                }

                const ifVal = parseFloat((npSeg / ftp).toFixed(2));
                const tssSeg = parseFloat(((duracionSeg * npSeg * (npSeg / ftp)) / (ftp * 36.0)).toFixed(1));
                const tssHora = parseFloat((tssSeg / Math.max(0.01, horasSeg)).toFixed(1));

                let kjSeg = Math.max(0, Math.round(kjFin - kjIni));
                if (kjSeg <= 0) kjSeg = Math.round((potMedia * duracionSeg) / 1000.0);
                const kjKg = parseFloat((kjSeg / peso).toFixed(1));
                const kjKgH = parseFloat((kjKg / Math.max(0.01, horasSeg)).toFixed(1));

                const fcMedia = hrCount > 0 ? Math.round(hrSum / hrCount) : 0;
                const cadMedia = cadCount > 0 ? Math.round(cadSum / cadCount) : 0;

                const hh = Math.floor(duracionSeg / 3600);
                const mm = Math.floor((duracionSeg % 3600) / 60);
                const ss = Math.floor(duracionSeg % 60);
                let timeStr = "";
                if (hh > 0) {
                    timeStr = `${hh}h ${String(mm).padStart(2, '0')}m ${String(ss).padStart(2, '0')}s`;
                } else {
                    timeStr = `${mm}m ${String(ss).padStart(2, '0')}s`;
                }

                riderResults.push({
                    idx: idx,
                    nombre: s.nombre,
                    color: s.color,
                    color_sec: s.color_sec,
                    glow: s.glow,
                    peso: peso,
                    ftp: ftp,
                    duracion_seg: duracionSeg,
                    tiempo_str: timeStr,
                    vel_media_kmh: velMedia,
                    pot_media_w: potMedia,
                    w_kg: wkgMedia,
                    np_w: npSeg,
                    if_val: ifVal,
                    tss: tssSeg,
                    tss_hora: tssHora,
                    kj: kjSeg,
                    kj_kg: kjKg,
                    kj_kg_h: kjKgH,
                    fc_media: fcMedia,
                    fc_max: hrMax,
                    cad_media: cadMedia
                });
            });

            riderResults.sort((a, b) => a.duracion_seg - b.duracion_seg);

            const minDur = riderResults.length > 0 ? riderResults[0].duracion_seg : 0;
            riderResults.forEach((r, rank) => {
                r.posicion = rank + 1;
                const gap = r.duracion_seg - minDur;
                r.gap_seg = gap;
                if (gap === 0) {
                    r.gap_str = "Líder";
                } else {
                    const gMm = Math.floor(gap / 60);
                    const gSs = Math.floor(gap % 60);
                    r.gap_str = gMm > 0 ? `+${gMm}m ${String(gSs).padStart(2, '0')}s` : `+${gSs}s`;
                }
            });

            return {
                startKm: startKm,
                endKm: endKm,
                distancia_km: parseFloat(distSegmento.toFixed(2)),
                desnivel_pos_m: Math.round(desnivelPos),
                alt_inicio: Math.round(altIni || 0),
                alt_fin: Math.round(altFin || 0),
                pendiente_media: parseFloat(pendienteMedia.toFixed(1)),
                riders: riderResults
            };
        }

        function interpolateRiderAtKm(series, km) {
            if (!series || series.length === 0) return { t_sec: 0, pwr: 0, wkg: 0, spd: 0, hr: 0, cad: 0, kj: 0, alt: 0 };
            if (km <= series[0].d_km) return series[0];
            if (km >= series[series.length - 1].d_km) return series[series.length - 1];

            let low = 0;
            let high = series.length - 1;
            while (low <= high) {
                const mid = Math.floor((low + high) / 2);
                if (series[mid].d_km < km) low = mid + 1;
                else high = mid - 1;
            }
            const idx1 = Math.max(0, high);
            const idx2 = Math.min(series.length - 1, low);
            if (idx1 === idx2) return series[idx1];

            const p1 = series[idx1];
            const p2 = series[idx2];
            const ratio = (km - p1.d_km) / (p2.d_km - p1.d_km || 0.001);

            return {
                d_km: km,
                t_sec: Math.round(p1.t_sec + ratio * (p2.t_sec - p1.t_sec)),
                pwr: Math.round(p1.pwr + ratio * (p2.pwr - p1.pwr)),
                wkg: parseFloat((p1.wkg + ratio * (p2.wkg - p1.wkg)).toFixed(2)),
                spd: parseFloat(((p1.spd || 0) + ratio * ((p2.spd || 0) - (p1.spd || 0))).toFixed(1)),
                hr: Math.round(p1.hr + ratio * (p2.hr - p1.hr)),
                cad: Math.round(p1.cad + ratio * (p2.cad - p1.cad)),
                kj: Math.round(p1.kj + ratio * (p2.kj - p1.kj)),
                alt: Math.round(p1.alt + ratio * (p2.alt - p1.alt))
            };
        }

        function renderSegmentAnalysis(segData, segName) {
            const lblDist = document.getElementById('lblSegDistance');
            const lblElev = document.getElementById('lblSegElevation');
            const lblGrad = document.getElementById('lblSegGradient');
            const lblFastestRider = document.getElementById('lblSegFastestRider');
            const lblFastestTime = document.getElementById('lblSegFastestTime');

            if (lblDist) lblDist.innerText = `${segData.distancia_km} km`;
            if (lblElev) lblElev.innerText = `+${segData.desnivel_pos_m} m`;
            if (lblGrad) lblGrad.innerText = `${segData.pendiente_media}%`;

            const topRider = segData.riders[0];
            if (lblFastestRider && topRider) lblFastestRider.innerText = topRider.nombre;
            if (lblFastestTime && topRider) lblFastestTime.innerText = topRider.tiempo_str;

            const lblActiveName = document.getElementById('lblActiveSegmentName');
            const badgeKm = document.getElementById('badgeSegKm');
            const badgeElev = document.getElementById('badgeSegElev');
            const badgeSlope = document.getElementById('badgeSegSlope');

            if (lblActiveName) lblActiveName.innerText = `📍 ${segName || 'Tramo Seleccionado'} (Km ${segData.startKm} → ${segData.endKm})`;
            if (badgeKm) badgeKm.innerText = `${segData.distancia_km} km`;
            if (badgeElev) badgeElev.innerText = `+${segData.desnivel_pos_m} m D+`;
            if (badgeSlope) badgeSlope.innerText = `${segData.pendiente_media}% pend. med.`;

            renderSegmentKPIs(segData);
            renderSegmentTable(segData);
            updateSegmentBarChart(segData, activeSegmentMetric);
        }

        function renderSegmentKPIs(segData) {
            const container = document.getElementById('segmentKpisGrid');
            if (!container) return;

            const riders = segData.riders;
            if (!riders || riders.length === 0) {
                container.innerHTML = '';
                return;
            }

            const bestTimeRider = riders[0];
            const bestWkgRider = [...riders].sort((a, b) => b.w_kg - a.w_kg)[0];
            const bestNpRider = [...riders].sort((a, b) => b.np_w - a.np_w)[0];
            const highestRateRider = [...riders].sort((a, b) => b.kj_kg_h - a.kj_kg_h)[0];

            container.innerHTML = `
                <div class="segment-kpi-card">
                    <div class="segment-kpi-icon" style="background: rgba(245, 158, 11, 0.15); color: #fbbf24;">
                        <i data-lucide="trophy"></i>
                    </div>
                    <div>
                        <div class="segment-kpi-val" style="color: #fbbf24;">${bestTimeRider.tiempo_str}</div>
                        <div class="segment-kpi-lbl">Mejor Tiempo en Tramo</div>
                        <div class="segment-kpi-sub">${bestTimeRider.nombre} (${bestTimeRider.vel_media_kmh} km/h)</div>
                    </div>
                </div>

                <div class="segment-kpi-card">
                    <div class="segment-kpi-icon" style="background: rgba(236, 72, 153, 0.15); color: #ec4899;">
                        <i data-lucide="zap"></i>
                    </div>
                    <div>
                        <div class="segment-kpi-val" style="color: #ec4899;">${bestWkgRider.w_kg} <span style="font-size: 0.8rem;">W/kg</span></div>
                        <div class="segment-kpi-lbl">Máxima Potencia Relativa</div>
                        <div class="segment-kpi-sub">${bestWkgRider.nombre} (${bestWkgRider.pot_media_w} W)</div>
                    </div>
                </div>

                <div class="segment-kpi-card">
                    <div class="segment-kpi-icon" style="background: rgba(56, 189, 248, 0.15); color: #38bdf8;">
                        <i data-lucide="activity"></i>
                    </div>
                    <div>
                        <div class="segment-kpi-val" style="color: #38bdf8;">${bestNpRider.np_w} <span style="font-size: 0.8rem;">W NP</span></div>
                        <div class="segment-kpi-lbl">Mayor Potencia Normalizada</div>
                        <div class="segment-kpi-sub">${bestNpRider.nombre} (IF ${bestNpRider.if_val})</div>
                    </div>
                </div>

                <div class="segment-kpi-card">
                    <div class="segment-kpi-icon" style="background: rgba(168, 85, 247, 0.15); color: #c084fc;">
                        <i data-lucide="flame"></i>
                    </div>
                    <div>
                        <div class="segment-kpi-val" style="color: #c084fc;">${highestRateRider.kj_kg_h} <span style="font-size: 0.8rem;">kJ/kg/h</span></div>
                        <div class="segment-kpi-lbl">Mayor Demanda Metabólica</div>
                        <div class="segment-kpi-sub">${highestRateRider.nombre} (${highestRateRider.kj} kJ)</div>
                    </div>
                </div>
            `;

            if (typeof lucide !== 'undefined' && lucide.createIcons) lucide.createIcons();
        }

        function renderSegmentTable(segData) {
            const tbody = document.getElementById('segmentTableBody');
            if (!tbody) return;
            tbody.innerHTML = '';

            segData.riders.forEach((r, idx) => {
                const isLeader = (r.gap_seg === 0);
                let rateBadgeClass = 'rate-easy';
                if (r.kj_kg_h >= 34.0) rateBadgeClass = 'rate-extreme';
                else if (r.kj_kg_h >= 28.0) rateBadgeClass = 'rate-high';
                else if (r.kj_kg_h >= 22.0) rateBadgeClass = 'rate-moderate';

                const tr = document.createElement('tr');
                tr.innerHTML = `
                    <td style="text-align: center; font-weight: bold; color: ${isLeader ? '#fbbf24' : 'var(--text-muted)'};">${r.posicion}º</td>
                    <td>
                        <div class="rider-tag"><span class="rider-dot" style="--dot-color: ${r.color};"></span> ${r.nombre}</div>
                        <div style="font-size: 0.72rem; color: var(--text-muted); margin-top: 2px;">${r.peso} kg • FTP ${r.ftp} W</div>
                    </td>
                    <td><strong style="color: var(--text-main);">${r.tiempo_str}</strong></td>
                    <td><span class="rider-rank-badge ${isLeader ? 'leader' : ''}">${r.gap_str}</span></td>
                    <td>${r.vel_media_kmh} km/h</td>
                    <td><strong style="color: #38bdf8;">${r.pot_media_w} W</strong></td>
                    <td><strong style="color: #ec4899;">${r.w_kg}</strong> W/kg</td>
                    <td><strong style="color: #f59e0b;">${r.np_w} W</strong> <span style="font-size: 0.72rem; color: var(--text-muted);">(IF ${r.if_val})</span></td>
                    <td><strong style="color: #a855f7;">${r.tss} TSS</strong> <span style="font-size: 0.72rem; color: var(--text-muted);">(${r.tss_hora}/h)</span></td>
                    <td>
                        <div><strong style="color: #34d399;">${r.kj} kJ</strong> <span style="font-size: 0.72rem; color: var(--text-muted);">(${r.kj_kg} kJ/kg)</span></div>
                        <div class="rate-badge ${rateBadgeClass}" style="margin-top: 2px;">${r.kj_kg_h} kJ/kg/h</div>
                    </td>
                    <td>${r.fc_media > 0 ? r.fc_media + ' bpm' : '--'} <span style="font-size: 0.72rem; color: var(--text-muted);">${r.fc_max > 0 ? '(Máx ' + r.fc_max + ')' : ''}</span></td>
                    <td>${r.cad_media > 0 ? r.cad_media + ' rpm' : '--'}</td>
                `;
                tbody.appendChild(tr);
            });
        }

        function initSegmentBarChart() {
            const canvasEl = document.getElementById('segmentBarChart');
            if (!canvasEl) return;
            const ctx = canvasEl.getContext('2d');

            segmentBarChart = new Chart(ctx, {
                type: 'bar',
                data: { labels: [], datasets: [] },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    animation: { duration: 350 },
                    scales: {
                        x: {
                            grid: { color: 'rgba(124, 58, 237, 0.07)' },
                            ticks: { color: '#645a78', font: { family: 'Outfit', size: 12, weight: '600' } }
                        },
                        y: {
                            beginAtZero: true,
                            grid: { color: 'rgba(124, 58, 237, 0.07)' },
                            ticks: { color: '#38bdf8', font: { family: 'JetBrains Mono', size: 11 } }
                        }
                    },
                    plugins: {
                        legend: { display: false },
                        tooltip: {
                            backgroundColor: 'rgba(15, 23, 42, 0.95)',
                            titleFont: { family: 'Outfit', size: 13, weight: 'bold' },
                            bodyFont: { family: 'JetBrains Mono', size: 12 },
                            borderColor: 'rgba(255,255,255,0.12)',
                            borderWidth: 1,
                            padding: 10
                        }
                    }
                }
            });
        }

        function updateSegmentBarChart(segData, metric) {
            if (!segmentBarChart) return;

            const riders = segData.riders || [];
            const labels = riders.map(r => r.nombre);
            let dataVals = [];
            let yUnit = '';
            let yTitle = '';

            if (metric === 'wkg') {
                dataVals = riders.map(r => r.w_kg);
                yUnit = ' W/kg';
                yTitle = 'Potencia Relativa (W/kg)';
            } else if (metric === 'power') {
                dataVals = riders.map(r => r.pot_media_w);
                yUnit = ' W';
                yTitle = 'Potencia Media (W)';
            } else if (metric === 'time') {
                dataVals = riders.map(r => parseFloat((r.duracion_seg / 60.0).toFixed(1)));
                yUnit = ' min';
                yTitle = 'Tiempo Empleado (minutos)';
            } else if (metric === 'kjkg_h') {
                dataVals = riders.map(r => r.kj_kg_h);
                yUnit = ' kJ/kg/h';
                yTitle = 'Demanda Metabólica (kJ/kg/h)';
            } else if (metric === 'speed') {
                dataVals = riders.map(r => r.vel_media_kmh);
                yUnit = ' km/h';
                yTitle = 'Velocidad Media (km/h)';
            }

            segmentBarChart.data.labels = labels;
            segmentBarChart.data.datasets = [{
                label: yTitle,
                data: dataVals,
                backgroundColor: riders.map(r => r.color + 'cc'),
                borderColor: riders.map(r => r.color),
                borderWidth: 1.5,
                borderRadius: 8
            }];

            if (segmentBarChart.options.scales.y) {
                segmentBarChart.options.scales.y.title = { display: true, text: yTitle, color: '#645a78', font: { family: 'Outfit', size: 11, weight: '600' } };
                segmentBarChart.options.scales.y.ticks.callback = (v) => `${v}${yUnit}`;
            }

            segmentBarChart.update();
        }

        function zoomToCurrentSegment() {
            const startKm = Math.min(currentSegment.startKm, currentSegment.endKm);
            const endKm = Math.max(currentSegment.startKm, currentSegment.endKm);
            if (endKm - startKm < 0.1) return;

            if (telemetryChart) {
                telemetryChart.options.scales.x.min = startKm;
                telemetryChart.options.scales.x.max = endKm;
                telemetryChart.update();
            }
            if (elevationChart) {
                elevationChart.options.scales.x.min = startKm;
                elevationChart.options.scales.x.max = endKm;
                elevationChart.update();
            }
            currentSegment.isZoomed = true;

            const btnZoom = document.getElementById('btnChartZoomSeg');
            if (btnZoom) btnZoom.classList.add('primary');
        }

        function resetChartZoom() {
            const totalKm = DATA.etapa.distancia_total_km || 100.0;
            if (telemetryChart) {
                telemetryChart.options.scales.x.min = 0;
                telemetryChart.options.scales.x.max = totalKm;
                telemetryChart.update();
            }
            if (elevationChart) {
                elevationChart.options.scales.x.min = 0;
                elevationChart.options.scales.x.max = totalKm;
                elevationChart.update();
            }
            currentSegment.isZoomed = false;

            const btnZoom = document.getElementById('btnChartZoomSeg');
            if (btnZoom) btnZoom.classList.remove('primary');
        }

        function playSegmentSimulation() {
            const startKm = currentSegment.startKm;
            const endKm = currentSegment.endKm;
            const totalKm = DATA.etapa.distancia_total_km || 100.0;

            const startStep = Math.max(0, Math.round((startKm / totalKm) * 999));
            const endStep = Math.min(999, Math.round((endKm / totalKm) * 999));

            if (isPlaying) togglePlay();

            currentStep = startStep;
            const slider = document.getElementById('timelineSlider');
            if (slider) slider.value = currentStep;
            syncToStep(currentStep);

            togglePlay();

            if (currentSegment.simInterval) clearInterval(currentSegment.simInterval);
            currentSegment.simInterval = setInterval(() => {
                if (currentStep >= endStep) {
                    if (isPlaying) togglePlay();
                    clearInterval(currentSegment.simInterval);
                }
            }, 60);
        }

        function initTelemetryChart() {
            const canvasEl = document.getElementById('telemetryChart');
            if (!canvasEl) return;
            const ctx = canvasEl.getContext('2d');
            const perfil = DATA.etapa.perfil_altimetria;

            const altBgGradient = ctx.createLinearGradient(0, 0, 0, 360);
            altBgGradient.addColorStop(0, 'rgba(56, 189, 248, 0.18)');
            altBgGradient.addColorStop(0.5, 'rgba(14, 165, 233, 0.07)');
            altBgGradient.addColorStop(1, 'rgba(15, 23, 42, 0.0)');

            const datasets = [{
                label: 'Altimetría Etapa (Fondo)',
                data: perfil.map(p => ({ x: p.x, y: p.y })),
                yAxisID: 'yAltitude',
                borderColor: 'rgba(56, 189, 248, 0.35)',
                backgroundColor: altBgGradient,
                borderWidth: 1.5,
                borderDash: [4, 4],
                fill: true,
                tension: 0.15,
                pointRadius: 0,
                pointHoverRadius: 0,
                order: 99
            }];

            DATA.ciclistas.forEach(c => {
                datasets.push({
                    label: c.stats.nombre,
                    data: c.by_dist.map(s => ({ x: s.d_km, y: s.pwr })),
                    yAxisID: 'yMetric',
                    borderColor: c.stats.color,
                    backgroundColor: 'transparent',
                    borderWidth: 2,
                    pointRadius: 0,
                    pointHoverRadius: 4,
                    tension: 0.35,
                    order: 1
                });
            });

            const numCiclistas = DATA.ciclistas.length;
            DATA.ciclistas.forEach(c => {
                const firstPt = c.by_dist[0] || { d_km: 0, pwr: 0 };
                datasets.push({
                    label: `${c.stats.nombre} (Punto)`,
                    data: [{ x: firstPt.d_km, y: firstPt.pwr }],
                    yAxisID: 'yMetric',
                    borderColor: '#ffffff',
                    backgroundColor: c.stats.color,
                    borderWidth: 2.5,
                    pointRadius: 6,
                    pointHoverRadius: 8,
                    showLine: false,
                    order: 0
                });
            });

            telemetryChart = new Chart(ctx, {
                type: 'line',
                data: { datasets: datasets },
                plugins: [segmentHighlightPlugin],
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    animation: false,
                    interaction: { mode: 'nearest', intersect: false },
                    scales: {
                        x: {
                            type: 'linear',
                            min: 0,
                            max: DATA.etapa.distancia_total_km,
                            grid: { color: 'rgba(124, 58, 237, 0.07)' },
                            ticks: { color: '#645a78',
                                font: { family: 'JetBrains Mono', size: 11 },
                                callback: (v) => `${v.toFixed(1)} km`
                            }
                        },
                        yMetric: {
                            position: 'left',
                            grid: { color: 'rgba(124, 58, 237, 0.07)' },
                            ticks: {
                                color: '#38bdf8',
                                font: { family: 'JetBrains Mono', size: 11 },
                                callback: (v) => `${v} W`
                            }
                        },
                        yAltitude: {
                            position: 'right',
                            grid: { display: false },
                            ticks: {
                                color: 'rgba(56, 189, 248, 0.4)',
                                font: { family: 'JetBrains Mono', size: 10 },
                                callback: (v) => `${Math.round(v)} m`
                            }
                        }
                    },
                    plugins: {
                        legend: {
                            labels: { color: '#645a78',
                                font: { family: 'Outfit', size: 12 },
                                filter: (item) => !item.text.includes('Fondo') && !item.text.includes('(Punto)')
                            }
                        },
                        tooltip: {
                            backgroundColor: 'rgba(15, 23, 42, 0.95)',
                            titleFont: { family: 'Outfit', size: 13, weight: 'bold' },
                            bodyFont: { family: 'JetBrains Mono', size: 12 },
                            borderColor: 'rgba(255,255,255,0.1)',
                            borderWidth: 1,
                            callbacks: {
                                title: (items) => `Km ${items[0].raw.x.toFixed(2)}`,
                                label: (item) => {
                                    if (item.dataset.label.includes('Fondo')) {
                                        return `⛰️ Altitud de Etapa: ${Math.round(item.raw.y)} m`;
                                    }
                                    if (item.dataset.label.includes('(Punto)')) {
                                        return null;
                                    }
                                    let unit = ' W';
                                    if (activeMetric === 'wkg') unit = ' W/kg';
                                    else if (activeMetric === 'tss') unit = ' TSS';
                                    else if (activeMetric === 'kj') unit = ' kJ';
                                    else if (activeMetric === 'kjkg') unit = ' kJ/kg';
                                    else if (activeMetric === 'kjkg_h') unit = ' kJ/kg/h';
                                    else if (activeMetric === 'hr') unit = ' bpm';
                                    return `${item.dataset.label}: ${item.raw.y}${unit}`;
                                }
                            }
                        }
                    }
                }
            });

            // Conectar selección arrastrando con el ratón directamente en el gráfico de telemetría
            attachChartDragSelection(() => telemetryChart, canvasEl);

            document.querySelectorAll('.telemetry-tabs .tab-btn').forEach(btn => {
                btn.addEventListener('click', (e) => {
                    document.querySelectorAll('.telemetry-tabs .tab-btn').forEach(b => b.classList.remove('active'));
                    e.currentTarget.classList.add('active');
                    activeMetric = e.currentTarget.dataset.metric;
                    updateTelemetryChartMetric();
                });
            });
        }

        function updateTelemetryChartMetric() {
            if (!telemetryChart) return;
            let unit = ' W';
            if (activeMetric === 'wkg') unit = ' W/kg';
            else if (activeMetric === 'tss') unit = ' TSS';
            else if (activeMetric === 'kj') unit = ' kJ';
            else if (activeMetric === 'kjkg') unit = ' kJ/kg';
            else if (activeMetric === 'kjkg_h') unit = ' kJ/kg/h';
            else if (activeMetric === 'hr') unit = ' bpm';

            if (telemetryChart.options && telemetryChart.options.scales && telemetryChart.options.scales.yMetric) {
                telemetryChart.options.scales.yMetric.ticks.callback = (v) => `${v}${unit}`;
            }

            const numCiclistas = DATA.ciclistas.length;
            DATA.ciclistas.forEach((c, idx) => {
                const ds = telemetryChart.data.datasets[idx + 1];
                if (!ds) return;
                const series = syncMode === 'dist' ? c.by_dist : c.by_time;
                ds.data = series.map(s => {
                    let val = s.pwr;
                    if (activeMetric === 'wkg') val = s.wkg;
                    else if (activeMetric === 'tss') val = s.tss;
                    else if (activeMetric === 'kj') val = s.kj;
                    else if (activeMetric === 'kjkg') val = s.kj_kg;
                    else if (activeMetric === 'kjkg_h') val = (s.kjkg_h !== undefined) ? s.kjkg_h : parseFloat((s.wkg * 3.6).toFixed(1));
                    else if (activeMetric === 'hr') val = s.hr;
                    return { x: s.d_km, y: val };
                });

                const pointDs = telemetryChart.data.datasets[1 + numCiclistas + idx];
                if (pointDs) {
                    const sampleIdx = Math.min(series.length - 1, currentStep);
                    const s = series[sampleIdx];
                    let val = s.pwr;
                    if (activeMetric === 'wkg') val = s.wkg;
                    else if (activeMetric === 'tss') val = s.tss;
                    else if (activeMetric === 'kj') val = s.kj;
                    else if (activeMetric === 'kjkg') val = s.kj_kg;
                    else if (activeMetric === 'kjkg_h') val = (s.kjkg_h !== undefined) ? s.kjkg_h : parseFloat((s.wkg * 3.6).toFixed(1));
                    else if (activeMetric === 'hr') val = s.hr;
                    pointDs.data = [{ x: s.d_km, y: val }];
                }
            });
            telemetryChart.update();
        }

        function syncToStep(step) {
            const currentRiderData = [];
            const numCiclistas = DATA.ciclistas.length;

            DATA.ciclistas.forEach((c, idx) => {
                const series = syncMode === 'dist' ? c.by_dist : c.by_time;
                const sampleIdx = Math.min(series.length - 1, step);
                const s = series[sampleIdx];
                currentRiderData.push({ idx: idx, sample: s, stats: c.stats });

                if (riderMarkers[idx] && s.lat && s.lon) {
                    riderMarkers[idx].setLatLng([s.lat, s.lon]);
                }

                const elPwr = document.getElementById(`hud-pwr-${idx}`);
                const elWkg = document.getElementById(`hud-wkg-${idx}`);
                const elTss = document.getElementById(`hud-tss-${idx}`);
                const elKj  = document.getElementById(`hud-kj-${idx}`);
                const elKjKgLbl = document.getElementById(`hud-kjkg-lbl-${idx}`);
                const elHr  = document.getElementById(`hud-hr-${idx}`);
                const elAlt = document.getElementById(`hud-alt-${idx}`);
                const elDist = document.getElementById(`hud-dist-${idx}`);

                if (elPwr) elPwr.innerText = `${s.pwr} W`;
                if (elWkg) elWkg.innerText = `${s.wkg}`;
                if (elTss) elTss.innerText = `${s.tss} TSS`;
                if (elKj)  elKj.innerText  = `${s.kj.toLocaleString()} kJ`;
                if (elKjKgLbl) {
                    const kjKgH = s.t_sec > 60 ? (s.kj_kg / (s.t_sec / 3600.0)).toFixed(1) : (s.wkg * 3.6).toFixed(1);
                    elKjKgLbl.innerHTML = `Trabajo <span style="color: #38bdf8; font-weight: 600;">(${s.kj_kg} kJ/kg • ${kjKgH}/h)</span>`;
                }
                if (elHr)  elHr.innerText  = `${s.hr > 0 ? s.hr : '--'}`;
                if (elAlt) elAlt.innerText = `${s.alt} m`;
                if (elDist) elDist.innerText = `${s.d_km} km`;

                if (elevationChart && elevationChart.data.datasets[idx + 1]) {
                    elevationChart.data.datasets[idx + 1].data = [{ x: s.d_km, y: s.alt }];
                }

                if (telemetryChart && telemetryChart.data.datasets[1 + numCiclistas + idx]) {
                    let val = s.pwr;
                    if (activeMetric === 'wkg') val = s.wkg;
                    else if (activeMetric === 'tss') val = s.tss;
                    else if (activeMetric === 'kj') val = s.kj;
                    else if (activeMetric === 'kjkg') val = s.kj_kg;
                    else if (activeMetric === 'kjkg_h') val = (s.kjkg_h !== undefined) ? s.kjkg_h : parseFloat((s.wkg * 3.6).toFixed(1));
                    else if (activeMetric === 'hr') val = s.hr;
                    telemetryChart.data.datasets[1 + numCiclistas + idx].data = [{ x: s.d_km, y: val }];
                }
            });

            let leaderName = '--';
            if (syncMode === 'dist') {
                currentRiderData.sort((a, b) => a.sample.t_sec - b.sample.t_sec);
                const minSec = currentRiderData[0]?.sample.t_sec || 0;
                leaderName = currentRiderData[0]?.stats.nombre || '--';

                currentRiderData.forEach(r => {
                    const gapSec = r.sample.t_sec - minSec;
                    const elGap = document.getElementById(`hud-gap-${r.idx}`);
                    if (elGap) {
                        if (gapSec <= 0) {
                            elGap.innerText = 'Líder';
                            elGap.className = 'rider-rank-badge leader';
                        } else {
                            const mm = String(Math.floor(gapSec / 60)).padStart(2, '0');
                            const ss = String(Math.floor(gapSec % 60)).padStart(2, '0');
                            elGap.innerText = `+${mm}:${ss}`;
                            elGap.className = 'rider-rank-badge';
                        }
                    }
                });

                const currentKm = currentRiderData[0]?.sample.d_km || 0;
                const elTimer = document.getElementById('lblTimer');
                if (elTimer) elTimer.innerText = `Km ${currentKm.toFixed(1)} / ${DATA.etapa.distancia_total_km} km`;
                currentLeaderX = currentKm;
                currentLeaderXLabel = `Km ${currentKm.toFixed(1)}`;
            } else {
                currentRiderData.sort((a, b) => b.sample.d_km - a.sample.d_km);
                const maxDist = currentRiderData[0]?.sample.d_km || 0;
                leaderName = currentRiderData[0]?.stats.nombre || '--';

                currentRiderData.forEach(r => {
                    const gapDist = maxDist - r.sample.d_km;
                    const elGap = document.getElementById(`hud-gap-${r.idx}`);
                    if (elGap) {
                        if (gapDist <= 0.05) {
                            elGap.innerText = 'Líder';
                            elGap.className = 'rider-rank-badge leader';
                        } else {
                            elGap.innerText = `-${gapDist.toFixed(2)} km`;
                            elGap.className = 'rider-rank-badge';
                        }
                    }
                });

                const currentSec = currentRiderData[0]?.sample.t_sec || 0;
                const hh = String(Math.floor(currentSec / 3600)).padStart(2, '0');
                const mm = String(Math.floor((currentSec % 3600) / 60)).padStart(2, '0');
                const ss = String(Math.floor(currentSec % 60)).padStart(2, '0');
                const timerStr = `${hh}:${mm}:${ss}`;
                const elTimer = document.getElementById('lblTimer');
                if (elTimer) elTimer.innerText = timerStr;
                currentLeaderX = maxDist;
                currentLeaderXLabel = `${maxDist.toFixed(1)} km (${timerStr})`;
            }

            currentLeaderName = leaderName;
            const elLider = document.getElementById('lblLider');
            if (elLider) elLider.innerText = leaderName;

            // Actualizar iconos del mapa: resaltar líder y actualizar popup dinámico
            currentRiderData.forEach(r => {
                const marker = riderMarkers[r.idx];
                if (!marker) return;
                const s_stat = marker._riderStats || r.stats;
                const initials = marker._riderInitials || s_stat.nombre.split(' ').map(n => n[0]).join('').substring(0, 2).toUpperCase();
                const isLeader = (r.stats.nombre === leaderName);

                // Reconstruir icono con/sin clase 'leader'
                const iconSize = isLeader ? [42, 42] : [32, 32];
                const iconAnchor = isLeader ? [21, 21] : [16, 16];
                const newIcon = L.divIcon({
                    className: 'rider-marker-div',
                    html: `<div class="rider-map-marker${isLeader ? ' leader' : ''}" style="--m-color: ${s_stat.color}; --m-glow: ${s_stat.glow};">${initials}</div>`,
                    iconSize: iconSize,
                    iconAnchor: iconAnchor
                });
                marker.setIcon(newIcon);

                // Actualizar popup con métricas del step actual
                let gapTxt = '';
                if (syncMode === 'dist') {
                    const minSecAll = Math.min(...currentRiderData.map(x => x.sample.t_sec));
                    const gapSec = r.sample.t_sec - minSecAll;
                    gapTxt = gapSec <= 0 ? '<span style="color:#fbbf24;font-weight:700;">👑 Líder</span>'
                        : `<span style="color:#f87171;">+${String(Math.floor(gapSec/60)).padStart(2,'0')}:${String(Math.floor(gapSec%60)).padStart(2,'0')}</span>`;
                } else {
                    const maxDistAll = Math.max(...currentRiderData.map(x => x.sample.d_km));
                    const gapKm = maxDistAll - r.sample.d_km;
                    gapTxt = gapKm <= 0.05 ? '<span style="color:#fbbf24;font-weight:700;">👑 Líder</span>'
                        : `<span style="color:#f87171;">-${gapKm.toFixed(2)} km</span>`;
                }
                const hh = String(Math.floor(r.sample.t_sec / 3600)).padStart(2, '0');
                const mm = String(Math.floor((r.sample.t_sec % 3600) / 60)).padStart(2, '0');
                const ss = String(Math.floor(r.sample.t_sec % 60)).padStart(2, '0');
                const popupHtml = `
                    <div style="font-family:'Outfit',sans-serif;min-width:160px;">
                        <div style="font-size:13px;font-weight:700;color:${s_stat.color};margin-bottom:4px;">🚴 ${r.stats.nombre}</div>
                        <div style="display:grid;grid-template-columns:auto 1fr;gap:2px 8px;font-size:11px;">
                            <span style="color:#94a3b8;">📍 Pos.</span><span style="font-weight:600;">${r.sample.d_km.toFixed(1)} km</span>
                            <span style="color:#94a3b8;">⏱ Tiempo</span><span style="font-weight:600;">${hh}:${mm}:${ss}</span>
                            <span style="color:#94a3b8;">⚡ Potencia</span><span style="font-weight:600;">${r.sample.pwr} W (${r.sample.wkg} W/kg)</span>
                            <span style="color:#94a3b8;">❤️ FC</span><span style="font-weight:600;">${r.sample.hr > 0 ? r.sample.hr + ' bpm' : '--'}</span>
                            <span style="color:#94a3b8;">⛰ Alt.</span><span style="font-weight:600;">${r.sample.alt} m</span>
                            <span style="color:#94a3b8;">Gap</span><span>${gapTxt}</span>
                        </div>
                    </div>`;
                marker.setPopupContent(popupHtml);
            });

            if (elevationChart) elevationChart.update('none');
            if (telemetryChart) telemetryChart.update('none');
        }

        // 8. Control de Reproducción y Slider
        const slider = document.getElementById('timelineSlider');
        if (slider) {
            slider.addEventListener('input', (e) => {
                currentStep = parseInt(e.target.value);
                syncToStep(currentStep);
            });
        }

        function togglePlay() {
            isPlaying = !isPlaying;
            const btn = document.getElementById('btnPlayPause');
            const icon = document.getElementById('iconPlay');
            const txt = document.getElementById('txtPlay');

            if (isPlaying) {
                if (btn) btn.classList.add('playing');
                if (txt) txt.innerText = 'Pausar';
                if (icon) icon.setAttribute('data-lucide', 'pause');
                if (typeof lucide !== 'undefined' && lucide.createIcons) lucide.createIcons();

                playInterval = setInterval(() => {
                    currentStep += (1 * playSpeed);
                    if (currentStep >= 999) {
                        currentStep = 999;
                        togglePlay();
                    }
                    if (slider) slider.value = currentStep;
                    syncToStep(currentStep);
                }, 60);
            } else {
                if (btn) btn.classList.remove('playing');
                if (txt) txt.innerText = 'Reanudar';
                if (icon) icon.setAttribute('data-lucide', 'play');
                if (typeof lucide !== 'undefined' && lucide.createIcons) lucide.createIcons();
                if (playInterval) clearInterval(playInterval);
            }
        }

        const btnPlay = document.getElementById('btnPlayPause');
        if (btnPlay) btnPlay.addEventListener('click', togglePlay);

        const btnReset = document.getElementById('btnReset');
        if (btnReset) {
            btnReset.addEventListener('click', () => {
                if (isPlaying) togglePlay();
                currentStep = 0;
                if (slider) slider.value = 0;
                syncToStep(0);
            });
        }

        // Selector de Modo (Posición vs Tiempo)
        const btnModeDist = document.getElementById('btnModeDist');
        if (btnModeDist) {
            btnModeDist.addEventListener('click', () => {
                syncMode = 'dist';
                btnModeDist.classList.add('active');
                const btnTime = document.getElementById('btnModeTime');
                if (btnTime) btnTime.classList.remove('active');
                updateTelemetryChartMetric();
                syncToStep(currentStep);
            });
        }

        const btnModeTime = document.getElementById('btnModeTime');
        if (btnModeTime) {
            btnModeTime.addEventListener('click', () => {
                syncMode = 'time';
                btnModeTime.classList.add('active');
                const btnDist = document.getElementById('btnModeDist');
                if (btnDist) btnDist.classList.remove('active');
                updateTelemetryChartMetric();
                syncToStep(currentStep);
            });
        }

        // Selector de Velocidad
        document.querySelectorAll('.speed-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                document.querySelectorAll('.speed-btn').forEach(b => b.classList.remove('active'));
                e.currentTarget.classList.add('active');
                playSpeed = parseInt(e.currentTarget.dataset.speed) || 1;
            });
        });

        // 9. Mostrar / Ocultar Mapa y Perfil
        const btnToggleMapProfile = document.getElementById('btnToggleMapProfile');
        const vizGridSection = document.getElementById('vizGridSection');
        const iconToggleMapProfile = document.getElementById('iconToggleMapProfile');
        const txtToggleMapProfile = document.getElementById('txtToggleMapProfile');

        function toggleMapProfile(forceState) {
            if (!vizGridSection) return;
            const isCurrentlyHidden = vizGridSection.classList.contains('hidden');
            const shouldShow = forceState !== undefined ? forceState : isCurrentlyHidden;

            if (shouldShow) {
                vizGridSection.classList.remove('hidden');
                if (btnToggleMapProfile) btnToggleMapProfile.classList.add('active');
                if (txtToggleMapProfile) txtToggleMapProfile.innerText = 'Ocultar Mapa y Perfil';
                if (iconToggleMapProfile) iconToggleMapProfile.setAttribute('data-lucide', 'eye-off');
                if (typeof lucide !== 'undefined' && lucide.createIcons) lucide.createIcons();

                setTimeout(() => {
                    if (map) {
                        map.invalidateSize();
                        if (DATA.etapa.bounds) map.fitBounds(DATA.etapa.bounds, { padding: [30, 30] });
                    }
                    if (elevationChart) {
                        elevationChart.resize();
                        elevationChart.update('none');
                    }
                }, 60);
            } else {
                vizGridSection.classList.add('hidden');
                if (btnToggleMapProfile) btnToggleMapProfile.classList.remove('active');
                if (txtToggleMapProfile) txtToggleMapProfile.innerText = 'Mostrar Mapa y Perfil';
                if (iconToggleMapProfile) iconToggleMapProfile.setAttribute('data-lucide', 'eye');
                if (typeof lucide !== 'undefined' && lucide.createIcons) lucide.createIcons();
            }
        }

        if (btnToggleMapProfile) {
            btnToggleMapProfile.addEventListener('click', () => toggleMapProfile());
        }

        // =========================================================
        // 10. Módulo de Salud, Fisiología y Carga de Entrenamiento
        // =========================================================
        let healthLoadChart = null;
        let activeHealthMetric = 'fitness_freshness';
        let selectedHealthRiderId = 'all';

        function initHealthSection() {
            renderTeamHealthKPIs();
            renderRiderHealthCards();
            populateHealthRiderSelect();
            initHealthLoadChart();
            setupHealthEventListeners();
        }

        function renderTeamHealthKPIs() {
            const container = document.getElementById('teamKpisContainer');
            if (!container) return;
            const eq = DATA.equipo_salud_carga || {};

            const ctlStr = eq.ctl_medio !== null && eq.ctl_medio !== undefined ? `${eq.ctl_medio}` : '--';
            const atlStr = eq.atl_medio !== null && eq.atl_medio !== undefined ? `${eq.atl_medio}` : '--';
            const tsbVal = eq.tsb_medio;
            let tsbStr = '--';
            let tsbColor = '#94a3b8';
            if (tsbVal !== null && tsbVal !== undefined) {
                tsbStr = tsbVal > 0 ? `+${tsbVal}` : `${tsbVal}`;
                if (tsbVal >= 5) tsbColor = '#10b981';
                else if (tsbVal >= -10) tsbColor = '#38bdf8';
                else if (tsbVal >= -30) tsbColor = '#f59e0b';
                else tsbColor = '#ef4444';
            }

            const hrvStr = eq.hrv_medio !== null && eq.hrv_medio !== undefined ? `${eq.hrv_medio} ms` : '--';
            const rhrStr = eq.rhr_medio !== null && eq.rhr_medio !== undefined ? `${eq.rhr_medio} bpm` : '--';
            const sleepStr = eq.sleep_medio !== null && eq.sleep_medio !== undefined ? `${eq.sleep_medio} h` : '--';

            container.innerHTML = `
                <div class="team-kpi-card">
                    <div class="team-kpi-icon" style="background: rgba(56, 189, 248, 0.15); color: #38bdf8;">
                        <i data-lucide="shield"></i>
                    </div>
                    <div class="team-kpi-info">
                        <div class="team-kpi-val" style="color: #38bdf8;">${ctlStr}</div>
                        <div class="team-kpi-lbl">CTL Medio</div>
                        <div class="team-kpi-sub">Fitness 42 días</div>
                    </div>
                </div>
                <div class="team-kpi-card">
                    <div class="team-kpi-icon" style="background: rgba(236, 72, 153, 0.15); color: #ec4899;">
                        <i data-lucide="flame"></i>
                    </div>
                    <div class="team-kpi-info">
                        <div class="team-kpi-val" style="color: #ec4899;">${atlStr}</div>
                        <div class="team-kpi-lbl">ATL Medio</div>
                        <div class="team-kpi-sub">Fatiga 7 días</div>
                    </div>
                </div>
                <div class="team-kpi-card">
                    <div class="team-kpi-icon" style="background: rgba(16, 185, 129, 0.15); color: ${tsbColor};">
                        <i data-lucide="scale"></i>
                    </div>
                    <div class="team-kpi-info">
                        <div class="team-kpi-val" style="color: ${tsbColor};">${tsbStr}</div>
                        <div class="team-kpi-lbl">TSB Balance</div>
                        <div class="team-kpi-sub">Estado de Forma</div>
                    </div>
                </div>
                <div class="team-kpi-card">
                    <div class="team-kpi-icon" style="background: rgba(52, 211, 153, 0.15); color: #34d399;">
                        <i data-lucide="heart-pulse"></i>
                    </div>
                    <div class="team-kpi-info">
                        <div class="team-kpi-val" style="color: #34d399;">${hrvStr}</div>
                        <div class="team-kpi-lbl">RMSSD Medio</div>
                        <div class="team-kpi-sub">Variabilidad HRV</div>
                    </div>
                </div>
                <div class="team-kpi-card">
                    <div class="team-kpi-icon" style="background: rgba(245, 158, 11, 0.15); color: #fbbf24;">
                        <i data-lucide="heart"></i>
                    </div>
                    <div class="team-kpi-info">
                        <div class="team-kpi-val" style="color: #fbbf24;">${rhrStr}</div>
                        <div class="team-kpi-lbl">FC Reposo</div>
                        <div class="team-kpi-sub">Pulso Matutino</div>
                    </div>
                </div>
                <div class="team-kpi-card">
                    <div class="team-kpi-icon" style="background: rgba(168, 85, 247, 0.15); color: #c084fc;">
                        <i data-lucide="moon"></i>
                    </div>
                    <div class="team-kpi-info">
                        <div class="team-kpi-val" style="color: #c084fc;">${sleepStr}</div>
                        <div class="team-kpi-lbl">Sueño Medio</div>
                        <div class="team-kpi-sub">Descanso Nocturno</div>
                    </div>
                </div>
            `;
            if (typeof lucide !== 'undefined' && lucide.createIcons) lucide.createIcons();
        }

        function renderRiderHealthCards() {
            const container = document.getElementById('healthCardsContainer');
            if (!container) return;
            container.innerHTML = '';

            DATA.ciclistas.forEach((c, idx) => {
                const s = c.stats;
                const w = c.wellness_load || {};
                const st = w.status || { label: 'Sin datos', tag: 'badge-gray', color: '#94a3b8' };
                const initials = s.nombre.split(' ').map(n => n[0]).join('').substring(0, 2);

                const ctlVal = w.ctl !== null && w.ctl !== undefined ? `${w.ctl}` : '--';
                const atlVal = w.atl !== null && w.atl !== undefined ? `${w.atl}` : '--';
                const tsbVal = w.tsb !== null && w.tsb !== undefined ? (w.tsb > 0 ? `+${w.tsb}` : `${w.tsb}`) : '--';
                const rampVal = w.ramp_rate !== null && w.ramp_rate !== undefined ? (w.ramp_rate > 0 ? `+${w.ramp_rate}` : `${w.ramp_rate}`) : '--';

                const hrvVal = w.hrv_rmssd !== null && w.hrv_rmssd !== undefined ? `${w.hrv_rmssd} ms` : '--';
                const rhrVal = w.resting_hr !== null && w.resting_hr !== undefined ? `${w.resting_hr} bpm` : '--';
                const weightVal = w.weight !== null && w.weight !== undefined ? `${w.weight} kg` : `${s.peso_kg} kg`;
                const sleepVal = w.sleep_hours !== null && w.sleep_hours !== undefined ? `${w.sleep_hours} h` : '--';

                const card = document.createElement('div');
                card.className = 'health-card';
                card.style.setProperty('--rider-color', s.color);
                card.innerHTML = `
                    <div class="health-card-header">
                        <div class="health-rider-info">
                            <div class="health-avatar">${initials}</div>
                            <div>
                                <div class="health-rider-name">${s.nombre}</div>
                            </div>
                        </div>
                        <div class="health-form-pill ${st.tag}">
                            <i data-lucide="activity" style="width: 12px; height: 12px;"></i> ${st.label} (${tsbVal} TSB)
                        </div>
                    </div>
                    
                    <div class="health-metrics-row">
                        <div class="health-metric-box">
                            <div class="health-box-val" style="color: #38bdf8;">${ctlVal}</div>
                            <div class="health-box-lbl">CTL (Fitness)</div>
                            <div class="health-box-sub">42 días</div>
                        </div>
                        <div class="health-metric-box">
                            <div class="health-box-val" style="color: #ec4899;">${atlVal}</div>
                            <div class="health-box-lbl">ATL (Fatiga)</div>
                            <div class="health-box-sub">7 días</div>
                        </div>
                        <div class="health-metric-box">
                            <div class="health-box-val" style="color: ${st.color};">${tsbVal}</div>
                            <div class="health-box-lbl">TSB (Forma)</div>
                            <div class="health-box-sub">Balance</div>
                        </div>
                        <div class="health-metric-box">
                            <div class="health-box-val" style="color: #a855f7;">${rampVal}</div>
                            <div class="health-box-lbl">Ramp Rate</div>
                            <div class="health-box-sub">pts/sem</div>
                        </div>
                    </div>

                    <div class="health-biometrics-row">
                        <div class="health-bio-item">
                            <div class="health-bio-val" style="color: #34d399;">${hrvVal}</div>
                            <div class="health-bio-lbl">RMSSD (HRV)</div>
                            <div class="health-box-sub" style="font-size:0.65rem; color:var(--text-muted);">${w.hrv_media_7d ? '7d: ' + w.hrv_media_7d + ' ms' : ''}</div>
                        </div>
                        <div class="health-bio-item">
                            <div class="health-bio-val" style="color: #fbbf24;">${rhrVal}</div>
                            <div class="health-bio-lbl">FC Reposo</div>
                            <div class="health-box-sub" style="font-size:0.65rem; color:var(--text-muted);">${w.resting_hr_media_7d ? '7d: ' + w.resting_hr_media_7d + ' bpm' : ''}</div>
                        </div>
                        <div class="health-bio-item">
                            <div class="health-bio-val" style="color: #38bdf8;">${weightVal}</div>
                            <div class="health-bio-lbl">Peso</div>
                        </div>
                        <div class="health-bio-item">
                            <div class="health-bio-val" style="color: #c084fc;">${sleepVal}</div>
                            <div class="health-bio-lbl">Sueño</div>
                            <div class="health-box-sub" style="font-size:0.65rem; color:var(--text-muted);">${w.sleep_score ? 'Score: ' + w.sleep_score : ''}</div>
                        </div>
                    </div>
                `;
                container.appendChild(card);
            });
            if (typeof lucide !== 'undefined' && lucide.createIcons) lucide.createIcons();
        }

        function populateHealthRiderSelect() {
            const select = document.getElementById('healthRiderSelect');
            if (!select) return;
            select.innerHTML = '<option value="all">Todo el Equipo (Comparativa)</option>';
            DATA.ciclistas.forEach((c, idx) => {
                const opt = document.createElement('option');
                opt.value = idx;
                opt.textContent = c.stats.nombre;
                select.appendChild(opt);
            });
        }

        const tsbHealthBackgroundPlugin = {
            id: 'tsbHealthBackground',
            beforeDraw: (chart) => {
                if (activeHealthMetric !== 'tsb' && activeHealthMetric !== 'fitness_freshness') return;
                const { ctx, chartArea, scales } = chart;
                if (!chartArea) return;
                
                const targetScale = (activeHealthMetric === 'fitness_freshness' && scales.y2 && scales.y2.display) ? scales.y2 : scales.y;
                if (!targetScale) return;

                const top = chartArea.top;
                const bottom = chartArea.bottom;
                const left = chartArea.left;
                const width = chartArea.width;

                ctx.save();

                const zones = [
                    { min: 15, max: 100, color: 'rgba(16, 185, 129, 0.12)', text: 'Muy Fresco (> +15)', textColor: '#10b981' },
                    { min: 5, max: 15, color: 'rgba(56, 189, 248, 0.12)', text: 'Fresco / Competición (+5 a +15)', textColor: '#38bdf8' },
                    { min: -10, max: 5, color: 'rgba(129, 140, 248, 0.08)', text: 'Neutro / Balance (-10 a +5)', textColor: '#818cf8' },
                    { min: -30, max: -10, color: 'rgba(245, 158, 11, 0.12)', text: 'Fatiga Productiva (-30 a -10)', textColor: '#f59e0b' },
                    { min: -100, max: -30, color: 'rgba(239, 68, 68, 0.12)', text: 'Sobrecarga / Riesgo (< -30)', textColor: '#ef4444' }
                ];

                zones.forEach(z => {
                    const yTop = Math.max(top, Math.min(bottom, targetScale.getPixelForValue(z.max)));
                    const yBottom = Math.max(top, Math.min(bottom, targetScale.getPixelForValue(z.min)));
                    const h = yBottom - yTop;
                    if (h > 0) {
                        ctx.fillStyle = z.color;
                        ctx.fillRect(left, yTop, width, h);

                        if (h >= 14) {
                            ctx.fillStyle = z.textColor;
                            ctx.globalAlpha = 0.70;
                            ctx.font = '600 10px "Outfit", sans-serif';
                            ctx.textAlign = 'right';
                            ctx.fillText(z.text, left + width - 12, yTop + Math.min(14, h / 2 + 4));
                            ctx.globalAlpha = 1.0;
                        }
                    }
                });

                const yZero = targetScale.getPixelForValue(0);
                if (yZero >= top && yZero <= bottom) {
                    ctx.strokeStyle = 'rgba(148, 163, 184, 0.45)';
                    ctx.lineWidth = 1;
                    ctx.setLineDash([4, 4]);
                    ctx.beginPath();
                    ctx.moveTo(left, yZero);
                    ctx.lineTo(left + width, yZero);
                    ctx.stroke();
                    ctx.setLineDash([]);
                }

                ctx.restore();
            }
        };

        function initHealthLoadChart() {
            const ctx = document.getElementById('healthLoadChart');
            if (!ctx) return;

            healthLoadChart = new Chart(ctx.getContext('2d'), {
                type: 'line',
                data: { labels: [], datasets: [] },
                plugins: [tsbHealthBackgroundPlugin],
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    interaction: { mode: 'index', intersect: false },
                    scales: {
                        x: {
                            grid: { color: 'rgba(124, 58, 237, 0.07)' },
                            ticks: { color: '#645a78', font: { family: 'JetBrains Mono', size: 11 } }
                        },
                        y: {
                            position: 'left',
                            grid: { color: 'rgba(124, 58, 237, 0.07)' },
                            ticks: { color: '#645a78', font: { family: 'JetBrains Mono', size: 11 } }
                        },
                        y2: {
                            position: 'right',
                            display: false,
                            grid: { drawOnChartArea: false },
                            ticks: { color: '#645a78', font: { family: 'JetBrains Mono', size: 11 } }
                        }
                    },
                    plugins: {
                        legend: {
                            display: true,
                            position: 'top',
                            labels: { color: '#645a78',
                                font: { family: 'Outfit', size: 12, weight: '600' },
                                usePointStyle: true,
                                padding: 15
                            }
                        },
                        tooltip: {
                            backgroundColor: 'rgba(15, 23, 42, 0.95)',
                            titleFont: { family: 'Outfit', size: 13, weight: 'bold' },
                            bodyFont: { family: 'JetBrains Mono', size: 12 },
                            borderColor: 'rgba(255,255,255,0.1)',
                            borderWidth: 1,
                            callbacks: {
                                label: function(context) {
                                    const val = context.raw;
                                    if (val === null || val === undefined) return null;
                                    const label = context.dataset.label || '';
                                    let unit = '';
                                    if (label.includes('RMSSD') || label.includes('HRV')) unit = ' ms';
                                    else if (label.includes('FC Reposo') || label.includes('bpm')) unit = ' bpm';
                                    else if (label.includes('Peso') || label.includes('kg')) unit = ' kg';
                                    else if (label.includes('Sueño') || label.includes('Horas')) unit = ' h';
                                    else if (label.includes('CTL')) unit = ' CTL';
                                    else if (label.includes('ATL')) unit = ' ATL';
                                    else if (label.includes('TSB')) unit = ' TSB';
                                    return ` ${label}: ${val}${unit}`;
                                }
                            }
                        }
                    }
                }
            });

            updateHealthLoadChart(activeHealthMetric, selectedHealthRiderId);
        }

        function updateHealthLoadChart(metric, riderSelection) {
            if (!healthLoadChart) return;

            delete healthLoadChart.options.scales.y2.min;
            delete healthLoadChart.options.scales.y2.max;

            const fechasSet = new Set();
            DATA.ciclistas.forEach(c => {
                const hist = c.wellness_load?.historial || [];
                hist.forEach(h => { if (h.fecha) fechasSet.add(h.fecha); });
            });
            const fechas = Array.from(fechasSet).sort();

            healthLoadChart.data.labels = fechas.map(f => f.substring(5)); // 'MM-DD'
            const datasets = [];

            if (riderSelection !== 'all') {
                const idx = parseInt(riderSelection);
                const c = DATA.ciclistas[idx];
                if (c) {
                    const histMap = new Map();
                    (c.wellness_load?.historial || []).forEach(h => histMap.set(h.fecha, h));

                    if (metric === 'fitness_freshness') {
                        healthLoadChart.options.scales.y2.display = true;
                        healthLoadChart.options.scales.y2.min = -45;
                        healthLoadChart.options.scales.y2.max = 35;
                        healthLoadChart.options.scales.y.ticks.callback = (v) => `${v}`;
                        healthLoadChart.options.scales.y2.ticks.callback = (v) => `${v} TSB`;

                        datasets.push({
                            label: `${c.stats.nombre} - CTL (Fitness)`,
                            data: fechas.map(f => histMap.get(f)?.ctl ?? null),
                            borderColor: '#38bdf8',
                            backgroundColor: 'rgba(56, 189, 248, 0.1)',
                            borderWidth: 3,
                            pointRadius: 2,
                            yAxisID: 'y',
                            tension: 0.25
                        });
                        datasets.push({
                            label: `${c.stats.nombre} - ATL (Fatiga)`,
                            data: fechas.map(f => histMap.get(f)?.atl ?? null),
                            borderColor: '#ec4899',
                            backgroundColor: 'rgba(236, 72, 153, 0.1)',
                            borderWidth: 2.5,
                            pointRadius: 2,
                            yAxisID: 'y',
                            tension: 0.25
                        });
                        datasets.push({
                            label: `${c.stats.nombre} - TSB (Forma)`,
                            data: fechas.map(f => histMap.get(f)?.tsb ?? null),
                            borderColor: '#10b981',
                            backgroundColor: 'rgba(16, 185, 129, 0.15)',
                            fill: true,
                            borderWidth: 2,
                            pointRadius: 3,
                            yAxisID: 'y2',
                            tension: 0.2
                        });
                    } else if (metric === 'atl') {
                        healthLoadChart.options.scales.y2.display = false;
                        healthLoadChart.options.scales.y.ticks.callback = (v) => `${v} ATL`;

                        datasets.push({
                            label: `${c.stats.nombre} - ATL (Fatiga 7d)`,
                            data: fechas.map(f => histMap.get(f)?.atl ?? null),
                            borderColor: '#ec4899',
                            backgroundColor: 'rgba(236, 72, 153, 0.2)',
                            fill: true,
                            borderWidth: 3,
                            pointRadius: 3,
                            tension: 0.25
                        });
                    } else if (metric === 'ctl') {
                        healthLoadChart.options.scales.y2.display = false;
                        healthLoadChart.options.scales.y.ticks.callback = (v) => `${v} CTL`;

                        datasets.push({
                            label: `${c.stats.nombre} - CTL (Fitness 42d)`,
                            data: fechas.map(f => histMap.get(f)?.ctl ?? null),
                            borderColor: '#38bdf8',
                            backgroundColor: 'rgba(56, 189, 248, 0.2)',
                            fill: true,
                            borderWidth: 3,
                            pointRadius: 3,
                            tension: 0.25
                        });
                    } else if (metric === 'tsb') {
                        healthLoadChart.options.scales.y2.display = false;
                        healthLoadChart.options.scales.y.ticks.callback = (v) => `${v} TSB`;

                        datasets.push({
                            label: `${c.stats.nombre} - TSB (Forma / Balance)`,
                            data: fechas.map(f => histMap.get(f)?.tsb ?? null),
                            borderColor: '#10b981',
                            backgroundColor: 'rgba(16, 185, 129, 0.2)',
                            fill: true,
                            borderWidth: 3,
                            pointRadius: 3,
                            tension: 0.25
                        });
                    } else if (metric === 'hrv_rhr') {
                        healthLoadChart.options.scales.y2.display = true;
                        healthLoadChart.options.scales.y.ticks.callback = (v) => `${v} ms`;
                        healthLoadChart.options.scales.y2.ticks.callback = (v) => `${v} bpm`;

                        datasets.push({
                            label: `${c.stats.nombre} - RMSSD (ms)`,
                            data: fechas.map(f => histMap.get(f)?.hrv ?? null),
                            borderColor: '#34d399',
                            backgroundColor: 'rgba(52, 211, 153, 0.15)',
                            borderWidth: 2.5,
                            pointRadius: 3,
                            yAxisID: 'y',
                            tension: 0.2
                        });
                        datasets.push({
                            label: `${c.stats.nombre} - FC Reposo (bpm)`,
                            data: fechas.map(f => histMap.get(f)?.resting_hr ?? null),
                            borderColor: '#fbbf24',
                            backgroundColor: 'rgba(251, 191, 36, 0.15)',
                            borderWidth: 2.5,
                            pointRadius: 3,
                            yAxisID: 'y2',
                            tension: 0.2
                        });
                    } else if (metric === 'rhr') {
                        healthLoadChart.options.scales.y2.display = false;
                        healthLoadChart.options.scales.y.ticks.callback = (v) => `${v} bpm`;

                        datasets.push({
                            label: `${c.stats.nombre} - FC Reposo (bpm)`,
                            data: fechas.map(f => histMap.get(f)?.resting_hr ?? null),
                            borderColor: '#fbbf24',
                            backgroundColor: 'rgba(251, 191, 36, 0.2)',
                            fill: true,
                            borderWidth: 3,
                            pointRadius: 3,
                            tension: 0.2
                        });
                    } else if (metric === 'weight_sleep') {
                        healthLoadChart.options.scales.y2.display = true;
                        healthLoadChart.options.scales.y.ticks.callback = (v) => `${v} kg`;
                        healthLoadChart.options.scales.y2.ticks.callback = (v) => `${v} h`;

                        datasets.push({
                            label: `${c.stats.nombre} - Peso (kg)`,
                            data: fechas.map(f => histMap.get(f)?.weight ?? null),
                            borderColor: '#38bdf8',
                            backgroundColor: 'rgba(56, 189, 248, 0.15)',
                            borderWidth: 2.5,
                            pointRadius: 3,
                            yAxisID: 'y',
                            tension: 0.2
                        });
                        datasets.push({
                            label: `${c.stats.nombre} - Horas de Sueño`,
                            data: fechas.map(f => histMap.get(f)?.sleep_hours ?? null),
                            borderColor: '#c084fc',
                            backgroundColor: 'rgba(192, 132, 252, 0.2)',
                            borderWidth: 2,
                            pointRadius: 3,
                            yAxisID: 'y2',
                            tension: 0.2
                        });
                    }
                }
            } else {
                if (metric === 'fitness_freshness') {
                    healthLoadChart.options.scales.y2.display = true;
                    healthLoadChart.options.scales.y2.min = -45;
                    healthLoadChart.options.scales.y2.max = 35;
                    healthLoadChart.options.scales.y.ticks.callback = (v) => `${v}`;
                    healthLoadChart.options.scales.y2.ticks.callback = (v) => `${v} TSB`;
                    DATA.ciclistas.forEach(c => {
                        const histMap = new Map();
                        (c.wellness_load?.historial || []).forEach(h => histMap.set(h.fecha, h));

                        datasets.push({
                            label: `${c.stats.nombre} (CTL)`,
                            data: fechas.map(f => histMap.get(f)?.ctl ?? null),
                            borderColor: c.stats.color,
                            backgroundColor: c.stats.color,
                            borderWidth: 2.5,
                            pointRadius: 2,
                            yAxisID: 'y',
                            tension: 0.2
                        });
                        datasets.push({
                            label: `${c.stats.nombre} (ATL)`,
                            data: fechas.map(f => histMap.get(f)?.atl ?? null),
                            borderColor: c.stats.color,
                            borderDash: [5, 4],
                            backgroundColor: 'transparent',
                            borderWidth: 1.8,
                            pointRadius: 1.5,
                            yAxisID: 'y',
                            tension: 0.2
                        });
                    });
                } else if (metric === 'atl') {
                    healthLoadChart.options.scales.y2.display = false;
                    healthLoadChart.options.scales.y.ticks.callback = (v) => `${v} ATL`;
                    DATA.ciclistas.forEach(c => {
                        const histMap = new Map();
                        (c.wellness_load?.historial || []).forEach(h => histMap.set(h.fecha, h));
                        datasets.push({
                            label: `${c.stats.nombre} (ATL)`,
                            data: fechas.map(f => histMap.get(f)?.atl ?? null),
                            borderColor: c.stats.color,
                            backgroundColor: c.stats.color,
                            borderWidth: 2.2,
                            pointRadius: 2.5,
                            tension: 0.2
                        });
                    });
                } else if (metric === 'ctl') {
                    healthLoadChart.options.scales.y2.display = false;
                    healthLoadChart.options.scales.y.ticks.callback = (v) => `${v} CTL`;
                    DATA.ciclistas.forEach(c => {
                        const histMap = new Map();
                        (c.wellness_load?.historial || []).forEach(h => histMap.set(h.fecha, h));
                        datasets.push({
                            label: `${c.stats.nombre} (CTL)`,
                            data: fechas.map(f => histMap.get(f)?.ctl ?? null),
                            borderColor: c.stats.color,
                            backgroundColor: c.stats.color,
                            borderWidth: 2.2,
                            pointRadius: 2.5,
                            tension: 0.2
                        });
                    });
                } else if (metric === 'tsb') {
                    healthLoadChart.options.scales.y2.display = false;
                    healthLoadChart.options.scales.y.ticks.callback = (v) => `${v} TSB`;
                    DATA.ciclistas.forEach(c => {
                        const histMap = new Map();
                        (c.wellness_load?.historial || []).forEach(h => histMap.set(h.fecha, h));
                        datasets.push({
                            label: `${c.stats.nombre} (TSB)`,
                            data: fechas.map(f => histMap.get(f)?.tsb ?? null),
                            borderColor: c.stats.color,
                            backgroundColor: c.stats.color,
                            borderWidth: 2.2,
                            pointRadius: 2.5,
                            tension: 0.2
                        });
                    });
                } else if (metric === 'hrv_rhr') {
                    healthLoadChart.options.scales.y2.display = true;
                    healthLoadChart.options.scales.y.ticks.callback = (v) => `${v} ms`;
                    healthLoadChart.options.scales.y2.ticks.callback = (v) => `${v} bpm`;
                    DATA.ciclistas.forEach(c => {
                        const histMap = new Map();
                        (c.wellness_load?.historial || []).forEach(h => histMap.set(h.fecha, h));
                        // RMSSD (HRV) - Línea continua en eje izquierdo (ms)
                        datasets.push({
                            label: `${c.stats.nombre} (RMSSD)`,
                            data: fechas.map(f => histMap.get(f)?.hrv ?? null),
                            borderColor: c.stats.color,
                            backgroundColor: c.stats.color,
                            borderWidth: 2.2,
                            pointRadius: 2.5,
                            yAxisID: 'y',
                            tension: 0.2
                        });
                        // FC Reposo - Línea punteada en eje derecho (bpm)
                        datasets.push({
                            label: `${c.stats.nombre} (FC Reposo)`,
                            data: fechas.map(f => histMap.get(f)?.resting_hr ?? null),
                            borderColor: c.stats.color,
                            borderDash: [5, 4],
                            backgroundColor: 'transparent',
                            borderWidth: 1.8,
                            pointRadius: 2,
                            yAxisID: 'y2',
                            tension: 0.2
                        });
                    });
                } else if (metric === 'rhr') {
                    healthLoadChart.options.scales.y2.display = false;
                    healthLoadChart.options.scales.y.ticks.callback = (v) => `${v} bpm`;
                    DATA.ciclistas.forEach(c => {
                        const histMap = new Map();
                        (c.wellness_load?.historial || []).forEach(h => histMap.set(h.fecha, h));
                        datasets.push({
                            label: `${c.stats.nombre} (FC Reposo)`,
                            data: fechas.map(f => histMap.get(f)?.resting_hr ?? null),
                            borderColor: c.stats.color,
                            backgroundColor: c.stats.color,
                            borderWidth: 2.2,
                            pointRadius: 2.5,
                            tension: 0.2
                        });
                    });
                } else if (metric === 'weight_sleep') {
                    healthLoadChart.options.scales.y2.display = true;
                    healthLoadChart.options.scales.y.ticks.callback = (v) => `${v} kg`;
                    healthLoadChart.options.scales.y2.ticks.callback = (v) => `${v} h`;
                    DATA.ciclistas.forEach(c => {
                        const histMap = new Map();
                        (c.wellness_load?.historial || []).forEach(h => histMap.set(h.fecha, h));
                        // Peso (kg) - Línea continua en eje izquierdo
                        datasets.push({
                            label: `${c.stats.nombre} (Peso)`,
                            data: fechas.map(f => histMap.get(f)?.weight ?? null),
                            borderColor: c.stats.color,
                            backgroundColor: c.stats.color,
                            borderWidth: 2.2,
                            pointRadius: 2.5,
                            yAxisID: 'y',
                            tension: 0.2
                        });
                        // Sueño - Línea punteada en eje derecho
                        datasets.push({
                            label: `${c.stats.nombre} (Sueño)`,
                            data: fechas.map(f => histMap.get(f)?.sleep_hours ?? null),
                            borderColor: c.stats.color,
                            borderDash: [5, 4],
                            backgroundColor: 'transparent',
                            borderWidth: 1.8,
                            pointRadius: 2,
                            yAxisID: 'y2',
                            tension: 0.2
                        });
                    });
                }
            }

            healthLoadChart.data.datasets = datasets;
            healthLoadChart.update();
        }

        function setupHealthEventListeners() {
            const select = document.getElementById('healthRiderSelect');
            if (select) {
                select.addEventListener('change', (e) => {
                    selectedHealthRiderId = e.target.value;
                    updateHealthLoadChart(activeHealthMetric, selectedHealthRiderId);
                });
            }

            document.querySelectorAll('.health-tabs .tab-btn').forEach(btn => {
                btn.addEventListener('click', (e) => {
                    document.querySelectorAll('.health-tabs .tab-btn').forEach(b => b.classList.remove('active'));
                    e.currentTarget.classList.add('active');
                    activeHealthMetric = e.currentTarget.dataset.healthMetric;
                    updateHealthLoadChart(activeHealthMetric, selectedHealthRiderId);
                });
            });
        }

        // Inicialización Global
        function initApp() {
            initThemeToggle();
            initRiderCards();
            initSummaryTable();
            initSegmentAnalysis();
            initMetabolicSection();
            initHealthSection();
            initMap();
            initElevationChart();
            initTelemetryChart();
            syncToStep(0);
        }

        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', initApp);
        } else {
            initApp();
        }

        // ==========================================
        // THEME TOGGLE LOGIC
        // ==========================================
        const btnThemeToggle = document.getElementById('btnThemeToggle');
        const iconTheme = document.getElementById('iconTheme');
        
        function applyTheme(theme) {
            document.documentElement.setAttribute('data-theme', theme);
            if (iconTheme) {
                iconTheme.setAttribute('data-lucide', theme === 'dark' ? 'sun' : 'moon');
                if (typeof lucide !== 'undefined' && lucide.createIcons) lucide.createIcons();
            }
            
            // Update Map Tiles if map exists
            if (window.map) {
                const layerGroup = window.mapLayers;
                if (layerGroup) {
                    layerGroup.clearLayers();
                    const tileUrl = theme === 'dark' 
                        ? 'https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png'
                        : 'https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png';
                    L.tileLayer(tileUrl, {
                        attribution: '&copy; OpenStreetMap contributors &copy; CARTO',
                        subdomains: 'abcd',
                        maxZoom: 20
                    }).addTo(layerGroup);
                }
            }
            
            // Update Chart.js if exists
            if (window.telemetryChart) {
                const gridColor = theme === 'dark' ? 'rgba(255, 255, 255, 0.1)' : 'rgba(0, 0, 0, 0.1)';
                const textColor = theme === 'dark' ? '#94a3b8' : '#64748b';
                
                Chart.defaults.color = textColor;
                Chart.defaults.borderColor = gridColor;
                
                if (window.telemetryChart.options.scales.x) {
                    window.telemetryChart.options.scales.x.grid.color = gridColor;
                    window.telemetryChart.options.scales.x.ticks.color = textColor;
                }
                if (window.telemetryChart.options.scales.y) {
                    window.telemetryChart.options.scales.y.grid.color = gridColor;
                    window.telemetryChart.options.scales.y.ticks.color = textColor;
                }
                
                window.telemetryChart.update();
            }
        }

        // Initialize Theme
        let currentTheme = localStorage.getItem('theme');
        if (!currentTheme) {
            // Default to light as per variables, or system pref
            currentTheme = window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
        }
        applyTheme(currentTheme);

        if (btnThemeToggle) {
            btnThemeToggle.addEventListener('click', () => {
                currentTheme = document.documentElement.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
                localStorage.setItem('theme', currentTheme);
                applyTheme(currentTheme);
            });
        }
    </script>

</body>
</html>"""


def recopilar_datos_salud_y_carga(
    client: Optional[IntervalsClient],
    ciclistas_proc: List[Dict[str, Any]],
    fecha_etapa_str: Optional[str] = None,
    roster_df: Optional[pd.DataFrame] = None,
    dias_historia: int = 30
) -> Dict[str, Dict[str, Any]]:
    """
    Recopila desde la API de Intervals.icu los registros diarios de bienestar (wellness)
    y carga de entrenamiento (CTL, ATL, TSB, Ramp Rate, HRV, FC Reposo, Peso, Sueño)
    para cada ciclista presente en la etapa.
    """
    roster_df = roster_df if roster_df is not None else cargar_roster()
    nombres_map = dict(zip(roster_df['intervals_id'], roster_df['Name'])) if not roster_df.empty else {}
    pesos_map = dict(zip(roster_df['intervals_id'], roster_df['weight'])) if not roster_df.empty else {}
    nombres_pesos_map = dict(zip(roster_df['Name'], roster_df['weight'])) if not roster_df.empty else {}
    
    # Invertir mapa para buscar ID por nombre
    id_por_nombre = {str(name): str(aid) for aid, name in nombres_map.items()}

    try:
        fecha_ref = datetime.strptime(str(fecha_etapa_str)[:10], '%Y-%m-%d').date() if fecha_etapa_str else datetime.now().date()
    except Exception:
        fecha_ref = datetime.now().date()

    fecha_inicio = fecha_ref - timedelta(days=dias_historia)
    fecha_fin = fecha_ref + timedelta(days=1)

    wellness_map = {}

    for c in ciclistas_proc:
        stats = c.get('stats', {})
        aid = str(stats.get('atleta_id', '')).strip()
        nom = stats.get('nombre', '')
        peso_nominal = float(stats.get('peso_kg') or pesos_map.get(aid) or nombres_pesos_map.get(nom, DEFAULT_RIDER_WEIGHT))
        ftp_val = float(stats.get('ftp_w', 380.0))

        # Si el ID no es numérico/estándar de Intervals (ej. "Ciclista_1" o nombre), intentar buscar en el roster
        if (not aid or aid.startswith('Ciclista') or (not aid.isdigit() and not aid.startswith('i'))) and nom in id_por_nombre:
            aid = id_por_nombre[nom]

        datos_w = []
        if client is not None and aid and not aid.startswith('Ciclista_'):
            try:
                datos_w = client.get_wellness(aid, oldest=fecha_inicio, newest=fecha_fin)
            except Exception as e:
                print(f"⚠️ No se pudo descargar wellness para {nom} ({aid}): {e}")

        # Procesar registros
        if datos_w:
            datos_w = sorted(datos_w, key=lambda x: str(x.get('id') or x.get('date') or ''))
            
            # Buscar el registro más cercano a la fecha de la etapa (o el último disponible)
            rec_etapa = None
            f_ref_str = fecha_ref.strftime('%Y-%m-%d')
            for r in reversed(datos_w):
                f_r = str(r.get('id') or r.get('date') or '')[:10]
                if f_r <= f_ref_str:
                    rec_etapa = r
                    break
            if not rec_etapa and datos_w:
                rec_etapa = datos_w[-1]

            ctl = round(float(rec_etapa['ctl']), 1) if rec_etapa.get('ctl') is not None else None
            atl = round(float(rec_etapa['atl']), 1) if rec_etapa.get('atl') is not None else None
            tsb = round(ctl - atl, 1) if (ctl is not None and atl is not None) else None
            ramp_rate = round(float(rec_etapa['rampRate']), 2) if rec_etapa.get('rampRate') is not None else None
            hrv = round(float(rec_etapa['hrv']), 1) if rec_etapa.get('hrv') is not None else None
            hrv_sdnn = round(float(rec_etapa['hrvSDNN']), 1) if rec_etapa.get('hrvSDNN') is not None else None
            rhr = None
            for k in ['restingHR', 'resting_hr', 'restingHeartRate', 'fc_reposo']:
                if rec_etapa.get(k) is not None:
                    try:
                        rhr = int(round(float(rec_etapa[k])))
                        break
                    except (ValueError, TypeError):
                        pass
            weight = round(float(rec_etapa['weight']), 1) if rec_etapa.get('weight') is not None else peso_nominal
            sleep_secs = rec_etapa.get('sleepSecs')
            sleep_hours = round(float(sleep_secs) / 3600.0, 1) if sleep_secs is not None else None
            sleep_score = float(rec_etapa.get('sleepScore')) if rec_etapa.get('sleepScore') is not None else None
            sleep_quality = rec_etapa.get('sleepQuality')

            # Clasificación de Estado de Forma (TSB)
            if tsb is None:
                status = {"label": "Sin datos", "tag": "badge-gray", "color": "#94a3b8", "desc": "Sin registro de carga"}
            elif tsb > 15:
                status = {"label": "Muy Fresco", "tag": "badge-emerald", "color": "#10b981", "desc": "Pico de frescura para esfuerzos máximos"}
            elif 5 <= tsb <= 15:
                status = {"label": "Fresco / Competición", "tag": "badge-sky", "color": "#38bdf8", "desc": "Rango óptimo para carrera"}
            elif -10 <= tsb < 5:
                status = {"label": "Neutro / Balance", "tag": "badge-indigo", "color": "#818cf8", "desc": "Equilibrio entre fatiga y fitness"}
            elif -30 <= tsb < -10:
                status = {"label": "Fatiga Productiva", "tag": "badge-amber", "color": "#f59e0b", "desc": "Carga de entrenamiento alta"}
            else:
                status = {"label": "Sobrecarga / Riesgo", "tag": "badge-red", "color": "#ef4444", "desc": "Fatiga aguda muy elevada"}

            # Historial para gráficos
            historial = []
            for r in datos_w:
                f_iso = str(r.get('id') or r.get('date') or '')[:10]
                h_ctl = round(float(r['ctl']), 1) if r.get('ctl') is not None else None
                h_atl = round(float(r['atl']), 1) if r.get('atl') is not None else None
                h_tsb = round(h_ctl - h_atl, 1) if (h_ctl is not None and h_atl is not None) else None
                h_hrv = round(float(r['hrv']), 1) if r.get('hrv') is not None else None
                h_rhr = None
                for k in ['restingHR', 'resting_hr', 'restingHeartRate', 'fc_reposo']:
                    if r.get(k) is not None:
                        try:
                            h_rhr = int(round(float(r[k])))
                            break
                        except (ValueError, TypeError):
                            pass
                h_w = round(float(r['weight']), 1) if r.get('weight') is not None else peso_nominal
                h_s = round(float(r['sleepSecs']) / 3600.0, 1) if r.get('sleepSecs') is not None else None

                historial.append({
                    'fecha': f_iso,
                    'ctl': h_ctl,
                    'atl': h_atl,
                    'tsb': h_tsb,
                    'hrv': h_hrv,
                    'resting_hr': h_rhr,
                    'weight': h_w,
                    'sleep_hours': h_s
                })

            # Medias de 7 y 30 días
            hrv_valid = [h['hrv'] for h in historial if h['hrv'] is not None]
            rhr_valid = [h['resting_hr'] for h in historial if h['resting_hr'] is not None]
            hrv_7d = round(float(np.mean(hrv_valid[-7:])), 1) if len(hrv_valid) >= 1 else None
            rhr_7d = round(float(np.mean(rhr_valid[-7:])), 1) if len(rhr_valid) >= 1 else None

            w_info = {
                'atleta_id': aid,
                'nombre': nom,
                'ctl': ctl,
                'atl': atl,
                'tsb': tsb,
                'ramp_rate': ramp_rate,
                'hrv_rmssd': hrv,
                'hrv_sdnn': hrv_sdnn,
                'hrv_media_7d': hrv_7d,
                'resting_hr': rhr,
                'resting_hr_media_7d': rhr_7d,
                'weight': weight,
                'sleep_hours': sleep_hours,
                'sleep_score': sleep_score,
                'sleep_quality': sleep_quality,
                'soreness': rec_etapa.get('soreness'),
                'fatigue': rec_etapa.get('fatigue'),
                'stress': rec_etapa.get('stress'),
                'mood': rec_etapa.get('mood'),
                'readiness': rec_etapa.get('readiness'),
                'status': status,
                'historial': historial
            }
        else:
            # Fallback sin datos API
            w_info = {
                'atleta_id': aid,
                'nombre': nom,
                'ctl': None,
                'atl': None,
                'tsb': None,
                'ramp_rate': None,
                'hrv_rmssd': None,
                'hrv_sdnn': None,
                'hrv_media_7d': None,
                'resting_hr': None,
                'resting_hr_media_7d': None,
                'weight': peso_nominal,
                'sleep_hours': None,
                'sleep_score': None,
                'sleep_quality': None,
                'soreness': None,
                'fatigue': None,
                'stress': None,
                'mood': None,
                'readiness': None,
                'status': {"label": "Sin datos", "tag": "badge-gray", "color": "#94a3b8", "desc": "Sin registros de wellness"},
                'historial': []
            }

        if aid:
            wellness_map[aid] = w_info
        if nom:
            wellness_map[nom] = w_info

    return wellness_map


def generar_html_dashboard_interactivo(
    etapa_info: Dict[str, Any],
    ciclistas_proc: List[Dict[str, Any]],
    titulo_etapa: str = "Perfil Interactivo de Etapa",
    subtitulo_etapa: str = ""
) -> str:
    """
    Genera el código HTML/CSS/JavaScript del dashboard interactivo con soporte de
    sincronización por posición (km) y tiempo real, visualización de ciclistas sobre el perfil,
    y sección de salud, fisiología y carga de entrenamiento.
    """
    # Estadísticas globales de salud y carga del equipo
    ctl_list = [c['wellness_load']['ctl'] for c in ciclistas_proc if c.get('wellness_load') and c['wellness_load'].get('ctl') is not None]
    atl_list = [c['wellness_load']['atl'] for c in ciclistas_proc if c.get('wellness_load') and c['wellness_load'].get('atl') is not None]
    tsb_list = [c['wellness_load']['tsb'] for c in ciclistas_proc if c.get('wellness_load') and c['wellness_load'].get('tsb') is not None]
    hrv_list = [c['wellness_load']['hrv_rmssd'] for c in ciclistas_proc if c.get('wellness_load') and c['wellness_load'].get('hrv_rmssd') is not None]
    rhr_list = [c['wellness_load']['resting_hr'] for c in ciclistas_proc if c.get('wellness_load') and c['wellness_load'].get('resting_hr') is not None]
    sleep_list = [c['wellness_load']['sleep_hours'] for c in ciclistas_proc if c.get('wellness_load') and c['wellness_load'].get('sleep_hours') is not None]

    equipo_salud_carga = {
        'ctl_medio': round(float(np.mean(ctl_list)), 1) if ctl_list else None,
        'atl_medio': round(float(np.mean(atl_list)), 1) if atl_list else None,
        'tsb_medio': round(float(np.mean(tsb_list)), 1) if tsb_list else None,
        'hrv_medio': round(float(np.mean(hrv_list)), 1) if hrv_list else None,
        'rhr_medio': round(float(np.mean(rhr_list)), 1) if rhr_list else None,
        'sleep_medio': round(float(np.mean(sleep_list)), 1) if sleep_list else None,
    }

    payload = {
        'etapa': etapa_info,
        'ciclistas': [
            {
                'stats': c['stats'],
                'by_dist': c['samples_by_dist'],
                'by_time': c['samples_by_time'],
                'desglose_horas': c.get('desglose_horas', []),
                'wellness_load': c.get('wellness_load', {}),
            }
            for c in ciclistas_proc
        ],
        'equipo_salud_carga': equipo_salud_carga
    }
    payload_json = json.dumps(payload, ensure_ascii=False)

    # Estadísticas globales de Potencia Normalizada y Carga (TSS) del equipo
    np_vals = [c['stats']['np_w'] for c in ciclistas_proc if 'np_w' in c['stats'] and c['stats']['np_w'] > 0]
    np_media_equipo = int(round(float(np.mean(np_vals)))) if np_vals else 0
    np_max_equipo = int(round(float(np.max(np_vals)))) if np_vals else 0
    lider_np = max(ciclistas_proc, key=lambda c: c['stats'].get('np_w', 0))['stats']['nombre'] if ciclistas_proc else ''

    tss_vals = [c['stats']['tss_total'] for c in ciclistas_proc if 'tss_total' in c['stats'] and c['stats']['tss_total'] > 0]
    tss_medio_equipo = int(round(float(np.mean(tss_vals)))) if tss_vals else 0
    tss_max_equipo = int(round(float(np.max(tss_vals)))) if tss_vals else 0
    lider_tss = max(ciclistas_proc, key=lambda c: c['stats'].get('tss_total', 0))['stats']['nombre'] if ciclistas_proc else ''

    tssh_vals = [c['stats']['tss_hora'] for c in ciclistas_proc if 'tss_hora' in c['stats'] and c['stats']['tss_hora'] > 0]
    tssh_medio_equipo = round(float(np.mean(tssh_vals)), 1) if tssh_vals else 0.0

    if_vals = [c['stats']['if_val'] for c in ciclistas_proc if 'if_val' in c['stats'] and c['stats']['if_val'] > 0]
    if_medio_equipo = round(float(np.mean(if_vals)), 2) if if_vals else 0.0

    # Obtener logo corporativo negro en base64 para embebido autónomo (marca de agua a la derecha)
    logo_base64 = _obtener_logo_base64(preferencia="negro")
    logo_watermark_html = f'<div class="watermark-logo-badge"><img src="{logo_base64}" alt="Burgos BH Logo" class="watermark-img" /></div>' if logo_base64 else ''
    header_logo_html = f'<div class="logo-badge-header"><img src="{logo_base64}" alt="Burgos BH Logo" /></div>' if logo_base64 else ''

    html = HTML_TEMPLATE
    html = html.replace('__TITULO_ETAPA__', str(titulo_etapa))
    html = html.replace('__SUBTITULO_ETAPA__', str(subtitulo_etapa))
    html = html.replace('__DISTANCIA_TOTAL_KM__', str(etapa_info.get('distancia_total_km', 0)))
    html = html.replace('__DESNIVEL_POS_M__', str(etapa_info.get('desnivel_pos_m', 0)))
    html = html.replace('__ALTITUD_MAX__', str(etapa_info.get('altitud_max', 0)))
    html = html.replace('__NUM_CICLISTAS__', str(len(ciclistas_proc)))
    html = html.replace('__NP_MEDIA_EQUIPO__', str(np_media_equipo))
    html = html.replace('__IF_MEDIO_EQUIPO__', str(if_medio_equipo))
    html = html.replace('__TSS_MEDIO_EQUIPO__', str(tss_medio_equipo))
    html = html.replace('__TSSH_MEDIO_EQUIPO__', str(tssh_medio_equipo))
    html = html.replace('__TSS_MAX_EQUIPO__', str(tss_max_equipo))
    html = html.replace('__LIDER_TSS__', str(lider_tss))
    html = html.replace('__HEADER_LOGO_HTML__', header_logo_html)
    html = html.replace('__LOGO_WATERMARK_HTML__', logo_watermark_html)
    html = html.replace('__PAYLOAD_JSON__', payload_json)

    return html


def _normalizar_texto(texto: str) -> str:
    import unicodedata
    import re
    texto = unicodedata.normalize('NFKD', str(texto)).encode('ASCII', 'ignore').decode('utf-8').lower()
    return re.sub(r'[^a-z0-9]', '', texto)


def resolver_metadatos_ciclistas(
    archivos_o_datos: List[Union[str, Path, Dict[str, Any]]],
    client: Optional[IntervalsClient] = None,
    roster_df: Optional[pd.DataFrame] = None
) -> Dict[str, Dict[str, Any]]:
    """
    Construye un mapa de metadatos (nombre, peso, id de atleta, ftp, carrera) para cada archivo o actividad,
    soportando emparejamiento por ID de actividad, ID de atleta y nombres de archivo locales.
    """
    import re
    roster_df = roster_df if roster_df is not None else cargar_roster()
    nombres_map = dict(zip(roster_df['intervals_id'], roster_df['Name'])) if not roster_df.empty else {}
    pesos_map = dict(zip(roster_df['intervals_id'], roster_df['weight'])) if not roster_df.empty else {}
    ftp_map = dict(zip(roster_df['intervals_id'], roster_df['FTP'])) if not roster_df.empty and 'FTP' in roster_df.columns else {}
    nombres_ftp_map = dict(zip(roster_df['Name'], roster_df['FTP'])) if not roster_df.empty and 'FTP' in roster_df.columns else {}
    carrera_map = dict(zip(roster_df['intervals_id'], roster_df.get('carrera', 0))) if not roster_df.empty and 'carrera' in roster_df.columns else {}

    meta_map = {}
    
    # 1. Consultar actividades recientes vía API si está disponible
    if client is not None:
        try:
            atletas = client.get_athletes_list(roster_df=roster_df)
            hoy = datetime.now().date()
            inicio = hoy - timedelta(days=14)
            for a in atletas:
                aid = str(a.get('athlete_id', '')).strip()
                name = a.get('athlete_name', nombres_map.get(aid, f"Atleta_{aid}"))
                w = float(a.get('weight') or pesos_map.get(aid, DEFAULT_RIDER_WEIGHT))
                ftp_val = float(a.get('icu_ftp') or ftp_map.get(aid, nombres_ftp_map.get(name, 380.0)))
                es_carrera = int(carrera_map.get(aid, 1 if not carrera_map else 0))
                acts = client.get_activities(aid, oldest=inicio, newest=hoy + timedelta(days=1))
                for act in acts:
                    act_id = str(act.get('id', '')).strip()
                    if act_id:
                        meta_map[act_id] = {
                            'nombre': name,
                            'peso': w,
                            'ftp': ftp_val,
                            'atleta_id': aid,
                            'carrera': es_carrera,
                            'act_name': act.get('name', '')
                        }
        except Exception as e:
            print(f"⚠️ No se pudo consultar el mapa de actividades API: {e}")

    # 2. Añadir también los IDs del roster directamente
    for aid, name in nombres_map.items():
        aid_str = str(aid).strip()
        meta_map[aid_str] = {
            'nombre': name,
            'peso': float(pesos_map.get(aid, DEFAULT_RIDER_WEIGHT)),
            'ftp': float(ftp_map.get(aid, nombres_ftp_map.get(name, 380.0))),
            'atleta_id': aid_str,
            'carrera': int(carrera_map.get(aid, 0)),
            'act_name': ''
        }

    # 3. Emparejamiento inteligente de nombres de archivo locales con el roster
    for item in archivos_o_datos:
        if isinstance(item, (str, Path)):
            stem = Path(item).stem.replace('activity_', '').strip()
            if stem not in meta_map:
                stem_norm = _normalizar_texto(stem)
                
                # A) Coincidencia directa por ID normalizado
                matched_aid = None
                for aid in nombres_map:
                    if _normalizar_texto(aid) == stem_norm:
                        matched_aid = aid
                        break
                        
                # B) Coincidencia por nombre completo normalizado
                if not matched_aid:
                    for aid, name in nombres_map.items():
                        name_norm = _normalizar_texto(name)
                        if name_norm and (name_norm in stem_norm or stem_norm in name_norm):
                            matched_aid = aid
                            break
                            
                # C) Puntuación por coincidencia de subcadenas / tokens significativos
                if not matched_aid:
                    mejor_aid = None
                    mejor_score = 0
                    for aid, name in nombres_map.items():
                        parts = [p for p in re.split(r'[\s_\-]+', name) if len(p) >= 3]
                        if len(parts) >= 2:
                            parts.append(parts[0] + parts[1])
                        score = 0
                        for p in parts:
                            p_norm = _normalizar_texto(p)
                            if p_norm in stem_norm:
                                score += len(p_norm) ** 2
                        if score > mejor_score and score >= 16:
                            mejor_score = score
                            mejor_aid = aid
                    matched_aid = mejor_aid

                if matched_aid:
                    name = nombres_map[matched_aid]
                    meta_map[stem] = {
                        'nombre': name,
                        'peso': float(pesos_map.get(matched_aid, DEFAULT_RIDER_WEIGHT)),
                        'ftp': float(ftp_map.get(matched_aid, nombres_ftp_map.get(name, 380.0))),
                        'atleta_id': str(matched_aid).strip(),
                        'carrera': int(carrera_map.get(matched_aid, 0)),
                        'act_name': ''
                    }

    return meta_map


def sincronizar_ciclistas_primer_punto_comun(
    ciclistas_raw: List[Dict[str, Any]],
    max_dist_tolerancia: float = 85.0
) -> Tuple[Optional[Tuple[float, float]], List[Dict[str, Any]]]:
    """
    Localiza el primer punto geográfico común a todos los ciclistas y recorta
    el inicio de cada serie para que el análisis empiece desde ese punto.

    Estrategia de búsqueda multicapa:
    1. Tolerancias progresivas (85 → 150 → 300 m).
    2. Para cada tolerancia, itera sobre TODOS los puntos de cada ciclista como
       referencia (no solo los primeros 4000), probando cada uno como candidato
       a punto de salida común.
    3. Si ninguna combinación geográfica funciona, sincroniza por timestamp.
    """
    ciclistas_limpios = []
    for r in ciclistas_raw:
        df_c = r['df'].dropna(subset=['lat', 'lon']).reset_index(drop=True)
        if len(df_c) > 20:
            r_item = dict(r)
            r_item['df'] = df_c
            ciclistas_limpios.append(r_item)

    if len(ciclistas_limpios) <= 1:
        return None, ciclistas_raw

    punto_comun = None
    indices_corte = {}
    tolerancias = [85.0, 150.0, 300.0]
    tol_usada = tolerancias[-1]

    for tol in tolerancias:
        # Probar cada ciclista como referencia para maximizar las posibilidades
        # de encontrar un punto de salida común (especialmente útil cuando uno
        # tiene un calentamiento largo antes del km 0).
        for ciclista_ref in ciclistas_limpios:
            df_ref = ciclista_ref['df']
            n_total = len(df_ref)
            # Dos pasadas: 1ª muestreo cada 10s (rápido, cubre toda la actividad);
            # 2ª cada 1s solo los primeros 4000 puntos (refinamiento denso al inicio).
            indices_a_probar = list(range(0, n_total, 10)) + list(range(min(n_total, 4000)))
            indices_a_probar = sorted(set(indices_a_probar))
            for idx in indices_a_probar:
                row = df_ref.iloc[idx]
                lat_ref, lon_ref = float(row['lat']), float(row['lon'])
                todos_pasan = True
                temp_indices = {}
                for r in ciclistas_limpios:
                    df_r = r['df']
                    dists = np.array([
                        _haversine_distance(lat_ref, lon_ref, float(lat), float(lon))
                        for lat, lon in zip(df_r['lat'].values, df_r['lon'].values)
                    ])
                    min_idx = int(np.argmin(dists))
                    if dists[min_idx] <= tol:
                        temp_indices[r['nombre']] = min_idx
                    else:
                        todos_pasan = False
                        break
                if todos_pasan:
                    punto_comun = (lat_ref, lon_ref)
                    indices_corte = temp_indices
                    tol_usada = tol
                    break
            if punto_comun:
                break
        if punto_comun:
            break

    if punto_comun is None:
        print("⚠️ No se encontró punto común geográfico (tolerancia máxima 300m). "
              "Sincronizando por timestamp inicial máximo.")
        max_start = max([r['df']['timestamp'].iloc[0] for r in ciclistas_limpios])
        for r in ciclistas_limpios:
            idx_arr = r['df'][r['df']['timestamp'] >= max_start].index
            indices_corte[r['nombre']] = idx_arr[0] if len(idx_arr) > 0 else 0
    else:
        print(f"🎯 Punto común encontrado (tol {tol_usada}m): ({punto_comun[0]:.5f}, {punto_comun[1]:.5f})")

    ciclistas_sincronizados = []
    for r in ciclistas_limpios:
        nom = r['nombre']
        idx_corte = indices_corte.get(nom, 0)
        df_recortado = r['df'].iloc[idx_corte:].copy().reset_index(drop=True)
        if 'distancia' in df_recortado.columns:
            df_recortado['distancia'] = (df_recortado['distancia'] - df_recortado['distancia'].iloc[0]).clip(lower=0.0)
        r_sync = dict(r)
        r_sync['df'] = df_recortado
        r_sync['idx_corte'] = idx_corte
        ciclistas_sincronizados.append(r_sync)
        hora_inicio = df_recortado['timestamp'].iloc[0].strftime('%H:%M:%S')
        print(f"   • {nom:20s}: Sincronizado desde índice {idx_corte} ({hora_inicio})")

    return punto_comun, ciclistas_sincronizados


def sincronizar_ciclistas_ultimo_punto_comun(
    ciclistas_raw: List[Dict[str, Any]],
    max_dist_tolerancia: float = 200.0
) -> Tuple[Optional[Tuple[float, float]], List[Dict[str, Any]]]:
    """
    Localiza el último punto geográfico (lat, lon) donde todos los ciclistas han pasado
    y recorta el final de cada serie para que el análisis termine exactamente en ese punto común.

    Toma como referencia al ciclista cuyo timestamp final es el más temprano (el que acabó antes),
    recorre sus últimos puntos hacia atrás y busca la posición más avanzada de la ruta por la que
    también hayan pasado todos los demás dentro de la tolerancia dada.

    Args:
        ciclistas_raw: Lista de dicts con claves 'df', 'nombre', 'peso', 'ftp', 'atleta_id'.
        max_dist_tolerancia: Distancia máxima en metros para considerar que un ciclista pasó
            por el punto de referencia (default 200m, más holgado que el inicio para absorber
            dispersión GPS en llegadas de grupo o neutralizaciones).

    Returns:
        Tupla (punto_comun, ciclistas_sincronizados) donde punto_comun es (lat, lon) o None
        si no se encontró intersección válida.
    """
    ciclistas_limpios = []
    for r in ciclistas_raw:
        df_c = r['df'].dropna(subset=['lat', 'lon']).reset_index(drop=True)
        if len(df_c) > 20:
            r_item = dict(r)
            r_item['df'] = df_c
            ciclistas_limpios.append(r_item)

    if len(ciclistas_limpios) <= 1:
        return None, ciclistas_raw

    # Usar como referencia al ciclista cuyo timestamp final es el más temprano
    # (quien terminó antes define el punto de meta colectiva)
    ciclista_ref = min(ciclistas_limpios, key=lambda r: r['df']['timestamp'].iloc[-1])
    df_ref = ciclista_ref['df']

    punto_comun_fin = None
    indices_corte_fin = {}

    # Recorrer los últimos puntos del ciclista de referencia hacia atrás
    n_ref = len(df_ref)
    n_check = min(n_ref, 4000)
    start_scan = n_ref - 1
    end_scan = max(0, n_ref - n_check)

    for idx in range(start_scan, end_scan - 1, -1):
        row = df_ref.iloc[idx]
        lat_ref = float(row['lat'])
        lon_ref = float(row['lon'])

        todos_pasan = True
        temp_indices = {}

        for r in ciclistas_limpios:
            df_r = r['df']
            # Buscar en los últimos 4000 puntos de este ciclista
            lim_pts = min(len(df_r), 4000)
            lats_r = df_r['lat'].values[-lim_pts:]
            lons_r = df_r['lon'].values[-lim_pts:]
            offset = len(df_r) - lim_pts  # índice absoluto del primer punto del fragmento

            dists = np.array([
                _haversine_distance(lat_ref, lon_ref, float(lat), float(lon))
                for lat, lon in zip(lats_r, lons_r)
            ])
            if len(dists) == 0:
                todos_pasan = False
                break

            min_local_idx = int(np.argmin(dists))
            if dists[min_local_idx] <= max_dist_tolerancia:
                # Convertir índice local al índice absoluto en df_r
                temp_indices[r['nombre']] = offset + min_local_idx
            else:
                todos_pasan = False
                break

        if todos_pasan:
            punto_comun_fin = (lat_ref, lon_ref)
            indices_corte_fin = temp_indices
            break  # primer punto hacia atrás donde todos coinciden → es el más avanzado común

    if punto_comun_fin is None:
        print("ℹ️ No se encontró punto final común geográfico. No se aplica recorte de fin.")
        return None, ciclistas_limpios

    print(f"🏁 Punto común de fin de análisis encontrado en ({punto_comun_fin[0]:.5f}, {punto_comun_fin[1]:.5f})")

    ciclistas_recortados_fin = []
    for r in ciclistas_limpios:
        nom = r['nombre']
        idx_corte_fin = indices_corte_fin.get(nom, len(r['df']) - 1)
        # +1 para incluir el propio punto de llegada
        df_recortado = r['df'].iloc[:idx_corte_fin + 1].copy().reset_index(drop=True)

        if df_recortado.empty:
            print(f"⚠️ {nom}: El recorte de fin dejó el DataFrame vacío. Manteniendo datos originales.")
            df_recortado = r['df'].copy()

        r_fin = dict(r)
        r_fin['df'] = df_recortado
        r_fin['idx_corte_fin'] = idx_corte_fin
        ciclistas_recortados_fin.append(r_fin)

        hora_fin = df_recortado['timestamp'].iloc[-1].strftime('%H:%M:%S')
        print(f"   • {nom:20s}: Recortado hasta índice {idx_corte_fin} ({hora_fin}) — {len(df_recortado)} puntos")

    return punto_comun_fin, ciclistas_recortados_fin


def generar_dashboard_perfil_interactivo(
    archivos_o_datos: List[Union[str, Path, Dict[str, Any]]],
    roster_df: Optional[pd.DataFrame] = None,
    client: Optional[IntervalsClient] = None,
    solo_carrera: bool = True,
    grupo_carrera: Optional[int] = None,
    sincronizar_inicio_comun: bool = True,
    titulo: Optional[str] = None,
    output_html: Optional[Union[str, Path]] = None,
    output_pdf: Optional[Union[str, Path]] = None,
    generar_pdf: bool = True,
    fits_temporales_limpiar: Optional[List[Union[str, Path]]] = None
) -> Path:
    """
    Función principal para procesar los archivos FIT / datos con posicionamiento y generar
    el informe interactivo HTML completo, sincronizado desde el primer punto común.
    """
    roster_df = roster_df if roster_df is not None else cargar_roster()
    meta_map = resolver_metadatos_ciclistas(archivos_o_datos, client=client, roster_df=roster_df)

    nombres_ftp_map = dict(zip(roster_df['Name'], roster_df['FTP'])) if not roster_df.empty and 'FTP' in roster_df.columns else {}

    # Identificar IDs que tienen carrera > 0 (cualquier grupo de competición)
    ids_carrera = set()
    if not roster_df.empty and 'carrera' in roster_df.columns:
        ids_carrera = set(roster_df.loc[roster_df['carrera'] > 0, 'intervals_id'].astype(str).str.strip())
        nombres_carrera = set(roster_df.loc[roster_df['carrera'] > 0, 'Name'].astype(str).str.strip())
    else:
        nombres_carrera = set()

    ciclistas_raw = []
    
    for idx, item in enumerate(archivos_o_datos):
        if isinstance(item, (str, Path)):
            ruta = Path(item)
            stem = ruta.stem.replace('activity_', '').strip()
            meta = meta_map.get(stem, {})
            nombre = meta.get('nombre', stem)
            peso = float(meta.get('peso', DEFAULT_RIDER_WEIGHT))
            ftp = float(meta.get('ftp', nombres_ftp_map.get(nombre, 380.0)))
            aid = str(meta.get('atleta_id', stem)).strip()
            es_carrera = meta.get('carrera', 1 if (aid in ids_carrera or nombre in nombres_carrera) else 0)

            # Filtrar si solo_carrera está activo y no pertenece a ningún grupo de carrera
            if solo_carrera and ids_carrera:
                if aid not in ids_carrera and nombre not in nombres_carrera and int(es_carrera) <= 0:
                    continue
            # Filtrar por grupo específico de carrera (carrera=0 siempre excluido)
            if grupo_carrera is not None and int(es_carrera) != grupo_carrera:
                continue

            # Opción 2: Cargar FIT con filtrado de paradas y cálculo de tiempo en movimiento
            if ruta.stat().st_size < 1000:
                print(f"⚠️ Archivo FIT {ruta.name} demasiado pequeño o corrupto ({ruta.stat().st_size} bytes). Omitiendo.")
                continue
            try:
                df_fit = cargar_fit_con_tiempo_movimiento(ruta, solo_movimiento=True)
            except Exception as e:
                print(f"⚠️ Error al procesar archivo FIT {ruta.name}: {e}. Omitiendo.")
                continue
        elif isinstance(item, dict) and 'df' in item:
            df_fit = item['df']
            nombre = item.get('nombre', f"Ciclista_{idx+1}")
            peso = float(item.get('peso', DEFAULT_RIDER_WEIGHT))
            ftp = float(item.get('ftp', nombres_ftp_map.get(nombre, 380.0)))
            aid = str(item.get('atleta_id', '')).strip()
            es_carrera = item.get('carrera', 1 if (aid in ids_carrera or nombre in nombres_carrera) else 0)

            if solo_carrera and ids_carrera:
                if aid not in ids_carrera and nombre not in nombres_carrera and int(es_carrera) <= 0:
                    continue
            # Filtrar por grupo específico de carrera (carrera=0 siempre excluido)
            if grupo_carrera is not None and int(es_carrera) != grupo_carrera:
                continue
        else:
            continue

        # Normalizar timestamp a tz-naive para consistencia total
        if 'timestamp' in df_fit.columns and len(df_fit) > 0:
            ts_series = pd.to_datetime(df_fit['timestamp'])
            if ts_series.dt.tz is not None:
                ts_series = ts_series.dt.tz_convert('UTC').dt.tz_localize(None)
            df_fit['timestamp'] = ts_series

        ciclistas_raw.append({
            'df': df_fit,
            'nombre': nombre,
            'peso': peso,
            'ftp': ftp,
            'atleta_id': aid,
        })

    if not ciclistas_raw:
        raise ValueError("No se pudo cargar ningún ciclista con datos de posicionamiento válidos.")

    # Si hay múltiples actividades o fechas, filtrar por la fecha más frecuente de carrera
    # para que la etapa contenga únicamente las actividades sincronizables de ese mismo día
    if len(ciclistas_raw) > 1:
        fechas_disponibles = []
        for c in ciclistas_raw:
            df = c['df']
            if 'timestamp' in df.columns and len(df) > 0 and pd.notna(df['timestamp'].iloc[0]):
                fechas_disponibles.append(df['timestamp'].iloc[0].strftime('%Y-%m-%d'))
        if fechas_disponibles:
            from collections import Counter
            fecha_objetivo = Counter(fechas_disponibles).most_common(1)[0][0]
            ciclistas_filtrados = []
            atletas_vistos = set()
            for c in ciclistas_raw:
                df = c['df']
                if 'timestamp' in df.columns and len(df) > 0 and pd.notna(df['timestamp'].iloc[0]):
                    f_str = df['timestamp'].iloc[0].strftime('%Y-%m-%d')
                    if f_str == fecha_objetivo and c['nombre'] not in atletas_vistos:
                        ciclistas_filtrados.append(c)
                        atletas_vistos.add(c['nombre'])
            if ciclistas_filtrados:
                ciclistas_raw = ciclistas_filtrados

    # Sincronización en el primer punto común si está activada
    punto_comun = None
    if sincronizar_inicio_comun:
        punto_comun, ciclistas_para_procesar = sincronizar_ciclistas_primer_punto_comun(ciclistas_raw)
    else:
        ciclistas_para_procesar = ciclistas_raw

    # ─────────────────────────────────────────────────────────────────────────
    # CASO: sin intersección GPS → saltar al informe de salud / biometría
    # Esto solo ocurre cuando los ciclistas no comparten ningún tramo de ruta
    # dentro de la tolerancia máxima (300 m) Y tampoco tienen datos GPS válidos
    # suficientes para generar el perfil. Cuando punto_comun es None pero
    # ciclistas_para_procesar tiene datos (sincronización por timestamp),
    # continuamos al flujo normal para generar el perfil completo.
    # ─────────────────────────────────────────────────────────────────────────
    _hay_gps_valido = any(
        len(r['df'].dropna(subset=['lat', 'lon'])) > 20
        for r in ciclistas_para_procesar
    ) if ciclistas_para_procesar else False

    if punto_comun is None and sincronizar_inicio_comun and not _hay_gps_valido:
        print("ℹ️ Sin ruta GPS válida entre ciclistas. Generando informe de salud y biometría directamente.")

        # Slug y ruta del fichero (sin sufijo de carrera en el nombre de la función)
        titulo_final = titulo or f"Informe Biometría / Carga{' | Carrera ' + str(grupo_carrera) if grupo_carrera else ''}"
        _titulo_slug = re.sub(r'_+', '_', re.sub(r'[^A-Za-z0-9_]', '', re.sub(
            r'[\s\-/\\|]+', '_',
            unicodedata.normalize('NFKD', titulo_final).encode('ASCII', 'ignore').decode('utf-8')
        ))).strip('_')[:60]
        _titulo_part = f"_{_titulo_slug}" if _titulo_slug else ""
        fecha_etapa = datetime.now().strftime('%Y-%m-%d')
        for r in ciclistas_para_procesar:
            df_r = r['df']
            if 'timestamp' in df_r.columns and len(df_r) > 0 and pd.notna(df_r['timestamp'].iloc[0]):
                fecha_etapa = df_r['timestamp'].iloc[0].strftime('%Y-%m-%d')
                break

        # Filtro de distancia: descartar ciclistas con < 70% de la mediana del grupo
        _dists_bio = []
        for r in ciclistas_para_procesar:
            df_r = r['df']
            if 'distancia' in df_r.columns and df_r['distancia'].notna().any():
                _dists_bio.append(float((df_r['distancia'].max() - df_r['distancia'].iloc[0])) / 1000.0)
            else:
                _dists_bio.append(float(len(df_r)) / 1000.0)  # aprox por nº de muestras
        if _dists_bio:
            _mediana_bio = float(np.median(_dists_bio))
            _umbral_bio = _mediana_bio * 0.70
            _filtrados_bio = []
            for r, d in zip(ciclistas_para_procesar, _dists_bio):
                if d >= _umbral_bio:
                    _filtrados_bio.append(r)
                else:
                    print(f"⚠️ {r['nombre']} descartado por distancia insuficiente ({d:.1f} km < 70% de mediana {_mediana_bio:.1f} km = {_umbral_bio:.1f} km)")
            if _filtrados_bio:
                ciclistas_para_procesar = _filtrados_bio

        # Construir ciclistas_proc mínimo (solo stats básicos sin mapa/perfil)
        ciclistas_proc_bio = []
        for idx, r in enumerate(ciclistas_para_procesar):
            color_cfg = COLORES_CICLISTAS[idx % len(COLORES_CICLISTAS)]
            df_r = r['df']
            tiempo_mov_seg = len(df_r)  # 1 muestra ≈ 1 segundo en streams limpios
            if 'distancia' in df_r.columns and df_r['distancia'].notna().any():
                dist_km = float((df_r['distancia'].max() - df_r['distancia'].iloc[0])) / 1000.0
            else:
                dist_km = 0.0
            stats_min = {
                'nombre': r['nombre'],
                'atleta_id': r.get('atleta_id', ''),
                'peso': r.get('peso', DEFAULT_RIDER_WEIGHT),
                'ftp': r.get('ftp', 380.0),
                'color': color_cfg.get('color', '#888888'),
                'tiempo_mov_seg': tiempo_mov_seg,
                'distancia_km': round(dist_km, 2),
                'gap_lider_seg': 0,
                'gap_lider_str': '',
                'posicion_str': f"{idx+1}º",
            }
            ciclistas_proc_bio.append({'stats': stats_min, 'df_gps': pd.DataFrame(), 'wellness_load': {}})

        print(f"🩺 Recopilando datos de salud, biometría y carga para {len(ciclistas_proc_bio)} ciclistas...")
        wellness_carga_map = recopilar_datos_salud_y_carga(
            client=client,
            ciclistas_proc=ciclistas_proc_bio,
            fecha_etapa_str=fecha_etapa,
            roster_df=roster_df
        )
        for c in ciclistas_proc_bio:
            aid = str(c['stats'].get('atleta_id', '')).strip()
            nom = c['stats'].get('nombre', '')
            c['wellness_load'] = wellness_carga_map.get(aid) or wellness_carga_map.get(nom) or {}

        out_path = Path(output_html or (OUTPUT_DIR / f"etapa_{fecha_etapa}{_titulo_part}.html"))
        out_path.parent.mkdir(parents=True, exist_ok=True)
        # HTML mínimo informativo (sin mapa ni perfil)
        nombres_lista = ", ".join(c['stats']['nombre'] for c in ciclistas_proc_bio)
        out_path.write_text(
            f"<html><head><meta charset='utf-8'><title>{titulo_final}</title></head>"
            f"<body><h1>{titulo_final}</h1>"
            f"<p>No se encontró ruta GPS común entre los ciclistas ({nombres_lista}). "
            f"El perfil comparativo no está disponible. Consulta el PDF de biometría.</p>"
            f"</body></html>",
            encoding='utf-8'
        )

        if generar_pdf:
            try:
                etapa_info_bio = {'distancia_total_km': 0, 'desnivel_pos_m': 0,
                                  'perfil_lat': [], 'perfil_lon': [], 'perfil_alt': [],
                                  'perfil_dist_km': [], 'nombre_ciclistas': [c['stats']['nombre'] for c in ciclistas_proc_bio]}
                pdf_target = output_pdf or (OUTPUT_DIR / f"etapa_{fecha_etapa}{_titulo_part}.pdf")
                print(f"📄 Generando informe PDF de biometría en: {pdf_target}...")
                ruta_pdf = generar_informe_etapa_pdf(
                    etapa_info=etapa_info_bio,
                    ciclistas_proc=ciclistas_proc_bio,
                    wellness_carga_map=wellness_carga_map,
                    titulo=titulo_final,
                    output_pdf=pdf_target
                )
                print(f"✅ ¡Informe PDF generado con éxito! Archivo: {ruta_pdf.resolve()}")
            except Exception as e:
                print(f"⚠️ No se pudo generar el informe PDF de biometría: {e}")

        if fits_temporales_limpiar:
            for f_temp in fits_temporales_limpiar:
                try:
                    p = Path(f_temp)
                    if p.exists():
                        p.unlink()
                except Exception:
                    pass
        return out_path

    # ─────────────────────────────────────────────────────────────────────────
    # CASO NORMAL: ruta común encontrada → procesar telemetría completa
    # ─────────────────────────────────────────────────────────────────────────

    # Sincronización en el último punto común: recortar el final de cada serie
    # para que el análisis termine en la posición más avanzada por la que pasaron todos.
    punto_comun_fin = None
    if sincronizar_inicio_comun and len(ciclistas_para_procesar) > 1:
        punto_comun_fin, ciclistas_para_procesar = sincronizar_ciclistas_ultimo_punto_comun(ciclistas_para_procesar)

    # Calcular la distancia de referencia (el ciclista con más km recorridos)
    # para normalizar el eje X compartido y que todos terminen en la misma meta.
    dist_ref_etapa: Optional[float] = None
    if len(ciclistas_para_procesar) > 1:
        dists_tmp = []
        for r in ciclistas_para_procesar:
            df_tmp = r['df'].dropna(subset=['lat', 'lon'])
            if 'distancia' in df_tmp.columns and df_tmp['distancia'].notna().any() and df_tmp['distancia'].max() > 0:
                d_km = float((df_tmp['distancia'].max() - df_tmp['distancia'].iloc[0])) / 1000.0
            else:
                import math as _math
                d = 0.0
                lats = df_tmp['lat'].values
                lons = df_tmp['lon'].values
                for i in range(1, len(lats)):
                    phi1, phi2 = _math.radians(lats[i-1]), _math.radians(lats[i])
                    dphi = _math.radians(lats[i] - lats[i-1])
                    dlam = _math.radians(lons[i] - lons[i-1])
                    a = _math.sin(dphi/2)**2 + _math.cos(phi1)*_math.cos(phi2)*_math.sin(dlam/2)**2
                    d += 2 * 6371000.0 * _math.atan2(_math.sqrt(a), _math.sqrt(1-a))
                d_km = d / 1000.0
            dists_tmp.append(d_km)
        if dists_tmp:
            # Usamos el mínimo: todos los ciclistas terminan en el punto final común,
            # así el eje X compartido refleja la distancia real de la etapa sin estiramientos.
            dist_ref_etapa = min(dists_tmp)
            print(f"📏 Distancia de referencia para grid compartido (punto final común): {dist_ref_etapa:.2f} km")

    # Filtro de distancia: descartar ciclistas con < 70% de la mediana del grupo
    if len(ciclistas_para_procesar) > 1:
        _dists_norm = []
        for r in ciclistas_para_procesar:
            df_tmp = r['df'].dropna(subset=['lat', 'lon'])
            if 'distancia' in df_tmp.columns and df_tmp['distancia'].notna().any() and df_tmp['distancia'].max() > 0:
                _dists_norm.append(float((df_tmp['distancia'].max() - df_tmp['distancia'].iloc[0])) / 1000.0)
            else:
                _dists_norm.append(float(len(df_tmp)) / 1000.0)
        _mediana_norm = float(np.median(_dists_norm))
        _umbral_norm = _mediana_norm * 0.70
        _filtrados_norm = []
        for r, d in zip(ciclistas_para_procesar, _dists_norm):
            if d >= _umbral_norm:
                _filtrados_norm.append(r)
            else:
                print(f"⚠️ {r['nombre']} descartado por distancia insuficiente ({d:.1f} km < 70% de mediana {_mediana_norm:.1f} km = {_umbral_norm:.1f} km)")
        if _filtrados_norm:
            ciclistas_para_procesar = _filtrados_norm

    ciclistas_proc = []
    for idx, r in enumerate(ciclistas_para_procesar):
        color_cfg = COLORES_CICLISTAS[idx % len(COLORES_CICLISTAS)]
        try:
            proc = procesar_telemetria_ciclista(
                df=r['df'],
                nombre=r['nombre'],
                peso=r['peso'],
                color_cfg=color_cfg,
                atleta_id=r['atleta_id'],
                ftp=r.get('ftp', 380.0),
                dist_referencia_km=dist_ref_etapa
            )
            ciclistas_proc.append(proc)
        except Exception as e:
            print(f"⚠️ No se pudo procesar la telemetría de {r['nombre']}: {e}")

    if not ciclistas_proc:
        raise ValueError("No se pudo procesar ningún ciclista con coordenadas GPS válidas.")

    # Calcular gaps oficiales y ordenar clasificación de llegada de la etapa sobre tiempo en movimiento
    min_duracion = min(c['stats']['tiempo_mov_seg'] for c in ciclistas_proc)
    for c in ciclistas_proc:
        gap_seg = c['stats']['tiempo_mov_seg'] - min_duracion
        c['stats']['gap_lider_seg'] = gap_seg
        if gap_seg == 0:
            c['stats']['gap_lider_str'] = "Líder"
        else:
            mm = int(gap_seg // 60)
            ss = int(gap_seg % 60)
            c['stats']['gap_lider_str'] = f"+{mm}m {ss:02d}s" if mm > 0 else f"+{ss}s"

    # Ordenar por tiempo en movimiento de carrera ascendente
    ciclistas_proc.sort(key=lambda c: c['stats']['tiempo_mov_seg'])
    for pos, c in enumerate(ciclistas_proc, 1):
        c['stats']['posicion_str'] = f"{pos}º"

    # Construir perfil de referencia de la etapa
    etapa_info = construir_perfil_etapa_referencia(ciclistas_proc)
    if punto_comun:
        etapa_info['punto_sincronizado'] = [round(punto_comun[0], 5), round(punto_comun[1], 5)]
    if punto_comun_fin:
        etapa_info['punto_sincronizado_fin'] = [round(punto_comun_fin[0], 5), round(punto_comun_fin[1], 5)]

    # Determinar fecha de la etapa para el nombre del archivo HTML
    fecha_etapa = None
    for c in ciclistas_proc:
        if 'df_gps' in c and not c['df_gps'].empty and 'timestamp' in c['df_gps'].columns:
            ts = c['df_gps']['timestamp'].iloc[0]
            if pd.notna(ts):
                fecha_etapa = ts.strftime('%Y-%m-%d')
                break
    if not fecha_etapa:
        fecha_etapa = datetime.now().strftime('%Y-%m-%d')

    # Recopilar métricas de salud, HRV y carga de entrenamiento (CTL/ATL/TSB)
    print(f"🩺 Recopilando datos de salud, biometría y carga para {len(ciclistas_proc)} ciclistas...")
    wellness_carga_map = recopilar_datos_salud_y_carga(
        client=client,
        ciclistas_proc=ciclistas_proc,
        fecha_etapa_str=fecha_etapa,
        roster_df=roster_df
    )
    for c in ciclistas_proc:
        aid = str(c['stats'].get('atleta_id', '')).strip()
        nom = c['stats'].get('nombre', '')
        c['wellness_load'] = wellness_carga_map.get(aid) or wellness_carga_map.get(nom) or {}

    # Generar HTML
    _grupo_label = f" | Carrera {grupo_carrera}" if grupo_carrera is not None else ""
    titulo_final = titulo or f"Etapa {etapa_info['distancia_total_km']} km (+{etapa_info['desnivel_pos_m']}m D+){_grupo_label} | Perfil Sincronizado"
    subtitulo_final = ""
    html_content = generar_html_dashboard_interactivo(
        etapa_info=etapa_info,
        ciclistas_proc=ciclistas_proc,
        titulo_etapa=titulo_final,
        subtitulo_etapa=subtitulo_final
    )

    # Slug del título para incluirlo en el nombre de fichero
    _titulo_slug = unicodedata.normalize('NFKD', titulo_final).encode('ASCII', 'ignore').decode('utf-8')
    _titulo_slug = re.sub(r'[\s\-/\\|]+', '_', _titulo_slug)          # espacios/guiones → _
    _titulo_slug = re.sub(r'[^A-Za-z0-9_]', '', _titulo_slug)          # eliminar resto de especiales
    _titulo_slug = re.sub(r'_+', '_', _titulo_slug).strip('_')          # colapsar _ dobles
    _titulo_slug = _titulo_slug[:60]                                      # limitar longitud

    #_carrera_suffix = f"_carrera_{grupo_carrera}" if grupo_carrera is not None else ""
    _titulo_part = f"_{_titulo_slug}" if _titulo_slug else ""
    out_path = Path(output_html or (OUTPUT_DIR / f"etapa_{fecha_etapa}{_titulo_part}.html"))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(html_content)

    # Generar también el informe ejecutivo en PDF
    if generar_pdf:
        try:
            pdf_target = output_pdf or (OUTPUT_DIR / f"etapa_{fecha_etapa}{_titulo_part}.pdf")
            print(f"📄 Generando informe PDF completo de la etapa en: {pdf_target}...")
            ruta_pdf = generar_informe_etapa_pdf(
                etapa_info=etapa_info,
                ciclistas_proc=ciclistas_proc,
                wellness_carga_map=wellness_carga_map,
                titulo=titulo_final,
                output_pdf=pdf_target
            )
            print(f"✅ ¡Informe PDF generado con éxito! Archivo: {ruta_pdf.resolve()}")
        except Exception as e:
            print(f"⚠️ No se pudo generar el informe PDF: {e}")

    # Limpieza automática de archivos FIT temporales de la API (las actividades no-Strava)
    if fits_temporales_limpiar:
        eliminados = 0
        for f_temp in fits_temporales_limpiar:
            try:
                p = Path(f_temp)
                if p.exists() and p.is_file():
                    p.unlink()
                    eliminados += 1
            except Exception:
                pass
        if eliminados > 0:
            print(f"🧹 Eliminados {eliminados} archivos FIT temporales de la API (conservados archivos de Strava).")

    return out_path


def buscar_fit_local_ciclista(
    nombre: str,
    atleta_id: str = "",
    act_id: str = "",
    directorios_busqueda: Optional[List[Union[str, Path]]] = None
) -> Optional[Path]:
    """
    Busca en las carpetas locales (por defecto data/today_race/ y data/) un archivo .fit
    que pertenezca al ciclista indicado por nombre, ID de atleta o ID de actividad.
    Especialmente utilizado para actividades cuyo origen sea STRAVA.
    """
    import re
    if directorios_busqueda is None:
        directorios_busqueda = [Path("data/today_race"), Path("data")]

    candidatos_fits = []
    for d in directorios_busqueda:
        p = Path(d)
        if p.exists() and p.is_dir():
            candidatos_fits.extend(list(p.glob("*.fit")) + list(p.glob("*.FIT")))

    if not candidatos_fits:
        return None

    # 1. Coincidencia directa por act_id
    if act_id:
        act_id_norm = _normalizar_texto(act_id)
        for f in candidatos_fits:
            if _normalizar_texto(f.stem) == act_id_norm or act_id_norm in _normalizar_texto(f.stem):
                return f

    # 2. Coincidencia directa por atleta_id
    if atleta_id:
        aid_norm = _normalizar_texto(atleta_id)
        for f in candidatos_fits:
            if _normalizar_texto(f.stem) == aid_norm or aid_norm in _normalizar_texto(f.stem):
                return f

    # 3. Coincidencia por nombre completo o subcadenas/tokens
    nombre_norm = _normalizar_texto(nombre)
    for f in candidatos_fits:
        stem_norm = _normalizar_texto(f.stem)
        if nombre_norm and (nombre_norm in stem_norm or stem_norm in nombre_norm):
            return f

    # 4. Puntuación por tokens de nombre
    mejor_fit = None
    mejor_score = 0
    parts = [p for p in re.split(r'[\s_\-]+', nombre) if len(p) >= 3]
    if len(parts) >= 2:
        parts.append(parts[0] + parts[1])

    for f in candidatos_fits:
        stem_norm = _normalizar_texto(f.stem)
        score = 0
        for p in parts:
            p_norm = _normalizar_texto(p)
            if p_norm in stem_norm:
                score += len(p_norm) ** 2
        if score > mejor_score and score >= 16:
            mejor_score = score
            mejor_fit = f

    return mejor_fit


def descargar_o_recopilar_fits_etapa(
    client: Optional[IntervalsClient] = None,
    roster_df: Optional[pd.DataFrame] = None,
    fecha_str: Optional[str] = None,
    activity_id: Optional[str] = None,
    ultima_individual: bool = False,
    solo_carrera: bool = True,
    cache_dir: Optional[Union[str, Path]] = None,
) -> Tuple[List[Union[Path, Dict[str, Any]]], List[Path]]:
    """
    Recopila los datos de telemetría de los ciclistas para la etapa:
    1. Prioridad API Streams: Descarga directamente los flujos (streams) segundo a segundo
       desde la API de Intervals.icu, donde los periodos de parada ya vienen eliminados por la plataforma.
    2. Fallback FIT (Opción 2): Si los streams no están disponibles o para orígenes restringidos,
       descarga o localiza el archivo .fit y lo procesa eliminando paradas y derivas GPS.
    
    Devuelve: (elementos_encontrados, fits_temporales_no_strava)
    """
    roster_df = roster_df if roster_df is not None else cargar_roster()
    cache_path = Path(cache_dir or "data/today_race")
    cache_path.mkdir(parents=True, exist_ok=True)

    pesos_map = dict(zip(roster_df['intervals_id'], roster_df['weight'])) if not roster_df.empty and 'weight' in roster_df.columns else {}
    ftp_map = dict(zip(roster_df['intervals_id'], roster_df['FTP'])) if not roster_df.empty and 'FTP' in roster_df.columns else {}
    ids_carrera = set(roster_df.loc[roster_df['carrera'] > 0, 'intervals_id'].astype(str).str.strip()) if not roster_df.empty and 'carrera' in roster_df.columns else set()
    nombres_carrera = set(roster_df.loc[roster_df['carrera'] > 0, 'Name'].astype(str).str.strip()) if not roster_df.empty and 'carrera' in roster_df.columns else set()
    # Mapa completo intervals_id → número de grupo real (1, 2, …) para anotar correctamente cada item
    carrera_map = dict(zip(roster_df['intervals_id'].astype(str).str.strip(), roster_df['carrera'].astype(int))) if not roster_df.empty and 'carrera' in roster_df.columns else {}

    if client is None:
        try:
            client = IntervalsClient()
        except Exception as e:
            print(f"⚠️ No se pudo conectar con la API de Intervals.icu: {e}. Usando archivos locales.")
            return list(cache_path.glob("*.fit")) or list(Path("data").glob("*.fit")), []

    print(f"🔍 Consultando actividades en la API de Intervals.icu (solo_carrera={solo_carrera})...")
    atletas = client.get_athletes_list(roster_df=roster_df, solo_carrera=solo_carrera)

    items_encontrados: List[Union[Path, Dict[str, Any]]] = []
    fits_temporales_api: List[Path] = []

    # 1. Caso: Descarga de una sola actividad por activity_id específico
    if activity_id:
        act_id = str(activity_id).strip()
        print(f"🎯 Procesando actividad individual con ID: {act_id}...")
        
        # Intentar Streams primero
        try:
            print(f"   ⚡ Consultando Streams limpios de actividad {act_id}...")
            df_stream = client.get_activity_streams(act_id)
            if df_stream is not None and len(df_stream) >= 10 and 'lat' in df_stream.columns and df_stream['lat'].notna().sum() >= 10:
                print(f"   ✅ Obtenidos Streams limpios directamente ({len(df_stream)} muestras en movimiento)")
                items_encontrados.append({
                    'df': df_stream,
                    'nombre': f"Actividad_{act_id}",
                    'peso': DEFAULT_RIDER_WEIGHT,
                    'ftp': 380.0,
                    'atleta_id': '',
                    'origen': 'intervals_streams'
                })
                return items_encontrados, []
        except Exception as e:
            print(f"   ⚠️ No se pudieron obtener streams ({e}). Usando fallback FIT.")

        local_fit = cache_path / f"{act_id}.fit"
        ok = client.download_activity_file(act_id, str(local_fit))
        if ok and local_fit.exists() and local_fit.stat().st_size > 0:
            items_encontrados.append(local_fit)
            fits_temporales_api.append(local_fit)
        else:
            # Intentar sesión web o fit local
            if client.download_activity_fit_via_web_session(act_id, local_fit):
                items_encontrados.append(local_fit)
            else:
                fit_local = buscar_fit_local_ciclista("", "", act_id, [cache_path, Path("data")])
                if fit_local:
                    items_encontrados.append(fit_local)
        return items_encontrados, fits_temporales_api

    # 2. Caso: Detección automática de la fecha más reciente de carrera si no se indicó
    if not fecha_str or ultima_individual:
        hoy = datetime.now().date()
        oldest_search = hoy - timedelta(days=14)
        todas_acts = []
        for a in atletas:
            aid = a.get('athlete_id')
            name = a.get('athlete_name')
            acts = client.get_activities(aid, oldest=oldest_search, newest=hoy)
            for act in acts:
                tipo = act.get('type')
                dist = act.get('distance') or 0
                src = str(act.get('source', '')).upper()
                if tipo in ['Ride', 'VirtualRide'] or dist > 15000 or src == 'STRAVA':
                    todas_acts.append({
                        'athlete_id': aid,
                        'athlete_name': name,
                        'act_id': str(act.get('id')),
                        'act_name': act.get('name') or '',
                        'start_date_local': act.get('start_date_local') or '',
                        'fecha': (act.get('start_date_local') or '')[:10],
                        'distance': dist,
                        'source': src,
                        'act_obj': act
                    })

        if not todas_acts:
            print("⚠️ No se encontraron actividades en los últimos 14 días.")
            return list(cache_path.glob("*.fit")) or list(Path("data").glob("*.fit")), []

        if ultima_individual:
            todas_acts.sort(key=lambda x: x['start_date_local'], reverse=True)
            act_top = todas_acts[0]
            print(f"🚴 Última actividad individual encontrada: {act_top['athlete_name']} - {act_top['start_date_local']} (ID: {act_top['act_id']})")
            act_id = act_top['act_id']
            source = act_top['source']
            aid_top = act_top['athlete_id']
            name_top = act_top['athlete_name']

            # Intentar Streams primero
            try:
                print(f"   ⚡ Consultando Streams limpios para {name_top} ({act_id})...")
                df_stream = client.get_activity_streams(act_id, start_date=act_top.get('start_date_local'))
                if df_stream is not None and len(df_stream) >= 10 and 'lat' in df_stream.columns and df_stream['lat'].notna().sum() >= 10:
                    print(f"   ✅ Obtenidos Streams limpios directamente ({len(df_stream)} muestras en movimiento)")
                    items_encontrados.append({
                        'df': df_stream,
                        'nombre': name_top,
                        'atleta_id': aid_top,
                        'peso': float(pesos_map.get(aid_top, DEFAULT_RIDER_WEIGHT)),
                        'ftp': float(ftp_map.get(aid_top, 380.0)),
                        'carrera': int(carrera_map.get(aid_top, 0)),
                        'origen': 'intervals_streams'
                    })
                    return items_encontrados, []
            except Exception as e:
                print(f"   ⚠️ No se pudieron obtener streams ({e}).")

            local_fit = cache_path / f"{act_id}.fit"
            if source != 'STRAVA':
                if client.download_activity_file(act_id, str(local_fit)):
                    items_encontrados.append(local_fit)
                    fits_temporales_api.append(local_fit)
            else:
                fit_local = buscar_fit_local_ciclista(act_top['athlete_name'], act_top['athlete_id'], act_id, [cache_path, Path("data")])
                if fit_local:
                    items_encontrados.append(fit_local)
            return items_encontrados, fits_temporales_api

        # Determinar la fecha de carrera más reciente
        fechas_candidatas = [x['fecha'] for x in todas_acts if x['fecha']]
        fecha_str = max(fechas_candidatas)
        print(f"📅 Última etapa de carrera detectada automáticamente: {fecha_str}")
    else:
        print(f"📅 Fecha objetivo de etapa: {fecha_str}")

    # 3. Descargar las actividades de la fecha seleccionada para cada ciclista
    for a in atletas:
        aid = str(a.get('athlete_id', '')).strip()
        name = a.get('athlete_name', f"Atleta_{aid}")
        peso_atleta = float(pesos_map.get(aid, DEFAULT_RIDER_WEIGHT))
        ftp_atleta = float(ftp_map.get(aid, 380.0))
        es_carrera_atleta = int(carrera_map.get(aid, 0))

        acts = client.get_activities(aid, oldest=fecha_str, newest=fecha_str)
        acts_ciclismo = []
        for act in acts:
            tipo = act.get('type')
            dist = act.get('distance') or 0
            src = str(act.get('source', '')).upper()
            if tipo in ['Ride', 'VirtualRide'] or dist > 2000 or src == 'STRAVA':
                acts_ciclismo.append(act)

        if not acts_ciclismo:
            continue

        # Ordenar por distancia y hora de inicio dentro del mismo día para tomar la etapa principal
        acts_ciclismo.sort(key=lambda x: (x.get('distance') or 0, x.get('start_date_local') or ''), reverse=True)
        act_sel = acts_ciclismo[0]
        act_id = str(act_sel.get('id', ''))
        source = str(act_sel.get('source', '')).upper()

        # 1º Intentar obtener Streams limpios de tiempo en movimiento directamente de Intervals.icu
        try:
            print(f"   ⚡ {name}: Consultando Streams limpios de actividad {act_id}...")
            df_stream = client.get_activity_streams(act_id, start_date=act_sel.get('start_date_local'))
            if df_stream is not None and len(df_stream) >= 10 and 'lat' in df_stream.columns and df_stream['lat'].notna().sum() >= 10:
                print(f"      ✅ Obtenidos Streams limpios directamente ({len(df_stream)} muestras en movimiento)")
                items_encontrados.append({
                    'df': df_stream,
                    'nombre': name,
                    'atleta_id': aid,
                    'peso': peso_atleta,
                    'ftp': ftp_atleta,
                    'carrera': es_carrera_atleta,
                    'origen': 'intervals_streams'
                })
                continue
        except Exception as e:
            print(f"      ⚠️ No se pudieron obtener streams ({e}). Usando fallback FIT.")

        # 2º Fallback a descarga FIT (Opción 2)
        if source == 'STRAVA':
            print(f"   ⚠️ {name}: Actividad {act_id} con origen STRAVA (restringida en API estándar).")
            local_fit = cache_path / f"{act_id}.fit"
            
            descargado_web = False
            if local_fit.exists() and local_fit.stat().st_size > 1000:
                descargado_web = True
            else:
                print(f"      🌐 Intentando descarga automática de FIT para {name} vía sesión web...")
                descargado_web = client.download_activity_fit_via_web_session(act_id, local_fit)

            if descargado_web and local_fit.exists() and local_fit.stat().st_size > 1000:
                print(f"      ✅ Obtenido archivo FIT de Strava vía sesión web: {local_fit.name} ({local_fit.stat().st_size} bytes)")
                items_encontrados.append(local_fit)
            else:
                print(f"      📁 Buscando archivo .fit local en '{cache_path}' para {name}...")
                fit_local = buscar_fit_local_ciclista(name, aid, act_id, [cache_path, Path("data")])
                if fit_local and fit_local.exists() and fit_local.stat().st_size > 1000:
                    print(f"      ✅ Encontrado .fit local de Strava: {fit_local.name}")
                    items_encontrados.append(fit_local)
                else:
                    print(f"      ❌ No se encontró .fit local válido en '{cache_path}' para {name}.")
        else:
            # Descargar directamente desde la API oficial de Intervals.icu (temporal)
            local_fit = cache_path / f"{act_id}.fit"
            print(f"   📥 {name}: Descargando FIT ({act_id}, origen {source}) desde la API de Intervals.icu...")
            ok = client.download_activity_file(act_id, str(local_fit))
            if ok and local_fit.exists() and local_fit.stat().st_size > 1000:
                print(f"      ✅ Descargado con éxito: {local_fit.name} ({local_fit.stat().st_size} bytes)")
                items_encontrados.append(local_fit)
                fits_temporales_api.append(local_fit)
            else:
                # Fallback alternativo
                fit_local = buscar_fit_local_ciclista(name, aid, act_id, [cache_path, Path("data")])
                if fit_local and fit_local.exists() and fit_local.stat().st_size > 1000:
                    print(f"      ✅ Encontrado .fit local alternativo: {fit_local.name}")
                    items_encontrados.append(fit_local)

    # Si no se encontró nada por API, usar archivos existentes en cache_path / data
    if not items_encontrados:
        items_encontrados = [f for f in list(cache_path.glob("*.fit")) + list(Path("data").glob("*.fit")) if f.stat().st_size > 1000]

    # Quitar duplicados preservando orden
    unicos = []
    vistos = set()
    for item in items_encontrados:
        if isinstance(item, (str, Path)):
            res = str(Path(item).resolve())
            if res not in vistos:
                unicos.append(Path(item))
                vistos.add(res)
        elif isinstance(item, dict):
            key = (item.get('atleta_id'), item.get('nombre'))
            if key not in vistos:
                unicos.append(item)
                vistos.add(key)

    return unicos, fits_temporales_api


if __name__ == '__main__':
    client = None
    try:
        client = IntervalsClient()
    except Exception:
        pass

    roster_df = cargar_roster()
    fits_disponibles, fits_temporales = descargar_o_recopilar_fits_etapa(
        client=client,
        roster_df=roster_df,
        solo_carrera=True,
        cache_dir=Path("data/today_race")
    )

    if fits_disponibles:
        print(f"\n🚀 Generando perfil interactivo sincronizado en punto común con {len(fits_disponibles)} ciclistas...")
        ruta_res = generar_dashboard_perfil_interactivo(
            fits_disponibles,
            client=client,
            roster_df=roster_df,
            solo_carrera=True,
            sincronizar_inicio_comun=True,
            fits_temporales_limpiar=fits_temporales
        )
        print(f"✅ ¡Dashboard generado con éxito! Archivo: {ruta_res.resolve()}")
    else:
        print("ℹ️ No se encontraron archivos FIT con posicionamiento para generar el dashboard.")
