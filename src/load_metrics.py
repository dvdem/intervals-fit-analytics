"""
Módulo de Métricas de Carga, Fatiga y Forma (CTL, ATL, TSB, Ramp Rate).
Implementa el modelo de impulso-respuesta con medias móviles exponenciales clásicas
(CTL 42 días, ATL 7 días, Form/TSB y tasa de incremento Ramp Rate).
"""

from datetime import datetime, timedelta
from typing import Dict, List, Optional, Union
import pandas as pd
import numpy as np


def calcular_serie_carga_atleta(
    actividades: List[Dict],
    nombre_atleta: str,
    fecha_inicio: datetime.date,
    fecha_fin: datetime.date,
    span_ctl: int = 42,
    span_atl: int = 7
) -> pd.DataFrame:
    """
    Construye la serie temporal diaria continua con CTL, ATL, TSB y Ramp Rate
    para un atleta específico a partir de su lista de actividades.
    """
    fechas_completas = pd.date_range(start=fecha_inicio, end=fecha_fin, freq='D')
    
    rows = []
    for act in actividades:
        fecha_txt = act.get('start_date_local') or act.get('start_date')
        if not fecha_txt:
            continue

        fecha = pd.to_datetime(fecha_txt, errors='coerce')
        if pd.isna(fecha):
            continue

        load = act.get('icu_training_load')
        if load is None:
            load = act.get('training_load')
        if load is None:
            load = 0.0

        rows.append({"fecha": fecha.date(), "load": float(load)})

    df_acts = pd.DataFrame(rows)
    if df_acts.empty:
        df_diario = pd.DataFrame({'fecha': [], 'daily_load': []})
    else:
        df_diario = (
            df_acts.groupby('fecha', as_index=False)['load']
            .sum()
            .rename(columns={'load': 'daily_load'})
        )

    serie = pd.DataFrame({'fecha': fechas_completas.date})
    serie = serie.merge(df_diario, on='fecha', how='left')
    serie['daily_load'] = serie['daily_load'].fillna(0.0)

    # Cálculo de medias exponenciales
    serie['ctl'] = serie['daily_load'].ewm(span=span_ctl, adjust=False).mean()
    serie['atl'] = serie['daily_load'].ewm(span=span_atl, adjust=False).mean()
    serie['tsb'] = serie['ctl'] - serie['atl']  # Form / TSB
    serie['ramp_rate_7d'] = serie['ctl'] - serie['ctl'].shift(7)
    serie['athlete_name'] = nombre_atleta

    return serie


def calcular_metricas_carga(
    client,
    atletas: List[Dict],
    dias_historia: int = 60,
    dias_plot: int = 60,
    nombres_map: Optional[Dict[str, str]] = None
) -> pd.DataFrame:
    """
    Descarga actividades y calcula CTL/ATL/Ramp Rate para todos los atletas indicados.
    """
    hoy = datetime.now().date()
    fecha_inicio_carga = hoy - timedelta(days=dias_historia)
    fecha_inicio_plot = hoy - timedelta(days=dias_plot)

    resultados = []
    nombres_map = nombres_map or {}

    for atleta in atletas:
        aid = str(atleta.get('athlete_id', '')).strip()
        nombre = nombres_map.get(aid, atleta.get('athlete_name', f"Atleta_{aid}"))

        try:
            actividades = client.get_activities(
                athlete_id=aid,
                oldest=fecha_inicio_carga,
                newest=hoy
            )
        except Exception as e:
            print(f"⚠️ No se pudieron cargar actividades para {nombre}: {e}")
            continue

        if not actividades:
            continue

        serie = calcular_serie_carga_atleta(
            actividades=actividades,
            nombre_atleta=nombre,
            fecha_inicio=fecha_inicio_carga,
            fecha_fin=hoy
        )

        # Filtrar rango visual
        serie_plot = serie[serie['fecha'] >= fecha_inicio_plot].copy()
        resultados.append(serie_plot)

    if not resultados:
        return pd.DataFrame(columns=['fecha', 'daily_load', 'ctl', 'atl', 'tsb', 'ramp_rate_7d', 'athlete_name'])

    metrics_df = pd.concat(resultados, ignore_index=True)
    metrics_df['fecha'] = pd.to_datetime(metrics_df['fecha'])
    return metrics_df


def resumen_metricas_carga(metrics_df: pd.DataFrame) -> pd.DataFrame:
    """
    Genera un DataFrame resumido con los puntos semanales y el valor final de cada atleta.
    """
    if metrics_df.empty:
        return pd.DataFrame()

    resumen = []
    for nombre, g in metrics_df.groupby('athlete_name'):
        g_sorted = g.sort_values('fecha').reset_index(drop=True)
        g_sem = g_sorted.iloc[::7].copy()
        last_row = g_sorted.iloc[-1]

        for _, r in g_sem.iterrows():
            resumen.append({
                'athlete_name': nombre,
                'fecha': r['fecha'].strftime('%Y-%m-%d'),
                'tipo': 'Semanal',
                'ctl': round(float(r['ctl']), 1),
                'atl': round(float(r['atl']), 1),
                'tsb': round(float(r['tsb']), 1),
                'ramp_rate_7d': round(float(r['ramp_rate_7d']), 2) if pd.notnull(r['ramp_rate_7d']) else None
            })

        resumen.append({
            'athlete_name': nombre,
            'fecha': last_row['fecha'].strftime('%Y-%m-%d'),
            'tipo': 'FINAL',
            'ctl': round(float(last_row['ctl']), 1),
            'atl': round(float(last_row['atl']), 1),
            'tsb': round(float(last_row['tsb']), 1),
            'ramp_rate_7d': round(float(last_row['ramp_rate_7d']), 2) if pd.notnull(last_row['ramp_rate_7d']) else None
        })

    resumen_df = pd.DataFrame(resumen).drop_duplicates(subset=['athlete_name', 'fecha'])
    return resumen_df.sort_values(['athlete_name', 'fecha']).reset_index(drop=True)
