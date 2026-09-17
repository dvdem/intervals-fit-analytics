"""
Pruebas unitarias para la sincronización incremental de actividades con Intervals.icu.
"""

import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch
import pandas as pd
from starlette.testclient import TestClient

from src.history_manager import (
    init_history_db,
    sincronizar_historico_desde_api
)
from web.app import app, _SYNC_STATUS
from src.auth_manager import crear_usuario, eliminar_usuario, ROL_ADMINISTRADOR


class TestSyncIncremental(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp_dir.name, "test_history.db")
        self.roster_path = os.path.join(self.tmp_dir.name, "test_roster.csv")

        # Roster de prueba con 1 atleta
        df = pd.DataFrame([{
            "Name": "Ciclista Test",
            "intervals_id": "i99999",
            "weight": 68.5,
            "FTP": 360,
            "crank_length_m": 0.1725
        }])
        df.to_csv(self.roster_path, index=False)

        init_history_db(self.db_path)

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_sincronizacion_incremental_solo_nuevas(self):
        """Verifica que con solo_nuevas=True únicamente se descarguen y guarden actividades no registradas."""
        mock_client = MagicMock()

        # Actividad inicial
        act1 = {
            "id": "act_001",
            "type": "Ride",
            "start_date_local": "2026-03-01T10:00:00",
            "name": "Entrenamiento 1",
            "distance": 80000,
            "total_elevation_gain": 1200,
            "moving_time": 7200,
            "elapsed_time": 7400,
            "icu_average_watts": 250,
            "icu_joules": 1800000,
            "icu_training_load": 120
        }

        mock_client.get_activities.return_value = [act1]
        mock_client.get_athlete_power_curves.return_value = {
            "list": [{"secs": [60, 300], "watts": [450, 350], "watts_per_kg": [6.5, 5.1], "activity_id": ["act_001", "act_001"]}],
            "activities": {"act_001": {"name": "Entrenamiento 1", "start_date_local": "2026-03-01T10:00:00"}}
        }
        mock_client.get_wellness.return_value = [
            {"id": "2026-03-01", "hrv": 65, "restingHR": 48, "ctl": 80, "atl": 90, "tsb": -10}
        ]

        # 1. Primera sincronización (inicial)
        res1 = sincronizar_historico_desde_api(
            roster_path=self.roster_path,
            fecha_inicio="2026-01-01",
            db_path=self.db_path,
            client=mock_client,
            incluir_wellness=True,
            incluir_picos=True,
            verbose=False,
            solo_nuevas=True
        )

        self.assertEqual(res1["total_actividades"], 1)
        self.assertEqual(mock_client.get_athlete_power_curves.call_count, 1)

        # 2. Segunda sincronización sin actividades nuevas en la API
        mock_client.get_activities.reset_mock()
        mock_client.get_athlete_power_curves.reset_mock()
        mock_client.get_wellness.reset_mock()

        # Devuelve la misma actividad act1 desde 2026-03-01
        mock_client.get_activities.return_value = [act1]
        mock_client.get_wellness.return_value = []

        res2 = sincronizar_historico_desde_api(
            roster_path=self.roster_path,
            fecha_inicio="2026-01-01",
            db_path=self.db_path,
            client=mock_client,
            incluir_wellness=True,
            incluir_picos=True,
            verbose=False,
            solo_nuevas=True
        )

        # No debe haber actividades nuevas
        self.assertEqual(res2["total_actividades"], 0)
        # Se debe consultar a partir de la fecha máxima del atleta ('2026-03-01')
        mock_client.get_activities.assert_called_once_with(
            athlete_id="i99999",
            oldest="2026-03-01",
            newest=unittest.mock.ANY
        )
        # Como no hay actividades nuevas y ya existen picos, NO se deben recalcular curvas
        self.assertEqual(mock_client.get_athlete_power_curves.call_count, 0)

        # 3. Tercera sincronización: aparece una actividad nueva act_002
        act2 = {
            "id": "act_002",
            "type": "Ride",
            "start_date_local": "2026-03-05T10:00:00",
            "name": "Carrera Clásica",
            "distance": 140000,
            "total_elevation_gain": 2200,
            "moving_time": 14400,
            "elapsed_time": 14600,
            "icu_average_watts": 280,
            "icu_joules": 3500000,
            "icu_training_load": 220
        }
        mock_client.get_activities.reset_mock()
        mock_client.get_athlete_power_curves.reset_mock()
        mock_client.get_activities.return_value = [act1, act2]

        res3 = sincronizar_historico_desde_api(
            roster_path=self.roster_path,
            fecha_inicio="2026-01-01",
            db_path=self.db_path,
            client=mock_client,
            incluir_wellness=False,
            incluir_picos=True,
            verbose=False,
            solo_nuevas=True
        )

        # Solo debe registrar la actividad nueva (1)
        self.assertEqual(res3["total_actividades"], 1)
        # Al haber nueva actividad, debe recalcular curvas de potencia
        self.assertEqual(mock_client.get_athlete_power_curves.call_count, 1)

    def test_api_endpoint_sync_solo_nuevas(self):
        """Verifica que el endpoint /api/sync acepte solo_nuevas=true."""
        admin_user = "admin_test_sync"
        try:
            eliminar_usuario(admin_user)
        except Exception:
            pass
        crear_usuario(admin_user, "adminpass123", ROL_ADMINISTRADOR, "Admin Sync")

        client = TestClient(app)
        client.post("/api/auth/login", json={
            "username": admin_user,
            "password": "adminpass123"
        })

        # Asegurar estado limpio
        _SYNC_STATUS["running"] = False

        # Invocación con solo_nuevas=true
        with patch("web.app._run_background_sync") as mock_bg:
            res = client.post("/api/sync?solo_nuevas=true")
            self.assertEqual(res.status_code, 200)
            data = res.json()
            self.assertEqual(data["status"], "started")
            self.assertIn("actividades nuevas", data["message"])

        eliminar_usuario(admin_user)


if __name__ == '__main__':
    unittest.main()
