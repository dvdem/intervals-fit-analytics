"""
Interfaz de Línea de Comandos (CLI) de Intervals Fit Analytics.
Permite ejecutar análisis de potencias, carga, HRV y estimación de CdA desde la terminal.
"""

import argparse
import sys
from datetime import datetime, timedelta
from pathlib import Path

# Configurar encoding seguro para Windows
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
try:
    from tabulate import tabulate
except ImportError:
    def tabulate(datos, headers=None, tablefmt=None, showindex=True):
        import pandas as pd
        if isinstance(datos, pd.DataFrame):
            return datos.to_string(index=showindex)
        df = pd.DataFrame(datos, columns=headers if isinstance(headers, list) else None)
        return df.to_string(index=False)

from config import (
    cargar_roster,
    DEFAULT_ROSTER_PATH,
    OUTPUT_DIR,
    DEFAULT_BIKE_WEIGHT,
    DEFAULT_RIDER_WEIGHT,
    DEFAULT_CRANK_LENGTH
)
from src import (
    IntervalsClient,
    cargar_fit,
    cargar_fit_con_tiempo_movimiento,
    preprocesar_datos,
    estimar_cda,
    calcular_picos_potencia,
    generar_tabla_picos_comparativa,
    calcular_metricas_carga,
    resumen_metricas_carga,
    descargar_wellness_atletas,
    resumen_estadisticas_hrv,
    generar_informe_potencias_y_carga,
    generar_informe_wellness_hrv,
    generar_informe_etapa_pdf,
    generar_dashboard_perfil_interactivo,
    descargar_o_recopilar_fits_etapa,
    calcular_metricas_torque_completas,
)
from src.fit_analyzer import graficar_analisis_fit


def cmd_list_athletes(args):
    """Lista todos los atletas vinculados a la cuenta de Intervals.icu."""
    client = IntervalsClient()
    roster_df = cargar_roster(args.roster)
    atletas = client.get_athletes_list(roster_df=roster_df, solo_carrera=args.solo_carrera)

    print(f"\n🚴 Se encontraron {len(atletas)} atletas:")
    tabla = []
    for a in atletas:
        aid = a.get('athlete_id')
        name = a.get('athlete_name')
        weight = a.get('weight') or '-'
        fitness = round(float(a.get('fitness')), 1) if a.get('fitness') is not None else '-'
        fatigue = round(float(a.get('fatigue')), 1) if a.get('fatigue') is not None else '-'
        form = round(float(a.get('form')), 1) if a.get('form') is not None else '-'
        tabla.append([aid, name, weight, fitness, fatigue, form])

    print(tabulate(tabla, headers=["ID", "Nombre", "Peso (kg)", "Fitness (CTL)", "Fatiga (ATL)", "Forma (TSB)"], tablefmt="fancy_grid"))


def cmd_power_report(args):
    """Genera el informe completo de potencias y carga en PDF, uno por cada grupo de carrera."""
    client = IntervalsClient()
    roster_df = cargar_roster(args.roster)
    atletas = client.get_athletes_list(roster_df=roster_df, solo_carrera=args.solo_carrera)

    # Identificar los grupos de carrera presentes (carrera > 0)
    grupos_carrera = sorted(set(
        int(a.get('carrera', 0)) for a in atletas if int(a.get('carrera', 0)) > 0
    ))
    if not grupos_carrera:
        # Fallback: tratar todos los atletas como un solo grupo sin etiquetar
        grupos_carrera = [None]

    print(f"\n📊 {len(atletas)} atletas en {len(grupos_carrera)} grupo(s) de carrera: {grupos_carrera}")

    # Calcular datos una sola vez para todos los atletas
    print("⏳ Calculando picos de potencia (30 días vs Histórico)...")
    peaks_df_total = calcular_picos_potencia(client, atletas, roster_df, dias_recientes=args.dias)

    print("⏳ Calculando evolución de carga diaria, CTL y ATL...")
    nombres_map = dict(zip(roster_df['intervals_id'], roster_df['Name'])) if not roster_df.empty else {}
    metrics_df_total = calcular_metricas_carga(client, atletas, dias_historia=args.dias_carga, dias_plot=args.dias_carga, nombres_map=nombres_map)

    # Mapa de nombre → número de carrera
    carrera_nombre_map = {}
    if not roster_df.empty and 'carrera' in roster_df.columns:
        carrera_nombre_map = dict(zip(roster_df['Name'], roster_df['carrera'].astype(int)))

    # Generar un PDF por grupo
    rutas_generadas = []
    for grupo in grupos_carrera:
        if grupo is None:
            atletas_grupo = atletas
            label = ""
        else:
            nombres_grupo = {n for n, c in carrera_nombre_map.items() if c == grupo}
            atletas_grupo = [a for a in atletas if a.get('athlete_name') in nombres_grupo]
            label = f"_carrera_{grupo}"

        if not atletas_grupo:
            print(f"⚠️  Grupo Carrera {grupo}: sin atletas, omitiendo.")
            continue

        nombres_grupo_set = {a.get('athlete_name') for a in atletas_grupo}
        peaks_g = peaks_df_total[peaks_df_total['athlete_name'].isin(nombres_grupo_set)].copy() if not peaks_df_total.empty else peaks_df_total
        metrics_g = metrics_df_total[metrics_df_total['athlete_name'].isin(nombres_grupo_set)].copy() if not metrics_df_total.empty else metrics_df_total
        tabla_g, _ = generar_tabla_picos_comparativa(peaks_g)

        if args.output and grupo == grupos_carrera[0]:
            out_pdf = Path(args.output)
        else:
            out_pdf = OUTPUT_DIR / f"intervals_informe{label}.pdf"

        titulo_g = f"Carrera {grupo}" if grupo else "Informe General"
        print(f"\n📄 [{titulo_g}] {len(atletas_grupo)} atletas → {out_pdf}")
        ruta_generada = generar_informe_potencias_y_carga(peaks_g, tabla_g, metrics_g, output_pdf=out_pdf)
        rutas_generadas.append(ruta_generada)
        print(f"   ✅ Generado: {ruta_generada.resolve()}")

    if rutas_generadas:
        print(f"\n✅ {len(rutas_generadas)} informe(s) generado(s) correctamente.")


def cmd_hrv_report(args):
    """Genera el informe de evolución de HRV (RMSSD) y bienestar en PDF, uno por cada grupo de carrera."""
    client = IntervalsClient()
    roster_df = cargar_roster(args.roster)
    atletas = client.get_athletes_list(roster_df=roster_df, solo_carrera=args.solo_carrera)

    # Identificar grupos de carrera presentes
    grupos_carrera = sorted(set(
        int(a.get('carrera', 0)) for a in atletas if int(a.get('carrera', 0)) > 0
    ))
    if not grupos_carrera:
        grupos_carrera = [None]

    print(f"\n🩺 Descargando datos de bienestar para {len(atletas)} atletas en {len(grupos_carrera)} grupo(s)...")
    nombres_map = dict(zip(roster_df['intervals_id'], roster_df['Name'])) if not roster_df.empty else {}
    wellness_df_total = descargar_wellness_atletas(client, atletas, nombres_map=nombres_map)

    if wellness_df_total.empty:
        print("❌ No se encontraron datos de bienestar para los atletas indicados.")
        return

    stats_df = resumen_estadisticas_hrv(wellness_df_total)
    print("\n📋 Resumen de Estadísticas HRV (todos los grupos):")
    print(tabulate(stats_df, headers="keys", tablefmt="fancy_grid", showindex=False))

    # Mapa nombre → carrera
    carrera_nombre_map = {}
    if not roster_df.empty and 'carrera' in roster_df.columns:
        carrera_nombre_map = dict(zip(roster_df['Name'], roster_df['carrera'].astype(int)))

    rutas_generadas = []
    for grupo in grupos_carrera:
        if grupo is None:
            wellness_g = wellness_df_total
            label = ""
        else:
            nombres_grupo = {n for n, c in carrera_nombre_map.items() if c == grupo}
            wellness_g = wellness_df_total[wellness_df_total['athlete_name'].isin(nombres_grupo)].copy()
            label = f"_carrera_{grupo}"

        if wellness_g.empty:
            print(f"⚠️  Grupo Carrera {grupo}: sin datos de wellness, omitiendo.")
            continue

        if args.output and grupo == grupos_carrera[0]:
            out_pdf = Path(args.output)
        else:
            out_pdf = OUTPUT_DIR / f"wellness_evolucion{label}.pdf"

        titulo_g = f"Carrera {grupo}" if grupo else "Informe General"
        print(f"\n📄 [{titulo_g}] → {out_pdf}")
        ruta_generada = generar_informe_wellness_hrv(wellness_g, output_pdf=out_pdf)
        rutas_generadas.append(ruta_generada)
        print(f"   ✅ Generado: {ruta_generada.resolve()}")

    if rutas_generadas:
        print(f"\n✅ {len(rutas_generadas)} informe(s) de HRV generado(s) correctamente.")


def cmd_fit_cda(args):
    """Analiza un archivo .fit y estima los parámetros aerodinámicos (CdA y Crr)."""
    ruta_fit = Path(args.fit_file)
    if not ruta_fit.exists():
        print(f"❌ Error: El archivo {ruta_fit} no existe.")
        sys.exit(1)

    print(f"\n🚴 Cargando archivo FIT: {ruta_fit.name}...")
    df_raw = cargar_fit(ruta_fit)
    print(f"   -> {len(df_raw)} registros leídos.")

    print("📉 Preprocesando datos cinemáticos y filtrando pausas...")
    df_proc = preprocesar_datos(df_raw, min_speed_ms=args.min_speed, min_power_w=args.min_power)
    print(f"   -> {len(df_proc)} registros de alta calidad listos para el modelo.")

    masa_total = args.peso_total or (args.peso_ciclista + args.peso_bici)
    print(f"⏳ Optimizando parámetros físicos (Masa total = {masa_total} kg)...")
    res = estimar_cda(df_proc, masa_total=masa_total, masa_bici=args.peso_bici, rho=args.rho)

    print("\n" + "=" * 45)
    print("🏆 RESULTADOS DE ESTIMACIÓN AERODINÁMICA")
    print("=" * 45)
    print(f"   • CdA Estimado:            {res['cda']:.4f} m²")
    print(f"   • Crr (Rodadura) Estimado: {res['crr']:.5f}")
    print(f"   • Error RMSE:              {res['rmse']:.2f} W")
    print(f"   • Error MSE:               {res['mse']:.2f} W²")
    print(f"   • Convergencia del modelo: {'Exitosa' if res['success'] else 'Fallida'}")
    print("=" * 45)

    if args.plot or args.save_plot:
        save_path = args.save_plot or (OUTPUT_DIR / f"cda_{ruta_fit.stem}.png")
        print(f"🎨 Guardando gráfico de validación en: {save_path}...")
        graficar_analisis_fit(df_proc, res, guardar_ruta=save_path, mostrar=args.plot)


def cmd_fit_torque(args):
    """Analiza la biomecánica de pedaleo, torque, fuerza (AEPF) y cuadrantes de un archivo FIT."""
    ruta_fit = Path(args.fit_file)
    if not ruta_fit.exists():
        print(f"❌ Error: El archivo {ruta_fit} no existe.")
        sys.exit(1)

    print(f"\n⚙️ Analizando biomecánica de torque y pedaleo: {ruta_fit.name}...")
    df_clean = cargar_fit_con_tiempo_movimiento(ruta_fit, solo_movimiento=True)
    if df_clean.empty:
        print("❌ Error: No se encontraron registros de movimiento válidos en el archivo FIT.")
        sys.exit(1)

    stats = calcular_metricas_torque_completas(df_clean, ftp=args.ftp, crank_length_m=args.crank_length)

    print("\n" + "=" * 55)
    print("🚴 RESULTADOS DE ANÁLISIS DE TORQUE Y BIOMECÁNICA")
    print("=" * 55)
    print(f"   • Torque Medio Pedaleando:   {stats['trq_media_nm']} N·m")
    print(f"   • Torque Mediana:            {stats['trq_mediana_nm']} N·m")
    print(f"   • Torque P95:                {stats['trq_p95_nm']} N·m")
    print(f"   • Torque Máximo Pico:        {stats['trq_max_nm']} N·m")
    print(f"   • Fuerza Efectiva Pedal Med: {stats['aepf_media_n']} N ({stats['kgf_media']} kgf)")
    print(f"   • Fuerza Efectiva Pedal Máx: {stats['aepf_max_n']} N ({stats['kgf_max']} kgf)")
    print(f"   • Longitud de Biela:         {stats['crank_length_mm']} mm")
    print("-" * 55)
    print("⚡ PICOS DE MEAN MAXIMAL TORQUE (MMT):")
    for sec, val in stats['mmt'].items():
        dur_str = f"{sec}s" if sec < 60 else f"{sec//60}m"
        print(f"   • Pico {dur_str:4s}:                 {val:5.1f} N·m")
    print("-" * 55)
    q = stats['cuadrantes']['cuadrantes']
    print("🎯 DISTRIBUCIÓN DE ANÁLISIS DE CUADRANTES (COGGAN):")
    print(f"   • QI  (Alta Cad, Alto Par - Sprint/Ataque): {q['q1_pct']:4.1f}% ({q['q1_sec']}s)")
    print(f"   • QII (Baja Cad, Alto Par - Escalada Dura): {q['q2_pct']:4.1f}% ({q['q2_sec']}s)")
    print(f"   • QIII(Baja Cad, Bajo Par - Recuperación):  {q['q3_pct']:4.1f}% ({q['q3_sec']}s)")
    print(f"   • QIV (Alta Cad, Bajo Par - Pelotón Ágil):  {q['q4_pct']:4.1f}% ({q['q4_sec']}s)")
    if stats.get('perfil_fv', {}).get('disponible'):
        fv = stats['perfil_fv']
        print("-" * 55)
        print("📐 PERFIL FUERZA - VELOCIDAD (F-v):")
        print(f"   • Torque Isométrico Teórico (T0): {fv['t0_nm']} N·m")
        print(f"   • Cadencia Máx Teórica (cad0):    {fv['cad0_rpm']} rpm")
        print(f"   • Cadencia Óptima Sprint:         {fv['cad_opt_rpm']} rpm")
        print(f"   • Potencia Máx Teórica (Pmax):    {fv['pmax_teorico_w']} W")
        print(f"   • Ajuste R²:                      {fv['r2']}")
    print("=" * 55 + "\n")


def cmd_download_fit(args):
    """Descarga el archivo FIT original de una actividad en Intervals.icu."""
    client = IntervalsClient()
    dest = Path(args.output or (OUTPUT_DIR / f"activity_{args.activity_id}.fit"))
    print(f"📥 Descargando archivo de la actividad {args.activity_id}...")
    exito = client.download_activity_file(args.activity_id, str(dest))
    if exito:
        print(f"✅ Descarga completada: {dest.resolve()}")
    else:
        print(f"❌ No se pudo descargar el archivo para la actividad {args.activity_id}")


def cmd_interactive_profile(args):
    """Genera el panel interactivo HTML con mapa, perfil de altimetría y posicionamiento de los ciclistas.

    Cuando el roster define grupos de carrera (carrera > 0), genera un HTML/PDF independiente
    por cada grupo (ej: etapa_2026-09-04_carrera_1.html, etapa_2026-09-04_carrera_2.html).
    Los riders con carrera=0 nunca se incluyen.
    """
    roster_df = cargar_roster(args.roster)
    client = None
    try:
        client = IntervalsClient()
    except Exception:
        pass

    fits_a_procesar = []
    fits_temporales = []

    # 1. Si se especificaron archivos o directorio directo
    if args.fit_files:
        for f in args.fit_files:
            p = Path(f)
            if p.is_file():
                fits_a_procesar.append(p)
            elif p.is_dir():
                fits_a_procesar.extend(list(p.glob("*.fit")) + list(p.glob("*.FIT")))
    elif args.fit_dir:
        fits_a_procesar.extend(list(Path(args.fit_dir).glob("*.fit")) + list(Path(args.fit_dir).glob("*.FIT")))
    else:
        # 2. Descargar o buscar automáticamente en API (con fallback local para Strava)
        cache_dir = Path("data/today_race")
        solo_carrera = not getattr(args, 'todos', False)
        fits_a_procesar, fits_temporales = descargar_o_recopilar_fits_etapa(
            client=client,
            roster_df=roster_df,
            fecha_str=args.fecha,
            activity_id=getattr(args, 'activity_id', None),
            ultima_individual=getattr(args, 'ultima_individual', False),
            solo_carrera=solo_carrera,
            cache_dir=cache_dir
        )

    if not fits_a_procesar:
        print("❌ No se encontraron archivos FIT con datos de posicionamiento.")
        return

    # Quitar duplicados preservando diccionarios de Streams y archivos FIT
    fits_unicos = []
    vistos = set()
    for f in fits_a_procesar:
        if isinstance(f, (str, Path)):
            res = str(Path(f).resolve())
            if res not in vistos:
                fits_unicos.append(Path(f))
                vistos.add(res)
        elif isinstance(f, dict):
            key = (f.get('atleta_id'), f.get('nombre'))
            if key not in vistos:
                fits_unicos.append(f)
                vistos.add(key)

    print(f"\n🚴 Procesando {len(fits_unicos)} ciclistas / fuentes de posicionamiento...")

    solo_carrera = not getattr(args, 'todos', False)
    generar_pdf = not getattr(args, 'no_pdf', False)
    fits_limpiar = fits_temporales if not getattr(args, 'mantener_fits', False) else None

    # Identificar grupos de carrera del roster (carrera > 0 → rider compite)
    grupos_carrera = []
    if not roster_df.empty and 'carrera' in roster_df.columns:
        grupos_carrera = sorted(set(
            int(c) for c in roster_df['carrera'] if int(c) > 0
        ))

    # Si se pasaron archivos manualmente o no hay grupos definidos → un único perfil global
    forzar_global = bool(args.fit_files or getattr(args, 'fit_dir', None)) or not grupos_carrera
    if forzar_global:
        out_html = Path(args.output) if args.output else None
        out_pdf = Path(args.output_pdf) if getattr(args, 'output_pdf', None) else None
        ruta_generada = generar_dashboard_perfil_interactivo(
            fits_unicos,
            roster_df=roster_df,
            client=client,
            solo_carrera=solo_carrera,
            titulo=args.titulo,
            output_html=out_html,
            output_pdf=out_pdf,
            generar_pdf=generar_pdf,
            fits_temporales_limpiar=fits_limpiar
        )
        pdf_estimado = out_pdf or ruta_generada.with_suffix('.pdf')
        print("\n" + "=" * 55)
        print("🏆 ¡PERFIL E INFORME DE ETAPA GENERADOS CON ÉXITO!")
        print("=" * 55)
        print(f"📄 Archivo HTML: {ruta_generada.resolve()}")
        if generar_pdf and pdf_estimado.exists():
            print(f"📄 Archivo PDF:  {pdf_estimado.resolve()}")
        print("💡 Ábrelo en cualquier navegador o visor PDF para ver el análisis")
        print("   completo de la etapa, comparativas y fisiología.")
        print("=" * 55 + "\n")
        return

    # Generar un perfil HTML (y PDF) independiente por cada grupo de carrera
    print(f"\n🏁 Detectados {len(grupos_carrera)} grupo(s) de carrera: {grupos_carrera}")
    rutas_generadas = []
    for idx, grupo in enumerate(grupos_carrera):
        print(f"\n{'='*55}")
        print(f"🏁 Generando perfil para Grupo Carrera {grupo}...")
        print(f"{'='*55}")

        # Nombre de salida: añadir sufijo _carrera_N si hay ruta explícita
        out_html_grupo = None
        if args.output:
            p = Path(args.output)
            out_html_grupo = p.parent / f"{p.stem}_carrera_{grupo}{p.suffix}"

        out_pdf_grupo = None
        if getattr(args, 'output_pdf', None):
            p = Path(args.output_pdf)
            out_pdf_grupo = p.parent / f"{p.stem}_carrera_{grupo}{p.suffix}"

        # Título: prioridad → 1) --titulo-N específico del grupo, 2) --titulo base, 3) genérico
        titulos_por_grupo = {
            1: getattr(args, 'titulo_1', ''),
            2: getattr(args, 'titulo_2', ''),
            3: getattr(args, 'titulo_3', ''),
        }
        titulo_especifico = titulos_por_grupo.get(grupo, '')
        if titulo_especifico:
            titulo_grupo = titulo_especifico
        elif args.titulo:
            titulo_grupo = f"{args.titulo} - Carrera {grupo}"
        else:
            titulo_grupo = f"Grupo Carrera {grupo}"

        # Solo limpiar FITs temporales tras generar el último grupo
        fits_limpiar_grupo = fits_limpiar if idx == len(grupos_carrera) - 1 else None

        try:
            ruta = generar_dashboard_perfil_interactivo(
                fits_unicos,
                roster_df=roster_df,
                client=client,
                solo_carrera=True,
                grupo_carrera=grupo,
                titulo=titulo_grupo,
                output_html=out_html_grupo,
                output_pdf=out_pdf_grupo,
                generar_pdf=generar_pdf,
                fits_temporales_limpiar=fits_limpiar_grupo
            )
            rutas_generadas.append((grupo, ruta))
        except Exception as e:
            print(f"⚠️  No se pudo generar el perfil para Carrera {grupo}: {e}")

    if rutas_generadas:
        print("\n" + "=" * 55)
        print("🏆 ¡PERFILES DE ETAPA GENERADOS CON ÉXITO!")
        print("=" * 55)
        for grupo, ruta in rutas_generadas:
            print(f"   📄 Carrera {grupo}: {ruta.resolve()}")
        print("💡 Ábrelos en cualquier navegador para ver el análisis completo.")
        print("=" * 55 + "\n")


def main():
    parser = argparse.ArgumentParser(
        prog="intervals-fit",
        description="Suite de Análisis de Ciclismo: Intervals.icu API + Telemetría FIT + CdA Modeling"
    )
    subparsers = parser.add_subparsers(dest="command", help="Comando a ejecutar")

    # Comando: list-athletes
    p_athletes = subparsers.add_parser("list-athletes", help="Lista los atletas vinculados")
    p_athletes.add_argument("--roster", default=str(DEFAULT_ROSTER_PATH), help="Ruta al archivo CSV de plantilla")
    p_athletes.add_argument("--solo-carrera", action="store_true", help="Filtrar solo atletas con carrera=1")
    p_athletes.set_defaults(func=cmd_list_athletes)

    # Comando: power-report
    p_power = subparsers.add_parser("power-report", help="Genera el informe de potencias y carga en PDF")
    p_power.add_argument("--roster", default=str(DEFAULT_ROSTER_PATH), help="Ruta al archivo CSV de plantilla")
    p_power.add_argument("--solo-carrera", action="store_true", help="Filtrar solo atletas con carrera=1")
    p_power.add_argument("--dias", type=int, default=30, help="Ventana de días para picos de potencia recientes")
    p_power.add_argument("--dias-carga", type=int, default=60, help="Ventana de días para evolución de CTL/ATL")
    p_power.add_argument("--output", help="Ruta del archivo PDF de salida")
    p_power.set_defaults(func=cmd_power_report)

    # Comando: hrv-report
    p_hrv = subparsers.add_parser("hrv-report", help="Genera el informe de HRV y bienestar en PDF")
    p_hrv.add_argument("--roster", default=str(DEFAULT_ROSTER_PATH), help="Ruta al archivo CSV de plantilla")
    p_hrv.add_argument("--solo-carrera", action="store_true", help="Filtrar solo atletas con carrera=1")
    p_hrv.add_argument("--output", help="Ruta del archivo PDF de salida")
    p_hrv.set_defaults(func=cmd_hrv_report)

    # Comando: fit-cda
    p_fit = subparsers.add_parser("fit-cda", help="Estima CdA y Crr a partir de un archivo .fit")
    p_fit.add_argument("fit_file", help="Ruta al archivo .fit a analizar")
    p_fit.add_argument("--peso-ciclista", type=float, default=DEFAULT_RIDER_WEIGHT, help="Peso del ciclista en kg")
    p_fit.add_argument("--peso-bici", type=float, default=DEFAULT_BIKE_WEIGHT, help="Peso de la bicicleta en kg")
    p_fit.add_argument("--peso-total", type=float, help="Peso total combinado (ciclista + bici + ropa)")
    p_fit.add_argument("--rho", type=float, default=1.15, help="Densidad del aire (kg/m³)")
    p_fit.add_argument("--min-speed", type=float, default=3.0, help="Velocidad mínima de corte (m/s)")
    p_fit.add_argument("--min-power", type=float, default=30.0, help="Potencia mínima de corte (W)")
    p_fit.add_argument("--plot", action="store_true", help="Mostrar gráficos interactivos")
    p_fit.add_argument("--save-plot", help="Guardar gráfico PNG en la ruta indicada")
    p_fit.set_defaults(func=cmd_fit_cda)

    # Comando: fit-torque
    p_torque = subparsers.add_parser("fit-torque", help="Analiza la biomecánica de torque, fuerza en pedales y cuadrantes de un archivo FIT")
    p_torque.add_argument("fit_file", help="Ruta al archivo .fit a analizar")
    p_torque.add_argument("--ftp", type=float, default=380.0, help="FTP de referencia del ciclista en vatios (default: 380)")
    p_torque.add_argument("--crank-length", type=float, default=DEFAULT_CRANK_LENGTH, help=f"Longitud de biela en metros (default: {DEFAULT_CRANK_LENGTH})")
    p_torque.set_defaults(func=cmd_fit_torque)

    # Comando: download-fit
    p_down = subparsers.add_parser("download-fit", help="Descarga el archivo FIT de una actividad")
    p_down.add_argument("activity_id", help="ID de la actividad en Intervals.icu")
    p_down.add_argument("--output", help="Ruta del archivo de destino")
    p_down.set_defaults(func=cmd_download_fit)

    # Comando: interactive-profile / profile-report
    p_prof = subparsers.add_parser("profile-report", aliases=["interactive-profile"], help="Genera el perfil interactivo HTML y el informe ejecutivo PDF con mapa, altimetría, comparativas y fisiología")
    p_prof.add_argument("fit_files", nargs="*", help="Archivos FIT opcionales a incluir")
    p_prof.add_argument("--fit-dir", help="Directorio con archivos FIT")
    p_prof.add_argument("--fecha", help="Fecha de la etapa / actividad (YYYY-MM-DD)")
    p_prof.add_argument("--activity-id", help="Procesar una actividad individual específica por su ID en Intervals.icu")
    p_prof.add_argument("--ultima-individual", action="store_true", help="Procesar únicamente la última actividad individual absoluta")
    p_prof.add_argument("--mantener-fits", action="store_true", help="Conservar en disco los archivos FIT descargados de la API tras procesarlos")
    p_prof.add_argument("--roster", default=str(DEFAULT_ROSTER_PATH), help="Ruta al archivo CSV de plantilla")
    p_prof.add_argument("--todos", action="store_true", help="Incluir a todos los atletas del equipo (incluso carrera=0)")
    p_prof.add_argument("--solo-carrera", action="store_true", default=True, help="Filtrar solo atletas con carrera=1 (por defecto)")
    p_prof.add_argument("--titulo", help="Título base para la etapa (aplicado a todos los grupos)")
    p_prof.add_argument("--titulo-1", dest="titulo_1", default="", help="Título personalizado para el grupo Carrera 1")
    p_prof.add_argument("--titulo-2", dest="titulo_2", default="", help="Título personalizado para el grupo Carrera 2")
    p_prof.add_argument("--titulo-3", dest="titulo_3", default="", help="Título personalizado para el grupo Carrera 3")
    p_prof.add_argument("--output", help="Ruta del archivo HTML de salida")
    p_prof.add_argument("--output-pdf", help="Ruta del archivo PDF de salida")
    p_prof.add_argument("--no-pdf", action="store_true", help="Omitir la generación del informe PDF")
    p_prof.set_defaults(func=cmd_interactive_profile)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(0)

    args.func(args)


if __name__ == "__main__":
    main()
