"""
Pruebas unitarias para el gestor de caché de cálculos (src/cache_manager.py).
"""

import sys
import unittest
import tempfile
import json
from pathlib import Path
from unittest.mock import patch

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.cache_manager import (
    formatear_bytes,
    obtener_estado_cache,
    limpiar_cache_calculos
)


class TestCacheManager(unittest.TestCase):

    def test_formatear_bytes(self):
        self.assertEqual(formatear_bytes(500), "500 B")
        self.assertEqual(formatear_bytes(1024), "1.0 KB")
        self.assertEqual(formatear_bytes(1024 * 1024), "1.00 MB")
        self.assertEqual(formatear_bytes(1024 * 1024 * 1024), "1.00 GB")

    def test_obtener_estado_cache_structure(self):
        estado = obtener_estado_cache()
        self.assertIn("total_archivos", estado)
        self.assertIn("total_bytes", estado)
        self.assertIn("total_tamano_str", estado)
        self.assertIn("categorias", estado)
        self.assertIn("fits", estado["categorias"])
        self.assertIn("clima", estado["categorias"])
        self.assertIn("picos", estado["categorias"])
        self.assertIn("scratch", estado["categorias"])

    def test_limpiar_cache_simulada(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            t_today = tmp_path / "today_race"
            t_yesterday = tmp_path / "yesterday_race"
            t_weather = tmp_path / "weather_cache"
            t_cache = tmp_path / "cache"
            t_scratch = tmp_path / "scratch"

            t_today.mkdir()
            t_yesterday.mkdir()
            t_weather.mkdir()
            t_cache.mkdir()
            t_scratch.mkdir()

            # Crear archivos simulados
            fit1 = t_today / "test1.fit"
            fit1.write_bytes(b"FITDATA12345")
            w1 = t_weather / "weather_2026-09-18_0_0.json"
            w1.write_text('{"temp": 20}')
            picos_f = t_cache / "historical_peaks_cache.json"
            picos_f.write_text('{"act_1": {"peaks": {}}}')
            sc1 = t_scratch / "temp.pkl"
            sc1.write_bytes(b"PKLDATA")

            with patch("src.cache_manager.TODAY_RACE_DIR", t_today), \
                 patch("src.cache_manager.YESTERDAY_RACE_DIR", t_yesterday), \
                 patch("src.cache_manager.WEATHER_CACHE_DIR", t_weather), \
                 patch("src.cache_manager.HISTORICAL_PEAKS_CACHE_FILE", picos_f), \
                 patch("src.cache_manager.SCRATCH_DIR", t_scratch):

                # 1. Verificar estado
                estado = obtener_estado_cache()
                self.assertEqual(estado["categorias"]["fits"]["num_archivos"], 1)
                self.assertEqual(estado["categorias"]["clima"]["num_archivos"], 1)
                self.assertEqual(estado["categorias"]["picos"]["num_actividades"], 1)
                self.assertEqual(estado["categorias"]["scratch"]["num_archivos"], 1)
                self.assertGreater(estado["total_bytes"], 0)

                # 2. Limpiar
                res = limpiar_cache_calculos(limpiar_fits=True, limpiar_clima=True, limpiar_picos=True, limpiar_scratch=True)
                self.assertEqual(res["status"], "ok")
                self.assertEqual(res["detalles"]["fits_eliminados"], 1)
                self.assertEqual(res["detalles"]["clima_eliminados"], 1)
                self.assertTrue(res["detalles"]["picos_reseteados"])
                self.assertEqual(res["detalles"]["scratch_eliminados"], 1)

                # 3. Comprobar que los archivos se borraron y picos es {}
                self.assertFalse(fit1.exists())
                self.assertFalse(w1.exists())
                self.assertFalse(sc1.exists())
                self.assertTrue(picos_f.exists())
                self.assertEqual(json.loads(picos_f.read_text()), {})


if __name__ == "__main__":
    unittest.main()
