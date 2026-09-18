"""
Módulo de Gestión de Histórico y Persistencia Ultraligera (SQLite Database).
Permite almacenar y consultar instantáneamente resúmenes de etapas, gastos metabólicos
acumulados en carreras y mejores picos de potencia/torque de la temporada con contexto de fatiga.
"""

import sys
from pathlib import Path

# Permitir ejecución modular o directa
_ROOT_DIR = Path(__file__).resolve().parent.parent
if str(_ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(_ROOT_DIR))

import json
import sqlite3
import re
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Union
import pandas as pd

try:
    from config import HISTORY_DB_PATH, DATA_DIR
except (ImportError, ValueError):
    from ..config import HISTORY_DB_PATH, DATA_DIR


from contextlib import contextmanager


def _obtener_db_path(db_path: Optional[Union[str, Path]] = None) -> Path:
    """Devuelve la ruta resuelta a la base de datos SQLite."""
    if db_path is not None:
        p = Path(db_path)
    else:
        p = Path(HISTORY_DB_PATH)
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


@contextmanager
def _conectar_db(path: Path):
    """Context manager que garantiza el cierre limpio de la conexión SQLite en Windows."""
    conn = sqlite3.connect(path)
    try:
        yield conn
    finally:
        conn.close()


def init_history_db(db_path: Optional[Union[str, Path]] = None) -> Path:
    """
    Inicializa el esquema relacional con tablas e índices optimizados en SQLite.
    Aplica WAL (Write-Ahead Logging) y claves foráneas para máximo rendimiento y consistencia.
    """
    path = _obtener_db_path(db_path)

    with _conectar_db(path) as conn:
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        conn.execute("PRAGMA foreign_keys = ON;")
        cursor = conn.cursor()

        # 1. Tabla de Ciclistas (Directorio del equipo)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS ciclistas (
                atleta_id TEXT PRIMARY KEY,
                nombre TEXT NOT NULL,
                peso_base REAL,
                ftp_base REAL,
                crank_length_mm REAL,
                actualizado_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        # 2. Tabla de Etapas y Resumen de Actividades (Gasto energético y carga)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS etapas_resumen (
                actividad_id TEXT PRIMARY KEY,
                atleta_id TEXT NOT NULL,
                nombre_ciclista TEXT,
                carrera_id TEXT,
                nombre_carrera TEXT,
                etapa_num INTEGER DEFAULT 1,
                fecha DATE NOT NULL,
                temporada INTEGER NOT NULL,
                peso_kg REAL,
                ftp_w REAL,
                distancia_km REAL,
                desnivel_m INTEGER,
                tiempo_mov_s INTEGER,
                duracion_bruta_s INTEGER,
                vel_media_kmh REAL,
                vel_max_kmh REAL,
                pot_media_w INTEGER,
                pot_max_w INTEGER,
                np_w INTEGER,
                kj_total REAL,
                kj_kg REAL,
                kj_kg_h REAL,
                np_kj_kg_h REAL,
                tss REAL,
                tss_h REAL,
                if_val REAL,
                fc_media INTEGER,
                fc_max INTEGER,
                cadencia_media INTEGER,
                torque_media_nm REAL,
                aepf_media_n REAL,
                temp_media_c REAL,
                desglose_horas_json TEXT,
                metadata_json TEXT,
                creado_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (atleta_id) REFERENCES ciclistas(atleta_id) ON UPDATE CASCADE
            );
        """)

        # 3. Tabla de Picos de Potencia y Torque con Contexto de Fatiga
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS picos_historicos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                atleta_id TEXT NOT NULL,
                actividad_id TEXT NOT NULL,
                fecha DATE NOT NULL,
                temporada INTEGER NOT NULL,
                duracion_s INTEGER NOT NULL,
                watts INTEGER NOT NULL,
                w_kg REAL NOT NULL,
                torque_nm REAL,
                aepf_n REAL,
                kj_previos REAL DEFAULT 0.0,
                kjkg_previos REAL DEFAULT 0.0,
                kj_esfuerzo REAL DEFAULT 0.0,
                kj_totales REAL DEFAULT 0.0,
                start_index INTEGER,
                end_index INTEGER,
                FOREIGN KEY (actividad_id) REFERENCES etapas_resumen(actividad_id) ON DELETE CASCADE
            );
        """)

        # Migración dinámica idempotente para columnas de kilojulios en bases de datos existentes
        cursor.execute("PRAGMA table_info(picos_historicos);")
        cols_picos = {row[1] for row in cursor.fetchall()}
        if 'kj_esfuerzo' not in cols_picos:
            cursor.execute("ALTER TABLE picos_historicos ADD COLUMN kj_esfuerzo REAL DEFAULT 0.0;")
        if 'kj_totales' not in cols_picos:
            cursor.execute("ALTER TABLE picos_historicos ADD COLUMN kj_totales REAL DEFAULT 0.0;")
        if 'end_index' not in cols_picos:
            cursor.execute("ALTER TABLE picos_historicos ADD COLUMN end_index INTEGER;")

        # 4. Tabla de Métricas Diarias de Bienestar y Recuperación
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS wellness_diario (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                atleta_id TEXT NOT NULL,
                fecha DATE NOT NULL,
                hrv_rmssd REAL,
                fc_reposo INTEGER,
                peso_kg REAL,
                ctl REAL,
                atl REAL,
                tsb REAL,
                sueno_horas REAL,
                sueno_calidad INTEGER,
                UNIQUE(atleta_id, fecha),
                FOREIGN KEY (atleta_id) REFERENCES ciclistas(atleta_id) ON UPDATE CASCADE
            );
        """)

        # 5. Tabla de Configuración de Grupos de Carrera Activos
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS grupos_carrera (
                grupo_id INTEGER PRIMARY KEY,
                nombre_carrera TEXT NOT NULL,
                carrera_id_link TEXT,
                categoria TEXT DEFAULT 'UCI 2.Pro',
                pais TEXT DEFAULT 'España',
                fecha_inicio DATE,
                fecha_fin DATE,
                total_etapas INTEGER DEFAULT 5,
                etapa_actual INTEGER DEFAULT 1,
                notas TEXT,
                actualizado_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        # Insertar registros iniciales por defecto si la tabla está vacía
        cursor.execute("SELECT COUNT(*) FROM grupos_carrera;")
        if cursor.fetchone()[0] == 0:
            cursor.execute("""
                INSERT INTO grupos_carrera (grupo_id, nombre_carrera, carrera_id_link, categoria, pais, total_etapas, etapa_actual, notas)
                VALUES 
                (1, 'Vuelta a Burgos', 'vuelta_a_burgos', 'UCI 2.Pro', 'España', 5, 3, 'Objetivo clasificación general y etapas de montaña.'),
                (2, 'Tour of Slovenia', 'tour_of_slovenia', 'UCI 2.Pro', 'Eslovenia', 5, 2, 'Bloque de media montaña y sprints.');
            """)

        # 6. Tabla Maestra de Carreras y Calendario de Competición
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS carreras (
                carrera_id TEXT PRIMARY KEY,
                nombre_carrera TEXT NOT NULL,
                categoria TEXT DEFAULT 'UCI 2.Pro',
                pais TEXT DEFAULT 'España',
                fecha_inicio DATE NOT NULL,
                fecha_fin DATE NOT NULL,
                total_etapas INTEGER DEFAULT 1,
                etapa_actual INTEGER DEFAULT 0,
                notas TEXT,
                creado_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                actualizado_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        # 7. Tabla de Convocatorias Históricas de Ciclistas por Carrera
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS carrera_convocados (
                carrera_id TEXT NOT NULL,
                atleta_id TEXT NOT NULL,
                dorsal INTEGER,
                rol TEXT DEFAULT 'Corredor',
                notas TEXT,
                asignado_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (carrera_id, atleta_id),
                FOREIGN KEY (carrera_id) REFERENCES carreras(carrera_id) ON DELETE CASCADE
            );
        """)

        # Índices B-Tree optimizados para consultas en sub-milisegundos
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_etapas_carrera ON etapas_resumen(carrera_id, etapa_num);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_etapas_atleta_fecha ON etapas_resumen(atleta_id, fecha);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_etapas_temporada ON etapas_resumen(temporada);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_picos_atleta_duracion ON picos_historicos(atleta_id, duracion_s, watts DESC);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_picos_temporada ON picos_historicos(temporada, duracion_s, watts DESC);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_wellness_atleta ON wellness_diario(atleta_id, fecha);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_carreras_fechas ON carreras(fecha_inicio, fecha_fin);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_convocados_carrera ON carrera_convocados(carrera_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_convocados_atleta ON carrera_convocados(atleta_id);")

        # Poblado inicial de carreras si la tabla está vacía
        cursor.execute("SELECT COUNT(*) FROM carreras;")
        if cursor.fetchone()[0] == 0:
            cursor.execute("""
                INSERT INTO carreras (carrera_id, nombre_carrera, categoria, pais, fecha_inicio, fecha_fin, total_etapas, etapa_actual, notas)
                VALUES 
                ('vuelta_a_burgos_2026', 'Vuelta a Burgos 2026', 'UCI 2.Pro', 'España', '2026-08-04', '2026-08-08', 5, 3, 'Objetivo clasificación general y etapas de montaña.'),
                ('tour_of_slovenia_2026', 'Tour of Slovenia 2026', 'UCI 2.Pro', 'Eslovenia', '2026-06-17', '2026-06-21', 5, 2, 'Bloque de media montaña y sprints.'),
                ('tres_cantos_ciclismo_en_ruta', 'Tres Cantos Ciclismo en Ruta', 'Copa España', 'España', '2026-01-01', '2026-01-01', 1, 1, 'Inicio de temporada.');
            """)

        # Migración dinámica: Desvincular de carreras oficiales aquellas actividades
        # cuya fecha no coincida con las fechas oficiales de la carrera
        cursor.execute("""
            UPDATE etapas_resumen
            SET carrera_id = 'entrenamiento',
                nombre_carrera = 'Entrenamiento'
            WHERE actividad_id IN (
                SELECT e.actividad_id
                FROM etapas_resumen e
                JOIN carreras c ON LOWER(e.carrera_id) = LOWER(c.carrera_id)
                WHERE e.fecha < c.fecha_inicio OR e.fecha > c.fecha_fin
            );
        """)

        conn.commit()

    # Inicializar tablas de autenticación y asegurar usuario admin por defecto
    try:
        from src.auth_manager import init_auth_db
    except (ImportError, ValueError):
        from .auth_manager import init_auth_db
    init_auth_db(path)

    return path


def guardar_ciclista(
    atleta_id: str,
    nombre: str,
    peso: Optional[float] = None,
    ftp: Optional[float] = None,
    crank_length_mm: Optional[float] = None,
    db_path: Optional[Union[str, Path]] = None
) -> None:
    """Registra o actualiza un ciclista en la base de datos."""
    init_history_db(db_path)
    path = _obtener_db_path(db_path)

    with _conectar_db(path) as conn:
        conn.execute("""
            INSERT INTO ciclistas (atleta_id, nombre, peso_base, ftp_base, crank_length_mm, actualizado_en)
            VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(atleta_id) DO UPDATE SET
                nombre = excluded.nombre,
                peso_base = COALESCE(excluded.peso_base, ciclistas.peso_base),
                ftp_base = COALESCE(excluded.ftp_base, ciclistas.ftp_base),
                crank_length_mm = COALESCE(excluded.crank_length_mm, ciclistas.crank_length_mm),
                actualizado_en = CURRENT_TIMESTAMP;
        """, (str(atleta_id).strip(), str(nombre).strip(), peso, ftp, crank_length_mm))
        conn.commit()


def guardar_resumen_etapa(
    stats: Dict[str, Any],
    carrera_id: Optional[str] = None,
    etapa_num: int = 1,
    fecha: Optional[Union[str, datetime]] = None,
    nombre_carrera: Optional[str] = None,
    actividad_id: Optional[str] = None,
    db_path: Optional[Union[str, Path]] = None
) -> str:
    """
    Inserta o actualiza el resumen completo de una etapa o actividad en la base de datos.
    También persiste de forma automática los picos de potencia (MMP) y torque con sus kJ previos.
    """
    init_history_db(db_path)
    path = _obtener_db_path(db_path)

    atleta_id = str(stats.get('atleta_id', '')).strip()
    nombre = str(stats.get('nombre', 'Ciclista')).strip()
    if not atleta_id:
        atleta_id = f"c_{abs(hash(nombre)) % 1000000}"

    # Resolver fecha y temporada
    fecha_str = ""
    if fecha is not None:
        fecha_str = fecha.strftime('%Y-%m-%d') if isinstance(fecha, datetime) else str(fecha)
    elif stats.get('fecha'):
        fecha_str = str(stats.get('fecha'))
    else:
        fecha_str = datetime.now().strftime('%Y-%m-%d')

    try:
        temporada = int(fecha_str.split('-')[0])
    except Exception:
        temporada = datetime.now().year

    carrera_id_clean = str(carrera_id or stats.get('carrera_id') or '').strip()
    nom_carrera_clean = str(nombre_carrera or stats.get('nombre_carrera') or '').strip()

    # Si no se especificó carrera o es genérica, auto-detectar por fecha y convocatoria
    if not carrera_id_clean or carrera_id_clean.lower() in ['entrenamiento', 'act', 'carrera', 'none', 'null']:
        c_match = auto_detectar_carrera_atleta(atleta_id, fecha_str, db_path=path)
        if c_match:
            carrera_id_clean = c_match['carrera_id']
            nom_carrera_clean = nom_carrera_clean or c_match['nombre_carrera']
        else:
            carrera_id_clean = carrera_id_clean or 'entrenamiento'
            nom_carrera_clean = nom_carrera_clean or carrera_id_clean.replace('_', ' ').title()
    else:
        # Si es un número/alias (ej. "1", "2") o slug, resolver contra carreras
        c_res = resolver_carrera(carrera_id_clean, fecha=fecha_str, db_path=path)
        if c_res:
            f_ini = c_res.get('fecha_inicio')
            f_fin = c_res.get('fecha_fin')
            if f_ini and f_fin and not (str(f_ini) <= str(fecha_str) <= str(f_fin)):
                print(f"⚠️ Actividad ({fecha_str}) fuera de las fechas de la carrera '{c_res.get('nombre_carrera', carrera_id_clean)}' ({f_ini} a {f_fin}). No se asigna a datos históricos de la carrera.")
                carrera_id_clean = 'entrenamiento'
                nom_carrera_clean = 'Entrenamiento'
            else:
                carrera_id_clean = c_res['carrera_id']
                nom_carrera_clean = nom_carrera_clean or c_res['nombre_carrera']
        else:
            nom_carrera_clean = nom_carrera_clean or carrera_id_clean.replace('_', ' ').title()

    # Actividad ID única
    if not actividad_id:
        actividad_id = str(stats.get('actividad_id') or f"{atleta_id}_{carrera_id_clean}_{etapa_num}_{fecha_str}").strip()

    # Asegurar que el ciclista exista en la tabla ciclistas
    guardar_ciclista(
        atleta_id=atleta_id,
        nombre=nombre,
        peso=stats.get('peso_kg'),
        ftp=stats.get('ftp_w'),
        crank_length_mm=stats.get('crank_length_mm'),
        db_path=path
    )

    # Serializar desglose horario si existe
    desglose_json = None
    if 'desglose_horas' in stats and stats['desglose_horas']:
        try:
            desglose_json = json.dumps(stats['desglose_horas'], ensure_ascii=False)
        except Exception:
            pass

    # Metadatos auxiliares en JSON compacto
    meta_dict = {
        'posicion_str': stats.get('posicion_str', ''),
        'gap_lider_str': stats.get('gap_lider_str', ''),
        'cuadrantes': stats.get('cuadrantes', {}),
        'zonas_torque': stats.get('zonas_torque', {}),
    }
    meta_json = json.dumps(meta_dict, ensure_ascii=False)

    with _conectar_db(path) as conn:
        # Si ya existe una etapa para este ciclista en la misma fecha y carrera,
        # eliminar el registro previo y sus picos asociados para sobreescribir limpiamente.
        c = conn.cursor()
        c.execute("""
            SELECT actividad_id FROM etapas_resumen 
            WHERE atleta_id = ? AND fecha = ? AND (LOWER(carrera_id) = LOWER(?) OR LOWER(carrera_id) = 'entrenamiento' OR ? = 'entrenamiento');
        """, (atleta_id, fecha_str, carrera_id_clean, carrera_id_clean))
        prev_acts = [r[0] for r in c.fetchall()]
        for prev_id in prev_acts:
            if prev_id != actividad_id:
                conn.execute("DELETE FROM picos_historicos WHERE actividad_id = ?;", (prev_id,))
                conn.execute("DELETE FROM etapas_resumen WHERE actividad_id = ?;", (prev_id,))

        conn.execute("""
            INSERT OR REPLACE INTO etapas_resumen (
                actividad_id, atleta_id, nombre_ciclista, carrera_id, nombre_carrera,
                etapa_num, fecha, temporada, peso_kg, ftp_w, distancia_km, desnivel_m,
                tiempo_mov_s, duracion_bruta_s, vel_media_kmh, vel_max_kmh, pot_media_w,
                pot_max_w, np_w, kj_total, kj_kg, kj_kg_h, np_kj_kg_h, tss, tss_h,
                if_val, fc_media, fc_max, cadencia_media, torque_media_nm, aepf_media_n,
                temp_media_c, desglose_horas_json, metadata_json
            ) VALUES (
                ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?,
                ?, ?, ?
            );
        """, (
            actividad_id, atleta_id, nombre, carrera_id_clean, nom_carrera_clean,
            int(etapa_num), fecha_str, temporada, stats.get('peso_kg'), stats.get('ftp_w'),
            stats.get('distancia_km'), stats.get('desnivel_pos_m'),
            stats.get('tiempo_mov_seg') or stats.get('duracion_seg'),
            stats.get('duracion_bruta_seg'),
            stats.get('vel_media_kmh'), stats.get('vel_max_kmh'),
            stats.get('pot_media_w'), stats.get('pot_max_w'), stats.get('np_w'),
            stats.get('kilojulios_total'), stats.get('kj_kg'), stats.get('kj_kg_hora'),
            stats.get('np_kj_kg_hora'), stats.get('tss_total'), stats.get('tss_hora'),
            stats.get('if_val'), stats.get('fc_media_bpm'), stats.get('fc_max_bpm'),
            stats.get('cadencia_media_rpm'), stats.get('torque_media_nm'), stats.get('aepf_media_n'),
            stats.get('temp_media_c'), desglose_json, meta_json
        ))

        # Guardar los picos de potencia históricos
        curva_mmp = stats.get('curva_mmp_completa') or {}
        picos_simples = stats.get('potencia_mmp') or {}
        torque_mmt = stats.get('torque_mmt') or {}
        peso_val = float(stats.get('peso_kg') or 70.0)

        # Borrar picos previos de esta misma actividad antes de re-insertar
        conn.execute("DELETE FROM picos_historicos WHERE actividad_id = ?;", (actividad_id,))

        # Si tenemos la curva rica (con kJ previos)
        if curva_mmp:
            for dur_k, p_info in curva_mmp.items():
                if not isinstance(p_info, dict):
                    continue
                d_sec = int(dur_k)
                w_val = int(round(p_info.get('watts', 0)))
                if w_val <= 0:
                    continue
                wkg = float(p_info.get('w_kg', round(w_val / max(30.0, peso_val), 2)))
                trq_val = float(torque_mmt.get(d_sec, 0.0))
                kj_prev = float(p_info.get('kj_previos', 0.0))
                kjkg_prev = float(p_info.get('kjkg_previos', round(kj_prev / max(30.0, peso_val), 1)))
                kj_esf = round((w_val * d_sec) / 1000.0, 1)
                kj_tot = round(kj_prev + kj_esf, 1)
                s_idx = p_info.get('start_index')
                end_idx = (s_idx + d_sec) if s_idx is not None else None

                conn.execute("""
                    INSERT INTO picos_historicos (
                        atleta_id, actividad_id, fecha, temporada, duracion_s,
                        watts, w_kg, torque_nm, aepf_n, kj_previos, kjkg_previos,
                        kj_esfuerzo, kj_totales, start_index, end_index
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """, (
                    atleta_id, actividad_id, fecha_str, temporada, d_sec,
                    w_val, wkg, trq_val if trq_val > 0 else None,
                    round(trq_val / 0.170, 1) if trq_val > 0 else None,
                    kj_prev, kjkg_prev, kj_esf, kj_tot, s_idx, end_idx
                ))
        elif picos_simples:
            for dur_k, w_val in picos_simples.items():
                d_sec = int(dur_k)
                w_val = int(round(float(w_val)))
                if w_val <= 0:
                    continue
                wkg = round(w_val / max(30.0, peso_val), 2)
                trq_val = float(torque_mmt.get(d_sec, 0.0))
                kj_esf = round((w_val * d_sec) / 1000.0, 1)
                conn.execute("""
                    INSERT INTO picos_historicos (
                        atleta_id, actividad_id, fecha, temporada, duracion_s,
                        watts, w_kg, torque_nm, aepf_n, kj_previos, kjkg_previos,
                        kj_esfuerzo, kj_totales, start_index, end_index
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0.0, 0.0, ?, ?, NULL, NULL);
                """, (
                    atleta_id, actividad_id, fecha_str, temporada, d_sec,
                    w_val, wkg, trq_val if trq_val > 0 else None,
                    round(trq_val / 0.170, 1) if trq_val > 0 else None,
                    kj_esf, kj_esf
                ))

        conn.commit()

    return actividad_id


def guardar_wellness_diario(
    atleta_id: str,
    fecha: Union[str, datetime],
    wellness_data: Dict[str, Any],
    db_path: Optional[Union[str, Path]] = None
) -> None:
    """Guarda o actualiza las métricas de recuperación y fatiga matutinas (HRV, FC reposo, CTL/ATL/TSB)."""
    init_history_db(db_path)
    path = _obtener_db_path(db_path)
    fecha_str = fecha.strftime('%Y-%m-%d') if isinstance(fecha, datetime) else str(fecha)

    with _conectar_db(path) as conn:
        conn.execute("""
            INSERT INTO wellness_diario (
                atleta_id, fecha, hrv_rmssd, fc_reposo, peso_kg, ctl, atl, tsb, sueno_horas, sueno_calidad
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(atleta_id, fecha) DO UPDATE SET
                hrv_rmssd = COALESCE(excluded.hrv_rmssd, wellness_diario.hrv_rmssd),
                fc_reposo = COALESCE(excluded.fc_reposo, wellness_diario.fc_reposo),
                peso_kg = COALESCE(excluded.peso_kg, wellness_diario.peso_kg),
                ctl = COALESCE(excluded.ctl, wellness_diario.ctl),
                atl = COALESCE(excluded.atl, wellness_diario.atl),
                tsb = COALESCE(excluded.tsb, wellness_diario.tsb),
                sueno_horas = COALESCE(excluded.sueno_horas, wellness_diario.sueno_horas),
                sueno_calidad = COALESCE(excluded.sueno_calidad, wellness_diario.sueno_calidad);
        """, (
            str(atleta_id).strip(),
            fecha_str,
            wellness_data.get('hrv') or wellness_data.get('rmssd'),
            wellness_data.get('restingHR') or wellness_data.get('fc_reposo'),
            wellness_data.get('weight') or wellness_data.get('peso_kg'),
            wellness_data.get('ctl'),
            wellness_data.get('atl'),
            wellness_data.get('tsb'),
            wellness_data.get('sleepSecs', 0) / 3600.0 if wellness_data.get('sleepSecs') else None,
            wellness_data.get('sleepScore')
        ))
        conn.commit()


# =============================================================================
# MÉTODOS DE CONSULTA Y ANÁLISIS HISTÓRICO
# =============================================================================

def obtener_historico_carrera_etapas(
    carrera_id: str,
    db_path: Optional[Union[str, Path]] = None
) -> pd.DataFrame:
    """
    Devuelve la evolución etapa por etapa y el gasto energético acumulado de una carrera.
    Filtra estrictamente para considerar solo ficheros y actividades comprendidos
    dentro de las fechas oficiales de la carrera.
    Calcula dinámicamente mediante funciones de ventana SQL:
    - kj_acumulados: Kilojulios totales sumados etapa tras etapa
    - kj_kg_acumulados: kJ/kg acumulados a lo largo de la vuelta
    - tss_acumulado: Carga de fatiga total acumulada en la carrera
    - km_acumulados y desnivel_acumulado
    """
    path = _obtener_db_path(db_path)
    if not path.exists():
        return pd.DataFrame()

    c_res = resolver_carrera(carrera_id, db_path=path)
    target_carrera_id = c_res['carrera_id'] if c_res else str(carrera_id).strip()
    f_inicio = c_res.get('fecha_inicio') if c_res else None
    f_fin = c_res.get('fecha_fin') if c_res else None

    params = [target_carrera_id, str(carrera_id).strip()]
    if f_inicio and f_fin:
        filtro_fechas_sql = "AND e.fecha >= ? AND e.fecha <= ?"
        params.extend([str(f_inicio), str(f_fin)])
    else:
        filtro_fechas_sql = "AND (car.fecha_inicio IS NULL OR (e.fecha >= car.fecha_inicio AND e.fecha <= car.fecha_fin))"

    query = f"""
        SELECT
            e.atleta_id,
            COALESCE(c.nombre, e.nombre_ciclista) AS nombre,
            e.carrera_id,
            e.nombre_carrera,
            e.etapa_num,
            e.fecha,
            e.distancia_km,
            e.desnivel_m,
            e.tiempo_mov_s,
            ROUND(e.tiempo_mov_s / 3600.0, 2) AS tiempo_mov_h,
            e.pot_media_w,
            e.np_w,
            e.kj_total,
            e.kj_kg,
            e.kj_kg_h,
            e.np_kj_kg_h,
            e.tss,
            e.tss_h,
            e.if_val,
            e.fc_media,
            e.cadencia_media,
            e.torque_media_nm,
            -- Métricas acumuladas en la carrera
            ROUND(SUM(e.kj_total) OVER (PARTITION BY e.atleta_id ORDER BY e.etapa_num, e.fecha), 1) AS kj_acumulados,
            ROUND(SUM(e.kj_kg) OVER (PARTITION BY e.atleta_id ORDER BY e.etapa_num, e.fecha), 1) AS kj_kg_acumulados,
            ROUND(SUM(e.tss) OVER (PARTITION BY e.atleta_id ORDER BY e.etapa_num, e.fecha), 1) AS tss_acumulado,
            ROUND(SUM(e.distancia_km) OVER (PARTITION BY e.atleta_id ORDER BY e.etapa_num, e.fecha), 1) AS km_acumulados,
            SUM(e.desnivel_m) OVER (PARTITION BY e.atleta_id ORDER BY e.etapa_num, e.fecha) AS desnivel_acumulado
        FROM etapas_resumen e
        LEFT JOIN ciclistas c ON e.atleta_id = c.atleta_id
        LEFT JOIN carreras car ON LOWER(car.carrera_id) = LOWER(e.carrera_id)
        WHERE (LOWER(e.carrera_id) = LOWER(?) OR LOWER(e.carrera_id) = LOWER(?))
        {filtro_fechas_sql}
        ORDER BY e.atleta_id, e.etapa_num ASC, e.fecha ASC;
    """

    with _conectar_db(path) as conn:
        df = pd.read_sql_query(query, conn, params=params)
    return df


def obtener_resumen_acumulado_carrera(
    carrera_id: str,
    db_path: Optional[Union[str, Path]] = None
) -> pd.DataFrame:
    """
    Devuelve la tabla resumen final por ciclista al término de la carrera por etapas,
    ordenada por mayor gasto energético total (kJ).
    Filtra estrictamente para considerar solo ficheros y actividades dentro de las fechas oficiales de carrera.
    """
    path = _obtener_db_path(db_path)
    if not path.exists():
        return pd.DataFrame()

    c_res = resolver_carrera(carrera_id, db_path=path)
    target_carrera_id = c_res['carrera_id'] if c_res else str(carrera_id).strip()
    f_inicio = c_res.get('fecha_inicio') if c_res else None
    f_fin = c_res.get('fecha_fin') if c_res else None

    params = [target_carrera_id, str(carrera_id).strip()]
    if f_inicio and f_fin:
        filtro_fechas_sql = "AND e.fecha >= ? AND e.fecha <= ?"
        params.extend([str(f_inicio), str(f_fin)])
    else:
        filtro_fechas_sql = "AND (car.fecha_inicio IS NULL OR (e.fecha >= car.fecha_inicio AND e.fecha <= car.fecha_fin))"

    query = f"""
        SELECT
            e.atleta_id,
            COALESCE(c.nombre, e.nombre_ciclista) AS nombre,
            COUNT(e.actividad_id) AS etapas_disputadas,
            ROUND(SUM(e.distancia_km), 1) AS total_km,
            SUM(e.desnivel_m) AS total_desnivel_m,
            ROUND(SUM(e.tiempo_mov_s) / 3600.0, 1) AS total_horas,
            ROUND(SUM(e.kj_total), 0) AS total_kj,
            ROUND(SUM(e.kj_kg), 1) AS total_kj_kg,
            ROUND(AVG(e.kj_kg_h), 1) AS media_kj_kg_h,
            ROUND(SUM(e.tss), 0) AS total_tss,
            ROUND(AVG(e.np_w), 0) AS media_np_w,
            ROUND(AVG(e.if_val), 2) AS media_if
        FROM etapas_resumen e
        LEFT JOIN ciclistas c ON e.atleta_id = c.atleta_id
        LEFT JOIN carreras car ON LOWER(car.carrera_id) = LOWER(e.carrera_id)
        WHERE (LOWER(e.carrera_id) = LOWER(?) OR LOWER(e.carrera_id) = LOWER(?))
        {filtro_fechas_sql}
        GROUP BY e.atleta_id
        ORDER BY total_kj DESC;
    """

    with _conectar_db(path) as conn:
        df = pd.read_sql_query(query, conn, params=params)
    return df


def obtener_config_grupos_carrera(db_path: Optional[Union[str, Path]] = None) -> List[Dict[str, Any]]:
    """Devuelve la configuración y metadatos de los grupos de carrera activos."""
    path = _obtener_db_path(db_path)
    init_history_db(path)

    query = """
        SELECT grupo_id, nombre_carrera, carrera_id_link, categoria, pais,
               fecha_inicio, fecha_fin, total_etapas, etapa_actual, notas, actualizado_en
        FROM grupos_carrera
        ORDER BY grupo_id ASC;
    """
    with _conectar_db(path) as conn:
        cursor = conn.cursor()
        cursor.execute(query)
        rows = cursor.fetchall()
        grupos = []
        for r in rows:
            grupos.append({
                "grupo_id": r[0],
                "nombre_carrera": r[1],
                "carrera_id_link": r[2] or "",
                "categoria": r[3] or "UCI 2.Pro",
                "pais": r[4] or "España",
                "fecha_inicio": r[5] or "",
                "fecha_fin": r[6] or "",
                "total_etapas": r[7] or 5,
                "etapa_actual": r[8] or 1,
                "notas": r[9] or "",
                "actualizado_en": r[10]
            })
    return grupos


def guardar_config_grupo_carrera(
    grupo_id: int,
    datos: Dict[str, Any],
    db_path: Optional[Union[str, Path]] = None
) -> bool:
    """Guarda o actualiza la información y carrera asignada a un grupo."""
    path = _obtener_db_path(db_path)
    init_history_db(path)

    query = """
        INSERT INTO grupos_carrera (
            grupo_id, nombre_carrera, carrera_id_link, categoria, pais,
            fecha_inicio, fecha_fin, total_etapas, etapa_actual, notas, actualizado_en
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(grupo_id) DO UPDATE SET
            nombre_carrera = excluded.nombre_carrera,
            carrera_id_link = excluded.carrera_id_link,
            categoria = excluded.categoria,
            pais = excluded.pais,
            fecha_inicio = excluded.fecha_inicio,
            fecha_fin = excluded.fecha_fin,
            total_etapas = excluded.total_etapas,
            etapa_actual = excluded.etapa_actual,
            notas = excluded.notas,
            actualizado_en = CURRENT_TIMESTAMP;
    """
    with _conectar_db(path) as conn:
        conn.execute(query, (
            int(grupo_id),
            str(datos.get("nombre_carrera", f"Grupo Carrera {grupo_id}")),
            datos.get("carrera_id_link") or None,
            str(datos.get("categoria", "UCI 2.Pro")),
            str(datos.get("pais", "España")),
            datos.get("fecha_inicio") or None,
            datos.get("fecha_fin") or None,
            int(datos.get("total_etapas", 5)),
            int(datos.get("etapa_actual", 1)),
            datos.get("notas", "")
        ))
        conn.commit()
    return True


# =============================================================================
# GESTIÓN INTEGRAL DE CALENDARIO DE CARRERAS Y CONVOCATORIAS
# =============================================================================

def guardar_carrera(
    datos: Dict[str, Any],
    atletas_ids: Optional[List[str]] = None,
    db_path: Optional[Union[str, Path]] = None
) -> str:
    """Crea o actualiza una carrera y opcionalmente su convocatoria de ciclistas."""
    path = _obtener_db_path(db_path)
    init_history_db(path)

    nombre = str(datos.get('nombre_carrera') or datos.get('nombre') or 'Nueva Carrera').strip()
    carrera_id = str(datos.get('carrera_id') or '').strip()
    if not carrera_id:
        carrera_id = re.sub(r'[^a-z0-9]+', '_', nombre.lower()).strip('_')
        if not carrera_id:
            carrera_id = f"carrera_{int(datetime.now().timestamp())}"

    categoria = str(datos.get('categoria') or 'UCI 2.Pro').strip()
    pais = str(datos.get('pais') or 'España').strip()
    f_inicio = str(datos.get('fecha_inicio') or datetime.now().strftime('%Y-%m-%d')).strip()
    f_fin = str(datos.get('fecha_fin') or f_inicio).strip()
    total_etapas = int(datos.get('total_etapas') or 1)
    etapa_actual = int(datos.get('etapa_actual') or 0)
    notas = str(datos.get('notas') or '').strip()

    with _conectar_db(path) as conn:
        conn.execute("""
            INSERT INTO carreras (
                carrera_id, nombre_carrera, categoria, pais, fecha_inicio, fecha_fin,
                total_etapas, etapa_actual, notas, actualizado_en
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(carrera_id) DO UPDATE SET
                nombre_carrera = excluded.nombre_carrera,
                categoria = excluded.categoria,
                pais = excluded.pais,
                fecha_inicio = excluded.fecha_inicio,
                fecha_fin = excluded.fecha_fin,
                total_etapas = excluded.total_etapas,
                etapa_actual = excluded.etapa_actual,
                notas = excluded.notas,
                actualizado_en = CURRENT_TIMESTAMP;
        """, (carrera_id, nombre, categoria, pais, f_inicio, f_fin, total_etapas, etapa_actual, notas))

        if atletas_ids is not None:
            conn.execute("DELETE FROM carrera_convocados WHERE carrera_id = ?;", (carrera_id,))
            for aid in atletas_ids:
                aid_clean = str(aid).strip()
                if aid_clean:
                    conn.execute("""
                        INSERT OR IGNORE INTO carrera_convocados (carrera_id, atleta_id)
                        VALUES (?, ?);
                    """, (carrera_id, aid_clean))

        conn.commit()

    return carrera_id


def eliminar_carrera(carrera_id: str, db_path: Optional[Union[str, Path]] = None) -> bool:
    """Elimina una carrera y su convocatoria asociada."""
    path = _obtener_db_path(db_path)
    cid = str(carrera_id).strip()
    with _conectar_db(path) as conn:
        conn.execute("DELETE FROM carrera_convocados WHERE carrera_id = ?;", (cid,))
        conn.execute("DELETE FROM carreras WHERE carrera_id = ?;", (cid,))
        conn.commit()
    return True


def asignar_convocados_carrera(
    carrera_id: str,
    atletas_ids: List[str],
    db_path: Optional[Union[str, Path]] = None
) -> bool:
    """Actualiza la lista de ciclistas convocados para una carrera."""
    path = _obtener_db_path(db_path)
    init_history_db(path)
    cid = str(carrera_id).strip()

    with _conectar_db(path) as conn:
        conn.execute("DELETE FROM carrera_convocados WHERE carrera_id = ?;", (cid,))
        for aid in atletas_ids:
            aid_clean = str(aid).strip()
            if aid_clean:
                conn.execute("""
                    INSERT OR IGNORE INTO carrera_convocados (carrera_id, atleta_id)
                    VALUES (?, ?);
                """, (cid, aid_clean))
        conn.commit()
    return True


def obtener_convocados_carrera(
    carrera_id: str,
    db_path: Optional[Union[str, Path]] = None
) -> List[Dict[str, Any]]:
    """Devuelve la lista detallada de ciclistas convocados para una carrera."""
    path = _obtener_db_path(db_path)
    init_history_db(path)
    cid = str(carrera_id).strip()

    query = """
        SELECT
            cc.atleta_id,
            COALESCE(c.nombre, cc.atleta_id) AS nombre,
            c.peso_base AS peso,
            c.ftp_base AS ftp,
            cc.dorsal,
            cc.rol,
            cc.notas
        FROM carrera_convocados cc
        LEFT JOIN ciclistas c ON cc.atleta_id = c.atleta_id
        WHERE cc.carrera_id = ?
        ORDER BY cc.dorsal ASC, nombre ASC;
    """
    with _conectar_db(path) as conn:
        cursor = conn.cursor()
        cursor.execute(query, (cid,))
        rows = cursor.fetchall()
        convocados = []
        for r in rows:
            convocados.append({
                "atleta_id": r[0],
                "nombre": r[1],
                "name": r[1],
                "peso": r[2] or 70.0,
                "ftp": r[3] or 380.0,
                "dorsal": r[4],
                "rol": r[5] or "Corredor",
                "notas": r[6] or ""
            })
    return convocados


def obtener_carreras_calendario(
    filtro_estado: Optional[str] = None,
    fecha_referencia: Optional[str] = None,
    db_path: Optional[Union[str, Path]] = None
) -> List[Dict[str, Any]]:
    """
    Devuelve la lista completa de carreras del calendario con su convocatoria y métricas agregadas.
    Calcula el estado ('en_curso', 'proxima', 'finalizada') relativo a fecha_referencia.
    """
    path = _obtener_db_path(db_path)
    init_history_db(path)

    hoy = fecha_referencia or datetime.now().strftime('%Y-%m-%d')

    query = """
        SELECT
            c.carrera_id,
            c.nombre_carrera,
            c.categoria,
            c.pais,
            c.fecha_inicio,
            c.fecha_fin,
            c.total_etapas,
            c.etapa_actual,
            c.notas,
            c.creado_en,
            COALESCE(SUM(e.distancia_km), 0.0) AS dist_total_km,
            COALESCE(SUM(e.kj_total), 0.0) AS kj_totales,
            COUNT(DISTINCT e.etapa_num) AS num_etapas_disputadas
        FROM carreras c
        LEFT JOIN etapas_resumen e ON (
            e.carrera_id = c.carrera_id OR LOWER(e.carrera_id) = LOWER(c.carrera_id)
        )
        GROUP BY c.carrera_id
        ORDER BY c.fecha_inicio ASC;
    """

    with _conectar_db(path) as conn:
        cursor = conn.cursor()
        cursor.execute(query)
        rows = cursor.fetchall()

        carreras = []
        for r in rows:
            cid = r[0]
            f_inicio = r[4]
            f_fin = r[5]
            tot_etapas = r[6] or 1
            et_actual = r[7] or 0

            # Estado dinámico por fecha
            if f_inicio <= hoy <= f_fin:
                estado = 'en_curso'
                estado_label = 'En Competición'
            elif f_inicio > hoy:
                estado = 'proxima'
                estado_label = 'Próxima'
            else:
                estado = 'finalizada'
                estado_label = 'Finalizada'

            if filtro_estado and estado != filtro_estado:
                continue

            # Obtener convocados
            conv_cursor = conn.cursor()
            conv_cursor.execute("""
                SELECT cc.atleta_id, COALESCE(ci.nombre, cc.atleta_id) as nombre, cc.rol, cc.dorsal
                FROM carrera_convocados cc
                LEFT JOIN ciclistas ci ON cc.atleta_id = ci.atleta_id
                WHERE cc.carrera_id = ?
                ORDER BY cc.dorsal ASC, nombre ASC;
            """, (cid,))
            conv_rows = conv_cursor.fetchall()
            convocados = [{
                "atleta_id": cr[0],
                "nombre": cr[1],
                "name": cr[1],
                "rol": cr[2] or "Corredor",
                "dorsal": cr[3]
            } for cr in conv_rows]

            progreso_pct = min(100, int(round((et_actual / max(1, tot_etapas)) * 100)))

            carreras.append({
                "carrera_id": cid,
                "nombre_carrera": r[1],
                "categoria": r[2] or "UCI 2.Pro",
                "pais": r[3] or "España",
                "fecha_inicio": f_inicio,
                "fecha_fin": f_fin,
                "total_etapas": tot_etapas,
                "etapa_actual": et_actual,
                "progreso_pct": progreso_pct,
                "estado": estado,
                "estado_label": estado_label,
                "notas": r[8] or "",
                "dist_total_km": round(float(r[10] or 0.0), 1),
                "kj_totales": int(round(float(r[11] or 0.0))),
                "num_etapas_disputadas": r[12] or 0,
                "num_convocados": len(convocados),
                "convocados": convocados
            })

    def orden_carrera(item):
        if item["estado"] == "en_curso":
            return (0, item["fecha_inicio"])
        elif item["estado"] == "proxima":
            return (1, item["fecha_inicio"])
        else:
            return (2, item["fecha_fin"])

    carreras.sort(key=orden_carrera)
    return carreras


def obtener_carrera_detalle(
    carrera_id: str,
    fecha_referencia: Optional[str] = None,
    db_path: Optional[Union[str, Path]] = None
) -> Optional[Dict[str, Any]]:
    """Devuelve la información detallada de una carrera particular y su nómina de convocados."""
    carreras = obtener_carreras_calendario(fecha_referencia=fecha_referencia, db_path=db_path)
    for c in carreras:
        if c["carrera_id"].lower() == str(carrera_id).strip().lower():
            return c
    return None


def obtener_carreras_activas_fecha(
    fecha: Optional[str] = None,
    db_path: Optional[Union[str, Path]] = None
) -> List[Dict[str, Any]]:
    """Devuelve las carreras que están en disputa en una fecha determinada (por defecto hoy)."""
    path = _obtener_db_path(db_path)
    init_history_db(path)
    f_ref = str(fecha or datetime.now().strftime('%Y-%m-%d')).strip()[:10]

    with _conectar_db(path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT carrera_id, nombre_carrera, categoria, pais, fecha_inicio, fecha_fin, total_etapas, etapa_actual, notas
            FROM carreras
            WHERE fecha_inicio <= ? AND fecha_fin >= ?
            ORDER BY fecha_inicio ASC, nombre_carrera ASC;
        """, (f_ref, f_ref))
        rows = cursor.fetchall()
        carreras = []
        for r in rows:
            cid = r[0]
            conv_cursor = conn.cursor()
            conv_cursor.execute("""
                SELECT cc.atleta_id, COALESCE(ci.nombre, cc.atleta_id) as nombre, cc.rol, cc.dorsal
                FROM carrera_convocados cc
                LEFT JOIN ciclistas ci ON cc.atleta_id = ci.atleta_id
                WHERE cc.carrera_id = ?
                ORDER BY cc.dorsal ASC, nombre ASC;
            """, (cid,))
            conv = [{"atleta_id": cr[0], "nombre": cr[1], "name": cr[1], "rol": cr[2], "dorsal": cr[3]} for cr in conv_cursor.fetchall()]
            carreras.append({
                "carrera_id": cid,
                "nombre_carrera": r[1],
                "categoria": r[2] or "UCI 2.Pro",
                "pais": r[3] or "España",
                "fecha_inicio": r[4],
                "fecha_fin": r[5],
                "total_etapas": r[6] or 1,
                "etapa_actual": r[7] or 0,
                "notas": r[8] or "",
                "convocados": conv,
                "num_convocados": len(conv)
            })
    return carreras


def resolver_carrera(
    carrera_ref: Optional[Union[str, int]] = None,
    fecha: Optional[str] = None,
    db_path: Optional[Union[str, Path]] = None
) -> Optional[Dict[str, Any]]:
    """
    Resuelve una referencia a carrera (id, slug, nombre o alias numérico tipo 1 o 2).
    Si se pasa un número (ej. 1), devuelve la N-ésima carrera activa en esa fecha (o en el calendario).
    """
    if carrera_ref is None:
        return None

    path = _obtener_db_path(db_path)
    init_history_db(path)

    ref_str = str(carrera_ref).strip()
    if not ref_str:
        return None

    # Caso 1: Es un número entero o alias (1, 2, etc.)
    if ref_str.isdigit():
        num = int(ref_str)
        if num > 0:
            activas = obtener_carreras_activas_fecha(fecha=fecha, db_path=path)
            if 0 < num <= len(activas):
                return activas[num - 1]

            # Si no hay activas en la fecha exacta, buscar en el calendario ordenado por fecha
            todas = obtener_carreras_calendario(db_path=path)
            if 0 < num <= len(todas):
                return todas[num - 1]

    # Caso 2: Es un slug o nombre de carrera
    ref_norm = ref_str.lower()
    with _conectar_db(path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT carrera_id, nombre_carrera, categoria, pais, fecha_inicio, fecha_fin, total_etapas, etapa_actual, notas
            FROM carreras
            WHERE LOWER(carrera_id) = ?;
        """, (ref_norm,))
        row = cursor.fetchone()

        if not row:
            cursor.execute("""
                SELECT carrera_id, nombre_carrera, categoria, pais, fecha_inicio, fecha_fin, total_etapas, etapa_actual, notas
                FROM carreras
                WHERE LOWER(nombre_carrera) LIKE ? OR LOWER(carrera_id) LIKE ?
                ORDER BY fecha_inicio DESC
                LIMIT 1;
            """, (f"%{ref_norm}%", f"%{ref_norm}%"))
            row = cursor.fetchone()

        if row:
            cid = row[0]
            conv_cursor = conn.cursor()
            conv_cursor.execute("""
                SELECT cc.atleta_id, COALESCE(ci.nombre, cc.atleta_id) as nombre, cc.rol, cc.dorsal
                FROM carrera_convocados cc
                LEFT JOIN ciclistas ci ON cc.atleta_id = ci.atleta_id
                WHERE cc.carrera_id = ?
                ORDER BY cc.dorsal ASC, nombre ASC;
            """, (cid,))
            conv = [{"atleta_id": cr[0], "nombre": cr[1], "name": cr[1], "rol": cr[2], "dorsal": cr[3]} for cr in conv_cursor.fetchall()]
            return {
                "carrera_id": cid,
                "nombre_carrera": row[1],
                "categoria": row[2] or "UCI 2.Pro",
                "pais": row[3] or "España",
                "fecha_inicio": row[4],
                "fecha_fin": row[5],
                "total_etapas": row[6] or 1,
                "etapa_actual": row[7] or 0,
                "notas": row[8] or "",
                "convocados": conv,
                "num_convocados": len(conv)
            }

    return None


def auto_detectar_carrera_atleta(
    atleta_id: str,
    fecha_str: str,
    db_path: Optional[Union[str, Path]] = None
) -> Optional[Dict[str, Any]]:
    """Detecta automáticamente si la actividad de un ciclista en una fecha pertenece a una carrera."""
    path = _obtener_db_path(db_path)
    init_history_db(path)
    aid = str(atleta_id).strip()
    f_clean = str(fecha_str).strip()[:10]

    with _conectar_db(path) as conn:
        cursor = conn.cursor()
        # 1. Prioridad: el ciclista está convocado a una carrera en curso en esa fecha
        cursor.execute("""
            SELECT c.carrera_id, c.nombre_carrera, c.categoria, c.pais, c.fecha_inicio, c.fecha_fin, c.total_etapas, c.etapa_actual
            FROM carreras c
            JOIN carrera_convocados cc ON c.carrera_id = cc.carrera_id
            WHERE cc.atleta_id = ? AND ? >= c.fecha_inicio AND ? <= c.fecha_fin
            ORDER BY c.fecha_inicio DESC
            LIMIT 1;
        """, (aid, f_clean, f_clean))
        row = cursor.fetchone()
        if row:
            return {
                "carrera_id": row[0],
                "nombre_carrera": row[1],
                "categoria": row[2],
                "pais": row[3],
                "fecha_inicio": row[4],
                "fecha_fin": row[5],
                "total_etapas": row[6],
                "etapa_actual": row[7]
            }

        # 2. Si no hay convocatoria explícita pero solo hay UNA carrera activa en el calendario ese día
        cursor.execute("""
            SELECT c.carrera_id, c.nombre_carrera, c.categoria, c.pais, c.fecha_inicio, c.fecha_fin, c.total_etapas, c.etapa_actual
            FROM carreras c
            WHERE ? >= c.fecha_inicio AND ? <= c.fecha_fin;
        """, (f_clean, f_clean))
        rows = cursor.fetchall()
        if len(rows) == 1:
            r = rows[0]
            return {
                "carrera_id": r[0],
                "nombre_carrera": r[1],
                "categoria": r[2],
                "pais": r[3],
                "fecha_inicio": r[4],
                "fecha_fin": r[5],
                "total_etapas": r[6],
                "etapa_actual": r[7]
            }

    return None


def obtener_atletas_por_carrera(
    carrera_id: str,
    db_path: Optional[Union[str, Path]] = None
) -> List[Dict[str, Any]]:
    """Devuelve los ciclistas convocados a una carrera, con sus datos de peso y FTP."""
    return obtener_convocados_carrera(carrera_id, db_path=db_path)


def obtener_mejores_numeros_temporada(
    atleta_id: str,
    temporada: Optional[int] = None,
    db_path: Optional[Union[str, Path]] = None
) -> pd.DataFrame:
    """
    Devuelve la envolvente de potencia récord (MMP) del atleta para la temporada especificada
    (o histórico global si temporada es None), indicando la fecha, vatios, W/kg y los kJ
    previos al récord.
    """
    path = _obtener_db_path(db_path)
    if not path.exists():
        return pd.DataFrame()

    params = [str(atleta_id).strip()]
    cond_temp = ""
    if temporada is not None:
        cond_temp = "AND p.temporada = ?"
        params.append(int(temporada))

    query = f"""
        WITH picos_maximos AS (
            SELECT
                p.duracion_s,
                MAX(p.watts) AS max_watts
            FROM picos_historicos p
            WHERE p.atleta_id = ? {cond_temp}
            GROUP BY p.duracion_s
        )
        SELECT
            p.duracion_s,
            CASE
                WHEN p.duracion_s < 60 THEN p.duracion_s || 's'
                WHEN p.duracion_s < 3600 THEN (p.duracion_s / 60) || 'm'
                ELSE (p.duracion_s / 3600) || 'h'
            END AS duracion_str,
            p.watts AS max_watts,
            p.w_kg,
            p.torque_nm,
            p.kj_previos,
            p.kjkg_previos,
            COALESCE(p.kj_esfuerzo, ROUND((p.watts * p.duracion_s) / 1000.0, 1)) AS kj_esfuerzo,
            COALESCE(p.kj_totales, ROUND(COALESCE(p.kj_previos, 0.0) + ((p.watts * p.duracion_s) / 1000.0), 1)) AS kj_totales,
            p.start_index,
            p.end_index,
            CASE 
                WHEN p.start_index IS NOT NULL AND p.start_index > 0 THEN 
                    PRINTF('%02d:%02d:%02d', p.start_index / 3600, (p.start_index % 3600) / 60, p.start_index % 60)
                ELSE '00:00:00'
            END AS momento_carrera,
            p.fecha,
            e.nombre_carrera,
            e.etapa_num
        FROM picos_historicos p
        INNER JOIN picos_maximos pm
            ON p.duracion_s = pm.duracion_s AND p.watts = pm.max_watts
        LEFT JOIN etapas_resumen e
            ON p.actividad_id = e.actividad_id
        WHERE p.atleta_id = ? {cond_temp}
        GROUP BY p.duracion_s
        ORDER BY p.duracion_s ASC;
    """
    # Se duplica la lista de parámetros por la subconsulta y el WHERE principal
    full_params = params + params

    with _conectar_db(path) as conn:
        df = pd.read_sql_query(query, conn, params=full_params)
    return df


def resolver_kj_picos_atleta(
    atleta_id: str,
    client: Optional[Any] = None,
    db_path: Optional[Union[str, Path]] = None,
    verbose: bool = True
) -> int:
    """
    Consulta las actividades de Intervals.icu correspondientes a los picos récord
    del atleta y resuelve con precisión los kilojulios previos gastados antes de alcanzar cada pico.
    Actualiza picos_historicos en la base de datos SQLite.
    """
    try:
        from src.intervals_api import IntervalsClient
    except (ImportError, ValueError):
        from .intervals_api import IntervalsClient

    if client is None:
        client = IntervalsClient()

    path = _obtener_db_path(db_path)
    atleta_id_clean = str(atleta_id).strip()

    with _conectar_db(path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT DISTINCT actividad_id 
            FROM picos_historicos 
            WHERE atleta_id = ? AND (kj_totales IS NULL OR kj_totales = 0.0 OR start_index IS NULL);
        """, (atleta_id_clean,))
        act_ids = [row[0] for row in cursor.fetchall() if row[0] and not row[0].startswith(atleta_id_clean)]

        cursor.execute("SELECT peso_base FROM ciclistas WHERE atleta_id = ?;", (atleta_id_clean,))
        row_peso = cursor.fetchone()
        peso_ref = float(row_peso[0]) if row_peso and row_peso[0] else 70.0

    if not act_ids:
        # Aunque no haya actividades nuevas de telemetría, asegurar que kj_esfuerzo y kj_totales estén rellenados
        with _conectar_db(path) as conn:
            conn.execute("""
                UPDATE picos_historicos 
                SET kj_esfuerzo = ROUND((watts * duracion_s) / 1000.0, 1),
                    kj_totales = ROUND(COALESCE(kj_previos, 0.0) + ((watts * duracion_s) / 1000.0), 1),
                    end_index = CASE WHEN start_index IS NOT NULL THEN start_index + duracion_s ELSE NULL END
                WHERE atleta_id = ? AND (kj_totales IS NULL OR kj_totales = 0.0);
            """, (atleta_id_clean,))
            conn.commit()
        return 0

    if verbose:
        print(f"⚡ Resolviendo kilojulios de fatiga y gasto metabólico para {len(act_ids)} actividades de récord de {atleta_id}...")

    actualizados = 0
    import numpy as np

    for act_id in act_ids:
        try:
            curve_json = client.get_activity_power_curve_json(act_id)
            if not curve_json:
                continue

            secs_arr = curve_json.get('secs', [])
            start_indices = curve_json.get('start_index', [])
            weight_act = float(curve_json.get('weight') or peso_ref)

            sec_to_start = {}
            for idx_c, s_c in enumerate(secs_arr):
                if idx_c < len(start_indices):
                    sec_to_start[s_c] = start_indices[idx_c]

            stream_df = client.get_activity_streams(act_id)
            kj_cum = None
            if stream_df is not None and 'potencia' in stream_df.columns:
                pot_vals = stream_df['potencia'].fillna(0.0).values
                kj_cum = np.cumsum(pot_vals) / 1000.0

            with _conectar_db(path) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT duracion_s, id, watts FROM picos_historicos 
                    WHERE atleta_id = ? AND actividad_id = ?;
                """, (atleta_id_clean, act_id))
                picos_act = cursor.fetchall()

                for dur_s, p_id, w_rec in picos_act:
                    kj_esf = round((w_rec * dur_s) / 1000.0, 1)
                    s_idx = sec_to_start.get(dur_s)
                    if s_idx is not None:
                        if kj_cum is not None and len(kj_cum) > 0:
                            idx_pos = min(max(0, s_idx - 1), len(kj_cum) - 1)
                            kj_val = float(kj_cum[idx_pos]) if s_idx > 0 else 0.0
                        else:
                            kj_val = round((w_rec * 0.82 * s_idx) / 1000.0, 1) if s_idx > 0 else 0.0

                        kjkg_val = round(kj_val / max(30.0, weight_act), 1)
                        kj_tot = round(kj_val + kj_esf, 1)
                        end_idx = s_idx + dur_s

                        cursor.execute("""
                            UPDATE picos_historicos 
                            SET kj_previos = ?, kjkg_previos = ?, kj_esfuerzo = ?, kj_totales = ?, start_index = ?, end_index = ?
                            WHERE id = ?;
                        """, (round(kj_val, 1), kjkg_val, kj_esf, kj_tot, s_idx, end_idx, p_id))
                        actualizados += 1
                    else:
                        cursor.execute("""
                            UPDATE picos_historicos 
                            SET kj_esfuerzo = ?, kj_totales = ROUND(COALESCE(kj_previos, 0.0) + ?, 1)
                            WHERE id = ?;
                        """, (kj_esf, kj_esf, p_id))
                conn.commit()
            time.sleep(0.05)
        except Exception as e:
            if verbose:
                print(f"   ⚠️ Error al resolver kJ para actividad {act_id}: {e}")

    return actualizados


def obtener_curva_potencia_fatiga(
    atleta_id: str,
    umbral_kj: float = 2000.0,
    temporada: Optional[int] = None,
    db_path: Optional[Union[str, Path]] = None
) -> pd.DataFrame:
    """
    Compara la potencia máxima del atleta lograda en 'Fresco' (< umbral_kj) frente a 'Bajo Fatiga' (>= umbral_kj).
    Métrica esencial para evaluar la durabilidad y capacidad de remate en finales de etapa.
    """
    path = _obtener_db_path(db_path)
    if not path.exists():
        return pd.DataFrame()

    params_base = [str(atleta_id).strip()]
    params_fresco = [str(atleta_id).strip(), float(umbral_kj)]
    params_fatiga = [str(atleta_id).strip(), float(umbral_kj)]
    cond_fresco = ""
    cond_fatiga = ""

    if temporada is not None:
        cond_fresco = "AND temporada = ?"
        cond_fatiga = "AND temporada = ?"
        params_fresco.append(int(temporada))
        params_fatiga.append(int(temporada))

    query = f"""
        WITH duraciones AS (
            SELECT DISTINCT duracion_s
            FROM picos_historicos
            WHERE atleta_id = ?
        )
        SELECT
            d.duracion_s,
            CASE
                WHEN d.duracion_s < 60 THEN d.duracion_s || 's'
                WHEN d.duracion_s < 3600 THEN (d.duracion_s / 60) || 'm'
                ELSE (d.duracion_s / 3600) || 'h'
            END AS duracion_str,
            f.watts_fresco,
            f.wkg_fresco,
            fat.watts_fatiga,
            fat.wkg_fatiga,
            ROUND(((fat.watts_fatiga - f.watts_fresco) * 100.0 / NULLIF(f.watts_fresco, 0)), 1) AS perdida_pct
        FROM duraciones d
        LEFT JOIN (
            SELECT duracion_s, MAX(watts) AS watts_fresco, MAX(w_kg) AS wkg_fresco
            FROM picos_historicos
            WHERE atleta_id = ? AND kj_previos < ? {cond_fresco}
            GROUP BY duracion_s
        ) f ON d.duracion_s = f.duracion_s
        LEFT JOIN (
            SELECT duracion_s, MAX(watts) AS watts_fatiga, MAX(w_kg) AS wkg_fatiga
            FROM picos_historicos
            WHERE atleta_id = ? AND kj_previos >= ? {cond_fatiga}
            GROUP BY duracion_s
        ) fat ON d.duracion_s = fat.duracion_s
        ORDER BY d.duracion_s ASC;
    """

    with _conectar_db(path) as conn:
        df = pd.read_sql_query(query, conn, params=params_base + params_fresco + params_fatiga)
    return df


def obtener_ranking_equipo_pico(
    duracion_s: int,
    temporada: Optional[int] = None,
    carrera_id: Optional[str] = None,
    db_path: Optional[Union[str, Path]] = None
) -> pd.DataFrame:
    """
    Devuelve el ranking del equipo para un intervalo de tiempo específico (ej. 5s, 60s, 300s, 1200s).
    """
    path = _obtener_db_path(db_path)
    if not path.exists():
        return pd.DataFrame()

    filtros = ["p.duracion_s = ?"]
    params = [int(duracion_s)]

    if temporada is not None:
        filtros.append("p.temporada = ?")
        params.append(int(temporada))

    if carrera_id is not None:
        filtros.append("LOWER(e.carrera_id) = LOWER(?)")
        params.append(str(carrera_id).strip())

    where_clause = " AND ".join(filtros)

    query = f"""
        SELECT
            p.atleta_id,
            COALESCE(c.nombre, e.nombre_ciclista, p.atleta_id) AS nombre,
            MAX(p.watts) AS max_watts,
            MAX(p.w_kg) AS max_w_kg,
            p.torque_nm,
            p.kj_previos,
            p.fecha,
            e.nombre_carrera
        FROM picos_historicos p
        LEFT JOIN ciclistas c ON p.atleta_id = c.atleta_id
        LEFT JOIN etapas_resumen e ON p.actividad_id = e.actividad_id
        WHERE {where_clause}
        GROUP BY p.atleta_id
        ORDER BY max_watts DESC;
    """

    with _conectar_db(path) as conn:
        df = pd.read_sql_query(query, conn, params=params)
    return df


def obtener_estadisticas_generales_bd(db_path: Optional[Union[str, Path]] = None) -> Dict[str, Any]:
    """Devuelve un diagnóstico rápido del tamaño de la base de datos y registros almacenados."""
    path = _obtener_db_path(db_path)
    if not path.exists():
        return {"existe": False, "tamano_kb": 0}

    size_kb = round(path.stat().st_size / 1024.0, 1)

    with _conectar_db(path) as conn:
        cursor = conn.cursor()
        ciclistas_count = cursor.execute("SELECT COUNT(*) FROM ciclistas;").fetchone()[0]
        etapas_count = cursor.execute("SELECT COUNT(*) FROM etapas_resumen;").fetchone()[0]
        picos_count = cursor.execute("SELECT COUNT(*) FROM picos_historicos;").fetchone()[0]
        carreras_unicas = cursor.execute("SELECT COUNT(DISTINCT carrera_id) FROM etapas_resumen;").fetchone()[0]
        kj_acumulados = cursor.execute("SELECT COALESCE(SUM(kj_total), 0) FROM etapas_resumen;").fetchone()[0]

    return {
        "existe": True,
        "ruta": str(path),
        "tamano_kb": size_kb,
        "num_ciclistas": ciclistas_count,
        "num_actividades": etapas_count,
        "num_picos_registrados": picos_count,
        "num_carreras": carreras_unicas,
        "total_kj_registrados": round(kj_acumulados, 0)
    }


def sincronizar_historico_desde_api(
    roster_path: Optional[Union[str, Path]] = None,
    fecha_inicio: str = "2026-01-01",
    fecha_fin: Optional[str] = None,
    db_path: Optional[Union[str, Path]] = None,
    client: Optional[Any] = None,
    incluir_wellness: bool = True,
    incluir_picos: bool = True,
    verbose: bool = True,
    solo_nuevas: bool = False
) -> Dict[str, Any]:
    """
    Descarga desde la API de Intervals.icu y almacena en SQLite las actividades,
    curvas de potencia récord y métricas de bienestar de los ciclistas.

    :param solo_nuevas: Si es True, descarga únicamente actividades y métricas a partir del último
                        registro en base de datos para cada ciclista, omitiendo re-descargas de
                        actividades y cálculos de curvas si no hay actividades nuevas.
    """
    try:
        from config import cargar_roster, DEFAULT_ROSTER_PATH
    except (ImportError, ValueError):
        from ..config import cargar_roster, DEFAULT_ROSTER_PATH

    try:
        from src.intervals_api import IntervalsClient
    except (ImportError, ValueError):
        from .intervals_api import IntervalsClient

    if client is None:
        client = IntervalsClient()

    roster_file = roster_path or DEFAULT_ROSTER_PATH
    roster_df = cargar_roster(roster_file)
    if roster_df.empty:
        raise ValueError(f"No se pudieron cargar ciclistas desde {roster_file}")

    fecha_fin = fecha_fin or datetime.now().strftime('%Y-%m-%d')
    init_history_db(db_path)
    path = _obtener_db_path(db_path)

    total_actividades = 0
    total_picos = 0
    total_wellness = 0
    ciclistas_procesados = 0

    modo_txt = "incremental (solo nuevas actividades)" if solo_nuevas else "completa"
    if verbose:
        print(f"\n🚀 Iniciando sincronización [{modo_txt}] para {len(roster_df)} ciclistas ({fecha_inicio} -> {fecha_fin})...")

    for idx, (_, r) in enumerate(roster_df.iterrows(), 1):
        aid = str(r.get('intervals_id', '')).strip()
        nom = str(r.get('Name', '')).strip()
        if not aid:
            continue

        peso_base = float(r['weight']) if pd.notna(r.get('weight')) else 70.0
        ftp_base = float(r['FTP']) if pd.notna(r.get('FTP')) else 380.0
        crank_m = float(r['crank_length_m']) if pd.notna(r.get('crank_length_m')) else 0.170
        crank_mm = round(crank_m * 1000.0, 1)

        # 1. Registrar ciclista
        guardar_ciclista(
            atleta_id=aid,
            nombre=nom,
            peso=peso_base,
            ftp=ftp_base,
            crank_length_mm=crank_mm,
            db_path=path
        )

        # Consultar estado previo del ciclista en SQLite
        with _conectar_db(path) as conn:
            cur = conn.cursor()
            cur.execute("SELECT MAX(fecha) FROM etapas_resumen WHERE atleta_id = ?", (aid,))
            row_max = cur.fetchone()
            max_fecha_act = row_max[0] if row_max and row_max[0] else None

            cur.execute("SELECT actividad_id FROM etapas_resumen WHERE atleta_id = ?", (aid,))
            existing_act_ids = set(str(r_id[0]).strip() for r_id in cur.fetchall() if r_id[0])

            cur.execute("SELECT COUNT(*) FROM picos_historicos WHERE atleta_id = ?", (aid,))
            picos_existentes_count = cur.fetchone()[0]

            cur.execute("SELECT MAX(fecha) FROM wellness_diario WHERE atleta_id = ?", (aid,))
            row_w = cur.fetchone()
            max_fecha_wellness = row_w[0] if row_w and row_w[0] else None

        fecha_act_oldest = max_fecha_act if (solo_nuevas and max_fecha_act) else fecha_inicio

        if verbose:
            tag_sync = "solo nuevas" if solo_nuevas else "completa"
            print(f"[{idx}/{len(roster_df)}] 🚴 Sincronizando {nom} ({aid}) [{tag_sync}] desde {fecha_act_oldest}...")

        # 2. Descargar actividades del periodo
        try:
            acts = client.get_activities(athlete_id=aid, oldest=fecha_act_oldest, newest=fecha_fin)
        except Exception as e:
            if verbose:
                print(f"   ⚠️ Error al obtener actividades para {nom}: {e}")
            acts = []

        # Si solo_nuevas es True, filtrar solo aquellas no presentes en base de datos
        if solo_nuevas:
            nuevas_acts = [act for act in acts if str(act.get('id', '')).strip() not in existing_act_ids]
        else:
            nuevas_acts = acts

        # Preparar registros para inserción en etapas_resumen
        registros_etapas = []
        for act in nuevas_acts:
            tipo = act.get('type', '')
            if tipo not in ['Ride', 'VirtualRide', 'EBikeRide', 'GravelRide', 'MountainBikeRide'] and not act.get('icu_joules') and not act.get('distance'):
                continue

            act_id = str(act.get('id', '')).strip()
            if not act_id:
                continue

            f_local = act.get('start_date_local') or act.get('start_date') or fecha_inicio
            f_str = f_local[:10]
            try:
                temporada = int(f_str.split('-')[0])
            except Exception:
                temporada = 2026

            nombre_act = act.get('name') or "Actividad"
            etapa_num = 1
            m_etapa = re.search(r'(?:etapa|stage)\s*(\d+)', nombre_act, re.IGNORECASE)
            if m_etapa:
                etapa_num = int(m_etapa.group(1))

            carrera_match = auto_detectar_carrera_atleta(aid, f_str, db_path=path)
            if carrera_match:
                carrera_id = carrera_match['carrera_id']
                nom_carrera = carrera_match['nombre_carrera']
            else:
                carrera_id = re.sub(r'[^a-zA-Z0-9]+', '_', nombre_act.lower()).strip('_')[:40]
                nom_carrera = nombre_act

            dist_km = round(float(act.get('distance') or 0.0) / 1000.0, 2)
            desnivel_m = int(round(float(act.get('total_elevation_gain') or 0.0)))
            t_mov_s = int(round(float(act.get('moving_time') or act.get('elapsed_time') or 0.0)))
            t_bruto_s = int(round(float(act.get('elapsed_time') or act.get('moving_time') or 0.0)))

            pot_med = int(round(float(act.get('icu_average_watts') or 0.0)))
            pot_max = int(round(float(act.get('p_max') or act.get('icu_pm_p_max') or 0.0)))
            np_w = int(round(float(act.get('icu_weighted_avg_watts') or 0.0)))

            kj_tot = round(float(act.get('icu_joules') or 0.0) / 1000.0, 1)
            if kj_tot <= 0 and pot_med > 0 and t_mov_s > 0:
                kj_tot = round(pot_med * t_mov_s / 1000.0, 1)

            peso_act = float(act.get('icu_weight') or peso_base)
            ftp_act = float(act.get('icu_ftp') or ftp_base)

            kj_kg = round(kj_tot / max(30.0, peso_act), 1)
            horas_mov = max(0.01, t_mov_s / 3600.0)
            kj_kg_h = round(kj_kg / horas_mov, 1)
            np_kj_kg_h = round((np_w / max(30.0, peso_act)) * 3.6, 1) if np_w > 0 else 0.0

            tss = float(act.get('icu_training_load') or 0.0)
            tss_h = round(tss / horas_mov, 1)
            if_val = round(float(act.get('icu_intensity') or (np_w / ftp_act if ftp_act else 0.0)), 2)

            vel_med = round(float(act.get('average_speed', 0.0)) * 3.6, 1) if act.get('average_speed') else round(dist_km / horas_mov, 1)
            vel_max = round(float(act.get('max_speed', 0.0)) * 3.6, 1) if act.get('max_speed') else 0.0

            fc_med = int(round(float(act.get('average_heartrate') or 0.0)))
            fc_max = int(round(float(act.get('max_heartrate') or 0.0)))
            cad_med = int(round(float(act.get('average_cadence') or 0.0)))
            temp_med = round(float(act.get('average_temp')), 1) if act.get('average_temp') is not None else None

            registros_etapas.append((
                act_id, aid, nom, carrera_id, nom_carrera,
                etapa_num, f_str, temporada, peso_act, ftp_act,
                dist_km, desnivel_m, t_mov_s, t_bruto_s,
                vel_med, vel_max, pot_med, pot_max, np_w,
                kj_tot, kj_kg, kj_kg_h, np_kj_kg_h,
                tss, tss_h, if_val, fc_med, fc_max, cad_med,
                None, None, temp_med, None, None
            ))

        if registros_etapas:
            with _conectar_db(path) as conn:
                conn.executemany("""
                    INSERT OR REPLACE INTO etapas_resumen (
                        actividad_id, atleta_id, nombre_ciclista, carrera_id, nombre_carrera,
                        etapa_num, fecha, temporada, peso_kg, ftp_w, distancia_km, desnivel_m,
                        tiempo_mov_s, duracion_bruta_s, vel_media_kmh, vel_max_kmh, pot_media_w,
                        pot_max_w, np_w, kj_total, kj_kg, kj_kg_h, np_kj_kg_h, tss, tss_h,
                        if_val, fc_media, fc_max, cadencia_media, torque_media_nm, aepf_media_n,
                        temp_media_c, desglose_horas_json, metadata_json
                    ) VALUES (
                        ?, ?, ?, ?, ?,
                        ?, ?, ?, ?, ?, ?, ?,
                        ?, ?, ?, ?, ?,
                        ?, ?, ?, ?, ?, ?, ?, ?,
                        ?, ?, ?, ?, ?, ?,
                        ?, ?, ?
                    );
                """, registros_etapas)
                conn.commit()

            total_actividades += len(registros_etapas)
            if verbose:
                tag_act = "actividades nuevas" if solo_nuevas else "actividades"
                print(f"   • Guardadas {len(registros_etapas)} {tag_act}.")
        else:
            if verbose:
                if solo_nuevas:
                    print(f"   • Sin actividades nuevas (al día).")
                else:
                    print(f"   • 0 actividades encontradas.")

        # 3. Descargar y almacenar curvas de potencia de la temporada
        debe_actualizar_picos = incluir_picos and (not solo_nuevas or len(registros_etapas) > 0 or picos_existentes_count == 0)
        if debe_actualizar_picos:
            try:
                date_curves_param = f"r.{fecha_inicio}.{fecha_fin}"
                pc = client.get_athlete_power_curves(athlete_id=aid, date_curves=date_curves_param)
                curve_list = pc.get('list', [])
                activities_meta = pc.get('activities', {})

                if curve_list and isinstance(curve_list, list) and len(curve_list) > 0:
                    c_data = curve_list[0]
                    secs_arr = c_data.get('secs', [])
                    watts_arr = c_data.get('watts', []) or c_data.get('values', [])
                    wkg_arr = c_data.get('watts_per_kg', [])
                    act_ids_arr = c_data.get('activity_id', [])

                    stub_actividades = []
                    for ref_act_id, ref_meta in activities_meta.items():
                        ref_act_str = str(ref_act_id).strip()
                        if not ref_act_str:
                            continue
                        f_stub = (ref_meta.get('start_date_local') or fecha_inicio)[:10]
                        try:
                            temp_stub = int(f_stub.split('-')[0])
                        except Exception:
                            temp_stub = 2026
                        stub_actividades.append((
                            ref_act_str, aid, nom, 'actividad', ref_meta.get('name', 'Actividad'),
                            1, f_stub, temp_stub, ref_meta.get('icu_weight') or peso_base,
                            ftp_base, round(float(ref_meta.get('distance') or 0.0) / 1000.0, 2),
                            int(ref_meta.get('total_elevation_gain') or 0),
                            int(ref_meta.get('moving_time') or 0), int(ref_meta.get('moving_time') or 0),
                            0.0, 0.0, 0, 0, 0, 0.0, 0.0, 0.0, 0.0,
                            float(ref_meta.get('training_load') or 0.0), 0.0, 0.0, 0, 0, 0,
                            None, None, None, None, None
                        ))

                    with _conectar_db(path) as conn:
                        conn.executemany("""
                            INSERT OR IGNORE INTO etapas_resumen (
                                actividad_id, atleta_id, nombre_ciclista, carrera_id, nombre_carrera,
                                etapa_num, fecha, temporada, peso_kg, ftp_w, distancia_km, desnivel_m,
                                tiempo_mov_s, duracion_bruta_s, vel_media_kmh, vel_max_kmh, pot_media_w,
                                pot_max_w, np_w, kj_total, kj_kg, kj_kg_h, np_kj_kg_h, tss, tss_h,
                                if_val, fc_media, fc_max, cadencia_media, torque_media_nm, aepf_media_n,
                                temp_media_c, desglose_horas_json, metadata_json
                            ) VALUES (
                                ?, ?, ?, ?, ?,
                                ?, ?, ?, ?, ?, ?, ?,
                                ?, ?, ?, ?, ?,
                                ?, ?, ?, ?, ?, ?, ?, ?,
                                ?, ?, ?, ?, ?, ?,
                                ?, ?, ?
                            );
                        """, stub_actividades)

                        registros_picos = []
                        n_picos = min(len(secs_arr), len(watts_arr))
                        for i_p in range(n_picos):
                            s_val = int(secs_arr[i_p])
                            w_val = int(round(float(watts_arr[i_p])))
                            if w_val <= 0:
                                continue
                            wkg_val = round(float(wkg_arr[i_p]), 2) if i_p < len(wkg_arr) and wkg_arr[i_p] else round(w_val / max(30.0, peso_base), 2)
                            act_ref = str(act_ids_arr[i_p]).strip() if i_p < len(act_ids_arr) and act_ids_arr[i_p] else f"{aid}_peak_{s_val}"
                            
                            f_pico = fecha_inicio
                            if act_ref in activities_meta:
                                f_pico = (activities_meta[act_ref].get('start_date_local') or fecha_inicio)[:10]

                            try:
                                temp_pico = int(f_pico.split('-')[0])
                            except Exception:
                                temp_pico = 2026

                            kj_esf_val = round((w_val * s_val) / 1000.0, 1)
                            registros_picos.append((
                                aid, act_ref, f_pico, temp_pico, s_val,
                                w_val, wkg_val, None, None, 0.0, 0.0,
                                kj_esf_val, kj_esf_val, None, None
                            ))

                        conn.execute("DELETE FROM picos_historicos WHERE atleta_id = ? AND temporada = ?;", (aid, 2026))
                        conn.executemany("""
                            INSERT INTO picos_historicos (
                                atleta_id, actividad_id, fecha, temporada, duracion_s,
                                watts, w_kg, torque_nm, aepf_n, kj_previos, kjkg_previos,
                                kj_esfuerzo, kj_totales, start_index, end_index
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                        """, registros_picos)
                        conn.commit()

                    total_picos += len(registros_picos)
                    if verbose:
                        print(f"   • Guardados {len(registros_picos)} picos de potencia de la temporada.")

                    # Resolver automáticamente kilojulios de fatiga y momento de inicio para los récords
                    picos_resueltos = resolver_kj_picos_atleta(aid, client=client, db_path=path, verbose=False)
                    if verbose and picos_resueltos > 0:
                        print(f"   • Resueltos con precisión {picos_resueltos} picos con su fatiga acumulada (kJ previos y totales).")
            except Exception as e:
                if verbose:
                    print(f"   ⚠️ Error al procesar curvas de potencia para {nom}: {e}")
        elif incluir_picos and verbose and solo_nuevas:
            print(f"   • Curvas de potencia al día (sin actividades nuevas).")

        # 4. Descargar y almacenar datos de bienestar (Wellness / HRV)
        if incluir_wellness:
            fecha_w_oldest = max_fecha_wellness if (solo_nuevas and max_fecha_wellness) else fecha_inicio
            try:
                w_list = client.get_wellness(athlete_id=aid, oldest=fecha_w_oldest, newest=fecha_fin)
                registros_wellness = []
                for w in w_list:
                    f_w = str(w.get('id', '')).strip()
                    if not f_w:
                        continue
                    registros_wellness.append((
                        aid, f_w,
                        w.get('hrv') or w.get('rmssd'),
                        w.get('restingHR'),
                        w.get('weight'),
                        w.get('ctl'),
                        w.get('atl'),
                        w.get('tsb'),
                        w.get('sleepSecs', 0) / 3600.0 if w.get('sleepSecs') else None,
                        w.get('sleepScore')
                    ))

                if registros_wellness:
                    with _conectar_db(path) as conn:
                        conn.executemany("""
                            INSERT INTO wellness_diario (
                                atleta_id, fecha, hrv_rmssd, fc_reposo, peso_kg, ctl, atl, tsb, sueno_horas, sueno_calidad
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            ON CONFLICT(atleta_id, fecha) DO UPDATE SET
                                hrv_rmssd = COALESCE(excluded.hrv_rmssd, wellness_diario.hrv_rmssd),
                                fc_reposo = COALESCE(excluded.fc_reposo, wellness_diario.fc_reposo),
                                peso_kg = COALESCE(excluded.peso_kg, wellness_diario.peso_kg),
                                ctl = COALESCE(excluded.ctl, wellness_diario.ctl),
                                atl = COALESCE(excluded.atl, wellness_diario.atl),
                                tsb = COALESCE(excluded.tsb, wellness_diario.tsb),
                                sueno_horas = COALESCE(excluded.sueno_horas, wellness_diario.sueno_horas),
                                sueno_calidad = COALESCE(excluded.sueno_calidad, wellness_diario.sueno_calidad);
                        """, registros_wellness)
                        conn.commit()

                    total_wellness += len(registros_wellness)
                    if verbose:
                        print(f"   • Guardados {len(registros_wellness)} días de bienestar/HRV.")
            except Exception as e:
                if verbose:
                    print(f"   ⚠️ Error al procesar wellness para {nom}: {e}")

        ciclistas_procesados += 1
        time.sleep(0.1)

    db_stats = obtener_estadisticas_generales_bd(path)
    if verbose:
        titulo_sync = "SINCRONIZACIÓN INCREMENTAL" if solo_nuevas else "SINCRONIZACIÓN HISTÓRICA"
        print("\n" + "=" * 60)
        print(f"✅ ¡{titulo_sync} COMPLETADA CON ÉXITO!")
        print("=" * 60)
        print(f"   • Ciclistas procesados: {ciclistas_procesados}")
        tag_acts_tot = "Nuevas actividades almacenadas" if solo_nuevas else "Actividades almacenadas"
        print(f"   • {tag_acts_tot}: {total_actividades}")
        print(f"   • Picos de potencia guardados: {total_picos}")
        print(f"   • Días de bienestar (HRV/Carga): {total_wellness}")
        print(f"   • Tamaño final de la base de datos: {db_stats.get('tamano_kb', 0)} KB ({db_stats.get('tamano_kb', 0)/1024.0:.2f} MB)")
        print("=" * 60 + "\n")

    return {
        "ciclistas_procesados": ciclistas_procesados,
        "total_actividades": total_actividades,
        "total_picos": total_picos,
        "total_wellness": total_wellness,
        "db_stats": db_stats,
        "solo_nuevas": solo_nuevas
    }
