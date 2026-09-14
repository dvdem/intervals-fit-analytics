import unittest
import numpy as np
import pandas as pd
from pathlib import Path
import sys

# Asegurar path raíz
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.torque_analytics import (
    calcular_torque_seguro,
    calcular_picos_torque,
    calcular_picos_potencia_serie,
    calcular_analisis_cuadrantes,
    calcular_zonas_torque,
    calcular_perfil_fuerza_velocidad,
    calcular_degradacion_fatiga_torque,
    calcular_metricas_torque_completas
)
from src.fit_analyzer import cargar_fit_con_tiempo_movimiento, cargar_fit


class TestTorqueAnalytics(unittest.TestCase):

    def test_calcular_torque_seguro_matematica(self):
        # 450 W a 90 rpm con biela de 172.5 mm
        # omega = 90 * 2 * pi / 60 = 3 * pi = 9.42477796 rad/s
        # tau = 450 / 9.42477796 = 47.74648 N*m
        # aepf = 47.74648 / 0.1725 = 276.791 N
        pot = np.array([450.0])
        cad = np.array([90.0])
        trq, aepf = calcular_torque_seguro(pot, cad, crank_length_m=0.1725)

        self.assertAlmostEqual(trq[0], 47.746, places=2)
        self.assertAlmostEqual(aepf[0], 276.79, places=1)

    def test_calcular_torque_seguro_bajas_cadencias_y_coasting(self):
        # Cadencia 0 (coasting) y cadencia 8 (transitoria / enganche)
        pot = np.array([0.0, 300.0, 200.0])
        cad = np.array([0.0, 5.0, 14.9])  # < 15 rpm
        trq, aepf = calcular_torque_seguro(pot, cad)

        self.assertEqual(trq[0], 0.0)
        self.assertEqual(trq[1], 0.0)
        self.assertEqual(trq[2], 0.0)
        self.assertEqual(aepf[0], 0.0)

    def test_calcular_torque_seguro_clipping(self):
        # Pico numérico artificial extremo (ej. 1500W a 20 rpm = 716 N*m)
        pot = np.array([1500.0])
        cad = np.array([20.0])
        trq, _ = calcular_torque_seguro(pot, cad, torque_max_clip=250.0)
        self.assertLessEqual(trq[0], 250.0)

    def test_picos_torque_mmt(self):
        # Serie sintética con un bloque de 5s a 100 N*m
        trq_arr = np.array([20.0] * 10 + [100.0] * 5 + [30.0] * 10)
        picos = calcular_picos_torque(trq_arr, duraciones={1: "1s", 5: "5s", 10: "10s"})

        self.assertEqual(picos[1], 100.0)
        self.assertEqual(picos[5], 100.0)
        self.assertLess(picos[10], 100.0)

    def test_picos_potencia_mmp(self):
        # Serie sintética de potencia con pico de 5s a 900 W
        pwr_arr = np.array([200.0] * 10 + [900.0] * 5 + [300.0] * 10)
        picos_pwr = calcular_picos_potencia_serie(pwr_arr, duraciones={1: "1s", 5: "5s", 10: "10s"})

        self.assertEqual(picos_pwr[1], 900.0)
        self.assertEqual(picos_pwr[5], 900.0)
        self.assertLess(picos_pwr[10], 900.0)

    def test_analisis_cuadrantes(self):
        # 100s en Q1 (alta cad 95, alto trq 60)
        # 100s en Q2 (baja cad 70, alto trq 60)
        # 100s en Q3 (baja cad 70, bajo trq 25)
        # 100s en Q4 (alta cad 95, bajo trq 25)
        n = 100
        cad = np.array([95.0] * n + [70.0] * n + [70.0] * n + [95.0] * n)
        # trq_thresh para FTP 380W a 85 rpm es aprox 42.7 N*m
        # Generar potencias acordes a los torques
        # Q1: 60 N*m a 95 rpm -> P = 60 * 95 * 2pi/60 = 596.9 W
        # Q2: 60 N*m a 70 rpm -> P = 60 * 70 * 2pi/60 = 439.8 W
        # Q3: 25 N*m a 70 rpm -> P = 25 * 70 * 2pi/60 = 183.3 W
        # Q4: 25 N*m a 95 rpm -> P = 25 * 95 * 2pi/60 = 248.7 W
        p1 = 60.0 * 95.0 * (2.0 * np.pi / 60.0)
        p2 = 60.0 * 70.0 * (2.0 * np.pi / 60.0)
        p3 = 25.0 * 70.0 * (2.0 * np.pi / 60.0)
        p4 = 25.0 * 95.0 * (2.0 * np.pi / 60.0)
        pot = np.array([p1] * n + [p2] * n + [p3] * n + [p4] * n)

        df = pd.DataFrame({'cadencia': cad, 'potencia': pot})
        res = calcular_analisis_cuadrantes(df, ftp=380.0, cad_thresh=85.0)

        self.assertTrue(res['disponible'])
        quads = res['cuadrantes']
        # Cada cuadrante debería tener exactamente 25% (100 segundos)
        self.assertAlmostEqual(quads['q1_pct'], 25.0, delta=1.0)
        self.assertAlmostEqual(quads['q2_pct'], 25.0, delta=1.0)
        self.assertAlmostEqual(quads['q3_pct'], 25.0, delta=1.0)
        self.assertAlmostEqual(quads['q4_pct'], 25.0, delta=1.0)
        self.assertEqual(quads['q1_sec'] + quads['q2_sec'] + quads['q3_sec'] + quads['q4_sec'], 400)

    def test_archivo_fit_real(self):
        fit_path = ROOT_DIR / "data/today_race/20117221663.fit"
        if not fit_path.exists():
            self.skipTest("No se encontró el archivo FIT de prueba.")

        df = cargar_fit_con_tiempo_movimiento(fit_path, solo_movimiento=True)
        self.assertIn('torque', df.columns)
        self.assertIn('aepf', df.columns)
        self.assertFalse(df['torque'].isna().any())
        self.assertFalse(df['aepf'].isna().any())

        stats = calcular_metricas_torque_completas(df, ftp=380.0)
        self.assertTrue(stats['disponible'])
        self.assertGreater(stats['trq_media_nm'], 15.0)
        self.assertGreater(stats['trq_max_nm'], 50.0)
        self.assertIn(1, stats['mmt'])
        self.assertIn(5, stats['mmt'])
        self.assertIn('mmp', stats)
        self.assertIn(1, stats['mmp'])
        self.assertIn(5, stats['mmp'])
        self.assertIn('cuadrantes', stats)
        self.assertIn('zonas', stats)

    def test_cadencia_nula_o_incompleta(self):
        # FIT con cadencia ausente o NaN
        df_nan = pd.DataFrame({
            'potencia': [200.0, 300.0, 400.0] * 50,
            'cadencia': [np.nan] * 150
        })
        stats = calcular_metricas_torque_completas(df_nan, ftp=380.0)
        self.assertTrue(stats['disponible'])
        self.assertEqual(stats['trq_media_nm'], 0.0)
        self.assertIn('cuadrantes', stats)
    def test_crank_length_desde_burgos_csv_y_mm_a_metros(self):
        from config import obtener_crank_length_ciclista, normalizar_crank_length_m, DEFAULT_CRANK_LENGTH

        # Conversión de mm a metros
        self.assertAlmostEqual(normalizar_crank_length_m(172.5), 0.1725, places=4)
        self.assertAlmostEqual(normalizar_crank_length_m(165), 0.165, places=4)
        self.assertAlmostEqual(normalizar_crank_length_m(175.0), 0.175, places=4)
        self.assertAlmostEqual(normalizar_crank_length_m(0.170), 0.170, places=4)
        self.assertEqual(normalizar_crank_length_m(None), DEFAULT_CRANK_LENGTH)
        self.assertEqual(normalizar_crank_length_m("invalido"), DEFAULT_CRANK_LENGTH)

        # Resolución desde burgos.csv
        self.assertAlmostEqual(obtener_crank_length_ciclista('Carlos Garcia'), 0.165, places=4)
        self.assertAlmostEqual(obtener_crank_length_ciclista('Alex Mayer'), 0.165, places=4)
        self.assertAlmostEqual(obtener_crank_length_ciclista('Ander Okamika'), 0.175, places=4)
        self.assertAlmostEqual(obtener_crank_length_ciclista('Mario Aparicio'), 0.1725, places=4)
        self.assertAlmostEqual(obtener_crank_length_ciclista('i547157'), 0.170, places=4)  # Jose Manuel Diaz
        self.assertEqual(obtener_crank_length_ciclista('No Existe Ciclista'), DEFAULT_CRANK_LENGTH)

        # Equivalencia en calcular_torque_seguro pasando en mm vs metros
        pot = np.array([450.0])
        cad = np.array([90.0])
        trq_m, aepf_m = calcular_torque_seguro(pot, cad, crank_length_m=0.1725)
        trq_mm, aepf_mm = calcular_torque_seguro(pot, cad, crank_length_m=172.5)
        self.assertAlmostEqual(aepf_m[0], aepf_mm[0], places=2)

        # En calcular_metricas_torque_completas con identificador_ciclista
        df_dummy = pd.DataFrame({'potencia': [300.0] * 50, 'cadencia': [90.0] * 50})
        stats_mayer = calcular_metricas_torque_completas(df_dummy, ftp=350.0, identificador_ciclista='Alex Mayer')
        self.assertEqual(stats_mayer['crank_length_mm'], 165.0)
        self.assertEqual(stats_mayer['crank_length_m'], 0.165)


if __name__ == '__main__':
    unittest.main()
