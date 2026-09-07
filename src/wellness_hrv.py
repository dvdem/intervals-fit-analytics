"""
Módulo de Análisis de Bienestar, Peso y Variabilidad de Frecuencia Cardíaca (HRV).
Procesa registros de HRV (RMSSD, SDNN), peso, frecuencia cardíaca en reposo y fatiga.
"""

from datetime import datetime, timedelta
from typing import Dict, List, Optional, Union
import pandas as pd
import numpy as np


def extraer_campo(registro: dict, posibles_claves: List[str]) -> Optional[float]:
    """Busca en el diccionario la primera clave coincidente y devuelve float o None."""
    for k in posibles_claves:
        val = registro.get(k)
        if val is not None and val != "":
            try:
                return float(val)
            except (ValueError, TypeError):
                pass
    return None


def descargar_wellness_atletas(
    client,
    atletas: List[Dict],
    oldest: Optional[Union[str, datetime.date]] = None,
    newest: Optional[Union[str, datetime.date]] = None,
    nombres_map: Optional[Dict[str, str]] = None
) -> pd.DataFrame:
    """
    Descarga los registros de wellness/HRV de todos los atletas indicados desde la API.
    """
    hoy = datetime.now().date()
    oldest = oldest or (hoy - timedelta(days=30))
    newest = newest or hoy
    nombres_map = nombres_map or {}

    todos_registros = []

    for atleta in atletas:
        aid = str(atleta.get('athlete_id', '')).strip()
        nombre = nombres_map.get(aid, atleta.get('athlete_name', f"Atleta_{aid}"))

        try:
            datos_w = client.get_wellness(athlete_id=aid, oldest=oldest, newest=newest)
        except Exception as e:
            print(f"⚠️ Error al descargar wellness de {nombre} ({aid}): {e}")
            continue

        if not datos_w:
            continue

        for r in datos_w:
            fecha_str = r.get('id') or r.get('date')
            if not fecha_str:
                continue

            hrv_rmssd = extraer_campo(r, ['hrv', 'hrv_rmssd', 'hrvRmssd', 'hrv_r_mssd'])
            hrv_sdnn = extraer_campo(r, ['hrv_sdnn', 'hrvSdnn', 'sdnn'])
            peso = extraer_campo(r, ['weight', 'peso'])
            resting_hr = extraer_campo(r, ['restingHR', 'resting_hr', 'fc_reposo'])
            sueno_horas = extraer_campo(r, ['sleepSecs', 'sleep_secs'])
            if sueno_horas is not None:
                sueno_horas = round(sueno_horas / 3600.0, 1)

            todos_registros.append({
                'athlete_id': aid,
                'athlete_name': nombre,
                'date': str(fecha_str)[:10],
                'hrv_rmssd': hrv_rmssd,
                'hrv_sdnn': hrv_sdnn,
                'weight': peso,
                'resting_hr': resting_hr,
                'sleep_hours': sueno_horas,
                'soreness': r.get('soreness'),
                'fatigue': r.get('fatigue'),
                'stress': r.get('stress'),
                'mood': r.get('mood'),
            })

    if not todos_registros:
        return pd.DataFrame(columns=[
            'athlete_id', 'athlete_name', 'date', 'hrv_rmssd',
            'hrv_sdnn', 'weight', 'resting_hr', 'sleep_hours'
        ])

    df = pd.DataFrame(todos_registros)
    df['date'] = pd.to_datetime(df['date'])
    return df.sort_values(['athlete_name', 'date']).reset_index(drop=True)


def procesar_datos_wellness(df: pd.DataFrame) -> pd.DataFrame:
    """
    Limpia y valida el DataFrame de bienestar.
    """
    df = df.copy()
    if 'date' in df.columns:
        df['date'] = pd.to_datetime(df['date'])
    return df.sort_values(['athlete_name', 'date']).reset_index(drop=True)


def resumen_estadisticas_hrv(df: pd.DataFrame) -> pd.DataFrame:
    """
    Genera una tabla con estadísticas agregadas por ciclista (media HRV, rango, último peso, etc.).
    """
    if df.empty:
        return pd.DataFrame()

    stats = []
    for name, group in df.groupby('athlete_name'):
        records_count = len(group)

        # Estadísticas de HRV RMSSD
        hrv_group = group[group['hrv_rmssd'].notnull()]
        if not hrv_group.empty:
            avg_hrv = round(float(hrv_group['hrv_rmssd'].mean()), 1)
            min_hrv = round(float(hrv_group['hrv_rmssd'].min()), 1)
            max_hrv = round(float(hrv_group['hrv_rmssd'].max()), 1)
            std_hrv = round(float(hrv_group['hrv_rmssd'].std()), 1) if len(hrv_group) > 1 else 0.0
            rango_hrv = f"{min_hrv} - {max_hrv}"
        else:
            avg_hrv, min_hrv, max_hrv, std_hrv, rango_hrv = np.nan, np.nan, np.nan, np.nan, "-"

        # Estadísticas de peso
        weight_group = group[group['weight'].notnull()]
        last_weight = round(float(weight_group.iloc[-1]['weight']), 1) if not weight_group.empty else np.nan

        # Estadísticas FC Reposo
        rhr_group = group[group['resting_hr'].notnull()]
        avg_rhr = round(float(rhr_group['resting_hr'].mean()), 1) if not rhr_group.empty else np.nan

        stats.append({
            'athlete_name': name,
            'dias_con_datos': records_count,
            'media_hrv_rmssd': avg_hrv,
            'rango_hrv': rango_hrv,
            'desv_hrv': std_hrv,
            'ultimo_peso': last_weight,
            'media_fc_reposo': avg_rhr,
        })

    return pd.DataFrame(stats).sort_values('athlete_name').reset_index(drop=True)
