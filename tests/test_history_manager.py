"""
Pruebas unitarias para el módulo de persistencia y análisis histórico (history_manager.py).
"""

import sys
import unittest
import tempfile
import sqlite3
from pathlib import Path
from datetime import datetime

# Asegurar path raíz
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.history_manager import (
    init_history_db,
    guardar_ciclista,
    guardar_resumen_etapa,
    guardar_wellness_diario,
    obtener_historico_carrera_etapas,
    obtener_resumen_acumulado_carrera,
    obtener_mejores_numeros_temporada,
    obtener_curva_potencia_fatiga,
    obtener_ranking_equipo_pico,
    obtener_estadisticas_generales_bd,
    guardar_carrera,
    eliminar_carrera,
    asignar_convocados_carrera,
    obtener_convocados_carrera,
    obtener_carreras_calendario,
    obtener_carrera_detalle,
    resolver_carrera,
    obtener_carreras_activas_fecha,
    auto_detectar_carrera_atleta,
    obtener_atletas_por_carrera,
)


class TestHistoryManager(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db_path = Path(self.temp_dir.name) / "test_historico.db"

    def tearDown(self):
        import gc
        gc.collect()
        try:
            self.temp_dir.cleanup()
        except Exception:
            pass

    def test_init_db(self):
        """Verifica que la base de datos se inicialice con todas las tablas e índices."""
        path = init_history_db(self.db_path)
        self.assertTrue(path.exists())

        conn = sqlite3.connect(path)
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
            tables = {row[0] for row in cursor.fetchall()}
            self.assertIn("ciclistas", tables)
            self.assertIn("etapas_resumen", tables)
            self.assertIn("picos_historicos", tables)
            self.assertIn("wellness_diario", tables)

            cursor.execute("SELECT name FROM sqlite_master WHERE type='index';")
            indexes = {row[0] for row in cursor.fetchall()}
            self.assertIn("idx_etapas_carrera", indexes)
            self.assertIn("idx_picos_atleta_duracion", indexes)
        finally:
            conn.close()

    def test_guardar_resumen_etapa_y_picos(self):
        """Verifica el guardado y extracción de KPIs de etapa y picos con fatiga."""
        stats = {
            'nombre': 'Carlos Garcia',
            'atleta_id': 'i495562',
            'peso_kg': 62.0,
            'ftp_w': 380,
            'distancia_km': 154.2,
            'desnivel_pos_m': 2450,
            'tiempo_mov_seg': 14400,
            'duracion_bruta_seg': 15000,
            'vel_media_kmh': 38.5,
            'vel_max_kmh': 78.2,
            'pot_media_w': 245,
            'pot_max_w': 1050,
            'np_w': 295,
            'kilojulios_total': 3528,
            'kj_kg': 56.9,
            'kj_kg_hora': 14.2,
            'np_kj_kg_hora': 17.1,
            'tss_total': 242,
            'tss_hora': 60.5,
            'if_val': 0.78,
            'fc_media_bpm': 148,
            'fc_max_bpm': 185,
            'cadencia_media_rpm': 86,
            'torque_media_nm': 27.2,
            'aepf_media_n': 160.0,
            'temp_media_c': 24.5,
            'curva_mmp_completa': {
                5: {'watts': 980, 'w_kg': 15.8, 'kj_previos': 3200.0, 'kjkg_previos': 51.6, 'start_index': 14000},
                60: {'watts': 560, 'w_kg': 9.03, 'kj_previos': 2800.0, 'kjkg_previos': 45.2, 'start_index': 13500},
                300: {'watts': 430, 'w_kg': 6.94, 'kj_previos': 2500.0, 'kjkg_previos': 40.3, 'start_index': 12000},
                1200: {'watts': 370, 'w_kg': 5.97, 'kj_previos': 1800.0, 'kjkg_previos': 29.0, 'start_index': 8000},
            }
        }

        act_id = guardar_resumen_etapa(
            stats=stats,
            carrera_id="burgos_2026",
            etapa_num=1,
            fecha="2026-08-04",
            nombre_carrera="Vuelta a Burgos",
            db_path=self.db_path
        )
        self.assertTrue(bool(act_id))

        # Verificar consulta de mejores números
        df_mmp = obtener_mejores_numeros_temporada('i495562', temporada=2026, db_path=self.db_path)
        self.assertEqual(len(df_mmp), 4)
        pico_5m = df_mmp[df_mmp['duracion_s'] == 300].iloc[0]
        self.assertEqual(pico_5m['max_watts'], 430)
        self.assertEqual(pico_5m['kj_previos'], 2500.0)
        self.assertEqual(pico_5m['kj_esfuerzo'], 129.0)
        self.assertEqual(pico_5m['kj_totales'], 2629.0)

    def test_carrera_etapas_acumulados(self):
        """Verifica la acumulación de gasto energético (kJ) y fatiga (TSS) a lo largo de varias etapas."""
        carrera = "volta_catalunya_2026"

        # Etapa 1 - Corredor A y B
        stats_a1 = {
            'nombre': 'Carlos Garcia', 'atleta_id': 'c1', 'peso_kg': 62.0,
            'distancia_km': 160.0, 'desnivel_pos_m': 2000, 'tiempo_mov_seg': 14400,
            'pot_media_w': 240, 'np_w': 280, 'kilojulios_total': 3456, 'kj_kg': 55.7,
            'kj_kg_hora': 13.9, 'tss_total': 210, 'if_val': 0.74
        }
        stats_b1 = {
            'nombre': 'Ander Okamika', 'atleta_id': 'c2', 'peso_kg': 70.0,
            'distancia_km': 160.0, 'desnivel_pos_m': 2000, 'tiempo_mov_seg': 14400,
            'pot_media_w': 270, 'np_w': 310, 'kilojulios_total': 3888, 'kj_kg': 55.5,
            'kj_kg_hora': 13.9, 'tss_total': 215, 'if_val': 0.75
        }
        guardar_resumen_etapa(stats_a1, carrera_id=carrera, etapa_num=1, fecha="2026-03-23", db_path=self.db_path)
        guardar_resumen_etapa(stats_b1, carrera_id=carrera, etapa_num=1, fecha="2026-03-23", db_path=self.db_path)

        # Etapa 2 - Corredor A y B
        stats_a2 = {
            'nombre': 'Carlos Garcia', 'atleta_id': 'c1', 'peso_kg': 62.0,
            'distancia_km': 175.0, 'desnivel_pos_m': 3100, 'tiempo_mov_seg': 16200,
            'pot_media_w': 255, 'np_w': 305, 'kilojulios_total': 4131, 'kj_kg': 66.6,
            'kj_kg_hora': 14.8, 'tss_total': 265, 'if_val': 0.80
        }
        stats_b2 = {
            'nombre': 'Ander Okamika', 'atleta_id': 'c2', 'peso_kg': 70.0,
            'distancia_km': 175.0, 'desnivel_pos_m': 3100, 'tiempo_mov_seg': 16200,
            'pot_media_w': 285, 'np_w': 335, 'kilojulios_total': 4617, 'kj_kg': 66.0,
            'kj_kg_hora': 14.7, 'tss_total': 268, 'if_val': 0.81
        }
        guardar_resumen_etapa(stats_a2, carrera_id=carrera, etapa_num=2, fecha="2026-03-24", db_path=self.db_path)
        guardar_resumen_etapa(stats_b2, carrera_id=carrera, etapa_num=2, fecha="2026-03-24", db_path=self.db_path)

        # Consultar desglose acumulativo
        df_etapas = obtener_historico_carrera_etapas(carrera, db_path=self.db_path)
        self.assertEqual(len(df_etapas), 4)

        # Verificar sumas acumuladas de Carlos (c1) tras etapa 2
        c1_e2 = df_etapas[(df_etapas['atleta_id'] == 'c1') & (df_etapas['etapa_num'] == 2)].iloc[0]
        self.assertEqual(c1_e2['kj_acumulados'], 3456 + 4131)
        self.assertEqual(c1_e2['tss_acumulado'], 210 + 265)
        self.assertEqual(c1_e2['km_acumulados'], 160.0 + 175.0)

        # Consultar resumen final acumulado de la carrera
        df_totales = obtener_resumen_acumulado_carrera(carrera, db_path=self.db_path)
        self.assertEqual(len(df_totales), 2)
        # Ander (c2) tiene mayor gasto total en kJ por peso, debe estar primero
        self.assertEqual(df_totales.iloc[0]['atleta_id'], 'c2')
        self.assertEqual(df_totales.iloc[0]['total_kj'], 3888 + 4617)

    def test_potencia_fresco_vs_fatiga(self):
        """Verifica el análisis de pérdida de potencia bajo fatiga (> 2000 kJ previos)."""
        stats_fresco = {
            'nombre': 'Carlos Garcia', 'atleta_id': 'c1', 'peso_kg': 60.0,
            'curva_mmp_completa': {
                300: {'watts': 450, 'w_kg': 7.5, 'kj_previos': 800.0}   # Fresco
            }
        }
        stats_fatiga = {
            'nombre': 'Carlos Garcia', 'atleta_id': 'c1', 'peso_kg': 60.0,
            'curva_mmp_completa': {
                300: {'watts': 405, 'w_kg': 6.75, 'kj_previos': 2900.0} # Bajo fatiga
            }
        }
        guardar_resumen_etapa(stats_fresco, carrera_id="etapa_1", fecha="2026-05-10", db_path=self.db_path)
        guardar_resumen_etapa(stats_fatiga, carrera_id="etapa_2", fecha="2026-05-11", db_path=self.db_path)

        df_fat = obtener_curva_potencia_fatiga('c1', umbral_kj=2000.0, db_path=self.db_path)
        self.assertEqual(len(df_fat), 1)
        row = df_fat.iloc[0]
        self.assertEqual(row['watts_fresco'], 450)
        self.assertEqual(row['watts_fatiga'], 405)
        self.assertEqual(row['perdida_pct'], -10.0)

    def test_ranking_equipo(self):
        """Verifica ranking del equipo para duraciones específicas."""
        s1 = {'nombre': 'Sprinter', 'atleta_id': 's1', 'peso_kg': 75.0, 'curva_mmp_completa': {5: {'watts': 1400, 'w_kg': 18.67, 'kj_previos': 100}}}
        s2 = {'nombre': 'Escalador', 'atleta_id': 's2', 'peso_kg': 58.0, 'curva_mmp_completa': {5: {'watts': 950, 'w_kg': 16.38, 'kj_previos': 100}}}
        guardar_resumen_etapa(s1, carrera_id="c1", fecha="2026-06-01", db_path=self.db_path)
        guardar_resumen_etapa(s2, carrera_id="c1", fecha="2026-06-01", db_path=self.db_path)

        rank_5s = obtener_ranking_equipo_pico(5, db_path=self.db_path)
        self.assertEqual(len(rank_5s), 2)
        self.assertEqual(rank_5s.iloc[0]['atleta_id'], 's1')
        self.assertEqual(rank_5s.iloc[0]['max_watts'], 1400)

    def test_wellness_y_estadisticas_db(self):
        """Verifica persistencia de wellness y métricas globales de la base de datos."""
        guardar_ciclista('c1', 'Carlos Garcia', peso=62.0, ftp=380.0, db_path=self.db_path)
        guardar_wellness_diario('c1', '2026-08-01', {'hrv': 78.5, 'fc_reposo': 42, 'ctl': 110.0, 'atl': 95.0, 'tsb': 15.0}, db_path=self.db_path)

        stats_db = obtener_estadisticas_generales_bd(self.db_path)
        self.assertTrue(stats_db['existe'])
        self.assertEqual(stats_db['num_ciclistas'], 1)
        self.assertGreater(stats_db['tamano_kb'], 0)

    def test_carreras_y_convocatorias_crud(self):
        """Verifica ciclo de vida completo de carreras del calendario y convocatorias históricas."""
        # 1. Crear ciclistas base
        guardar_ciclista('ath1', 'Carlos Líder', peso=63.0, ftp=400.0, db_path=self.db_path)
        guardar_ciclista('ath2', 'Mario Sprinter', peso=71.0, ftp=430.0, db_path=self.db_path)
        guardar_ciclista('ath3', 'Eric Gregario', peso=68.0, ftp=390.0, db_path=self.db_path)

        # 2. Dar de alta una carrera planificada con convocados
        datos_carrera = {
            'carrera_id': 'volta_valencia_2026',
            'nombre_carrera': 'Volta a la Comunitat Valenciana 2026',
            'categoria': 'UCI 2.Pro',
            'pais': 'España',
            'fecha_inicio': '2026-02-04',
            'fecha_fin': '2026-02-08',
            'total_etapas': 5,
            'etapa_actual': 0,
            'notas': 'Luchar por victorias de etapa al sprint.'
        }
        cid = guardar_carrera(datos_carrera, atletas_ids=['ath1', 'ath2'], db_path=self.db_path)
        self.assertEqual(cid, 'volta_valencia_2026')

        # 3. Comprobar consulta de convocados
        convocados = obtener_convocados_carrera('volta_valencia_2026', db_path=self.db_path)
        self.assertEqual(len(convocados), 2)
        aids = [c['atleta_id'] for c in convocados]
        self.assertIn('ath1', aids)
        self.assertIn('ath2', aids)

        # 4. Actualizar convocatoria (añadir ath3)
        asignar_convocados_carrera('volta_valencia_2026', ['ath1', 'ath2', 'ath3'], db_path=self.db_path)
        convocados_post = obtener_convocados_carrera('volta_valencia_2026', db_path=self.db_path)
        self.assertEqual(len(convocados_post), 3)

        # 5. Consultar calendario con fecha referencia
        # Si hoy es 2026-02-06, la carrera debe figurar 'en_curso'
        carreras_en_curso = obtener_carreras_calendario(
            filtro_estado='en_curso',
            fecha_referencia='2026-02-06',
            db_path=self.db_path
        )
        self.assertTrue(any(c['carrera_id'] == 'volta_valencia_2026' for c in carreras_en_curso))

        # Si hoy es 2026-01-15, la carrera debe figurar 'proxima'
        carreras_proximas = obtener_carreras_calendario(
            filtro_estado='proxima',
            fecha_referencia='2026-01-15',
            db_path=self.db_path
        )
        self.assertTrue(any(c['carrera_id'] == 'volta_valencia_2026' for c in carreras_proximas))

        # Si hoy es 2026-03-01, la carrera debe figurar 'finalizada'
        carreras_fin = obtener_carreras_calendario(
            filtro_estado='finalizada',
            fecha_referencia='2026-03-01',
            db_path=self.db_path
        )
        self.assertTrue(any(c['carrera_id'] == 'volta_valencia_2026' for c in carreras_fin))

        # 6. Eliminar carrera
        eliminar_carrera('volta_valencia_2026', db_path=self.db_path)
        convocados_del = obtener_convocados_carrera('volta_valencia_2026', db_path=self.db_path)
        self.assertEqual(len(convocados_del), 0)
        carrera_del = obtener_carrera_detalle('volta_valencia_2026', db_path=self.db_path)
        self.assertIsNone(carrera_del)

    def test_resolver_carrera_and_auto_deteccion(self):
        """Verifica la resolución dinámica de carreras por slug, alias numérico y detección por convocatoria."""
        init_history_db(self.db_path)

        # 1. Crear dos carreras en el calendario
        c1 = {
            'carrera_id': 'volta_valencia_2026',
            'nombre_carrera': 'Volta a la Comunitat Valenciana',
            'fecha_inicio': '2026-02-04',
            'fecha_fin': '2026-02-08',
            'total_etapas': 5
        }
        guardar_carrera(c1, atletas_ids=['ath_val1', 'ath_val2'], db_path=self.db_path)

        c2 = {
            'carrera_id': 'tour_oman_2026',
            'nombre_carrera': 'Tour of Oman',
            'fecha_inicio': '2026-02-05',
            'fecha_fin': '2026-02-09',
            'total_etapas': 5
        }
        guardar_carrera(c2, atletas_ids=['ath_oman1', 'ath_oman2'], db_path=self.db_path)

        # 2. Resolución directa por ID o nombre
        res_slug = resolver_carrera('volta_valencia_2026', db_path=self.db_path)
        self.assertIsNotNone(res_slug)
        self.assertEqual(res_slug['nombre_carrera'], 'Volta a la Comunitat Valenciana')

        res_name = resolver_carrera('valenciana', db_path=self.db_path)
        self.assertIsNotNone(res_name)
        self.assertEqual(res_name['carrera_id'], 'volta_valencia_2026')

        # 3. Carreras activas en fecha dada
        activas = obtener_carreras_activas_fecha('2026-02-06', db_path=self.db_path)
        self.assertEqual(len(activas), 2)
        slugs_act = [a['carrera_id'] for a in activas]
        self.assertIn('volta_valencia_2026', slugs_act)
        self.assertIn('tour_oman_2026', slugs_act)

        # 4. Resolución por alias numérico (1 -> 1ª carrera activa, 2 -> 2ª carrera activa)
        res_alias_1 = resolver_carrera(1, fecha='2026-02-06', db_path=self.db_path)
        self.assertIsNotNone(res_alias_1)
        self.assertEqual(res_alias_1['carrera_id'], activas[0]['carrera_id'])

        res_alias_2 = resolver_carrera(2, fecha='2026-02-06', db_path=self.db_path)
        self.assertIsNotNone(res_alias_2)
        self.assertEqual(res_alias_2['carrera_id'], activas[1]['carrera_id'])

        # 5. Autodetección de carrera según convocatoria del ciclista y fecha
        detected_val = auto_detectar_carrera_atleta('ath_val1', '2026-02-06', db_path=self.db_path)
        self.assertIsNotNone(detected_val)
        self.assertEqual(detected_val['carrera_id'], 'volta_valencia_2026')

        detected_oman = auto_detectar_carrera_atleta('ath_oman2', '2026-02-06', db_path=self.db_path)
        self.assertIsNotNone(detected_oman)
        self.assertEqual(detected_oman['carrera_id'], 'tour_oman_2026')

        # Ciclista no convocado en esa fecha
        detected_none = auto_detectar_carrera_atleta('ath_other', '2026-02-06', db_path=self.db_path)
        self.assertIsNone(detected_none)

        # 6. Obtener atletas por carrera
        ath_val_list = obtener_atletas_por_carrera('volta_valencia_2026', db_path=self.db_path)
        self.assertEqual(len(ath_val_list), 2)
        val_ids = [a['atleta_id'] for a in ath_val_list]
        self.assertIn('ath_val1', val_ids)

    def test_solo_datos_fechas_carrera(self):
        """Verifica que para los datos históricos de una carrera solo se toman en cuenta fechas de carrera."""
        # 1. Registrar una carrera oficial de 3 etapas
        carrera_info = {
            'carrera_id': 'vuelta_andalucia_2026',
            'nombre_carrera': 'Vuelta a Andalucía 2026',
            'fecha_inicio': '2026-02-18',
            'fecha_fin': '2026-02-20',
            'total_etapas': 3
        }
        guardar_carrera(carrera_info, atletas_ids=['rider_1'], db_path=self.db_path)

        # 2. Guardar actividades dentro de las fechas de carrera
        st1 = {'nombre': 'Rider 1', 'atleta_id': 'rider_1', 'distancia_km': 150.0, 'kilojulios_total': 3000, 'tss_total': 180, 'tiempo_mov_seg': 14400}
        st2 = {'nombre': 'Rider 1', 'atleta_id': 'rider_1', 'distancia_km': 160.0, 'kilojulios_total': 3200, 'tss_total': 190, 'tiempo_mov_seg': 15000}
        st3 = {'nombre': 'Rider 1', 'atleta_id': 'rider_1', 'distancia_km': 170.0, 'kilojulios_total': 3400, 'tss_total': 200, 'tiempo_mov_seg': 16000}

        guardar_resumen_etapa(st1, carrera_id='vuelta_andalucia_2026', etapa_num=1, fecha='2026-02-18', db_path=self.db_path)
        guardar_resumen_etapa(st2, carrera_id='vuelta_andalucia_2026', etapa_num=2, fecha='2026-02-19', db_path=self.db_path)
        guardar_resumen_etapa(st3, carrera_id='vuelta_andalucia_2026', etapa_num=3, fecha='2026-02-20', db_path=self.db_path)

        # 3. Intentar guardar un entrenamiento previo (fuera de fecha: 2026-02-15)
        st_prev = {'nombre': 'Rider 1', 'atleta_id': 'rider_1', 'distancia_km': 60.0, 'kilojulios_total': 1200, 'tss_total': 70, 'tiempo_mov_seg': 7200}
        act_prev_id = guardar_resumen_etapa(st_prev, carrera_id='vuelta_andalucia_2026', etapa_num=1, fecha='2026-02-15', db_path=self.db_path)

        # Verificar que guardar_resumen_etapa no lo asignó a vuelta_andalucia_2026
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("SELECT carrera_id FROM etapas_resumen WHERE actividad_id = ?", (act_prev_id,))
        row_prev = cur.fetchone()
        self.assertEqual(row_prev[0], 'entrenamiento')

        # 4. Insertar manualmente un registro desfasado con fecha posterior (2026-02-25) asignado a la carrera
        cur.execute("""
            INSERT INTO etapas_resumen (
                actividad_id, atleta_id, nombre_ciclista, carrera_id, nombre_carrera,
                etapa_num, fecha, temporada, distancia_km, tiempo_mov_s, pot_media_w, kj_total, tss
            ) VALUES (
                'rider_1_fake_post', 'rider_1', 'Rider 1', 'vuelta_andalucia_2026', 'Vuelta a Andalucía 2026',
                4, '2026-02-25', 2026, 100.0, 9000, 200, 2000, 100
            );
        """)
        conn.commit()
        conn.close()

        # 5. Consultar histórico etapa por etapa: SOLO deben figurar las 3 etapas oficiales
        df_etapas = obtener_historico_carrera_etapas('vuelta_andalucia_2026', db_path=self.db_path)
        self.assertEqual(len(df_etapas), 3)
        fechas = list(df_etapas['fecha'])
        self.assertEqual(fechas, ['2026-02-18', '2026-02-19', '2026-02-20'])
        self.assertNotIn('2026-02-15', fechas)
        self.assertNotIn('2026-02-25', fechas)

        # 6. Consultar resumen acumulado de la carrera: etapas_disputadas debe ser exactamente 3
        df_resumen = obtener_resumen_acumulado_carrera('vuelta_andalucia_2026', db_path=self.db_path)
        self.assertEqual(len(df_resumen), 1)
        self.assertEqual(df_resumen.iloc[0]['etapas_disputadas'], 3)
        self.assertEqual(df_resumen.iloc[0]['total_kj'], 3000 + 3200 + 3400)
        self.assertEqual(df_resumen.iloc[0]['total_km'], 150.0 + 160.0 + 170.0)

        # 7. Ejecutar migración en init_history_db y verificar limpieza del registro posterior
        init_history_db(self.db_path)
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("SELECT carrera_id FROM etapas_resumen WHERE actividad_id = 'rider_1_fake_post'")
        row_clean = cur.fetchone()
        self.assertEqual(row_clean[0], 'entrenamiento')
        conn.close()

    def test_obtener_fecha_archivo_fit(self):
        """Verifica la extracción de fecha de un archivo .fit y el filtrado por fechas de carrera."""
        from src.interactive_profile import obtener_fecha_archivo_fit, buscar_fit_local_ciclista
        fit_path = Path("data/today_race/19623637329.fit")
        if fit_path.exists():
            f_date = obtener_fecha_archivo_fit(fit_path)
            self.assertEqual(f_date, '2026-08-06')

            # Búsqueda local con rango de carrera que no coincide
            res_fuera = buscar_fit_local_ciclista(
                nombre="Adrian Fajardo",
                act_id="19623637329",
                directorios_busqueda=[Path("data/today_race")],
                rango_fechas=('2026-09-18', '2026-09-20')
            )
            self.assertIsNone(res_fuera)

            # Búsqueda local con fecha correcta
            res_dentro = buscar_fit_local_ciclista(
                nombre="Adrian Fajardo",
                act_id="19623637329",
                directorios_busqueda=[Path("data/today_race")],
                fecha_objetivo='2026-08-06'
            )
            self.assertIsNotNone(res_dentro)


if __name__ == '__main__':
    unittest.main()
