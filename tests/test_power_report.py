import unittest
from unittest.mock import patch, MagicMock
from pathlib import Path
import sys
import pandas as pd
import argparse

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.pdf_reports import generar_informe_potencias_y_carga


class TestPowerReportGroup(unittest.TestCase):

    def test_generar_informe_potencias_y_carga_con_grupo_carrera(self):
        """Verifica que generar_informe_potencias_y_carga acepte grupo_carrera y genere el PDF."""
        peaks_df = pd.DataFrame([
            {'athlete_name': 'Ciclista 1', 'duration_label': '5s', 'peak_wkg': 15.0, 'peak_watts': 900},
            {'athlete_name': 'Ciclista 2', 'duration_label': '5s', 'peak_wkg': 14.5, 'peak_watts': 870},
        ])
        tabla_peaks = pd.DataFrame([
            {'Ciclista 1': '900 W | 15.0 W/kg', 'Ciclista 2': '870 W | 14.5 W/kg'}
        ], index=['5s'])
        metrics_df = pd.DataFrame([
            {'athlete_name': 'Ciclista 1', 'fecha': '2026-09-10', 'ctl': 80.0, 'atl': 90.0, 'tsb': -10.0},
            {'athlete_name': 'Ciclista 2', 'fecha': '2026-09-10', 'ctl': 85.0, 'atl': 92.0, 'tsb': -7.0},
        ])

        out_pdf = ROOT_DIR / "output" / "test_power_carrera_1.pdf"
        try:
            ruta = generar_informe_potencias_y_carga(
                peaks_df=peaks_df,
                tabla_peaks=tabla_peaks,
                metrics_df=metrics_df,
                output_pdf=out_pdf,
                titulo="Test Carrera 1",
                grupo_carrera=1
            )
            self.assertTrue(ruta.exists())
            self.assertGreater(ruta.stat().st_size, 0)
        finally:
            if out_pdf.exists():
                out_pdf.unlink()

    def test_cli_parser_power_report_carrera_argument(self):
        """Verifica que el subparser de power-report acepte --carrera y --grupo."""
        test_parser = argparse.ArgumentParser(prog="intervals-fit")
        subs = test_parser.add_subparsers(dest="command")
        p_power = subs.add_parser("power-report")
        p_power.add_argument("--carrera", "--grupo", dest="carrera", type=int, default=None)
        p_power.add_argument("--todos", action="store_true", default=False)
        p_power.add_argument("--solo-carrera", action="store_true", default=True)
        p_power.add_argument("--titulo", help="Título base")
        args = test_parser.parse_args(["power-report", "--carrera", "2", "--titulo", "Etapa Reina"])
        
        self.assertEqual(args.carrera, 2)
        self.assertEqual(args.titulo, "Etapa Reina")
        self.assertTrue(args.solo_carrera)
        self.assertFalse(args.todos)

    @patch("cli.generar_informe_potencias_y_carga")
    @patch("cli.calcular_metricas_carga")
    @patch("cli.calcular_picos_potencia")
    @patch("cli.IntervalsClient")
    def test_cmd_power_report_filtra_por_carrera(self, mock_client_cls, mock_calc_peaks, mock_calc_metrics, mock_gen_pdf):
        """Verifica que cmd_power_report con --carrera 1 filtre únicamente los ciclistas de la carrera 1."""
        from cli import cmd_power_report
        
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_client.get_athletes_list.return_value = [
            {'athlete_id': 'i1', 'athlete_name': 'Rider Uno', 'carrera': 1},
            {'athlete_id': 'i2', 'athlete_name': 'Rider Dos', 'carrera': 2},
        ]
        
        mock_calc_peaks.return_value = pd.DataFrame([
            {
                'athlete_name': 'Rider Uno',
                'duration_label': '5s',
                'peak_wkg': 15.0,
                'peak_watts': 900,
                'peak_date': '2026-09-01',
                'all_time_watts': 920,
                'all_time_wkg': 15.3,
                'all_time_date': '2026-08-15'
            }
        ])
        mock_calc_metrics.return_value = pd.DataFrame([
            {'athlete_name': 'Rider Uno', 'fecha': '2026-09-10', 'ctl': 80.0, 'atl': 90.0, 'tsb': -10.0}
        ])
        mock_gen_pdf.return_value = Path("output/intervals_informe_carrera_1.pdf")
        
        args = argparse.Namespace(
            roster=str(ROOT_DIR / "data" / "burgos.csv"),
            carrera=1,
            todos=False,
            solo_carrera=True,
            dias=30,
            dias_carga=60,
            titulo=None,
            titulo_1="",
            titulo_2="",
            titulo_3="",
            output=None
        )
        
        cmd_power_report(args)
        
        # Verificar que se llamó a generar_informe_potencias_y_carga con grupo_carrera=1
        self.assertTrue(mock_gen_pdf.called)
        call_kwargs = mock_gen_pdf.call_args[1]
        self.assertEqual(call_kwargs.get('grupo_carrera'), 1)
        self.assertEqual(call_kwargs.get('titulo'), "Grupo Carrera 1")

    @patch("cli.generar_informe_potencias_y_carga")
    @patch("cli.calcular_metricas_carga")
    @patch("cli.calcular_picos_potencia")
    @patch("cli.IntervalsClient")
    def test_cmd_power_report_multiples_grupos(self, mock_client_cls, mock_calc_peaks, mock_calc_metrics, mock_gen_pdf):
        """Verifica que sin especificar --carrera, genere un informe independiente por cada grupo presente."""
        from cli import cmd_power_report
        
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_client.get_athletes_list.return_value = [
            {'athlete_id': 'i1', 'athlete_name': 'Rider G1', 'carrera': 1},
            {'athlete_id': 'i2', 'athlete_name': 'Rider G2', 'carrera': 2},
        ]
        
        mock_calc_peaks.return_value = pd.DataFrame([
            {'athlete_name': 'Rider G1', 'duration_label': '5s', 'peak_wkg': 15.0, 'peak_watts': 900, 'peak_date': '2026-09-01', 'all_time_watts': 920, 'all_time_wkg': 15.3, 'all_time_date': '2026-08-15'},
            {'athlete_name': 'Rider G2', 'duration_label': '5s', 'peak_wkg': 14.0, 'peak_watts': 840, 'peak_date': '2026-09-02', 'all_time_watts': 850, 'all_time_wkg': 14.2, 'all_time_date': '2026-08-10'},
        ])
        mock_calc_metrics.return_value = pd.DataFrame([
            {'athlete_name': 'Rider G1', 'fecha': '2026-09-10', 'ctl': 80.0, 'atl': 90.0, 'tsb': -10.0},
            {'athlete_name': 'Rider G2', 'fecha': '2026-09-10', 'ctl': 75.0, 'atl': 85.0, 'tsb': -10.0}
        ])
        mock_gen_pdf.side_effect = lambda *args, **kwargs: kwargs.get('output_pdf') or Path("output/intervals_informe.pdf")
        
        args = argparse.Namespace(
            roster=str(ROOT_DIR / "data" / "burgos.csv"),
            carrera=None,
            todos=False,
            solo_carrera=True,
            dias=30,
            dias_carga=60,
            titulo="Vuelta",
            titulo_1="Vuelta Grupo 1",
            titulo_2="Vuelta Grupo 2",
            titulo_3="",
            output=None
        )
        
        cmd_power_report(args)
        
        # Debió llamarse dos veces: una para Carrera 1 y otra para Carrera 2
        self.assertEqual(mock_gen_pdf.call_count, 2)
        call_1_kwargs = mock_gen_pdf.call_args_list[0][1]
        call_2_kwargs = mock_gen_pdf.call_args_list[1][1]
        
        self.assertEqual(call_1_kwargs.get('grupo_carrera'), 1)
        self.assertEqual(call_1_kwargs.get('titulo'), "Vuelta Grupo 1")
        self.assertEqual(call_2_kwargs.get('grupo_carrera'), 2)
        self.assertEqual(call_2_kwargs.get('titulo'), "Vuelta Grupo 2")

    @patch("cli.generar_informe_potencias_y_carga_word")
    @patch("cli.generar_informe_potencias_y_carga")
    @patch("cli.calcular_metricas_carga")
    @patch("cli.calcular_picos_potencia")
    @patch("cli.IntervalsClient")
    def test_cmd_power_report_formato_docx(self, mock_client_cls, mock_calc_peaks, mock_calc_metrics, mock_gen_pdf, mock_gen_word):
        """Verifica que con --formato docx se genere solo el documento Word y no el PDF."""
        from cli import cmd_power_report

        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_client.get_athletes_list.return_value = [
            {'athlete_id': 'i1', 'athlete_name': 'Rider Uno', 'carrera': 1},
        ]
        mock_calc_peaks.return_value = pd.DataFrame([
            {'athlete_name': 'Rider Uno', 'duration_label': '5s', 'peak_wkg': 15.0, 'peak_watts': 900, 'peak_date': '2026-09-01', 'all_time_watts': 920, 'all_time_wkg': 15.3, 'all_time_date': '2026-08-15'}
        ])
        mock_calc_metrics.return_value = pd.DataFrame([
            {'athlete_name': 'Rider Uno', 'fecha': '2026-09-10', 'ctl': 80.0, 'atl': 90.0, 'tsb': -10.0}
        ])
        mock_gen_word.return_value = Path("output/intervals_informe_carrera_1.docx")

        args = argparse.Namespace(
            roster=str(ROOT_DIR / "data" / "burgos.csv"),
            carrera=1,
            todos=False,
            solo_carrera=True,
            dias=30,
            dias_carga=60,
            titulo="Test Docx",
            titulo_1="",
            titulo_2="",
            titulo_3="",
            output=None,
            formato="docx",
            output_docx=None
        )

        cmd_power_report(args)

        self.assertFalse(mock_gen_pdf.called, "No debe generar PDF cuando formato='docx'")
        self.assertTrue(mock_gen_word.called, "Debe generar Word cuando formato='docx'")
        call_kwargs = mock_gen_word.call_args[1]
        self.assertEqual(call_kwargs.get('grupo_carrera'), 1)
        self.assertEqual(call_kwargs.get('titulo'), "Test Docx - Carrera 1")

    @patch("cli.generar_informe_potencias_y_carga_word")
    @patch("cli.generar_informe_potencias_y_carga")
    @patch("cli.calcular_metricas_carga")
    @patch("cli.calcular_picos_potencia")
    @patch("cli.IntervalsClient")
    def test_cmd_power_report_formato_ambos(self, mock_client_cls, mock_calc_peaks, mock_calc_metrics, mock_gen_pdf, mock_gen_word):
        """Verifica que con --formato ambos se generen tanto PDF como Word."""
        from cli import cmd_power_report

        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_client.get_athletes_list.return_value = [
            {'athlete_id': 'i1', 'athlete_name': 'Rider Uno', 'carrera': 1},
        ]
        mock_calc_peaks.return_value = pd.DataFrame([
            {'athlete_name': 'Rider Uno', 'duration_label': '5s', 'peak_wkg': 15.0, 'peak_watts': 900, 'peak_date': '2026-09-01', 'all_time_watts': 920, 'all_time_wkg': 15.3, 'all_time_date': '2026-08-15'}
        ])
        mock_calc_metrics.return_value = pd.DataFrame([
            {'athlete_name': 'Rider Uno', 'fecha': '2026-09-10', 'ctl': 80.0, 'atl': 90.0, 'tsb': -10.0}
        ])
        mock_gen_pdf.return_value = Path("output/intervals_informe_carrera_1.pdf")
        mock_gen_word.return_value = Path("output/intervals_informe_carrera_1.docx")

        args = argparse.Namespace(
            roster=str(ROOT_DIR / "data" / "burgos.csv"),
            carrera=1,
            todos=False,
            solo_carrera=True,
            dias=30,
            dias_carga=60,
            titulo="Test Ambos",
            titulo_1="",
            titulo_2="",
            titulo_3="",
            output=None,
            formato="ambos",
            output_docx=None
        )

        cmd_power_report(args)

        self.assertTrue(mock_gen_pdf.called, "Debe generar PDF cuando formato='ambos'")
        self.assertTrue(mock_gen_word.called, "Debe generar Word cuando formato='ambos'")


if __name__ == "__main__":
    unittest.main()
