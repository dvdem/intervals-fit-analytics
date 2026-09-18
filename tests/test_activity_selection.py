"""
Pruebas unitarias para la selección de actividad óptima por consenso de compañeros
en fechas con múltiples actividades (tiempo y distancia).
"""

import sys
import unittest
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.interactive_profile import (
    extraer_segundos_hora_dia,
    seleccionar_actividad_cercana_companeros
)


class TestActivitySelection(unittest.TestCase):

    def test_extraer_segundos_hora_dia(self):
        # Casos válidos con T
        self.assertEqual(extraer_segundos_hora_dia("2026-08-06T12:30:00"), 12 * 3600 + 30 * 60)
        self.assertEqual(extraer_segundos_hora_dia("2026-08-06T09:15:30Z"), 9 * 3600 + 15 * 60 + 30)
        self.assertEqual(extraer_segundos_hora_dia("2026-08-06T14:00:00+02:00"), 14 * 3600)

        # Casos con espacio
        self.assertEqual(extraer_segundos_hora_dia("2026-08-06 12:30:00"), 12 * 3600 + 30 * 60)

        # Casos inválidos o nulos
        self.assertIsNone(extraer_segundos_hora_dia(None))
        self.assertIsNone(extraer_segundos_hora_dia(""))
        self.assertIsNone(extraer_segundos_hora_dia("invalido"))

    def test_ciclista_con_una_sola_actividad(self):
        acts_rider = [{"id": "act_1", "distance": 150000, "start_date_local": "2026-08-06T12:00:00"}]
        acts_comp = [{"id": "act_c1", "distance": 152000, "start_date_local": "2026-08-06T12:00:00"}]
        sel = seleccionar_actividad_cercana_companeros(acts_rider, acts_comp)
        self.assertEqual(sel["id"], "act_1")

    def test_seleccion_carrera_vs_calentamiento(self):
        """
        Un ciclista tiene un calentamiento matutino (12 km a las 09:30)
        y la etapa oficial (155 km a las 12:30).
        Sus compañeros han corrido ~154-156 km a las 12:30.
        Debe seleccionar la etapa oficial.
        """
        acts_rider = [
            {
                "id": "act_calentamiento",
                "name": "Rodillo calentamiento",
                "distance": 12000.0,
                "start_date_local": "2026-08-06T09:30:00",
                "moving_time": 1800.0
            },
            {
                "id": "act_etapa_real",
                "name": "Vuelta a Burgos - Etapa 2",
                "distance": 155000.0,
                "start_date_local": "2026-08-06T12:30:00",
                "moving_time": 14200.0
            }
        ]

        acts_companeros = [
            {
                "id": "comp_1",
                "distance": 154500.0,
                "start_date_local": "2026-08-06T12:30:10",
                "moving_time": 14180.0
            },
            {
                "id": "comp_2",
                "distance": 155200.0,
                "start_date_local": "2026-08-06T12:30:05",
                "moving_time": 14210.0
            },
            {
                "id": "comp_3",
                "distance": 154800.0,
                "start_date_local": "2026-08-06T12:30:00",
                "moving_time": 14190.0
            }
        ]

        sel = seleccionar_actividad_cercana_companeros(acts_rider, acts_companeros)
        self.assertEqual(sel["id"], "act_etapa_real")

    def test_seleccion_carrera_vs_soltar_piernas_tarde(self):
        """
        El ciclista tiene la etapa (140 km a las 12:00) y un paseo de vuelta al hotel (15 km a las 17:30).
        Debe seleccionar la etapa.
        """
        acts_rider = [
            {
                "id": "act_paseo_hotel",
                "name": "Vuelta al hotel",
                "distance": 15000.0,
                "start_date_local": "2026-08-06T17:30:00",
                "moving_time": 2100.0
            },
            {
                "id": "act_carrera",
                "name": "Etapa 1",
                "distance": 140000.0,
                "start_date_local": "2026-08-06T12:01:00",
                "moving_time": 13500.0
            }
        ]

        acts_companeros = [
            {
                "id": "comp_1",
                "distance": 141000.0,
                "start_date_local": "2026-08-06T12:00:00",
                "moving_time": 13550.0
            }
        ]

        sel = seleccionar_actividad_cercana_companeros(acts_rider, acts_companeros)
        self.assertEqual(sel["id"], "act_carrera")

    def test_sin_companeros_fallback_mayor_distancia(self):
        """
        Si un ciclista no tiene compañeros registrados para comparar,
        debe seleccionar la actividad de mayor distancia por defecto.
        """
        acts_rider = [
            {"id": "corta", "distance": 10000.0, "start_date_local": "2026-08-06T09:00:00"},
            {"id": "larga", "distance": 120000.0, "start_date_local": "2026-08-06T12:00:00"}
        ]
        sel = seleccionar_actividad_cercana_companeros(acts_rider, [])
        self.assertEqual(sel["id"], "larga")


if __name__ == "__main__":
    unittest.main()
