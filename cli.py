"""
Interfaz de Línea de Comandos (CLI) de Intervals Fit Analytics.
Permite ejecutar análisis de potencias, carga, HRV y estimación de CdA desde la terminal.
"""

import argparse
import sys
import subprocess
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
    generar_informe_potencias_y_carga_word,
    generar_informe_wellness_hrv,
    generar_informe_etapa_pdf,
    generar_dashboard_perfil_interactivo,
    descargar_o_recopilar_fits_etapa,
    calcular_metricas_torque_completas,
    obtener_historico_carrera_etapas,
    obtener_resumen_acumulado_carrera,
    obtener_mejores_numeros_temporada,
    obtener_curva_potencia_fatiga,
    obtener_ranking_equipo_pico,
    obtener_estadisticas_generales_bd,
    sincronizar_historico_desde_api,
    resolver_kj_picos_atleta,
    resolver_carrera,
    obtener_carreras_calendario,
    obtener_carreras_activas_fecha,
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
    """Genera el informe completo de potencias y carga en PDF, uno por cada grupo de carrera o filtrado por grupo."""
    client = IntervalsClient()
    roster_df = cargar_roster(args.roster)

    grupo_especifico = getattr(args, 'carrera', None)
    todos = getattr(args, 'todos', False)
    solo_carrera = not todos

    carrera_res = resolver_carrera(grupo_especifico) if grupo_especifico is not None else None

    if grupo_especifico is not None:
        try:
            g_num = int(grupo_especifico)
            es_numero = True
        except (ValueError, TypeError):
            es_numero = False

        if carrera_res is not None and carrera_res.get('convocados'):
            conv_ids = {str(c['atleta_id']).strip() for c in carrera_res.get('convocados', []) if c.get('atleta_id')}
            atletas = client.get_athletes_list(roster_df=roster_df, convocados_ids=conv_ids)
            if es_numero and any(int(a.get('carrera', 0)) == g_num for a in atletas):
                grupos_carrera = [g_num]
                atletas = [a for a in atletas if int(a.get('carrera', 0)) == g_num]
            else:
                grupos_carrera = [carrera_res['carrera_id']]
            print(f"\n📊 [{carrera_res['nombre_carrera']}] {len(atletas)} atletas convocados:")
        elif es_numero:
            grupos_carrera = [g_num]
            atletas_raw = client.get_athletes_list(roster_df=roster_df, solo_carrera=False)
            atletas = [a for a in atletas_raw if int(a.get('carrera', 0)) == g_num] if any('carrera' in a for a in atletas_raw) else atletas_raw
            c_nom = carrera_res['nombre_carrera'] if carrera_res else f"Grupo Carrera {g_num}"
            print(f"\n📊 [{c_nom}] {len(atletas)} atletas seleccionados:")
        else:
            grupos_carrera = [grupo_especifico]
            atletas = client.get_athletes_list(roster_df=roster_df, solo_carrera=False)
            print(f"\n📊 [{grupo_especifico}] {len(atletas)} atletas seleccionados:")
    else:
        # Modo: Sin carrera específica
        if solo_carrera:
            from src.history_manager import obtener_carreras_calendario
            atletas_raw = client.get_athletes_list(roster_df=roster_df, solo_carrera=True)
            if any(int(a.get('carrera', 0)) > 0 for a in atletas_raw):
                atletas = atletas_raw
                grupos_carrera = sorted(set(int(a.get('carrera', 0)) for a in atletas if int(a.get('carrera', 0)) > 0))
            else:
                carreras = [c for c in obtener_carreras_calendario() if c.get('convocados')]
                carreras_activas = [c for c in carreras if c.get('estado') == 'en_curso']
                carreras_usar = carreras_activas if carreras_activas else carreras
                if carreras_usar:
                    grupos_carrera = [c['carrera_id'] for c in carreras_usar]
                    all_conv = set()
                    for c in carreras_usar:
                        for conv in c.get('convocados', []):
                            if conv.get('atleta_id'):
                                all_conv.add(str(conv['atleta_id']).strip())
                    atletas = client.get_athletes_list(roster_df=roster_df, convocados_ids=all_conv)
                else:
                    atletas = atletas_raw
                    grupos_carrera = [None]
        else:
            atletas = client.get_athletes_list(roster_df=roster_df, solo_carrera=False)
            grupos_carrera = sorted(set(int(a.get('carrera', 0)) for a in atletas if int(a.get('carrera', 0)) > 0)) if any(a.get('carrera') for a in atletas) else [None]

        if not atletas:
            print("❌ No se encontraron atletas para analizar.")
            return

        print(f"\n📊 {len(atletas)} atletas en {len(grupos_carrera)} competición(es): {grupos_carrera}")

    for a in atletas:
        c_num = a.get('carrera', 0)
        c_tag = f" [Carrera {c_num}]" if c_num else ""
        print(f"   - {a.get('athlete_name')} ({a.get('athlete_id')}){c_tag}")

    # Calcular datos una sola vez para los atletas seleccionados
    print("\n⏳ Calculando picos de potencia (30 días vs Histórico)...")
    peaks_df_total = calcular_picos_potencia(client, atletas, roster_df, dias_recientes=args.dias)

    print("⏳ Calculando evolución de carga diaria, CTL y ATL...")
    nombres_map = dict(zip(roster_df['intervals_id'], roster_df['Name'])) if not roster_df.empty else {}
    metrics_df_total = calcular_metricas_carga(client, atletas, dias_historia=args.dias_carga, dias_plot=args.dias_carga, nombres_map=nombres_map)

    # Títulos personalizados por grupo
    titulos_por_grupo = {
        1: getattr(args, 'titulo_1', ''),
        2: getattr(args, 'titulo_2', ''),
        3: getattr(args, 'titulo_3', ''),
    }

    formato = getattr(args, 'formato', 'pdf')
    generar_pdf = (formato in ['pdf', 'ambos'])
    generar_docx = (formato in ['docx', 'ambos'])

    # Generar informes por grupo o competición
    rutas_generadas = []
    for grupo in grupos_carrera:
        c_info = resolver_carrera(grupo) if grupo is not None else None
        c_nombre = c_info['nombre_carrera'] if c_info else (f"Grupo Carrera {grupo}" if grupo is not None else "Informe General")
        c_slug = c_info['carrera_id'] if c_info else (f"carrera_{grupo}" if grupo is not None else "")

        if grupo is None:
            atletas_grupo = atletas
            label = ""
            titulo_grupo = getattr(args, 'titulo', None) or "Informe General"
        elif len(grupos_carrera) == 1:
            atletas_grupo = atletas
            label = f"_carrera_{grupo}" if isinstance(grupo, int) else (f"_{c_slug}" if c_slug else f"_{grupo}")
            titulo_esp = titulos_por_grupo.get(grupo, '') if isinstance(grupo, int) else ''
            if titulo_esp:
                titulo_grupo = titulo_esp
            elif getattr(args, 'titulo', None):
                titulo_grupo = f"{args.titulo} - Carrera {grupo}" if isinstance(grupo, int) else f"{args.titulo} - {c_nombre}"
            else:
                titulo_grupo = f"Grupo Carrera {grupo}" if isinstance(grupo, int) else c_nombre
        elif isinstance(grupo, int):
            atletas_grupo = [a for a in atletas if int(a.get('carrera', 0)) == grupo]
            label = f"_carrera_{grupo}"
            titulo_esp = titulos_por_grupo.get(grupo, '')
            titulo_grupo = titulo_esp if titulo_esp else (f"{args.titulo} - Carrera {grupo}" if getattr(args, 'titulo', None) else f"Grupo Carrera {grupo}")
        elif c_info and c_info.get('convocados'):
            conv_ids_g = {str(c['atleta_id']).strip() for c in c_info['convocados']}
            atletas_grupo = [a for a in atletas if str(a.get('athlete_id', '')).strip() in conv_ids_g]
            label = f"_{c_slug}" if c_slug else f"_{grupo}"
            titulo_grupo = f"{args.titulo} - {c_nombre}" if getattr(args, 'titulo', None) else c_nombre
        else:
            atletas_grupo = atletas
            label = f"_{grupo}"
            titulo_grupo = f"{args.titulo} - {c_nombre}" if getattr(args, 'titulo', None) else c_nombre

        if not atletas_grupo:
            print(f"⚠️  Grupo Carrera {grupo}: sin atletas, omitiendo.")
            continue

        nombres_grupo_set = {a.get('athlete_name') for a in atletas_grupo}
        peaks_g = peaks_df_total[peaks_df_total['athlete_name'].isin(nombres_grupo_set)].copy() if not peaks_df_total.empty else peaks_df_total
        metrics_g = metrics_df_total[metrics_df_total['athlete_name'].isin(nombres_grupo_set)].copy() if not metrics_df_total.empty else metrics_df_total
        tabla_g, _ = generar_tabla_picos_comparativa(peaks_g)

        # Determinar nombre del PDF de salida
        if args.output:
            if len(grupos_carrera) == 1:
                out_pdf = Path(args.output)
            else:
                p = Path(args.output)
                out_pdf = p.parent / f"{p.stem}{label}{p.suffix}"
        else:
            out_pdf = OUTPUT_DIR / f"intervals_informe{label}.pdf"

        # Determinar nombre del Word de salida
        if getattr(args, 'output_docx', None):
            if len(grupos_carrera) == 1:
                out_docx = Path(args.output_docx)
            else:
                p = Path(args.output_docx)
                out_docx = p.parent / f"{p.stem}{label}{p.suffix}"
        else:
            out_docx = out_pdf.with_suffix('.docx')

        rutas_grupo = {}
        if generar_pdf:
            print(f"\n📄 [{titulo_grupo}] {len(atletas_grupo)} atletas (PDF) → {out_pdf}")
            ruta_pdf = generar_informe_potencias_y_carga(
                peaks_g,
                tabla_g,
                metrics_g,
                output_pdf=out_pdf,
                titulo=titulo_grupo,
                grupo_carrera=grupo
            )
            rutas_grupo['pdf'] = ruta_pdf
            print(f"   ✅ PDF Generado: {ruta_pdf.resolve()}")

        if generar_docx:
            print(f"\n📝 [{titulo_grupo}] {len(atletas_grupo)} atletas (Word) → {out_docx}")
            ruta_docx = generar_informe_potencias_y_carga_word(
                peaks_g,
                tabla_g,
                metrics_g,
                output_docx=out_docx,
                titulo=titulo_grupo,
                grupo_carrera=grupo
            )
            rutas_grupo['docx'] = ruta_docx
            print(f"   ✅ Word Generado: {ruta_docx.resolve()}")

        rutas_generadas.append((grupo, titulo_grupo, rutas_grupo))

    if rutas_generadas:
        print("\n" + "=" * 55)
        print("🏆 Informes de potencia generados correctamente:")
        for _, tit, rg in rutas_generadas:
            print(f"   📊 {tit}:")
            if 'pdf' in rg:
                print(f"      📄 PDF:  {rg['pdf'].resolve()}")
            if 'docx' in rg:
                print(f"      📝 Word: {rg['docx'].resolve()}")
        print("=" * 55 + "\n")


def cmd_hrv_report(args):
    """Genera el informe de evolución de HRV (RMSSD) y bienestar en PDF, uno por cada grupo de carrera o filtrado por grupo."""
    client = IntervalsClient()
    roster_df = cargar_roster(args.roster)

    grupo_especifico = getattr(args, 'carrera', None)
    todos = getattr(args, 'todos', False)
    solo_carrera = not todos

    carrera_res = resolver_carrera(grupo_especifico) if grupo_especifico is not None else None

    if carrera_res is not None and carrera_res.get('convocados'):
        conv_ids = {str(c['atleta_id']).strip() for c in carrera_res.get('convocados', []) if c.get('atleta_id')}
        atletas = client.get_athletes_list(roster_df=roster_df, convocados_ids=conv_ids)
        grupos_carrera = [carrera_res['carrera_id']]
        print(f"\n🩺 [{carrera_res['nombre_carrera']}] {len(atletas)} atletas convocados:")
    elif grupo_especifico is not None:
        atletas_raw = client.get_athletes_list(roster_df=roster_df, solo_carrera=False)
        try:
            g_num = int(grupo_especifico)
            atletas = [a for a in atletas_raw if int(a.get('carrera', 0)) == g_num] if any('carrera' in a for a in atletas_raw) else atletas_raw
            grupos_carrera = [g_num]
        except Exception:
            atletas = atletas_raw
            grupos_carrera = [grupo_especifico]
        if not atletas:
            print(f"❌ No se encontraron atletas asignados a {grupo_especifico} en {args.roster}.")
            return
        print(f"\n🩺 [{grupo_especifico}] {len(atletas)} atletas seleccionados:")
    else:
        if solo_carrera:
            from src.history_manager import obtener_carreras_calendario
            carreras = [c for c in obtener_carreras_calendario() if c.get('convocados')]
            carreras_activas = [c for c in carreras if c.get('estado') == 'en_curso']
            carreras_usar = carreras_activas if carreras_activas else carreras
            if carreras_usar:
                grupos_carrera = [c['carrera_id'] for c in carreras_usar]
                all_conv = set()
                for c in carreras_usar:
                    for conv in c.get('convocados', []):
                        if conv.get('atleta_id'):
                            all_conv.add(str(conv['atleta_id']).strip())
                atletas = client.get_athletes_list(roster_df=roster_df, convocados_ids=all_conv)
            else:
                atletas = client.get_athletes_list(roster_df=roster_df, solo_carrera=solo_carrera)
                grupos_carrera = sorted(set(int(a.get('carrera', 0)) for a in atletas if int(a.get('carrera', 0)) > 0)) if any(a.get('carrera') for a in atletas) else [None]
        else:
            atletas = client.get_athletes_list(roster_df=roster_df, solo_carrera=False)
            grupos_carrera = sorted(set(int(a.get('carrera', 0)) for a in atletas if int(a.get('carrera', 0)) > 0)) if any(a.get('carrera') for a in atletas) else [None]

        if not atletas:
            print("❌ No se encontraron atletas para analizar.")
            return

        print(f"\n🩺 Descargando datos de bienestar para {len(atletas)} atletas en {len(grupos_carrera)} competición(es)...")

    for a in atletas:
        c_num = a.get('carrera', 0)
        c_tag = f" [Carrera {c_num}]" if c_num else ""
        print(f"   - {a.get('athlete_name')} ({a.get('athlete_id')}){c_tag}")

    nombres_map = dict(zip(roster_df['intervals_id'], roster_df['Name'])) if not roster_df.empty else {}
    wellness_df_total = descargar_wellness_atletas(client, atletas, nombres_map=nombres_map)

    if wellness_df_total.empty:
        print("❌ No se encontraron datos de bienestar para los atletas indicados.")
        return

    stats_df = resumen_estadisticas_hrv(wellness_df_total)
    print("\n📋 Resumen de Estadísticas HRV:")
    print(tabulate(stats_df, headers="keys", tablefmt="fancy_grid", showindex=False))

    titulos_por_grupo = {
        1: getattr(args, 'titulo_1', ''),
        2: getattr(args, 'titulo_2', ''),
        3: getattr(args, 'titulo_3', ''),
    }

    rutas_generadas = []
    for grupo in grupos_carrera:
        c_info = resolver_carrera(grupo) if grupo is not None else None
        c_nombre = c_info['nombre_carrera'] if c_info else (f"Grupo Carrera {grupo}" if grupo is not None else "Informe General")
        c_slug = c_info['carrera_id'] if c_info else (f"carrera_{grupo}" if grupo is not None else "")

        if grupo is None:
            wellness_g = wellness_df_total
            label = ""
            titulo_grupo = getattr(args, 'titulo', None) or "Informe General"
        elif c_info and c_info.get('convocados'):
            conv_ids_g = {str(c['atleta_id']).strip() for c in c_info['convocados']}
            atletas_grupo = [a for a in atletas if str(a.get('athlete_id', '')).strip() in conv_ids_g]
            nombres_grupo = {a.get('athlete_name') for a in atletas_grupo}
            wellness_g = wellness_df_total[wellness_df_total['athlete_name'].isin(nombres_grupo)].copy()
            label = f"_{c_slug}" if c_slug else f"_carrera_{grupo}"
            titulo_esp = titulos_por_grupo.get(grupo, '') if isinstance(grupo, int) else ''
            if titulo_esp:
                titulo_grupo = titulo_esp
            elif getattr(args, 'titulo', None):
                titulo_grupo = f"{args.titulo} - {c_nombre}"
            else:
                titulo_grupo = c_nombre
        else:
            atletas_grupo = [a for a in atletas if int(a.get('carrera', 0)) == grupo] if isinstance(grupo, int) else atletas
            nombres_grupo = {a.get('athlete_name') for a in atletas_grupo}
            wellness_g = wellness_df_total[wellness_df_total['athlete_name'].isin(nombres_grupo)].copy()
            label = f"_carrera_{grupo}"
            titulo_esp = titulos_por_grupo.get(grupo, '') if isinstance(grupo, int) else ''
            if titulo_esp:
                titulo_grupo = titulo_esp
            elif getattr(args, 'titulo', None):
                titulo_grupo = f"{args.titulo} - Carrera {grupo}"
            else:
                titulo_grupo = f"Grupo Carrera {grupo}"

        if wellness_g.empty:
            print(f"⚠️  Grupo Carrera {grupo}: sin datos de wellness, omitiendo.")
            continue

        if args.output:
            if len(grupos_carrera) == 1:
                out_pdf = Path(args.output)
            else:
                p = Path(args.output)
                out_pdf = p.parent / f"{p.stem}{label}{p.suffix}"
        else:
            out_pdf = OUTPUT_DIR / f"wellness_evolucion{label}.pdf"

        print(f"\n📄 [{titulo_grupo}] → {out_pdf}")
        ruta_generada = generar_informe_wellness_hrv(
            wellness_g,
            output_pdf=out_pdf,
            titulo=titulo_grupo,
            grupo_carrera=grupo
        )
        rutas_generadas.append(ruta_generada)
        print(f"   ✅ Generado: {ruta_generada.resolve()}")

    if rutas_generadas:
        print("\n" + "=" * 55)
        print(f"🏆 {len(rutas_generadas)} informe(s) de HRV generado(s) correctamente:")
        for r in rutas_generadas:
            print(f"   📄 {r.resolve()}")
        print("=" * 55 + "\n")


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
    formato = getattr(args, 'formato', 'pdf')
    generar_pdf = not getattr(args, 'no_pdf', False) and (formato in ['pdf', 'ambos'])
    generar_docx = (formato in ['docx', 'ambos'])
    fits_limpiar = fits_temporales if not getattr(args, 'mantener_fits', False) else None

    # Identificar competiciones del calendario
    carreras_detectadas = []
    carrera_arg = getattr(args, 'carrera', None)
    if carrera_arg:
        c_res = resolver_carrera(carrera_arg)
        if c_res:
            carreras_detectadas = [c_res['carrera_id']]
    else:
        try:
            from src.history_manager import obtener_carreras_calendario
            carreras_act = [c for c in obtener_carreras_calendario() if c.get('estado') == 'en_curso' and c.get('convocados')]
            if carreras_act:
                carreras_detectadas = [c['carrera_id'] for c in carreras_act]
        except Exception:
            pass

    # Si se pasaron archivos manualmente o no hay carreras definidas → un único perfil global
    forzar_global = bool(args.fit_files or getattr(args, 'fit_dir', None)) or not carreras_detectadas
    if forzar_global:
        out_html = Path(args.output) if args.output else None
        out_pdf = Path(args.output_pdf) if getattr(args, 'output_pdf', None) else None
        out_docx = Path(args.output_docx) if getattr(args, 'output_docx', None) else None
        ruta_generada = generar_dashboard_perfil_interactivo(
            fits_unicos,
            roster_df=roster_df,
            client=client,
            solo_carrera=solo_carrera,
            titulo=args.titulo,
            output_html=out_html,
            output_pdf=out_pdf,
            generar_pdf=generar_pdf,
            output_docx=out_docx,
            generar_docx=generar_docx,
            formato_informe=formato,
            fits_temporales_limpiar=fits_limpiar
        )
        pdf_estimado = out_pdf or ruta_generada.with_suffix('.pdf')
        docx_estimado = out_docx or ruta_generada.with_suffix('.docx')
        print("\n" + "=" * 55)
        print("🏆 ¡PERFIL E INFORME DE ETAPA GENERADOS CON ÉXITO!")
        print("=" * 55)
        print(f"📄 Archivo HTML: {ruta_generada.resolve()}")
        if generar_pdf and pdf_estimado.exists():
            print(f"📄 Archivo PDF:  {pdf_estimado.resolve()}")
        if generar_docx and docx_estimado.exists():
            print(f"📝 Archivo Word: {docx_estimado.resolve()}")
        print("💡 Ábrelo en cualquier navegador o procesador para ver el análisis")
        print("   completo de la etapa, comparativas y fisiología.")
        print("=" * 55 + "\n")
        return

    # Generar un perfil HTML (y PDF/Word) independiente por cada competición
    print(f"\n🏁 Detectadas {len(carreras_detectadas)} competición(es): {carreras_detectadas}")
    rutas_generadas = []
    for idx, c_id in enumerate(carreras_detectadas):
        c_res = resolver_carrera(c_id)
        c_nombre = c_res['nombre_carrera'] if c_res else c_id
        c_slug = c_res['carrera_id'] if c_res else c_id

        print(f"\n{'='*55}")
        print(f"🏁 Generando perfil para {c_nombre}...")
        print(f"{'='*55}")

        # Nombre de salida: añadir slug si hay ruta explícita
        out_html_grupo = None
        if args.output:
            p = Path(args.output)
            out_html_grupo = p.parent / f"{p.stem}_{c_slug}{p.suffix}"

        out_pdf_grupo = None
        if getattr(args, 'output_pdf', None):
            p = Path(args.output_pdf)
            out_pdf_grupo = p.parent / f"{p.stem}_{c_slug}{p.suffix}"

        out_docx_grupo = None
        if getattr(args, 'output_docx', None):
            p = Path(args.output_docx)
            out_docx_grupo = p.parent / f"{p.stem}_{c_slug}{p.suffix}"

        # Título: prioridad → 1) --titulo-N específico del grupo, 2) --titulo base, 3) nombre oficial de la carrera
        titulos_por_grupo = {
            1: getattr(args, 'titulo_1', ''),
            2: getattr(args, 'titulo_2', ''),
            3: getattr(args, 'titulo_3', ''),
        }
        titulo_especifico = titulos_por_grupo.get(grupo, '') if isinstance(grupo, int) else ''
        if titulo_especifico:
            titulo_grupo = titulo_especifico
        elif args.titulo:
            titulo_grupo = f"{args.titulo} - {c_nombre}"
        else:
            titulo_grupo = c_nombre

        # Solo limpiar FITs temporales tras generar el último grupo
        fits_limpiar_grupo = fits_limpiar if idx == len(grupos_carrera) - 1 else None

        try:
            ruta = generar_dashboard_perfil_interactivo(
                fits_unicos,
                roster_df=roster_df,
                client=client,
                solo_carrera=True,
                grupo_carrera=grupo,
                carrera_id=c_slug,
                titulo=titulo_grupo,
                output_html=out_html_grupo,
                output_pdf=out_pdf_grupo,
                generar_pdf=generar_pdf,
                output_docx=out_docx_grupo,
                generar_docx=generar_docx,
                formato_informe=formato,
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
            pdf_g = ruta.with_suffix('.pdf')
            docx_g = ruta.with_suffix('.docx')
            if generar_pdf and pdf_g.exists():
                print(f"      📄 PDF:  {pdf_g.resolve()}")
            if generar_docx and docx_g.exists():
                print(f"      📝 Word: {docx_g.resolve()}")
        print("💡 Ábrelos en cualquier navegador o visor para ver el análisis completo.")
        print("=" * 55 + "\n")


def cmd_stage_race(args):
    """Consulta el gasto energético acumulado de una carrera por etapas."""
    carrera_id = args.carrera_id
    if getattr(args, 'acumulado', False):
        df = obtener_resumen_acumulado_carrera(carrera_id)
        if df.empty:
            print(f"❌ No se encontraron datos para la carrera '{carrera_id}' en la base de datos histórica.")
            return
        print(f"\n📊 RESUMEN ACUMULADO FINAL - {carrera_id.upper()}")
        print(tabulate(df, headers="keys", tablefmt="fancy_grid", showindex=False))
    else:
        df = obtener_historico_carrera_etapas(carrera_id)
        if df.empty:
            print(f"❌ No se encontraron datos para la carrera '{carrera_id}' en la base de datos histórica.")
            return
        cols_mostrar = ['nombre', 'etapa_num', 'distancia_km', 'tiempo_mov_h', 'pot_media_w', 'np_w', 'kj_total', 'kj_kg_h', 'tss', 'kj_acumulados', 'tss_acumulado']
        cols_presentes = [c for c in cols_mostrar if c in df.columns]
        print(f"\n📈 EVOLUCIÓN DÍA A DÍA Y GASTO ENERGÉTICO ACUMULADO - {carrera_id.upper()}")
        print(tabulate(df[cols_presentes], headers="keys", tablefmt="fancy_grid", showindex=False))


def cmd_season_bests(args):
    """Consulta los mejores números (MMP) y registros bajo fatiga de un ciclista con gasto energético previo."""
    atleta_id = args.atleta
    nombre_atleta = atleta_id
    roster_df = cargar_roster(args.roster) if getattr(args, 'roster', None) else None
    if roster_df is not None and not roster_df.empty:
        nom_match = roster_df[roster_df['Name'].str.contains(atleta_id, case=False, na=False)]
        if not nom_match.empty:
            atleta_id = nom_match.iloc[0]['intervals_id']
            nombre_atleta = nom_match.iloc[0]['Name']

    temporada = getattr(args, 'temporada', None)
    if getattr(args, 'fatiga', False):
        umbral = getattr(args, 'umbral_kj', 2000.0)
        df = obtener_curva_potencia_fatiga(atleta_id=atleta_id, umbral_kj=umbral, temporada=temporada)
        if df.empty:
            print(f"❌ No se encontraron datos de picos de potencia para el atleta '{nombre_atleta}'.")
            return
        if not getattr(args, 'todas', False):
            duraciones_std = [1, 5, 10, 15, 30, 60, 120, 180, 300, 600, 900, 1200, 1800, 2700, 3600, 5400, 7200, 10800, 14400, 18000]
            df_filtrado = df[df['duracion_s'].isin(duraciones_std)]
            if not df_filtrado.empty:
                df = df_filtrado

        df_display = df.drop(columns=['duracion_s'], errors='ignore').copy()
        renombrar_fatiga = {
            'duracion_str': 'Duración',
            'watts_fresco': f'Fresco (<{int(umbral)} kJ) W',
            'wkg_fresco': 'W/kg (Fresco)',
            'watts_fatiga': f'Fatiga (≥{int(umbral)} kJ) W',
            'wkg_fatiga': 'W/kg (Fatiga)',
            'perdida_pct': 'Pérdida %'
        }
        df_display.rename(columns=renombrar_fatiga, inplace=True)
        print(f"\n⚡ COMPARATIVA DE POTENCIA: FRESCO (<{int(umbral)} kJ) VS BAJO FATIGA (≥{int(umbral)} kJ) [{nombre_atleta} - {atleta_id}]")
        print(tabulate(df_display, headers="keys", tablefmt="fancy_grid", showindex=False))
    else:
        df = obtener_mejores_numeros_temporada(atleta_id=atleta_id, temporada=temporada)
        if df.empty:
            print(f"❌ No se encontraron registros de récord para el atleta '{nombre_atleta}'.")
            return

        # Si aún no se han resuelto los kJ previos, resolver automáticamente
        if 'kj_previos' in df.columns and df['kj_previos'].fillna(0).sum() == 0:
            resolver_kj_picos_atleta(atleta_id=atleta_id, verbose=False)
            df = obtener_mejores_numeros_temporada(atleta_id=atleta_id, temporada=temporada)

        if not getattr(args, 'todas', False):
            duraciones_std = [1, 5, 10, 15, 30, 60, 120, 180, 300, 600, 900, 1200, 1800, 2700, 3600, 5400, 7200, 10800, 14400, 18000]
            df_filtrado = df[df['duracion_s'].isin(duraciones_std)]
            if not df_filtrado.empty:
                df = df_filtrado

        cols_mostrar = ['duracion_str', 'max_watts', 'w_kg', 'kj_previos', 'kjkg_previos', 'kj_esfuerzo', 'kj_totales', 'momento_carrera', 'fecha', 'nombre_carrera']
        cols_presentes = [c for c in cols_mostrar if c in df.columns]
        df_display = df[cols_presentes].copy()
        renombrar_mmp = {
            'duracion_str': 'Duración',
            'max_watts': 'Vatios (W)',
            'w_kg': 'W/kg',
            'kj_previos': 'kJ Previos (Fatiga)',
            'kjkg_previos': 'kJ/kg Prev.',
            'kj_esfuerzo': 'kJ Esfuerzo',
            'kj_totales': 'kJ Totales',
            'momento_carrera': 'Momento',
            'fecha': 'Fecha',
            'nombre_carrera': 'Carrera / Actividad'
        }
        df_display.rename(columns=renombrar_mmp, inplace=True)
        temp_str = f"TEMPORADA {temporada}" if temporada else "HISTÓRICO COMPLETO"
        print(f"\n🏆 MEJORES NÚMEROS (CURVA MMP) CON GASTO ENERGÉTICO PREVIO - {temp_str} [{nombre_atleta} - {atleta_id}]")
        print(tabulate(df_display, headers="keys", tablefmt="fancy_grid", showindex=False))


def cmd_team_ranking(args):
    """Muestra el ranking del equipo para un intervalo de tiempo."""
    from src.power_peaks import _a_int_segundos
    dur_s = _a_int_segundos(args.duracion) or 300
    df = obtener_ranking_equipo_pico(
        duracion_s=dur_s,
        temporada=getattr(args, 'temporada', None),
        carrera_id=getattr(args, 'carrera', None)
    )
    if df.empty:
        print(f"❌ No hay registros guardados para duración {args.duracion} ({dur_s}s).")
        return
    print(f"\n🏅 RANKING DEL EQUIPO PARA {args.duracion.upper()} ({dur_s}s):")
    print(tabulate(df, headers="keys", tablefmt="fancy_grid", showindex=False))


def cmd_db_status(args):
    """Muestra estadísticas y tamaño de la base de datos histórica."""
    stats = obtener_estadisticas_generales_bd()
    if not stats.get('existe'):
        print("ℹ️ La base de datos histórica aún no ha sido creada o no contiene registros.")
        return
    print("\n📦 ESTADO DE LA BASE DE DATOS HISTÓRICA (SQLite):")
    tabla = [
        ["Ruta", stats['ruta']],
        ["Tamaño en Disco", f"{stats['tamano_kb']} KB ({stats['tamano_kb']/1024.0:.2f} MB)"],
        ["Ciclistas Registrados", stats['num_ciclistas']],
        ["Actividades / Etapas Guardadas", stats['num_actividades']],
        ["Picos MMP Históricos Almacenados", stats['num_picos_registrados']],
        ["Carreras Únicas", stats['num_carreras']],
        ["Total Trabajo Registrado", f"{stats['total_kj_registrados']:,.0f} kJ"]
    ]
    print(tabulate(tabla, headers=["Propiedad", "Valor"], tablefmt="fancy_grid"))


def cmd_sync_history(args):
    """Sincroniza en la base de datos histórica todas las actividades y récords desde fecha indicada."""
    sincronizar_historico_desde_api(
        roster_path=args.roster,
        fecha_inicio=args.desde,
        fecha_fin=args.hasta,
        incluir_wellness=not args.no_wellness,
        incluir_picos=not args.no_picos,
        solo_nuevas=getattr(args, 'solo_nuevas', False),
        verbose=True
    )


def cmd_web(args):
    """Inicia el servidor local de la plataforma web."""
    from run_web import main as run_web_main
    sys.argv = ["run_web", "--host", args.host, "--port", str(args.port)]
    if args.no_browser:
        sys.argv.append("--no-browser")
    run_web_main()


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
    p_power.add_argument("--carrera", "--grupo", dest="carrera", default=None,
                         help="Filtrar por carrera (slug, nombre o número). Si no se indica, procesa cada competición activa por separado.")
    p_power.add_argument("--todos", action="store_true", default=False,
                         help="Incluir a todos los atletas del equipo (incluso los no asignados a carrera)")
    p_power.add_argument("--solo-carrera", action="store_true", default=True,
                         help="Filtrar solo atletas en carrera (carrera > 0 o convocados) [activo por defecto]")
    p_power.add_argument("--dias", type=int, default=30, help="Ventana de días para picos de potencia recientes")
    p_power.add_argument("--dias-carga", type=int, default=60, help="Ventana de días para evolución de CTL/ATL")
    p_power.add_argument("--titulo", help="Título base para el informe (ej. 'Vuelta a Burgos')")
    p_power.add_argument("--titulo-1", dest="titulo_1", default="", help="Título personalizado para Carrera 1")
    p_power.add_argument("--titulo-2", dest="titulo_2", default="", help="Título personalizado para Carrera 2")
    p_power.add_argument("--titulo-3", dest="titulo_3", default="", help="Título personalizado para Carrera 3")
    p_power.add_argument("--output", help="Ruta del archivo PDF de salida")
    p_power.add_argument("--output-docx", help="Ruta del archivo Word (.docx) de salida")
    p_power.add_argument("--formato", choices=["pdf", "docx", "ambos"], default="pdf",
                         help="Formato del informe: 'pdf', 'docx' (Word) o 'ambos' (por defecto: pdf)")
    p_power.set_defaults(func=cmd_power_report)

    # Comando: hrv-report
    p_hrv = subparsers.add_parser("hrv-report", help="Genera el informe de HRV y bienestar en PDF")
    p_hrv.add_argument("--roster", default=str(DEFAULT_ROSTER_PATH), help="Ruta al archivo CSV de plantilla")
    p_hrv.add_argument("--carrera", "--grupo", dest="carrera", default=None,
                       help="Filtrar por carrera específica (slug, nombre o número). Si no se indica, procesa cada carrera por separado.")
    p_hrv.add_argument("--todos", action="store_true", default=False,
                       help="Incluir a todos los atletas del equipo (incluso los no asignados a carrera)")
    p_hrv.add_argument("--solo-carrera", action="store_true", default=True,
                       help="Filtrar solo atletas en carrera (carrera > 0 o convocados) [activo por defecto]")
    p_hrv.add_argument("--titulo", help="Título base para el informe")
    p_hrv.add_argument("--titulo-1", dest="titulo_1", default="", help="Título personalizado para Carrera 1")
    p_hrv.add_argument("--titulo-2", dest="titulo_2", default="", help="Título personalizado para Carrera 2")
    p_hrv.add_argument("--titulo-3", dest="titulo_3", default="", help="Título personalizado para Carrera 3")
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
    p_prof.add_argument("--carrera", "--grupo", dest="carrera", default=None,
                        help="Filtrar por carrera específica (ej. vuelta_a_burgos, o 1, 2). Si no se indica, procesa cada carrera activa.")
    p_prof.add_argument("--todos", action="store_true", help="Incluir a todos los atletas del equipo (incluso carrera=0)")
    p_prof.add_argument("--solo-carrera", action="store_true", default=True, help="Filtrar solo atletas en competición (por defecto)")
    p_prof.add_argument("--titulo", help="Título base para la etapa (aplicado a todos los grupos)")
    p_prof.add_argument("--titulo-1", dest="titulo_1", default="", help="Título personalizado para el grupo Carrera 1")
    p_prof.add_argument("--titulo-2", dest="titulo_2", default="", help="Título personalizado para el grupo Carrera 2")
    p_prof.add_argument("--titulo-3", dest="titulo_3", default="", help="Título personalizado para el grupo Carrera 3")
    p_prof.add_argument("--output", help="Ruta del archivo HTML de salida")
    p_prof.add_argument("--output-pdf", help="Ruta del archivo PDF de salida")
    p_prof.add_argument("--output-docx", help="Ruta del archivo Word (.docx) de salida")
    p_prof.add_argument("--formato", choices=["pdf", "docx", "ambos"], default="pdf",
                        help="Formato del informe ejecutivo: 'pdf', 'docx' (Word) o 'ambos' (por defecto: pdf)")
    p_prof.add_argument("--no-pdf", action="store_true", help="Omitir la generación del informe PDF")
    p_prof.set_defaults(func=cmd_interactive_profile)

    # Comando: stage-race / race-history
    p_race = subparsers.add_parser("stage-race", aliases=["race-history"], help="Consulta el gasto energético acumulado de una carrera por etapas")
    p_race.add_argument("carrera_id", help="Identificador de la carrera (ej. 'burgos_2026' o 'carrera_1')")
    p_race.add_argument("--acumulado", action="store_true", help="Muestra la tabla de totales acumulados por ciclista")
    p_race.set_defaults(func=cmd_stage_race)

    # Comando: season-bests / records
    p_season = subparsers.add_parser("season-bests", aliases=["records"], help="Consulta los mejores números y picos de potencia de la temporada con contexto de fatiga")
    p_season.add_argument("atleta", help="ID del atleta en Intervals.icu o nombre (ej. 'i495562' o 'Carlos Garcia')")
    p_season.add_argument("--temporada", type=int, help="Año de la temporada (ej. 2026)")
    p_season.add_argument("--fatiga", action="store_true", help="Compara picos en fresco (<2000 kJ) vs bajo fatiga (≥2000 kJ)")
    p_season.add_argument("--umbral-kj", dest="umbral_kj", type=float, default=2000.0, help="Umbral en kJ para separar fresco de fatigado (default: 2000)")
    p_season.add_argument("--todas", action="store_true", help="Mostrar todas las 200+ duraciones en lugar de los intervalos estándar")
    p_season.add_argument("--roster", default=str(DEFAULT_ROSTER_PATH), help="Ruta al CSV de plantilla para buscar por nombre")
    p_season.set_defaults(func=cmd_season_bests)

    # Comando: team-ranking
    p_rank = subparsers.add_parser("team-ranking", help="Muestra el ranking del equipo para un intervalo de tiempo específico (ej. 5s, 1m, 5m, 20m)")
    p_rank.add_argument("duracion", help="Duración del pico (ej. '5s', '1m', '5m', '20m', '300')")
    p_rank.add_argument("--temporada", type=int, help="Filtrar por año de temporada (ej. 2026)")
    p_rank.add_argument("--carrera", help="Filtrar por ID de carrera específica")
    p_rank.set_defaults(func=cmd_team_ranking)

    # Comando: db-status
    p_db = subparsers.add_parser("db-status", help="Muestra el estado, peso en disco y número de registros de la base de datos histórica")
    p_db.set_defaults(func=cmd_db_status)

    # Comando: sync-history
    p_sync = subparsers.add_parser("sync-history", help="Descarga y almacena en la base de datos histórica todas las actividades y récords desde fecha indicada")
    p_sync.add_argument("--roster", default=str(DEFAULT_ROSTER_PATH), help="Ruta al CSV de plantilla de ciclistas (default: burgos.csv)")
    p_sync.add_argument("--desde", default="2026-01-01", help="Fecha de inicio para la sincronización YYYY-MM-DD (default: 2026-01-01)")
    p_sync.add_argument("--hasta", default=None, help="Fecha final para la sincronización YYYY-MM-DD (default: hoy)")
    p_sync.add_argument("--solo-nuevas", action="store_true", help="Descarga únicamente actividades nuevas a partir del último registro de cada ciclista")
    p_sync.add_argument("--no-wellness", action="store_true", help="Omitir descarga de datos de bienestar/HRV")
    p_sync.add_argument("--no-picos", action="store_true", help="Omitir descarga de curvas de potencia de la temporada")
    p_sync.set_defaults(func=cmd_sync_history)

    # Comando: web / app
    p_web = subparsers.add_parser("web", aliases=["app"], help="Inicia la plataforma web interactiva (Intervals Fit Analytics)")
    p_web.add_argument("--host", default="127.0.0.1", help="Host del servidor (default: 127.0.0.1)")
    p_web.add_argument("--port", type=int, default=8000, help="Puerto del servidor (default: 8000)")
    p_web.add_argument("--no-browser", action="store_true", help="No abrir automáticamente el navegador")
    p_web.set_defaults(func=cmd_web)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(0)

    args.func(args)


if __name__ == "__main__":
    import os
    _ROOT_DIR = Path(__file__).resolve().parent
    _VENV_PYTHON = _ROOT_DIR / ".venv" / "Scripts" / "python.exe"
    if _VENV_PYTHON.exists() and os.environ.get("INTERVALS_NO_VENV_REEXEC") != "1":
        try:
            if Path(sys.executable).resolve() != _VENV_PYTHON.resolve():
                env = os.environ.copy()
                env["INTERVALS_NO_VENV_REEXEC"] = "1"
                res = subprocess.run([str(_VENV_PYTHON)] + sys.argv, cwd=str(_ROOT_DIR), env=env)
                sys.exit(res.returncode)
        except Exception:
            pass

    main()
