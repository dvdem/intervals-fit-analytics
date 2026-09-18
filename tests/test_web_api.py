"""
Pruebas automatizadas para la API Web de Intervals Fit Analytics.
Verifica endpoints de dashboard, atletas (CRUD), récords con kJ y carreras.
"""

import sys
import unittest
from pathlib import Path

# Asegurar path raíz
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from fastapi.testclient import TestClient
from web.app import app


class TestWebAPI(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        # Iniciar sesión como administrador por defecto
        login_resp = cls.client.post("/api/auth/login", json={
            "username": "admin",
            "password": "#siemprevalientes"
        })
        assert login_resp.status_code == 200, f"Error en login: {login_resp.text}"

    def test_root_html(self):
        """Verifica que la página principal SPA cargue correctamente."""
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Intervals Fit Analytics", response.text)
        self.assertIn("Dashboard General", response.text)

    def test_dashboard_summary(self):
        """Verifica el endpoint de resumen general del equipo."""
        response = self.client.get("/api/dashboard")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("total_ciclistas", data)
        self.assertIn("db_stats", data)
        self.assertGreater(data["total_ciclistas"], 0)

    def test_athletes_list(self):
        """Verifica el listado de atletas desde el roster."""
        response = self.client.get("/api/athletes")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIsInstance(data, list)
        self.assertGreater(len(data), 0)
        # Mario Aparicio debe estar en la lista
        ids = [a["intervals_id"] for a in data]
        self.assertIn("i554068", ids)

    def test_season_bests_with_kj(self):
        """Verifica la consulta de mejores números con desglose de fatiga previa."""
        response = self.client.get("/api/season-bests/i554068?temporada=2026")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["athlete_id"], "i554068")
        records = data["records"]
        self.assertIsInstance(records, list)
        self.assertGreater(len(records), 0)
        first_rec = records[0]
        self.assertIn("max_watts", first_rec)
        self.assertIn("kj_previos", first_rec)
        self.assertIn("kj_esfuerzo", first_rec)
        self.assertIn("kj_totales", first_rec)
        self.assertIn("momento_carrera", first_rec)

    def test_races_list(self):
        """Verifica el historial de carreras registradas."""
        response = self.client.get("/api/races")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIsInstance(data, list)

    def test_athletes_crud_lifecycle(self):
        """Verifica el ciclo de vida completo de creación, edición y borrado de un atleta."""
        test_id = "test_cyclist_999"
        payload_create = {
            "name": "Ciclista Test Unit",
            "intervals_id": test_id,
            "weight": 68.5,
            "ftp": 395.0,
            "carrera": 2,
            "biela": 172.5
        }

        # 1. Crear
        res_create = self.client.post("/api/athletes", json=payload_create)
        self.assertEqual(res_create.status_code, 200)

        # 2. Verificar que existe
        res_list = self.client.get("/api/athletes")
        ids = [a["intervals_id"] for a in res_list.json()]
        self.assertIn(test_id, ids)

        # 3. Editar
        payload_update = {
            "weight": 67.0,
            "ftp": 405.0
        }
        res_update = self.client.put(f"/api/athletes/{test_id}", json=payload_update)
        self.assertEqual(res_update.status_code, 200)

        # 4. Eliminar
        res_del = self.client.delete(f"/api/athletes/{test_id}")
        self.assertEqual(res_del.status_code, 200)

        # 5. Confirmar borrado
        res_list_post = self.client.get("/api/athletes")
        ids_post = [a["intervals_id"] for a in res_list_post.json()]
        self.assertNotIn(test_id, ids_post)

    def test_power_report_data_endpoint(self):
        """Verifica que el endpoint /api/power-report/data responda con estructura válida."""
        from unittest.mock import patch
        import pandas as pd

        fake_peaks = pd.DataFrame([
            {
                'athlete_id': 'i1',
                'athlete_name': 'Test Rider',
                'weight_kg': 70.0,
                'duration_s': 5,
                'duration_label': '5s',
                'peak_watts': 1000.0,
                'peak_wkg': 14.29,
                'peak_date': '2026-09-01',
                'all_time_watts': 1100.0,
                'all_time_wkg': 15.71,
                'all_time_date': '2025-06-01'
            },
            {
                'athlete_id': 'i1',
                'athlete_name': 'Test Rider',
                'weight_kg': 70.0,
                'duration_s': 300,
                'duration_label': '5m',
                'peak_watts': 400.0,
                'peak_wkg': 5.71,
                'peak_date': '2026-09-01',
                'all_time_watts': 420.0,
                'all_time_wkg': 6.0,
                'all_time_date': '2025-06-01'
            }
        ])

        fake_metrics = pd.DataFrame([
            {
                'fecha': '2026-09-15',
                'daily_load': 100.0,
                'ctl': 85.0,
                'atl': 90.0,
                'tsb': -5.0,
                'ramp_rate_7d': 2.5,
                'athlete_name': 'Test Rider'
            }
        ])

        fake_athletes = [{'athlete_id': 'i1', 'athlete_name': 'Test Rider', 'carrera': 1}]

        with patch("web.app.IntervalsClient.get_athletes_list", return_value=fake_athletes), \
             patch("web.app.calcular_picos_potencia", return_value=fake_peaks), \
             patch("web.app.calcular_metricas_carga", return_value=fake_metrics):
            res = self.client.get("/api/power-report/data?dias=30&dias_carga=60&grupo=1")
            self.assertEqual(res.status_code, 200)
            data = res.json()
            self.assertIn("peaks_table", data)
            self.assertIn("metrics_table", data)
            self.assertGreater(len(data["peaks_table"]), 0)
            first_peak = data["peaks_table"][0]
            self.assertEqual(first_peak["Ciclista"], "Test Rider")
            self.assertIn("5s (W)", first_peak)
            self.assertIn("5s (W/kg)", first_peak)
            first_metric = data["metrics_table"][0]
            self.assertEqual(first_metric["athlete_name"], "Test Rider")
            self.assertEqual(first_metric["ctl"], 85.0)

            # Validar serie temporal de carga para gráfico CTL/ATL/TSB
            self.assertIn("load_timeseries", data)
            self.assertGreater(len(data["load_timeseries"]), 0)
            team_ts = next((ts for ts in data["load_timeseries"] if ts.get("is_team_avg")), None)
            self.assertIsNotNone(team_ts)
            rider_ts = next((ts for ts in data["load_timeseries"] if ts["athlete_name"] == "Test Rider"), None)
            self.assertIsNotNone(rider_ts)
            self.assertEqual(rider_ts["series"][0]["ctl"], 85.0)
            self.assertEqual(rider_ts["series"][0]["atl"], 90.0)
            self.assertEqual(rider_ts["series"][0]["tsb"], -5.0)

            # Validar comparativa con mejor registro histórico (PR)
            self.assertIn("duraciones", first_peak)
            self.assertIn("5s", first_peak["duraciones"])
            self.assertEqual(first_peak["duraciones"]["5s"]["peak_watts"], 1000)
            self.assertEqual(first_peak["duraciones"]["5s"]["all_time_watts"], 1100)
            self.assertAlmostEqual(first_peak["duraciones"]["5s"]["pct_pr"], 90.9, places=1)
            self.assertFalse(first_peak["duraciones"]["5s"]["es_pr"])

    def test_power_report_export_endpoint(self):
        """Verifica que el endpoint /api/power-report/export genere el enlace de descarga."""
        from unittest.mock import patch
        import pandas as pd

        fake_peaks = pd.DataFrame([
            {
                'athlete_id': 'i1',
                'athlete_name': 'Test Rider',
                'weight_kg': 70.0,
                'duration_s': 5,
                'duration_label': '5s',
                'peak_watts': 1000.0,
                'peak_wkg': 14.29,
                'peak_date': '2026-09-01',
                'all_time_watts': 1100.0,
                'all_time_wkg': 15.71,
                'all_time_date': '2025-06-01'
            }
        ])
        fake_metrics = pd.DataFrame()
        fake_athletes = [{'athlete_id': 'i1', 'athlete_name': 'Test Rider', 'carrera': 1}]

        with patch("web.app.IntervalsClient.get_athletes_list", return_value=fake_athletes), \
             patch("web.app.calcular_picos_potencia", return_value=fake_peaks), \
             patch("web.app.calcular_metricas_carga", return_value=fake_metrics), \
             patch("web.app.generar_informe_potencias_y_carga", return_value=Path("output/test.pdf")):
            res = self.client.post("/api/power-report/export", json={
                "grupo": 1,
                "dias": 30,
                "dias_carga": 60,
                "formato": "pdf"
            })
            self.assertEqual(res.status_code, 200)
            data = res.json()
            self.assertEqual(data["status"], "ok")
            self.assertIn("pdf", data["archivos"])

    def test_race_groups_endpoints(self):
        """Verifica la consulta y actualización de la configuración de grupos de carrera."""
        # 1. Obtener grupos
        res_get = self.client.get("/api/race-groups")
        self.assertEqual(res_get.status_code, 200)
        data = res_get.json()
        self.assertIn("1", data)
        self.assertIn("2", data)
        self.assertIn("nombre_carrera", data["1"])

        # 2. Actualizar configuración del Grupo 1
        original_name = data["1"]["nombre_carrera"]
        update_payload = {
            "nombre_carrera": "Volta a Catalunya Test",
            "categoria": "UCI WT",
            "pais": "España",
            "total_etapas": 7,
            "etapa_actual": 3,
            "fecha_inicio": "2026-03-23",
            "fecha_fin": "2026-03-29",
            "notas": "Objetivo victoria de etapa",
            "carrera_id_link": "tres_cantos_ciclismo_en_ruta"
        }
        res_post = self.client.post("/api/race-groups/1", json=update_payload)
        self.assertEqual(res_post.status_code, 200)
        self.assertEqual(res_post.json()["status"], "ok")

        # 3. Verificar persistencia
        res_verify = self.client.get("/api/race-groups")
        self.assertEqual(res_verify.json()["1"]["nombre_carrera"], "Volta a Catalunya Test")
        self.assertEqual(res_verify.json()["1"]["categoria"], "UCI WT")

        # 4. Restaurar estado original
        restore_payload = {
            "nombre_carrera": original_name,
            "categoria": "UCI 2.Pro",
            "pais": "España",
            "total_etapas": 5,
            "etapa_actual": 2,
            "carrera_id_link": "tres_cantos_ciclismo_en_ruta"
        }
        self.client.post("/api/race-groups/1", json=restore_payload)

    def test_dashboard_enriched_race_groups(self):
        """Verifica que el dashboard general incluya competiciones enriquecidas con métricas y convocados."""
        res = self.client.get("/api/dashboard")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("carreras_activas", data)
        self.assertIn("total_carreras", data)
        carrera_info = data.get("proxima_carrera") or data.get("ultima_carrera")
        if carrera_info:
            self.assertIn("nombre_carrera", carrera_info)
            self.assertIn("categoria", carrera_info)
            self.assertIn("dist_total_km", carrera_info)
            self.assertIn("kj_totales", carrera_info)
            self.assertIn("progreso_pct", carrera_info)
            self.assertIn("convocados", carrera_info)

    def test_race_history_and_summary(self):
        """Verifica la consulta de histórico etapa a etapa y balance final de una carrera."""
        carrera_id = "tres_cantos_ciclismo_en_ruta"

        # 1. Histórico de etapas
        res_hist = self.client.get(f"/api/races/{carrera_id}/history")
        self.assertEqual(res_hist.status_code, 200)
        hist_data = res_hist.json()
        self.assertEqual(hist_data["carrera_id"], carrera_id)
        self.assertIn("etapas", hist_data)
        self.assertGreater(hist_data["total_registros"], 0)

        first_stage = hist_data["etapas"][0]
        self.assertIn("atleta_id", first_stage)
        self.assertIn("etapa_num", first_stage)
        self.assertIn("kj_total", first_stage)
        self.assertIn("kj_acumulados", first_stage)
        self.assertIn("tss_acumulados", first_stage)

        # 2. Balance final / resumen de la vuelta
        res_sum = self.client.get(f"/api/races/{carrera_id}/summary")
        self.assertEqual(res_sum.status_code, 200)
        sum_data = res_sum.json()
        self.assertEqual(sum_data["carrera_id"], carrera_id)
        self.assertIn("resumen", sum_data)
        self.assertGreater(sum_data["total_atletas"], 0)

        first_athlete = sum_data["resumen"][0]
        self.assertIn("atleta_id", first_athlete)
        self.assertIn("etapas_disputadas", first_athlete)
        self.assertIn("distancia_total_km", first_athlete)
        self.assertIn("kj_totales", first_athlete)
        self.assertIn("tss_total", first_athlete)

        # 3. Carrera con valores nulos/NaN (ej. huangsan con torque_media_nm nulo)
        res_huang = self.client.get("/api/races/huangsan/history")
        self.assertEqual(res_huang.status_code, 200)
        huang_data = res_huang.json()
        self.assertGreater(huang_data["total_registros"], 0)
        self.assertIn("etapas", huang_data)

        res_huang_sum = self.client.get("/api/races/huangsan/summary")
        self.assertEqual(res_huang_sum.status_code, 200)
        huang_sum_data = res_huang_sum.json()
        self.assertGreater(huang_sum_data["total_atletas"], 0)

        # 4. Carrera inexistente debe responder 200 con lista vacía
        res_empty = self.client.get("/api/races/carrera_no_existente_999/history")
        self.assertEqual(res_empty.status_code, 200)
        self.assertEqual(res_empty.json()["total_registros"], 0)
    def test_races_calendar_and_convocatoria_api(self):
        """Verifica el ciclo de vida completo de creación, edición, convocatoria y borrado de carrera."""
        test_carrera_id = "test_itzulia_2026"
        payload_create = {
            "carrera_id": test_carrera_id,
            "nombre_carrera": "Itzulia Basque Country Test",
            "categoria": "UCI WT",
            "pais": "España",
            "fecha_inicio": "2026-04-06",
            "fecha_fin": "2026-04-11",
            "total_etapas": 6,
            "etapa_actual": 0,
            "notas": "Vuelta WorldTour por etapas",
            "atletas_ids": ["i554068"]
        }

        # 1. Crear carrera
        res_create = self.client.post("/api/races", json=payload_create)
        self.assertEqual(res_create.status_code, 200)
        data_create = res_create.json()
        self.assertEqual(data_create["status"], "ok")
        self.assertEqual(data_create["carrera_id"], test_carrera_id)

        # 2. Obtener lista con filtro
        res_list = self.client.get("/api/races")
        self.assertEqual(res_list.status_code, 200)
        carreras_ids = [c["carrera_id"] for c in res_list.json()]
        self.assertIn(test_carrera_id, carreras_ids)

        # 3. Detalle de carrera
        res_detail = self.client.get(f"/api/races/{test_carrera_id}")
        self.assertEqual(res_detail.status_code, 200)
        detail = res_detail.json()
        self.assertEqual(detail["nombre_carrera"], "Itzulia Basque Country Test")
        self.assertEqual(len(detail["convocados"]), 1)
        self.assertEqual(detail["convocados"][0]["atleta_id"], "i554068")

        # 4. Actualizar convocatoria
        res_conv = self.client.post(
            f"/api/races/{test_carrera_id}/convocatoria",
            json={"athlete_ids": ["i554068", "i999999"]}
        )
        self.assertEqual(res_conv.status_code, 200)
        self.assertEqual(res_conv.json()["total_convocados"], 2)

        # 5. Obtener convocatoria
        res_get_conv = self.client.get(f"/api/races/{test_carrera_id}/convocatoria")
        self.assertEqual(res_get_conv.status_code, 200)
        self.assertEqual(res_get_conv.json()["total_convocados"], 2)

        # 6. Actualizar metadatos (PUT)
        payload_update = {
            "nombre_carrera": "Itzulia Basque Country Test 2026 (Updated)",
            "categoria": "UCI WT",
            "pais": "España",
            "fecha_inicio": "2026-04-06",
            "fecha_fin": "2026-04-11",
            "total_etapas": 6,
            "etapa_actual": 2
        }
        res_put = self.client.put(f"/api/races/{test_carrera_id}", json=payload_update)
        self.assertEqual(res_put.status_code, 200)

        res_detail_updated = self.client.get(f"/api/races/{test_carrera_id}")
        self.assertEqual(res_detail_updated.json()["etapa_actual"], 2)

        # 7. Eliminar carrera
        res_del = self.client.delete(f"/api/races/{test_carrera_id}")
        self.assertEqual(res_del.status_code, 200)

        # Verificar que ya no existe
        res_check_del = self.client.get(f"/api/races/{test_carrera_id}")
        self.assertEqual(res_check_del.status_code, 404)

    def test_dashboard_calendar_keys(self):
        """Verifica que el dashboard incluya los campos de carreras activas y calendario."""
        res = self.client.get("/api/dashboard")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("carreras_activas", data)
        self.assertIn("total_carreras", data)
        self.assertIsInstance(data["carreras_activas"], list)
        self.assertGreater(data["total_carreras"], 0)

    def test_stage_analyze_with_carrera_id(self):
        """Verifica que /api/stage/analyze acepte carrera_id y devuelva los enlaces de perfiles interactivos."""
        from unittest.mock import patch
        with patch("web.app.generar_dashboard_perfil_interactivo", return_value=Path("output/test_profile.html")):
            payload = {
                "fecha": "2026-08-06",
                "carrera_id": "vuelta-a-burgos-2026",
                "titulo": "Vuelta a Burgos - Etapa 2",
                "generar_pdf": False,
                "generar_docx": False
            }
            res = self.client.post("/api/stage/analyze", json=payload)
            self.assertEqual(res.status_code, 200)
            data = res.json()
            self.assertEqual(data["status"], "ok")
            self.assertIn("archivos", data)
            self.assertIn("html", data["archivos"])

    def test_stage_analyze_overwrites_existing_profile_same_date(self):
        """Verifica que al generar un perfil de etapa se sobreescriba si ya existe uno de la misma fecha/carrera."""
        from unittest.mock import patch
        from config import OUTPUT_DIR

        test_date = "2026-08-06"
        carrera_id = "test_carrera_overwrite"
        target_html = OUTPUT_DIR / f"perfil_interactivo_{test_date}_{carrera_id}.html"
        old_timestamped = OUTPUT_DIR / f"perfil_interactivo_{test_date}_{carrera_id}_20260806_112233.html"

        # Crear archivos previos de prueba
        target_html.write_text("contenido viejo", encoding="utf-8")
        old_timestamped.write_text("timestamped viejo", encoding="utf-8")

        def fake_generar(output_html, **kwargs):
            Path(output_html).write_text("contenido nuevo sobreescrito", encoding="utf-8")
            return Path(output_html)

        with patch("web.app.generar_dashboard_perfil_interactivo", side_effect=fake_generar):
            payload = {
                "fecha": test_date,
                "carrera_id": carrera_id,
                "titulo": "Test Overwrite",
                "generar_pdf": False,
                "generar_docx": False
            }
            res = self.client.post("/api/stage/analyze", json=payload)
            self.assertEqual(res.status_code, 200)

        # Verificar que el viejo timestamped fue eliminado
        self.assertFalse(old_timestamped.exists())
        # Verificar que el target principal fue sobreescrito con el nuevo contenido
        self.assertTrue(target_html.exists())
        self.assertEqual(target_html.read_text(encoding="utf-8"), "contenido nuevo sobreescrito")

        # Limpiar
        if target_html.exists():
            target_html.unlink()
        if old_timestamped.exists():
            old_timestamped.unlink()

    def test_guardar_resumen_etapa_overwrites_same_date(self):
        """Verifica que guardar_resumen_etapa sobreescriba actividades previas del mismo ciclista y fecha."""
        from src.history_manager import guardar_resumen_etapa, _conectar_db, HISTORY_DB_PATH

        test_ath = "test_overwriter_cyclist"
        test_fecha = "2026-09-18"
        test_carrera = "test_race_overwrite"

        stats_v1 = {
            'atleta_id': test_ath,
            'nombre': 'Ciclista Overwrite',
            'distancia_km': 100.0,
            'kilojulios_total': 2000.0,
            'actividad_id': 'act_v1_sync'
        }
        stats_v2 = {
            'atleta_id': test_ath,
            'nombre': 'Ciclista Overwrite',
            'distancia_km': 120.0,
            'kilojulios_total': 2500.0,
            'actividad_id': 'act_v2_analyzed'
        }

        # 1. Guardar versión 1
        guardar_resumen_etapa(stats_v1, carrera_id=test_carrera, etapa_num=1, fecha=test_fecha)

        # 2. Guardar versión 2 para la misma fecha y carrera
        guardar_resumen_etapa(stats_v2, carrera_id=test_carrera, etapa_num=1, fecha=test_fecha)

        # 3. Comprobar que solo existe 1 registro y es el v2
        with _conectar_db(HISTORY_DB_PATH) as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT actividad_id, distancia_km, kj_total 
                FROM etapas_resumen 
                WHERE atleta_id = ? AND fecha = ?;
            """, (test_ath, test_fecha))
            rows = cur.fetchall()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0][0], 'act_v2_analyzed')
            self.assertEqual(rows[0][1], 120.0)
            self.assertEqual(rows[0][2], 2500.0)

            # Limpiar registro de test
            conn.execute("DELETE FROM picos_historicos WHERE actividad_id = 'act_v2_analyzed';")
            conn.execute("DELETE FROM etapas_resumen WHERE atleta_id = ?;", (test_ath,))
            conn.execute("DELETE FROM ciclistas WHERE atleta_id = ?;", (test_ath,))
            conn.commit()


if __name__ == "__main__":
    unittest.main()
