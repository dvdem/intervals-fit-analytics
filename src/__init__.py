"""
Paquete principal de Intervals Fit Analytics.
Proporciona herramientas de conexión API a Intervals.icu, análisis de potencia,
estimación aerodinámica de archivos FIT y métricas de carga y bienestar.
"""

from .intervals_api import IntervalsClient
from .fit_analyzer import cargar_fit, cargar_fit_con_tiempo_movimiento, preprocesar_datos, modelo_potencia, estimar_cda
from .load_metrics import calcular_metricas_carga, resumen_metricas_carga
from .power_peaks import (
    calcular_picos_potencia,
    generar_tabla_picos_comparativa,
    obtener_curvas_referencia_atleta,
    comparar_curva_actividad_con_referencia
)
from .wellness_hrv import descargar_wellness_atletas, procesar_datos_wellness, resumen_estadisticas_hrv
from .pdf_reports import (
    generar_informe_potencias_y_carga,
    generar_informe_wellness_hrv,
    generar_informe_etapa_pdf
)
from .word_reports import (
    generar_informe_etapa_word,
    generar_informe_potencias_y_carga_word
)
from .weather_service import (
    calcular_rho_preciso,
    calcular_bearing_ciclista,
    calcular_viento_efectivo,
    obtener_clima_open_meteo,
    deg_to_cardinal
)
from .interactive_profile import (
    generar_dashboard_perfil_interactivo,
    procesar_telemetria_ciclista,
    buscar_fit_local_ciclista,
    descargar_o_recopilar_fits_etapa
)
from .torque_analytics import (
    calcular_torque_seguro,
    calcular_picos_torque,
    calcular_picos_potencia_serie,
    calcular_picos_potencia_con_contexto,
    calcular_analisis_cuadrantes,
    calcular_zonas_torque,
    calcular_perfil_fuerza_velocidad,
    calcular_degradacion_fatiga_torque,
    calcular_metricas_torque_completas
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
    "obtener_curvas_referencia_atleta",
    "comparar_curva_actividad_con_referencia",
    "descargar_wellness_atletas",
    "procesar_datos_wellness",
    "resumen_estadisticas_hrv",
    "generar_informe_potencias_y_carga",
    "generar_informe_potencias_y_carga_word",
    "generar_informe_wellness_hrv",
    "generar_informe_etapa_pdf",
    "generar_informe_etapa_word",
    "generar_dashboard_perfil_interactivo",
    "procesar_telemetria_ciclista",
    "buscar_fit_local_ciclista",
    "descargar_o_recopilar_fits_etapa",
    "calcular_rho_preciso",
    "calcular_bearing_ciclista",
    "calcular_viento_efectivo",
    "obtener_clima_open_meteo",
    "deg_to_cardinal",
    "calcular_torque_seguro",
    "calcular_picos_torque",
    "calcular_picos_potencia_serie",
    "calcular_picos_potencia_con_contexto",
    "calcular_analisis_cuadrantes",
    "calcular_zonas_torque",
    "calcular_perfil_fuerza_velocidad",
    "calcular_degradacion_fatiga_torque",
    "calcular_metricas_torque_completas",
]
