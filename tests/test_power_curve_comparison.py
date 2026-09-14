"""
Tests unitarios para la obtención y comparativa de picos de potencia (MMP vs PRs de Intervals.icu).
"""

import unittest
from unittest.mock import MagicMock
import numpy as np
import pandas as pd

from config import DEFAULT_POWER_DURATION_CURVE_DURATIONS
from src.power_peaks import (
    extraer_mejores_por_periodo,
    obtener_curvas_referencia_atleta,
    comparar_curva_actividad_con_referencia,
)
from src.interactive_profile import (
    procesar_telemetria_ciclista,
    COLORES_CICLISTAS,
)


class TestPowerCurveComparison(unittest.TestCase):

    def test_extraer_mejores_por_periodo_arrays_paralelos(self):
        """Verifica la extracción fiel de vatios desde la respuesta nativa de Intervals.icu."""
        payload_api = {
            "list": [
                {
                    "secs": [1, 5, 30, 60, 300, 1200],
                    "watts": [1250, 1180, 720, 540, 420, 360],
                    "ranks": [99.0, 99.0, 95.0, 90.0, 88.0, 85.0],  # No deben confundirse con vatios
                }
            ],
            "activities": {
                "act_1": {"name": "Criterium Vuelta", "start_date_local": "2024-05-10T14:00:00"}
            }
        }
        res = extraer_mejores_por_periodo(payload_api)
        self.assertEqual(res[1], 1250.0)
        self.assertEqual(res[5], 1180.0)
        self.assertEqual(res[30], 720.0)
        self.assertEqual(res[300], 420.0)
        self.assertEqual(res[1200], 360.0)

    def test_obtener_curvas_referencia_atleta_con_mock(self):
        """Verifica la obtención de curvas históricas y de temporada mediante cliente mockeado."""
        mock_client = MagicMock()
        mock_client.get_athlete_power_curves.side_effect = [
            # 1. All-time call
            {
                "list": [
                    {
                        "secs": [5, 60, 300],
                        "watts": [1200.0, 600.0, 400.0],
                        "watts_per_kg": [18.46, 9.23, 6.15],
                        "activity_id": ["a1", "a2", "a3"]
                    }
                ],
                "activities": {
                    "a1": {"name": "Sprint Final", "start_date_local": "2023-04-12T17:00:00"},
                    "a2": {"name": "Cronoescalada", "start_date_local": "2023-06-20T12:00:00"},
                    "a3": {"name": "Etapa Reina", "start_date_local": "2024-03-15T15:00:00"}
                }
            },
            # 2. Season call
            {
                "list": [
                    {
                        "secs": [5, 60, 300],
                        "watts": [1150.0, 580.0, 395.0],
                        "watts_per_kg": [17.69, 8.92, 6.08],
                        "activity_id": ["s1", "s2", "s3"]
                    }
                ],
                "activities": {
                    "s1": {"name": "Vuelta Burgos E1", "start_date_local": "2026-08-01T15:00:00"}
                }
            }
        ]

        curvas = obtener_curvas_referencia_atleta(mock_client, "i100", peso_kg=65.0)
        self.assertTrue(curvas['disponible'])
        self.assertIn(5, curvas['all_time']['curva'])
        self.assertEqual(curvas['all_time']['curva'][5], 1200.0)
        self.assertEqual(curvas['all_time']['actividades'][5]['nombre'], "Sprint Final")
        self.assertEqual(curvas['all_time']['actividades'][5]['fecha'], "2023-04-12")

        self.assertIn(300, curvas['temporada']['curva'])
        self.assertEqual(curvas['temporada']['curva'][300], 395.0)

    def test_comparar_curva_actividad_con_referencia(self):
        """Verifica la lógica de detección de PRs, cálculo de deltas y porcentajes de récord."""
        picos_actividad = {
            1: 1300.0,   # Récord superado (> 1250W)
            5: 1150.0,   # 1150 / 1200 = 95.8% (Top)
            30: 600.0,   # 600 / 700 = 85.7% (Alto)
            300: 350.0,  # 350 / 450 = 77.8% (Medio)
        }
        curva_ref = {
            1: 1250.0,
            5: 1200.0,
            30: 700.0,
            300: 450.0,
        }
        acts_meta = {
            1: {"nombre": "Sprint 2022", "fecha": "2022-07-01"}
        }

        duraciones = {1: "1s", 5: "5s", 30: "30s", 300: "5m"}
        comp = comparar_curva_actividad_con_referencia(
            picos_actividad=picos_actividad,
            curva_referencia=curva_ref,
            peso_kg=65.0,
            duraciones_obj=duraciones,
            actividades_meta=acts_meta
        )

        self.assertEqual(len(comp), 4)

        # 1s: Nuevo PR
        c1 = comp[0]
        self.assertTrue(c1['es_pr'])
        self.assertEqual(c1['nivel'], 'pr')
        self.assertIn('🏆 PR', c1['badge_texto'])
        self.assertEqual(c1['delta_w'], 50.0)
        self.assertEqual(c1['actividad_record'], "Sprint 2022")

        # 5s: Rendimiento Top (>= 95%)
        c5 = comp[1]
        self.assertFalse(c5['es_pr'])
        self.assertEqual(c5['nivel'], 'top')
        self.assertAlmostEqual(c5['pct_pr'], 95.8, places=1)
        self.assertEqual(c5['delta_w'], -50.0)

        # 30s: Rendimiento Alto (>= 85%)
        c30 = comp[2]
        self.assertEqual(c30['nivel'], 'alto')
        self.assertAlmostEqual(c30['pct_pr'], 85.7, places=1)

        # 300s: Rendimiento Medio
        c300 = comp[3]
        self.assertEqual(c300['nivel'], 'medio')
        self.assertAlmostEqual(c300['pct_pr'], 77.8, places=1)

    def test_procesar_telemetria_ciclista_calcula_curva_mmp_completa(self):
        """Verifica que procesar_telemetria_ciclista incluye stats['curva_mmp_completa'] para el dashboard."""
        n_puntos = 3605
        timestamps = pd.date_range("2026-08-05 10:00:00", periods=n_puntos, freq="1s")
        # Generar telemetría sintética con un sprint de 1000W al inicio y 300W el resto
        potencias = np.full(n_puntos, 300.0)
        potencias[:10] = 1000.0  # sprint 10s

        df_mock = pd.DataFrame({
            'timestamp': timestamps,
            'lat': np.linspace(42.34, 42.40, n_puntos),
            'lon': np.linspace(-3.70, -3.65, n_puntos),
            'altitud': np.linspace(800, 850, n_puntos),
            'velocidad': np.full(n_puntos, 10.0),
            'potencia': potencias,
            'cadencia': np.full(n_puntos, 90),
            'frecuencia_cardiaca': np.full(n_puntos, 150),
            'is_moving': np.full(n_puntos, True),
        })

        proc = procesar_telemetria_ciclista(
            df=df_mock,
            nombre="Ciclista Test",
            peso=68.0,
            color_cfg=COLORES_CICLISTAS[0],
            atleta_id="i999",
            ftp=350.0
        )

        stats = proc['stats']
        self.assertIn('curva_mmp_completa', stats)
        mmp = stats['curva_mmp_completa']

        # Verificar que contiene duraciones clave
        for d in [1, 5, 10, 60, 300, 1200, 3600]:
            self.assertIn(d, mmp)

        # 1s y 5s deben reflejar los 1000W del sprint
        val_1s = mmp[1]['watts'] if isinstance(mmp[1], dict) else mmp[1]
        val_5s = mmp[5]['watts'] if isinstance(mmp[5], dict) else mmp[5]
        self.assertAlmostEqual(val_1s, 1000.0, delta=1.0)
        self.assertAlmostEqual(val_5s, 1000.0, delta=1.0)
        if isinstance(mmp[1], dict):
            self.assertIn('kj_previos', mmp[1])
            self.assertIn('kjkg_previos', mmp[1])
            self.assertIn('tiempo_inicio_str', mmp[1])

        # 3600s debe estar cerca de ~302W
        val_3600 = mmp[3600]['watts'] if isinstance(mmp[3600], dict) else mmp[3600]
        self.assertTrue(300.0 <= val_3600 <= 310.0)

    def test_calcular_picos_potencia_con_contexto(self):
        """Verifica que calcular_picos_potencia_con_contexto calcula watts y kj_previos con exactitud."""
        from src.torque_analytics import calcular_picos_potencia_con_contexto

        # 10s a 200W, luego 5s a 1000W (sprint), luego 15s a 200W
        potencia = np.array([200.0] * 10 + [1000.0] * 5 + [200.0] * 15)
        res = calcular_picos_potencia_con_contexto(potencia, duraciones=[5], peso_kg=70.0)

        self.assertIn(5, res)
        pico_5s = res[5]
        self.assertEqual(pico_5s['watts'], 1000.0)
        self.assertEqual(pico_5s['idx_inicio'], 10)
        self.assertEqual(pico_5s['idx_fin'], 14)
        self.assertEqual(pico_5s['tiempo_inicio_str'], "00:00:10")
        # 10s * 200W = 2000 J = 2.0 kJ
        self.assertAlmostEqual(pico_5s['kj_previos'], 2.0, delta=0.1)
        self.assertAlmostEqual(pico_5s['kjkg_previos'], round(2.0 / 70.0, 1), delta=0.1)

    def test_comparar_curva_actividad_con_referencia_con_fatiga(self):
        """Verifica la asignación de badges de durabilidad y cálculo de deltas de kJ."""
        picos_actividad = {
            5: {
                'watts': 1250.0,  # Supera récord de 1200W
                'wkg': 19.23,
                'kj_previos': 1800.0,  # Fatiga severa (> 1500 kJ)
                'kjkg_previos': 27.7,
                'tiempo_inicio_str': '02:45:00',
                'pct_etapa': 65.0
            },
            60: {
                'watts': 590.0,  # 590 / 600 = 98.3% PR
                'wkg': 9.08,
                'kj_previos': 2200.0,
                'kjkg_previos': 33.8,
                'tiempo_inicio_str': '03:10:00',
                'pct_etapa': 75.0
            }
        }
        curva_ref = {5: 1200.0, 60: 600.0}
        actividades_meta = {
            5: {'nombre': 'Récord 5s', 'fecha': '2023-05-10', 'kj_previos': 400.0, 'kjkg_previos': 6.2},
            60: {'nombre': 'Récord 1m', 'fecha': '2023-06-12', 'kj_previos': 800.0, 'kjkg_previos': 12.3}
        }

        comp = comparar_curva_actividad_con_referencia(
            picos_actividad=picos_actividad,
            curva_referencia=curva_ref,
            peso_kg=65.0,
            duraciones_obj={5: "5s", 60: "1m"},
            actividades_meta=actividades_meta
        )

        item_5s = next(x for x in comp if x['segundos'] == 5)
        self.assertTrue(item_5s['es_pr'])
        self.assertEqual(item_5s['badge_durabilidad'], '🏆 PR en Fatiga')
        self.assertEqual(item_5s['kj_act'], 1800.0)
        self.assertEqual(item_5s['kj_ref'], 400.0)
        self.assertEqual(item_5s['delta_kj'], 1400.0)

        item_1m = next(x for x in comp if x['segundos'] == 60)
        self.assertFalse(item_1m['es_pr'])
        self.assertGreaterEqual(item_1m['pct_pr'], 95.0)
        # delta_kj = 2200 - 800 = 1400 > 500 -> Top bajo Fatiga
        self.assertEqual(item_1m['badge_durabilidad'], '🔥 Top bajo Fatiga')

    def test_generar_html_dashboard_interactivo_incluye_power_curve_section(self):
        """Verifica que el dashboard HTML generado contiene la sección de curva de potencia y sus controles."""
        from src.interactive_profile import generar_html_dashboard_interactivo

        etapa_info = {
            'distancia_total_km': 120.5,
            'desnivel_pos_m': 1800,
            'altitud_max': 1250,
            'tramos': [],
            'perfil': []
        }
        ciclistas_proc = [
            {
                'stats': {
                    'nombre': 'Rider Test',
                    'atleta_id': 'i100',
                    'peso_kg': 65.0,
                    'color': '#38bdf8',
                    'distancia_km': 120.5,
                    'tiempo_mov_seg': 10800,
                    'curva_mmp_completa': {
                        1: {'watts': 1200.0, 'wkg': 18.5, 'kj_previos': 500.0, 'kjkg_previos': 7.7},
                        5: {'watts': 1100.0, 'wkg': 16.9, 'kj_previos': 1200.0, 'kjkg_previos': 18.5},
                        60: {'watts': 500.0, 'wkg': 7.7, 'kj_previos': 1800.0, 'kjkg_previos': 27.7},
                        300: {'watts': 400.0, 'wkg': 6.2, 'kj_previos': 2100.0, 'kjkg_previos': 32.3}
                    },
                    'torque_media_nm': 35.0,
                    'torque_max_nm': 110.0,
                    'np_w': 320,
                    'tss_total': 210,
                    'tss_hora': 70.0,
                },
                'samples_by_dist': {},
                'samples_by_time': {},
                'power_curves_ref': {
                    'disponible': True,
                    'all_time': {'curva': {1: 1250.0, 5: 1150.0, 60: 520.0, 300: 410.0}, 'curva_wkg': {}, 'actividades': {}},
                    'temporada': {'curva': {1: 1180.0, 5: 1090.0, 60: 490.0, 300: 395.0}, 'curva_wkg': {}, 'actividades': {}}
                },
                'comparativa_picos': {
                    'all_time': [{'segundos': 5, 'pct_pr': 95.7, 'es_pr': False, 'delta_w': -50.0, 'kj_act': 1200.0}],
                    'temporada': [{'segundos': 5, 'pct_pr': 100.9, 'es_pr': True, 'delta_w': 10.0, 'kj_act': 1200.0}]
                }
            }
        ]

        html = generar_html_dashboard_interactivo(
            etapa_info=etapa_info,
            ciclistas_proc=ciclistas_proc,
            titulo_etapa="Test Etapa con Power Curve"
        )

        self.assertIn('id="powerCurveSection"', html)
        self.assertIn('id="powerDurationCurveChart"', html)
        self.assertIn('id="powerCurveRiderSelect"', html)
        self.assertIn('id="powerCurveTable"', html)
        self.assertIn('Desgaste Etapa (kJ)', html)
        self.assertIn('Contexto Durabilidad', html)
        self.assertIn('btnPdcAllTime', html)
        self.assertIn('btnPdcSeason', html)
        self.assertIn('initPowerCurveSection', html)
        self.assertIn('power_curves_ref', html)

    def test_resolver_kj_actividades_historicas_con_mock(self):
        """Verifica que resolver_kj_actividades_historicas procesa start_index y telemetría."""
        from src.power_peaks import resolver_kj_actividades_historicas

        mock_client = MagicMock()
        mock_client.get_activity_power_curve_json.return_value = {
            'secs': [5, 60],
            'watts': [1200, 550],
            'start_index': [100, 500],
            'weight': 65.0
        }
        mock_client.get_activity_streams.return_value = pd.DataFrame({
            'potencia': [200.0] * 1000
        })

        actividades_meta = {
            5: {'activity_id': 'act_mock_1', 'nombre': 'Carrera Mock', 'fecha': '2024-01-01'}
        }

        res = resolver_kj_actividades_historicas(mock_client, actividades_meta, peso_kg=65.0)

        self.assertIn(5, res)
        # 100s * 200W = 20.000 J = 20.0 kJ
        self.assertAlmostEqual(res[5]['kj_previos'], 20.0, delta=0.5)
        self.assertEqual(res[5]['start_index'], 100)
        self.assertEqual(res[5]['tiempo_hms'], "00:01:40")


if __name__ == '__main__':
    unittest.main()

