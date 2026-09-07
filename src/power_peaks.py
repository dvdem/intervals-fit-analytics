"""
Módulo de Análisis y Comparativa de Picos de Potencia (Power Peaks).
Calcula los mejores valores de potencia máxima en duraciones estándar
(5s, 30s, 1m, 5m, 10m, 20m) para los últimos 30 días frente a marcas históricas.
"""

import sys
from pathlib import Path

# Permitir ejecución directa del script o importación modular
_ROOT_DIR = Path(__file__).resolve().parent.parent
if str(_ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(_ROOT_DIR))

from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Union
import pandas as pd
import numpy as np

try:
    from config import DEFAULT_PEAK_DURATIONS
except (ImportError, ValueError):
    from ..config import DEFAULT_PEAK_DURATIONS


def _a_int_segundos(valor: Union[str, int, float]) -> Optional[int]:
    """Convierte cadenas como '30s', '5m', '1m' o números a segundos enteros."""
    if valor is None:
        return None
    if isinstance(valor, (int, float)):
        v = int(float(valor))
        return v if v > 0 else None
    if isinstance(valor, str):
        t = valor.strip().lower()
        if t.endswith('s') and t[:-1].replace('.', '', 1).isdigit():
            return int(float(t[:-1]))
        if t.endswith('m') and t[:-1].replace('.', '', 1).isdigit():
            return int(float(t[:-1]) * 60)
        if t.endswith('min') and t[:-3].replace('.', '', 1).isdigit():
            return int(float(t[:-3]) * 60)
        if t.replace('.', '', 1).isdigit():
            return int(float(t))
    return None


def extraer_mejores_por_periodo(datos: Union[dict, list]) -> Dict[int, float]:
    """Recorre estructuras JSON anidadas para extraer {segundos: max_watts}."""
    mejores = {}

    def actualizar(segundos, watts):
        s = _a_int_segundos(segundos)
        if s is None or s <= 0:
            return
        try:
            w = float(watts)
        except (TypeError, ValueError):
            return
        if w <= 0:
            return
        if s not in mejores or w > mejores[s]:
            mejores[s] = w

    def recorrer(obj):
        if isinstance(obj, list):
            for item in obj:
                recorrer(item)
            return
        if not isinstance(obj, dict):
            return

        posibles_periodos = [
            obj.get('secs'), obj.get('seconds'), obj.get('duration'),
            obj.get('duration_s'), obj.get('period'), obj.get('time')
        ]
        posibles_watts = [
            obj.get('watts'), obj.get('power'), obj.get('w'),
            obj.get('value'), obj.get('best')
        ]

        for p in posibles_periodos:
            for w in posibles_watts:
                if p is not None and w is not None:
                    actualizar(p, w)

        for k, v in obj.items():
            ks = _a_int_segundos(k)
            if ks is not None and isinstance(v, (int, float, str)):
                actualizar(ks, v)
            if isinstance(v, (dict, list)):
                recorrer(v)

    recorrer(datos)
    return mejores


def calcular_picos_potencia(
    client,
    atletas: List[Dict],
    roster_df: pd.DataFrame,
    duraciones: Optional[Dict[int, str]] = None,
    dias_recientes: int = 30,
    max_actividades_por_atleta: int = 25
) -> pd.DataFrame:
    """
    Calcula los picos de potencia recientes y all-time para cada atleta del equipo.
    """
    duraciones = duraciones or DEFAULT_PEAK_DURATIONS
    hoy = datetime.now().date()
    oldest_30 = hoy - timedelta(days=dias_recientes)
    newest_30 = hoy

    meta_roster = roster_df.copy()
    meta_roster['intervals_id'] = meta_roster['intervals_id'].astype(str).str.strip()

    resultados = []

    for atleta in atletas:
        aid = str(atleta.get('athlete_id', '')).strip()
        athlete_name = atleta.get('athlete_name', aid)

        meta_row = meta_roster[meta_roster['intervals_id'] == aid]
        if meta_row.empty:
            display_name = athlete_name
            weight_kg = atleta.get('weight') or 70.0
        else:
            display_name = meta_row.iloc[0]['Name']
            weight_kg = meta_row.iloc[0].get('weight')
            if pd.isna(weight_kg) or weight_kg <= 0:
                weight_kg = atleta.get('weight') or 70.0

        weight_kg = float(weight_kg)

        # 1. Obtener records históricos
        records_historicos = {d: {'watts': None, 'date': None} for d in duraciones}
        try:
            curvas_json = client.get_athlete_power_curves(aid)
            mejores_hist = extraer_mejores_por_periodo(curvas_json)
            for d in duraciones:
                if d in mejores_hist:
                    records_historicos[d]['watts'] = mejores_hist[d]
        except Exception:
            pass

        # 2. Obtener actividades de los últimos 30 días
        try:
            actividades_30 = client.get_activities(
                athlete_id=aid,
                oldest=oldest_30,
                newest=newest_30
            )
        except Exception:
            actividades_30 = []

        mejores_recientes = {d: None for d in duraciones}
        mejores_recientes_fecha = {d: None for d in duraciones}

        for act in actividades_30[:max_actividades_por_atleta]:
            act_id = act.get('id')
            if not act_id:
                continue
            act_fecha = (act.get('start_date_local') or act.get('start_date') or '')[:10]

            df_curva = client.get_activity_power_curve_csv(act_id)
            if df_curva is None or df_curva.empty:
                continue

            sec_col = [c for c in df_curva.columns if 'sec' in c.lower()][0]
            watts_col = [c for c in df_curva.columns if 'watt' in c.lower() or c.lower() == 'w'][0]

            for d in duraciones:
                fila = df_curva[df_curva[sec_col] == d]
                if not fila.empty:
                    val = float(fila[watts_col].max())
                    if mejores_recientes[d] is None or val > mejores_recientes[d]:
                        mejores_recientes[d] = val
                        mejores_recientes_fecha[d] = act_fecha

                    # Si supera el histórico o histórico está vacío
                    if records_historicos[d]['watts'] is None or val > records_historicos[d]['watts']:
                        records_historicos[d]['watts'] = val
                        records_historicos[d]['date'] = act_fecha

        # Consolidar resultados
        for d, d_label in duraciones.items():
            peak_w = mejores_recientes[d]
            hist_w = records_historicos[d]['watts']

            resultados.append({
                'athlete_id': aid,
                'athlete_name': display_name,
                'weight_kg': weight_kg,
                'duration_s': d,
                'duration_label': d_label,
                'peak_watts': peak_w,
                'peak_wkg': (peak_w / weight_kg) if peak_w is not None else None,
                'peak_date': mejores_recientes_fecha[d],
                'all_time_watts': hist_w,
                'all_time_wkg': (hist_w / weight_kg) if hist_w is not None else None,
                'all_time_date': records_historicos[d]['date'],
            })

    peaks_df = pd.DataFrame(resultados)
    if not peaks_df.empty:
        for col in ['peak_watts', 'all_time_watts']:
            peaks_df[col] = pd.to_numeric(peaks_df[col], errors='coerce').round()
        for col in ['peak_wkg', 'all_time_wkg']:
            peaks_df[col] = pd.to_numeric(peaks_df[col], errors='coerce').round(2)

    return peaks_df


def generar_tabla_picos_comparativa(peaks_df: pd.DataFrame) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """
    Construye la matriz de comparación (30 días vs Histórico) y su matriz de estilos de color.
    """
    if peaks_df.empty:
        return pd.DataFrame(), pd.DataFrame()

    orden_duraciones = ['5s', '30s', '1m', '5m', '10m', '20m']

    def _construir_tabla(watts_col, wkg_col, fecha_col):
        tabla_watts = peaks_df.pivot_table(
            index='duration_label', columns='athlete_name', values=watts_col, aggfunc='max'
        ).reindex(orden_duraciones)
        tabla_wkg = peaks_df.pivot_table(
            index='duration_label', columns='athlete_name', values=wkg_col, aggfunc='max'
        ).reindex(orden_duraciones)
        tabla_fecha = (
            peaks_df.dropna(subset=[watts_col])
            .sort_values(watts_col, ascending=False)
            .drop_duplicates(subset=['duration_label', 'athlete_name'])
            .pivot_table(
                index='duration_label', columns='athlete_name', values=fecha_col, aggfunc='first'
            )
            .reindex(orden_duraciones)
        )

        tabla = tabla_watts.copy().astype(object)
        for fila in tabla.index:
            for columna in tabla.columns:
                watts = tabla_watts.loc[fila, columna]
                wkg = tabla_wkg.loc[fila, columna]
                fecha = tabla_fecha.loc[fila, columna] if columna in tabla_fecha.columns else None
                fecha_str = f"\n({fecha})" if fecha and not (isinstance(fecha, float) and pd.isna(fecha)) else ""

                if pd.isna(watts) and pd.isna(wkg):
                    tabla.loc[fila, columna] = ''
                elif pd.isna(watts):
                    tabla.loc[fila, columna] = f"{wkg:.1f} W/kg{fecha_str}"
                elif pd.isna(wkg):
                    tabla.loc[fila, columna] = f"{int(watts)} W{fecha_str}"
                else:
                    tabla.loc[fila, columna] = f"{int(watts)} W | {wkg:.1f} W/kg{fecha_str}"
        return tabla

    tabla_30_dias = _construir_tabla('peak_watts', 'peak_wkg', 'peak_date')
    tabla_historica = _construir_tabla('all_time_watts', 'all_time_wkg', 'all_time_date')

    columnas_juntas = []
    for ciclista in tabla_30_dias.columns:
        columnas_juntas.extend([(ciclista, '30 dias'), (ciclista, 'historico')])

    columnas_multi = pd.MultiIndex.from_tuples(columnas_juntas)
    tabla_peaks = pd.concat(
        [
            tabla_30_dias.rename(columns=lambda c: (c, '30 dias')),
            tabla_historica.rename(columns=lambda c: (c, 'historico')),
        ],
        axis=1,
    ).reindex(columns=columnas_multi)
    tabla_peaks.index.name = 'potencia'

    # Matriz de colores semafóricos
    colores_tabla = pd.DataFrame('', index=tabla_peaks.index, columns=tabla_peaks.columns)
    for ciclista in tabla_30_dias.columns:
        for duracion in orden_duraciones:
            reciente_df = peaks_df[
                (peaks_df['athlete_name'] == ciclista) &
                (peaks_df['duration_label'] == duracion)
            ]
            if reciente_df.empty:
                continue

            reciente_w = reciente_df.iloc[0]['peak_watts']
            historico_w = reciente_df.iloc[0]['all_time_watts']

            if pd.isna(reciente_w) or pd.isna(historico_w):
                continue

            columna_reciente = (ciclista, '30 dias')
            if reciente_w < historico_w * 0.85:
                colores_tabla.loc[duracion, columna_reciente] = 'background-color: #fee2e2; color: #991b1b'  # Rojo suave
            elif reciente_w >= historico_w:
                colores_tabla.loc[duracion, columna_reciente] = 'background-color: #dcfce7; color: #166534'  # Verde suave

    return tabla_peaks, colores_tabla
