"""
Pruebas unitarias para el generador de informes en formato Word (.docx).
Verifica la creación del documento, estructura de tablas nativas, incrustación de gráficos y métricas de kJ.
"""

import unittest
import tempfile
from pathlib import Path
from datetime import datetime
import pandas as pd
import numpy as np

import docx
from src.word_reports import generar_informe_etapa_word, generar_informe_potencias_y_carga_word


class TestWordReports(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.output_docx = Path(self.temp_dir.name) / "test_etapa.docx"

        # Datos simulados de perfil y etapa
        self.etapa_info = {
            'distancia_total_km': 85.5,
            'desnivel_pos_m': 1420,
            'clima': {
                'temp_media_c': 22.4,
                'humedad_media_pct': 48,
                'viento_media_kmh': 14.5,
                'viento_cardinal': 'NE',
                'viento_rafagas_max_kmh': 24.0,
            },
            'perfil_altimetria': [
                {'x': 0.0, 'y': 650.0},
                {'x': 25.0, 'y': 890.0},
                {'x': 50.0, 'y': 1200.0},
                {'x': 85.5, 'y': 710.0}
            ]
        }

        # Datos simulados de telemetría y ciclistas
        d_seq = np.linspace(0, 85.5, 100)
        samples_mock = [
            {
                'd_km': float(d),
                'pwr': float(280 + 50 * np.sin(d / 10)),
                'wkg': float((280 + 50 * np.sin(d / 10)) / 68.0),
                'hr': float(155 + 15 * np.cos(d / 10)),
                'kj': float(d * 25.0),
                'kjkg_h': float(18.0 + 4.0 * np.sin(d / 8)),
                'tss': float(d * 1.5),
                'trq': float(38.0 + 8.0 * np.sin(d / 5))
            }
            for d in d_seq
        ]

        self.ciclistas_proc = [
            {
                'stats': {
                    'nombre': 'Ciclista Test 1',
                    'posicion_str': '1º',
                    'gap_lider_str': 'Líder',
                    'distancia_km': 85.5,
                    'tiempo_mov_seg': 7200,
                    'vel_media_kmh': 42.75,
                    'pot_media_w': 285,
                    'np_w': 310,
                    'w_kg_media': 4.19,
                    'fc_media_bpm': 158,
                    'fc_max_bpm': 186,
                    'cad_media_rpm': 88,
                    'cad_pedaleo_rpm': 91,
                    'pct_cad_baja': 12.0,
                    'pct_cad_optima': 76.0,
                    'pct_cad_alta': 12.0,
                    'kilojulios_total': 2140,
                    'kj_kg': 31.5,
                    'kj_kg_hora': 17.8,
                    'tss_total': 135,
                    'tss_hora': 67.5,
                    'torque_media_nm': 36.5,
                    'torque_max_nm': 78.0,
                    'peso_kg': 68.0,
                    'color': '#7c3aed',
                    'curva_mmp_completa': {
                        5: {'watts': 850, 'wkg': 12.5, 'kj_previos': 1850.0, 'kjkg_previos': 27.2, 'pct_etapa': 88.5},
                        60: {'watts': 520, 'wkg': 7.65, 'kj_previos': 1420.0, 'kjkg_previos': 20.9, 'pct_etapa': 65.0},
                        300: {'watts': 410, 'wkg': 6.03, 'kj_previos': 1100.0, 'kjkg_previos': 16.2, 'pct_etapa': 48.0},
                        1200: {'watts': 345, 'wkg': 5.07, 'kj_previos': 650.0, 'kjkg_previos': 9.6, 'pct_etapa': 28.0},
                        3600: {'watts': 295, 'wkg': 4.34, 'kj_previos': 120.0, 'kjkg_previos': 1.8, 'pct_etapa': 10.0}
                    },
                    'cuadrantes': {
                        'trq_thresh': 40.0,
                        'puntos': [{'cad': 85.0, 'trq': 36.0}, {'cad': 92.0, 'trq': 45.0}]
                    }
                },
                'samples_by_dist': samples_mock,
                'tramos_horarios': [
                    {'np_w': 315, 'fc_media_bpm': 156, 'distancia_km': 43.0},
                    {'np_w': 305, 'fc_media_bpm': 160, 'distancia_km': 42.5}
                ],
                'comparativa_picos': {
                    'all_time': [
                        {
                            'segundos': 300,
                            'watts_act': 410,
                            'watts_ref': 405,
                            'pct_pr': 101.2,
                            'es_pr': True,
                            'kj_act': 1100.0,
                            'kj_ref': 850.0,
                            'delta_kj': 250.0,
                            'durabilidad_badge': {'texto': '🏆 PR en Fatiga', 'clase': 'pr-badge-dur-pr'}
                        }
                    ]
                },
                'wellness_load': {
                    'ctl': 94.2,
                    'atl': 88.5,
                    'tsb': 5.7,
                    'status': {'label': 'Fresco / Competitivo'},
                    'hrv_rmssd': 68.4,
                    'hrv_media_7d': 65.1,
                    'resting_hr': 42,
                    'resting_hr_media_7d': 44,
                    'weight': 68.0,
                    'sleep_hours': 8.2,
                    'historial': [
                        {'fecha': '2026-09-01', 'ctl': 90.0, 'atl': 85.0, 'hrv': 64.0},
                        {'fecha': '2026-09-14', 'ctl': 94.2, 'atl': 88.5, 'hrv': 68.4}
                    ]
                }
            }
        ]

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_generacion_informe_word(self):
        """Verifica que el informe Word se crea y contiene las tablas y métricas esperadas."""
        ruta_res = generar_informe_etapa_word(
            etapa_info=self.etapa_info,
            ciclistas_proc=self.ciclistas_proc,
            titulo="Etapa Test Vuelta",
            output_docx=self.output_docx
        )

        self.assertTrue(ruta_res.exists())
        self.assertEqual(ruta_res.suffix, ".docx")
        self.assertGreater(ruta_res.stat().st_size, 30_000, "El documento Word debe incluir gráficos y tablas (> 30KB)")

        # Abrir el documento generado con docx para inspeccionar su estructura
        doc = docx.Document(str(ruta_res))

        # Verificar orientación horizontal (Landscape)
        section = doc.sections[0]
        self.assertGreater(section.page_width, section.page_height, "La página debe estar en orientación Landscape")

        # Verificar que contiene párrafos y tablas
        self.assertGreater(len(doc.paragraphs), 5)
        self.assertGreaterEqual(len(doc.tables), 4, "Debe contener al menos 4 tablas (encabezado, clasificación, MMP, wellness)")

        # Comprobar texto de clasificación y esfuerzos críticos
        todos_los_textos = []
        for t in doc.tables:
            for row in t.rows:
                for cell in row.cells:
                    todos_los_textos.append(cell.text)

        texto_global = " ".join(todos_los_textos)
        self.assertIn("Ciclista Test 1", texto_global)
        self.assertIn("2.140 kJ", texto_global)
        self.assertIn("410 W", texto_global)
        self.assertIn("1.100 kJ", texto_global) # Desgaste previo en 5m (300s)
        self.assertIn("🏆 PR en Fatiga", texto_global) # Insignia de durabilidad
        self.assertIn("Fresco / Competitivo", texto_global) # Wellness readiness

    def test_generacion_informe_potencias_y_carga_word(self):
        """Verifica que el informe Word de potencias y carga se crea correctamente con gráficos y tablas nativas."""
        peaks_df = pd.DataFrame([
            {'athlete_name': 'Rider Alfa', 'duration_label': '5s', 'peak_wkg': 15.2, 'peak_watts': 1050, 'all_time_wkg': 15.0, 'all_time_watts': 1030},
            {'athlete_name': 'Rider Alfa', 'duration_label': '1m', 'peak_wkg': 9.1, 'peak_watts': 630, 'all_time_wkg': 9.2, 'all_time_watts': 640},
            {'athlete_name': 'Rider Beta', 'duration_label': '5s', 'peak_wkg': 14.5, 'peak_watts': 980, 'all_time_wkg': 14.8, 'all_time_watts': 1000},
            {'athlete_name': 'Rider Beta', 'duration_label': '1m', 'peak_wkg': 8.8, 'peak_watts': 600, 'all_time_wkg': 8.8, 'all_time_watts': 600},
        ])
        tabla_peaks = pd.DataFrame({
            ('Rider Alfa', '69 kg'): ['1050 W | 15.2 W/kg (🏆PR)', '630 W | 9.1 W/kg (99% PR)'],
            ('Rider Beta', '68 kg'): ['980 W | 14.5 W/kg (98% PR)', '600 W | 8.8 W/kg (🏆PR)']
        }, index=['5s', '1m'])

        fechas = pd.date_range("2026-08-15", periods=30, freq="D").strftime("%Y-%m-%d")
        metrics_rows = []
        for f in fechas:
            metrics_rows.append({'athlete_name': 'Rider Alfa', 'fecha': f, 'ctl': 85.0, 'atl': 90.0, 'tsb': 8.0, 'ramp_rate_7d': 1.2})
            metrics_rows.append({'athlete_name': 'Rider Beta', 'fecha': f, 'ctl': 78.0, 'atl': 95.0, 'tsb': -17.0, 'ramp_rate_7d': -0.8})
        metrics_df = pd.DataFrame(metrics_rows)

        out_docx = Path(self.temp_dir.name) / "test_power_report.docx"
        res_path = generar_informe_potencias_y_carga_word(
            peaks_df=peaks_df,
            tabla_peaks=tabla_peaks,
            metrics_df=metrics_df,
            output_docx=out_docx,
            titulo="Test Potencias y Carga",
            grupo_carrera=1
        )

        self.assertTrue(res_path.exists())
        self.assertEqual(res_path.suffix, ".docx")
        self.assertGreater(res_path.stat().st_size, 30_000, "El documento Word debe contener gráficos y tablas (> 30KB)")

        doc = docx.Document(str(res_path))
        # Verificar orientación horizontal (Landscape)
        section = doc.sections[0]
        self.assertGreater(section.page_width, section.page_height, "La orientación debe ser Landscape")

        # Verificar tablas nativas
        self.assertGreaterEqual(len(doc.tables), 3, "Debe contener al menos encabezados, tabla de picos y tabla de carga")

        all_text = " ".join(cell.text for t in doc.tables for row in t.rows for cell in row.cells)
        self.assertIn("Rider Alfa", all_text)
        self.assertIn("Rider Beta", all_text)
        self.assertIn("1050 W", all_text)
        self.assertIn("🏆PR", all_text)
        self.assertIn("Fresco / Competición", all_text)
        self.assertIn("Fatiga Productiva", all_text)


if __name__ == '__main__':
    unittest.main()
