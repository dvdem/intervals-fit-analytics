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
from typing import Dict, List, Optional, Tuple, Union, Any
import pandas as pd
import numpy as np

import json

try:
    from config import DEFAULT_PEAK_DURATIONS, DEFAULT_POWER_DURATION_CURVE_DURATIONS, DATA_DIR
except (ImportError, ValueError):
    from ..config import DEFAULT_PEAK_DURATIONS, DEFAULT_POWER_DURATION_CURVE_DURATIONS, DATA_DIR

HISTORICAL_PEAKS_CACHE_FILE = Path(DATA_DIR) / "cache" / "historical_peaks_cache.json"


def _cargar_cache_picos_historicos() -> Dict[str, Any]:
    """Carga la base de datos local de kilojulios de actividades históricas."""
    try:
        if HISTORICAL_PEAKS_CACHE_FILE.exists():
            with open(HISTORICAL_PEAKS_CACHE_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def _guardar_cache_picos_historicos(cache: Dict[str, Any]) -> None:
    """Guarda en disco los kilojulios resueltos para actividades históricas."""
    try:
        HISTORICAL_PEAKS_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(HISTORICAL_PEAKS_CACHE_FILE, 'w', encoding='utf-8') as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def resolver_kj_actividades_historicas(
    client,
    actividades_meta: Dict[int, Dict[str, Any]],
    peso_kg: float = 70.0
) -> Dict[int, Dict[str, Any]]:
    """
    Resuelve y asocia a cada duración en actividades_meta los kilojulios gastados
    antes de alcanzar el récord en esa actividad histórica, apoyándose en una
    caché persistente local en disco.
    """
    if not actividades_meta:
        return actividades_meta

    peso = max(30.0, float(peso_kg) if peso_kg and peso_kg > 0 else 70.0)
    cache = _cargar_cache_picos_historicos()
    cache_modificada = False

    # 1. Identificar qué actividades y duraciones ya están en caché y cuáles faltan
    pendientes_por_actividad = {}  # {act_id: [duraciones]}

    for dur, meta in actividades_meta.items():
        act_id = str(meta.get('activity_id', '')).strip()
        if not act_id:
            continue

        dur_str = str(dur)
        act_cache = cache.get(act_id, {}).get('peaks', {})
        if dur_str in act_cache:
            c_entry = act_cache[dur_str]
            meta['kj_previos'] = c_entry.get('kj_previos')
            meta['kjkg_previos'] = c_entry.get('kjkg_previos')
            meta['tiempo_hms'] = c_entry.get('tiempo_hms', '')
            meta['start_index'] = c_entry.get('start_index')
        else:
            if act_id not in pendientes_por_actividad:
                pendientes_por_actividad[act_id] = []
            pendientes_por_actividad[act_id].append(dur)

    # 2. Si hay pendientes y disponemos de cliente de Intervals, resolverlas
    if pendientes_por_actividad and client is not None:
        for act_id, dur_list in pendientes_por_actividad.items():
            if act_id not in cache:
                cache[act_id] = {'peaks': {}}

            try:
                # Consultar power-curve.json de la actividad específica
                curve_json = None
                if hasattr(client, 'get_activity_power_curve_json'):
                    curve_json = client.get_activity_power_curve_json(act_id)
                elif hasattr(client, '_request'):
                    resp = client._request("GET", f"activity/{act_id}/power-curve.json")
                    if resp.status_code == 200:
                        curve_json = resp.json()

                if not curve_json:
                    continue

                secs_arr = curve_json.get('secs', [])
                start_indices = curve_json.get('start_index', [])
                watts_arr = curve_json.get('watts', [])
                weight_act = float(curve_json.get('weight') or peso)

                # Mapear sec -> start_index
                sec_to_start = {}
                sec_to_watt = {}
                for idx_c, s_c in enumerate(secs_arr):
                    if idx_c < len(start_indices):
                        sec_to_start[s_c] = start_indices[idx_c]
                    if idx_c < len(watts_arr):
                        sec_to_watt[s_c] = watts_arr[idx_c]

                # Obtener telemetría de streams para integral de energía acumulada
                stream_df = None
                if hasattr(client, 'get_activity_streams'):
                    stream_df = client.get_activity_streams(act_id)

                kj_cum = None
                if stream_df is not None and 'potencia' in stream_df.columns:
                    pot_vals = stream_df['potencia'].fillna(0.0).values
                    kj_cum = np.cumsum(pot_vals) / 1000.0

                for dur in dur_list:
                    dur_str = str(dur)
                    s_idx = sec_to_start.get(dur)
                    w_rec = sec_to_watt.get(dur)

                    if s_idx is not None:
                        if kj_cum is not None and len(kj_cum) > 0:
                            idx_pos = min(max(0, s_idx - 1), len(kj_cum) - 1)
                            kj_val = float(kj_cum[idx_pos]) if s_idx > 0 else 0.0
                        else:
                            # Fallback si no hay streams completos: estimar con potencia y start_index
                            avg_w = w_rec if w_rec else 250.0
                            kj_val = round((avg_w * 0.82 * s_idx) / 1000.0, 1)

                        kjkg_val = round(kj_val / weight_act, 1)
                        h = s_idx // 3600
                        m = (s_idx % 3600) // 60
                        sec_rem = s_idx % 60
                        t_hms = f"{h:02d}:{m:02d}:{sec_rem:02d}"

                        entry = {
                            'kj_previos': round(kj_val, 1),
                            'kjkg_previos': kjkg_val,
                            'tiempo_hms': t_hms,
                            'start_index': s_idx,
                            'watts': w_rec
                        }
                        cache[act_id]['peaks'][dur_str] = entry
                        cache_modificada = True

                        if dur in actividades_meta:
                            actividades_meta[dur]['kj_previos'] = entry['kj_previos']
                            actividades_meta[dur]['kjkg_previos'] = entry['kjkg_previos']
                            actividades_meta[dur]['tiempo_hms'] = entry['tiempo_hms']
                            actividades_meta[dur]['start_index'] = entry['start_index']
            except Exception:
                pass

    if cache_modificada:
        _guardar_cache_picos_historicos(cache)

    return actividades_meta



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
    """
    Recorre estructuras JSON anidadas para extraer {segundos: max_watts}.
    Soporta tanto diccionarios clave-valor como los arrays nativos paralelos
    'secs' y 'watts' que devuelve la API de Intervals.icu (/athlete/{id}/power-curves).
    """
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

        # 1. Soporte para arrays paralelos nativos de Intervals.icu (secs + watts/values)
        secs_arr = obj.get('secs') or obj.get('seconds')
        watts_arr = obj.get('watts') or obj.get('power') or obj.get('values')
        if isinstance(secs_arr, list) and isinstance(watts_arr, list):
            for s_val, w_val in zip(secs_arr, watts_arr):
                actualizar(s_val, w_val)

        # 2. Escalares dentro de diccionarios
        posibles_periodos = [
            obj.get('duration'), obj.get('duration_s'), obj.get('period'), obj.get('time')
        ]
        posibles_watts = [
            obj.get('power'), obj.get('w'), obj.get('value'), obj.get('best')
        ]

        for p in posibles_periodos:
            if p is not None and not isinstance(p, (list, dict)):
                for w in posibles_watts:
                    if w is not None and not isinstance(w, (list, dict)):
                        actualizar(p, w)

        # 3. Diccionarios con claves numéricas o de tiempo (ej. '300': 400.0)
        for k, v in obj.items():
            # Omitir metadatos y rankings estadísticos que podrían distorsionar vatios reales
            if k in ('ranks', 'powerModels', 'mapPlot', 'activities', 'activity_id', 'wkg_activity_id'):
                continue
            ks = _a_int_segundos(k)
            if ks is not None and isinstance(v, (int, float, str)):
                actualizar(ks, v)
            elif isinstance(v, (dict, list)):
                recorrer(v)

    recorrer(datos)
    return mejores


def obtener_curvas_referencia_atleta(
    client,
    athlete_id: str,
    peso_kg: float = 70.0,
    date_curves: Optional[str] = None
) -> Dict[str, Any]:
    """
    Obtiene las curvas de potencia de referencia para un atleta desde la API de Intervals.icu.
    Extrae la curva All-Time (Histórico) y la de Temporada actual con metadatos de las actividades de récord.
    """
    if not client or not athlete_id:
        return {'disponible': False, 'all_time': {}, 'temporada': {}}

    aid = str(athlete_id).strip()
    year_act = datetime.now().year
    peso = max(1.0, float(peso_kg) if peso_kg and peso_kg > 0 else 70.0)

    # 1. Curva All-Time (Histórico)
    curva_str = date_curves or f"r.2020-01-01.{year_act}-12-31"
    curva_all_time = {}
    curva_all_time_wkg = {}
    actividades_all_time = {}

    try:
        res_hist = client.get_athlete_power_curves(aid, date_curves=curva_str)
        if res_hist and 'list' in res_hist and res_hist['list']:
            item = res_hist['list'][0]
            secs = item.get('secs', [])
            watts = item.get('watts', [])
            wkg = item.get('watts_per_kg', [])
            act_ids = item.get('activity_id', [])
            acts_meta = res_hist.get('activities', {})

            for i, s in enumerate(secs):
                w_val = float(watts[i]) if i < len(watts) and watts[i] is not None else 0.0
                if w_val > 0:
                    curva_all_time[s] = w_val
                    curva_all_time_wkg[s] = float(wkg[i]) if i < len(wkg) and wkg[i] is not None else round(w_val / peso, 2)
                    if i < len(act_ids):
                        act_id = act_ids[i]
                        act_info = acts_meta.get(act_id, {})
                        actividades_all_time[s] = {
                            'activity_id': act_id,
                            'nombre': act_info.get('name', 'Actividad'),
                            'fecha': str(act_info.get('start_date_local') or act_info.get('start_date') or '')[:10]
                        }
    except Exception as e:
        print(f"⚠️ Error al obtener curva de potencia histórica para {aid}: {e}")

    # 2. Curva de Temporada Actual
    curva_temporada = {}
    curva_temporada_wkg = {}
    actividades_temporada = {}

    try:
        curva_temp_str = f"r.{year_act}-01-01.{year_act}-12-31"
        res_temp = client.get_athlete_power_curves(aid, date_curves=curva_temp_str)
        if res_temp and 'list' in res_temp and res_temp['list']:
            item_t = res_temp['list'][0]
            secs_t = item_t.get('secs', [])
            watts_t = item_t.get('watts', [])
            wkg_t = item_t.get('watts_per_kg', [])
            act_ids_t = item_t.get('activity_id', [])
            acts_meta_t = res_temp.get('activities', {})

            for i, s in enumerate(secs_t):
                w_val = float(watts_t[i]) if i < len(watts_t) and watts_t[i] is not None else 0.0
                if w_val > 0:
                    curva_temporada[s] = w_val
                    curva_temporada_wkg[s] = float(wkg_t[i]) if i < len(wkg_t) and wkg_t[i] is not None else round(w_val / peso, 2)
                    if i < len(act_ids_t):
                        act_id = act_ids_t[i]
                        act_info = acts_meta_t.get(act_id, {})
                        actividades_temporada[s] = {
                            'activity_id': act_id,
                            'nombre': act_info.get('name', 'Actividad'),
                            'fecha': str(act_info.get('start_date_local') or act_info.get('start_date') or '')[:10]
                        }
    except Exception:
        pass

    # 3. Resolver y asociar kilojulios de desgaste histórico con caché persistente
    try:
        if client and actividades_all_time:
            resolver_kj_actividades_historicas(client, actividades_all_time, peso_kg=peso)
        if client and actividades_temporada:
            resolver_kj_actividades_historicas(client, actividades_temporada, peso_kg=peso)
    except Exception:
        pass

    curva_all_time_kj = {s: info.get('kj_previos') for s, info in actividades_all_time.items() if info.get('kj_previos') is not None}
    curva_temporada_kj = {s: info.get('kj_previos') for s, info in actividades_temporada.items() if info.get('kj_previos') is not None}

    disponible = bool(curva_all_time or curva_temporada)
    return {
        'disponible': disponible,
        'atleta_id': aid,
        'peso_kg': peso,
        'all_time': {
            'curva': curva_all_time,
            'curva_wkg': curva_all_time_wkg,
            'curva_kj': curva_all_time_kj,
            'actividades': actividades_all_time
        },
        'temporada': {
            'curva': curva_temporada,
            'curva_wkg': curva_temporada_wkg,
            'curva_kj': curva_temporada_kj,
            'actividades': actividades_temporada
        }
    }


def comparar_curva_actividad_con_referencia(
    picos_actividad: Union[Dict[int, float], Dict[int, Dict[str, Any]]],
    curva_referencia: Dict[int, float],
    peso_kg: float = 70.0,
    duraciones_obj: Optional[Dict[int, str]] = None,
    actividades_meta: Optional[Dict[int, Dict]] = None
) -> List[Dict[str, Any]]:
    """
    Construye la comparativa entre los picos de potencia de la actividad y la curva de referencia (PR).
    Devuelve una lista de registros para cada duración con W, W/kg, % PR, delta vatios,
    kilojulios gastados antes del esfuerzo (etapa vs récord histórico) y badges de durabilidad.
    """
    if duraciones_obj is None:
        duraciones_obj = DEFAULT_POWER_DURATION_CURVE_DURATIONS

    peso = max(1.0, float(peso_kg) if peso_kg and peso_kg > 0 else 70.0)
    actividades_meta = actividades_meta or {}

    comparativa = []
    for seg, etiqueta in duraciones_obj.items():
        val_act = picos_actividad.get(seg, 0.0) if picos_actividad else 0.0
        if isinstance(val_act, dict):
            w_act = float(val_act.get('watts', 0.0))
            kj_act = val_act.get('kj_previos')
            kjkg_act = val_act.get('kjkg_previos')
            tiempo_act = val_act.get('tiempo_inicio_str', '')
            pct_etapa_act = val_act.get('pct_etapa')
        else:
            w_act = float(val_act) if val_act is not None else 0.0
            kj_act = None
            kjkg_act = None
            tiempo_act = ''
            pct_etapa_act = None

        w_ref = float(curva_referencia.get(seg, 0.0)) if curva_referencia else 0.0

        wkg_act = round(w_act / peso, 2) if w_act > 0 else 0.0
        wkg_ref = round(w_ref / peso, 2) if w_ref > 0 else 0.0

        if w_ref > 0 and w_act > 0:
            pct_pr = round((w_act / w_ref) * 100.0, 1)
            delta_w = round(w_act - w_ref, 1)
            delta_wkg = round(wkg_act - wkg_ref, 2)
            es_pr = bool(w_act >= w_ref)
        elif w_act > 0 and w_ref == 0:
            pct_pr = 100.0
            delta_w = 0.0
            delta_wkg = 0.0
            es_pr = True
        else:
            pct_pr = 0.0
            delta_w = 0.0
            delta_wkg = 0.0
            es_pr = False

        meta = actividades_meta.get(seg, {})
        fecha_rec = meta.get('fecha', '')
        nombre_rec = meta.get('nombre', '')
        kj_ref = meta.get('kj_previos')
        kjkg_ref = meta.get('kjkg_previos')
        tiempo_ref = meta.get('tiempo_hms', '')

        # Comparativa de fatiga previa entre etapa y récord
        delta_kj = round(kj_act - kj_ref, 1) if (kj_act is not None and kj_ref is not None) else None
        delta_kjkg = round(kjkg_act - kjkg_ref, 1) if (kjkg_act is not None and kjkg_ref is not None) else None

        # Determinar nivel tradicional de vatios
        if es_pr and w_act > 0:
            nivel = 'pr'
            badge_texto = '🏆 PR'
            badge_color = '#10b981'  # Esmeralda
        elif pct_pr >= 95.0:
            nivel = 'top'
            badge_texto = f'{pct_pr:.1f}% PR'
            badge_color = '#10b981'
        elif pct_pr >= 85.0:
            nivel = 'alto'
            badge_texto = f'{pct_pr:.1f}% PR'
            badge_color = '#f59e0b'  # Ámbar
        elif pct_pr > 0:
            nivel = 'medio'
            badge_texto = f'{pct_pr:.1f}% PR'
            badge_color = '#64748b'  # Slate
        else:
            nivel = 'sin_datos'
            badge_texto = '--'
            badge_color = '#94a3b8'

        # Determinar distintivo de durabilidad y fatiga
        if es_pr and w_act > 0 and kj_act is not None and kj_act >= 1500.0:
            badge_durabilidad = '🏆 PR en Fatiga'
            badge_durabilidad_tipo = 'pr_fatiga'
            badge_durabilidad_color = '#10b981'
        elif pct_pr >= 95.0 and delta_kj is not None and delta_kj > 500.0:
            badge_durabilidad = '🔥 Top bajo Fatiga'
            badge_durabilidad_tipo = 'top_fatiga'
            badge_durabilidad_color = '#ec4899'
        elif kj_act is not None and (kj_act >= 2500.0 or (kjkg_act is not None and kjkg_act >= 35.0)):
            badge_durabilidad = '⚡ Alta Carga'
            badge_durabilidad_tipo = 'alta_carga'
            badge_durabilidad_color = '#f59e0b'
        elif kj_act is not None and kj_act < 1000.0 and w_act > 0:
            badge_durabilidad = '❄️ Esfuerzo Fresco'
            badge_durabilidad_tipo = 'fresco'
            badge_durabilidad_color = '#38bdf8'
        elif w_act > 0:
            badge_durabilidad = '🚴 Rendimiento'
            badge_durabilidad_tipo = 'normal'
            badge_durabilidad_color = '#94a3b8'
        else:
            badge_durabilidad = '--'
            badge_durabilidad_tipo = 'sin_datos'
            badge_durabilidad_color = '#64748b'

        comparativa.append({
            'segundos': seg,
            'etiqueta': etiqueta,
            'vatios_act': round(w_act, 1),
            'wkg_act': wkg_act,
            'kj_act': kj_act,
            'kjkg_act': kjkg_act,
            'tiempo_act': tiempo_act,
            'pct_etapa_act': pct_etapa_act,
            'vatios_ref': round(w_ref, 1),
            'wkg_ref': wkg_ref,
            'kj_ref': kj_ref,
            'kjkg_ref': kjkg_ref,
            'tiempo_ref': tiempo_ref,
            'pct_pr': pct_pr,
            'delta_w': delta_w,
            'delta_wkg': delta_wkg,
            'delta_kj': delta_kj,
            'delta_kjkg': delta_kjkg,
            'es_pr': es_pr,
            'nivel': nivel,
            'badge_texto': badge_texto,
            'badge_color': badge_color,
            'badge_durabilidad': badge_durabilidad,
            'badge_durabilidad_tipo': badge_durabilidad_tipo,
            'badge_durabilidad_color': badge_durabilidad_color,
            'fecha_record': fecha_rec,
            'actividad_record': nombre_rec
        })


    return comparativa


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
    todos_atletas = [a for a in peaks_df['athlete_name'].dropna().unique() if a]
    if not todos_atletas:
        return pd.DataFrame(), pd.DataFrame()

    def _construir_tabla(watts_col, wkg_col, fecha_col, es_reciente=False):
        tabla_watts = peaks_df.pivot_table(
            index='duration_label', columns='athlete_name', values=watts_col, aggfunc='max'
        ).reindex(index=orden_duraciones, columns=todos_atletas)
        tabla_wkg = peaks_df.pivot_table(
            index='duration_label', columns='athlete_name', values=wkg_col, aggfunc='max'
        ).reindex(index=orden_duraciones, columns=todos_atletas)

        subset_fecha = peaks_df.dropna(subset=[watts_col])
        if not subset_fecha.empty:
            tabla_fecha = (
                subset_fecha.sort_values(watts_col, ascending=False)
                .drop_duplicates(subset=['duration_label', 'athlete_name'])
                .pivot_table(
                    index='duration_label', columns='athlete_name', values=fecha_col, aggfunc='first'
                )
                .reindex(index=orden_duraciones, columns=todos_atletas)
            )
        else:
            tabla_fecha = pd.DataFrame(index=orden_duraciones, columns=todos_atletas)

        tabla_hist_w = peaks_df.pivot_table(
            index='duration_label', columns='athlete_name', values='all_time_watts', aggfunc='max'
        ).reindex(index=orden_duraciones, columns=todos_atletas)

        tabla = tabla_watts.copy().astype(object)
        for fila in tabla.index:
            for columna in tabla.columns:
                watts = tabla_watts.loc[fila, columna]
                wkg = tabla_wkg.loc[fila, columna]
                fecha = tabla_fecha.loc[fila, columna] if columna in tabla_fecha.columns else None
                fecha_str = f"\n({fecha})" if fecha and not (isinstance(fecha, float) and pd.isna(fecha)) else ""

                pr_tag = ""
                if es_reciente and pd.notna(watts):
                    hist_w = tabla_hist_w.loc[fila, columna] if columna in tabla_hist_w.columns else None
                    if pd.notna(hist_w) and float(hist_w) > 0:
                        pct = (float(watts) / float(hist_w)) * 100.0
                        if float(watts) >= float(hist_w):
                            pr_tag = " (🏆PR)"
                        else:
                            pr_tag = f" ({pct:.0f}% PR)"

                if pd.isna(watts) and pd.isna(wkg):
                    tabla.loc[fila, columna] = ''
                elif pd.isna(watts):
                    tabla.loc[fila, columna] = f"{wkg:.1f} W/kg{fecha_str}"
                elif pd.isna(wkg):
                    tabla.loc[fila, columna] = f"{int(watts)} W{pr_tag}{fecha_str}"
                else:
                    tabla.loc[fila, columna] = f"{int(watts)} W | {wkg:.1f} W/kg{pr_tag}{fecha_str}"
        return tabla

    tabla_30_dias = _construir_tabla('peak_watts', 'peak_wkg', 'peak_date', es_reciente=True)
    tabla_historica = _construir_tabla('all_time_watts', 'all_time_wkg', 'all_time_date', es_reciente=False)

    columnas_juntas = []
    for ciclista in todos_atletas:
        columnas_juntas.extend([(ciclista, '30 dias'), (ciclista, 'historico')])

    if not columnas_juntas:
        return pd.DataFrame(), pd.DataFrame()

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
    for ciclista in todos_atletas:
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
            if reciente_w >= historico_w:
                colores_tabla.loc[duracion, columna_reciente] = 'background-color: #dcfce7; color: #166534; font-weight: bold'  # Verde PR
            elif reciente_w >= historico_w * 0.95:
                colores_tabla.loc[duracion, columna_reciente] = 'background-color: #ecfdf5; color: #047857'  # Verde menta
            elif reciente_w >= historico_w * 0.85:
                colores_tabla.loc[duracion, columna_reciente] = 'background-color: #fef3c7; color: #92400e'  # Ámbar suave
            else:
                colores_tabla.loc[duracion, columna_reciente] = 'background-color: #fee2e2; color: #991b1b'  # Rojo suave

    return tabla_peaks, colores_tabla
