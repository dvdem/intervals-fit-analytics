"""
Paquete principal de Intervals Fit Analytics.
Proporciona herramientas de conexión API a Intervals.icu, análisis de potencia,
estimación aerodinámica de archivos FIT y métricas de carga y bienestar.
"""

from .intervals_api import IntervalsClient
from .fit_analyzer import cargar_fit, cargar_fit_con_tiempo_movimiento, preprocesar_datos, modelo_potencia, estimar_cda
from .load_metrics import calcular_metricas_carga, resumen_metricas_carga
from .power_peaks import calcular_picos_potencia, generar_tabla_picos_comparativa
from .wellness_hrv import descargar_wellness_atletas, procesar_datos_wellness, resumen_estadisticas_hrv
from .pdf_reports import (
    generar_informe_potencias_y_carga,
    generar_informe_wellness_hrv,
    generar_informe_etapa_pdf
)
from .interactive_profile import (
    generar_dashboard_perfil_interactivo,
    procesar_telemetria_ciclista,
    buscar_fit_local_ciclista,
    descargar_o_recopilar_fits_etapa
)

__all__ = [
    "IntervalsClient",
    "cargar_fit",
    "cargar_fit_con_tiempo_movimiento",
    "preprocesar_datos",
    "modelo_potencia",
    "estimar_cda",
    "calcular_metricas_carga",
    "resumen_metricas_carga",
    "calcular_picos_potencia",
    "generar_tabla_picos_comparativa",
    "descargar_wellness_atletas",
    "procesar_datos_wellness",
    "resumen_estadisticas_hrv",
    "generar_informe_potencias_y_carga",
    "generar_informe_wellness_hrv",
    "generar_informe_etapa_pdf",
    "generar_dashboard_perfil_interactivo",
    "procesar_telemetria_ciclista",
    "buscar_fit_local_ciclista",
    "descargar_o_recopilar_fits_etapa",
]
