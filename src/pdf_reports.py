"""
Módulo de Generación de Informes Ejecutivos en PDF.
Genera documentos vectoriales multipágina con estética profesional:
1. Informe de Potencias y Métricas de Carga (CTL/ATL).
2. Informe de Bienestar y Evolución de HRV / Peso.
"""

import sys
from pathlib import Path

# Permitir ejecución directa del script o importación modular
_ROOT_DIR = Path(__file__).resolve().parent.parent
if str(_ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(_ROOT_DIR))

from datetime import datetime
from typing import Any, Dict, List, Optional, Union
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
import pandas as pd
import numpy as np

try:
    from config import DEFAULT_LOGO_PATH, OUTPUT_DIR
except (ImportError, ValueError):
    from ..config import DEFAULT_LOGO_PATH, OUTPUT_DIR


def _cargar_o_renderizar_svg(svg_path: Union[str, Path]) -> Optional[np.ndarray]:
    """Carga y rasteriza un archivo SVG a un array numpy RGBA para matplotlib."""
    svg_p = Path(svg_path)
    if not svg_p.exists() or not svg_p.is_file():
        return None

    # Si ya existe un PNG cacheado generado y actualizado
    png_cached = svg_p.with_suffix('.png')
    if png_cached.exists() and png_cached.stat().st_mtime >= svg_p.stat().st_mtime:
        try:
            from PIL import Image
            img = Image.open(png_cached).convert('RGBA')
            return np.array(img)
        except Exception:
            pass

    import subprocess
    import os
    from PIL import Image

    browser_binaries = [
        r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',
        r'C:\Program Files\Microsoft\Edge\Application\msedge.exe',
        r'C:\Program Files\Google\Chrome\Application\chrome.exe',
        r'C:\Program Files (x86)\Google\Chrome\Application\chrome.exe',
    ]

    selected_browser = None
    for b in browser_binaries:
        if os.path.exists(b):
            selected_browser = b
            break

    if selected_browser:
        html_temp = svg_p.parent / f"_temp_render_{svg_p.stem}.html"
        try:
            content = f"""<!DOCTYPE html>
<html>
<head>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ background: transparent; display: flex; align-items: center; justify-content: center; width: 1766px; height: 620px; overflow: hidden; }}
  img {{ width: 1766px; height: 620px; object-fit: contain; }}
</style>
</head>
<body>
  <img src="{svg_p.resolve().as_uri()}" />
</body>
</html>"""
            html_temp.write_text(content, encoding='utf-8')
            cmd = [
                selected_browser,
                '--headless=new',
                '--disable-gpu',
                '--default-background-color=00000000',
                '--window-size=1766,620',
                f'--screenshot={png_cached.resolve()}',
                html_temp.resolve().as_uri()
            ]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            if res.returncode == 0 and png_cached.exists():
                img = Image.open(png_cached).convert('RGBA')
                bbox = img.getbbox()
                if bbox:
                    img = img.crop(bbox)
                    img.save(png_cached)
                return np.array(img)
        except Exception:
            pass
        finally:
            if html_temp.exists():
                try:
                    html_temp.unlink()
                except Exception:
                    pass

    if png_cached.exists():
        try:
            from PIL import Image
            return np.array(Image.open(png_cached).convert('RGBA'))
        except Exception:
            pass

    return None


def _buscar_logo_img(logo_path: Optional[Union[str, Path]] = None):
    """Busca el archivo de logo más adecuado disponible (priorizando LOGO.svg de assets/)."""
    if logo_path and Path(logo_path).exists():
        p = Path(logo_path)
        if p.suffix.lower() == '.svg':
            svg_arr = _cargar_o_renderizar_svg(p)
            if svg_arr is not None:
                return svg_arr
        else:
            try:
                return plt.imread(p)
            except Exception:
                pass

    candidatos = [
        _ROOT_DIR / "assets" / "LOGO.svg",
        _ROOT_DIR / "assets" / "logo.svg",
        DEFAULT_LOGO_PATH,
        _ROOT_DIR / "assets" / "LOGO.png",
        _ROOT_DIR / "src" / "logonegro.png",
        _ROOT_DIR / "src" / "logo.png",
        _ROOT_DIR / "src" / "logoblanco.png",
    ]
    for p in candidatos:
        if p and Path(p).exists():
            if Path(p).suffix.lower() == '.svg':
                svg_arr = _cargar_o_renderizar_svg(p)
                if svg_arr is not None:
                    return svg_arr
            else:
                try:
                    return plt.imread(Path(p))
                except Exception:
                    pass
    return None


def _add_header(ax, logo_img, titulo: str, subtitulo: str):
    """Inserta LOGO.svg / LOGO.png a la izquierda y títulos estilizados a la derecha del logo."""
    ax.axis('off')
    if logo_img is None:
        logo_img = _buscar_logo_img(_ROOT_DIR / "assets" / "LOGO.svg")

    if logo_img is not None:
        # Proporción panorámica para logo Burgos BH (~2.8:1)
        ax_logo = ax.inset_axes([0.0, 0.05, 0.16, 0.90])
        ax_logo.axis('off')
        ax_logo.imshow(logo_img, aspect='equal')
        x_texto = 0.175
    else:
        x_texto = 0.0

    ax.text(
        x_texto, 0.65, titulo,
        transform=ax.transAxes,
        fontsize=16, fontweight='bold', va='center', color='#1e293b'
    )
    ax.text(
        x_texto, 0.25, subtitulo,
        transform=ax.transAxes,
        fontsize=9.5, color='#64748b', va='center'
    )


def _add_footer(fig, watermark_img=None, pagina_num: int = 1, total_paginas: int = 5):
    """Añade una barra de pie de página estilizada con la marca de agua del logo negro (logonegro.png)."""
    ax_footer = fig.add_axes([0.04, 0.006, 0.92, 0.035])
    ax_footer.axis('off')

    # Línea divisoria superior del pie de página
    ax_footer.plot([0.0, 1.0], [0.95, 0.95], transform=ax_footer.transAxes, color='#e2e8f0', linewidth=1.0)

    # Texto a la izquierda
    ax_footer.text(
        0.0, 0.35,
        "Burgos Burpellet BH Pro Team  •  Intervals Fit Analytics Suite",
        transform=ax_footer.transAxes,
        fontsize=8.5, color='#64748b', va='center'
    )

    # Numeración de página en el centro
    ax_footer.text(
        0.5, 0.35,
        f"Página {pagina_num} de {total_paginas}",
        transform=ax_footer.transAxes,
        fontsize=8.5, fontweight='bold', color='#94a3b8', ha='center', va='center'
    )

    # Marca de agua con logonegro.png a la derecha
    if watermark_img is None:
        watermark_img = _buscar_logo_img(_ROOT_DIR / "src" / "logonegro.png")

    if watermark_img is not None:
        ax_wm = ax_footer.inset_axes([0.86, 0.05, 0.13, 0.90])
        ax_wm.axis('off')
        ax_wm.imshow(watermark_img, aspect='equal', alpha=0.8)


def _ajustar_anchos_tabla(table, tabla_df: pd.DataFrame):
    """Calcula anchos proporcionados a los contenidos para que la tabla sea legible."""
    pesos = [max(10, len(str(tabla_df.index.name or 'potencia')) + 2)]
    for columna in tabla_df.columns:
        col_str = str(columna[0] if isinstance(columna, tuple) else columna)
        max_contenido = max(tabla_df[columna].map(len).max() if not tabla_df.empty else 0, len(col_str))
        pesos.append(max(12, max_contenido + 2))

    ancho_total = 0.98
    escala = ancho_total / sum(pesos)
    anchos = [peso * escala for peso in pesos]

    for fila in range(1, len(tabla_df.index) + 1):
        if (fila, -1) in table._cells:
            table[(fila, -1)].set_width(anchos[0])

    for col_idx in range(len(tabla_df.columns)):
        if (0, col_idx) in table._cells:
            table[(0, col_idx)].set_width(anchos[col_idx + 1])
        for fila in range(1, len(tabla_df.index) + 1):
            if (fila, col_idx) in table._cells:
                table[(fila, col_idx)].set_width(anchos[col_idx + 1])


def generar_informe_potencias_y_carga(
    peaks_df: pd.DataFrame,
    tabla_peaks: pd.DataFrame,
    metrics_df: pd.DataFrame,
    output_pdf: Optional[Union[str, Path]] = None,
    logo_path: Optional[Union[str, Path]] = None,
) -> Path:
    """
    Genera el PDF de 2 páginas con el informe de picos de potencia y evolución de carga (CTL/ATL).
    """
    output_pdf = Path(output_pdf or (OUTPUT_DIR / 'intervals_informe.pdf'))
    logo_img = _buscar_logo_img(logo_path or (_ROOT_DIR / "assets" / "LOGO.svg"))
    watermark_img = _buscar_logo_img(_ROOT_DIR / "src" / "logonegro.png")

    orden_duraciones = ['5s', '30s', '1m', '5m', '10m', '20m']
    plot_df = peaks_df.dropna(subset=['peak_wkg']).copy() if not peaks_df.empty else pd.DataFrame()

    pivot_pdf = pd.DataFrame()
    if not plot_df.empty:
        pivot_pdf = plot_df.pivot_table(
            index='duration_label',
            columns='athlete_name',
            values='peak_wkg',
            aggfunc='max'
        ).reindex(orden_duraciones)

    tabla_pdf = tabla_peaks.fillna('').astype(str) if not tabla_peaks.empty else pd.DataFrame()

    nombres_metricas = sorted(metrics_df['athlete_name'].dropna().unique()) if not metrics_df.empty else []
    palette = plt.cm.tab20.colors if len(nombres_metricas) > 10 else plt.cm.tab10.colors
    color_map_pdf = {
        nombre: palette[i % len(palette)]
        for i, nombre in enumerate(nombres_metricas)
    }

    def crear_pagina_potencias(pdf):
        cols_count = len(tabla_pdf.columns) if not tabla_pdf.empty else 5
        fig_ancho = max(17, 7 + cols_count * 1.5)
        fig_alto = max(12, 7 + len(tabla_pdf.index) * 0.6)

        fig = plt.figure(figsize=(fig_ancho, fig_alto))
        fig.set_layout_engine('constrained', rect=[0, 0.045, 1, 1])
        fig.patch.set_facecolor('#f8fafc')
        gs = fig.add_gridspec(3, 1, height_ratios=[0.8, 3.3, 2.5])

        ax_hdr = fig.add_subplot(gs[0])
        _add_header(ax_hdr, logo_img, 'Informe de Potencias', 'Gráfico de picos relativos y tabla resumen')

        ax_plot = fig.add_subplot(gs[1])
        if not pivot_pdf.empty:
            pivot_pdf.plot(kind='bar', ax=ax_plot, width=0.85)
            ax_plot.set_title('Mejores picos de potencia relativos - últimos 30 días', fontsize=12, fontweight='bold')
            ax_plot.set_xlabel('Duración')
            ax_plot.set_ylabel('Potencia relativa (W/kg)')
            ax_plot.grid(axis='y', alpha=0.3)
            ax_plot.tick_params(axis='x', rotation=0)
            ax_plot.legend(title='Ciclista', bbox_to_anchor=(0.5, -0.15), loc='upper center')

        ax_tbl = fig.add_subplot(gs[2])
        ax_tbl.axis('off')
        ax_tbl.set_title('Tabla Comparativa de Potencias', fontsize=13, pad=12)

        if not tabla_pdf.empty:
            table = ax_tbl.table(
                cellText=tabla_pdf.values,
                rowLabels=tabla_pdf.index.tolist(),
                colLabels=[f"{c[0]}\n({c[1]})" if isinstance(c, tuple) else str(c) for c in tabla_pdf.columns],
                loc='center',
                cellLoc='center'
            )
            table.auto_set_font_size(False)
            table.set_fontsize(8.5)
            table.scale(1, 1.45)
            _ajustar_anchos_tabla(table, tabla_pdf)

        _add_footer(fig, watermark_img=watermark_img, pagina_num=1, total_paginas=2)
        pdf.savefig(fig, bbox_inches='tight')
        plt.close(fig)

    def crear_pagina_carga(pdf):
        if metrics_df.empty:
            return

        fig = plt.figure(figsize=(16, 11))
        fig.set_layout_engine('constrained', rect=[0, 0.045, 1, 1])
        fig.patch.set_facecolor('#f8fafc')
        gs = fig.add_gridspec(4, 1, height_ratios=[0.7, 1.8, 1.8, 1.8])

        ax_hdr = fig.add_subplot(gs[0])
        _add_header(ax_hdr, logo_img, 'Informe de Carga, Fatiga y Forma', 'Evolución de CTL, ATL y TSB (Zonas de Forma) por ciclista')

        # Panel CTL
        ax_ctl = fig.add_subplot(gs[1])
        for nombre, g in metrics_df.groupby('athlete_name'):
            g_sorted = g.sort_values('fecha').reset_index(drop=True)
            g_sem = g_sorted.iloc[::7].copy()
            last_row = g_sorted.iloc[-1]
            final_ctl = last_row['ctl']
            color = color_map_pdf.get(nombre, '#3b82f6')

            ax_ctl.plot(g_sorted['fecha'], g_sorted['ctl'], linewidth=2, color=color, label=f"{nombre} (Final: {final_ctl:.1f})")
            ax_ctl.plot(g_sem['fecha'], g_sem['ctl'], marker='o', markersize=4.5, linestyle='', color=color)
            ax_ctl.plot(last_row['fecha'], final_ctl, marker='o', markersize=6.5, color=color)
            ax_ctl.annotate(f" {final_ctl:.0f}", (last_row['fecha'], final_ctl), textcoords="offset points", xytext=(4, -2), fontsize=7.5, fontweight='bold', color=color, va='center')
            for _, row in g_sem.iterrows():
                ax_ctl.annotate(f"{row['ctl']:.0f}", (row['fecha'], row['ctl']), textcoords="offset points", xytext=(0, 4), fontsize=6.5, color=color, ha='center', alpha=0.85)

        ax_ctl.set_title('CTL por Ciclista (Forma / Fitness acumulado)', fontsize=11, fontweight='bold')
        ax_ctl.set_ylabel('CTL')
        ax_ctl.grid(True, alpha=0.3)
        ax_ctl.legend(title='Ciclista (CTL Final)', bbox_to_anchor=(0.5, -0.15), loc='upper center', fontsize=7.5, frameon=True, facecolor='#ffffff', edgecolor='#cbd5e1', ncol=3)

        # Panel ATL
        ax_atl = fig.add_subplot(gs[2], sharex=ax_ctl)
        for nombre, g in metrics_df.groupby('athlete_name'):
            g_sorted = g.sort_values('fecha').reset_index(drop=True)
            g_sem = g_sorted.iloc[::7].copy()
            last_row = g_sorted.iloc[-1]
            final_atl = last_row['atl']
            color = color_map_pdf.get(nombre, '#3b82f6')

            ax_atl.plot(g_sorted['fecha'], g_sorted['atl'], linewidth=2, linestyle='--', color=color, label=f"{nombre} (Final: {final_atl:.1f})")
            ax_atl.plot(g_sem['fecha'], g_sem['atl'], marker='s', markersize=4.5, linestyle='', color=color)
            ax_atl.plot(last_row['fecha'], final_atl, marker='s', markersize=6.5, color=color)
            ax_atl.annotate(f" {final_atl:.0f}", (last_row['fecha'], final_atl), textcoords="offset points", xytext=(4, -2), fontsize=7.5, fontweight='bold', color=color, va='center')
            for _, row in g_sem.iterrows():
                ax_atl.annotate(f"{row['atl']:.0f}", (row['fecha'], row['atl']), textcoords="offset points", xytext=(0, 4), fontsize=6.5, color=color, ha='center', alpha=0.85)

        ax_atl.set_title('ATL por Ciclista (Fatiga aguda)', fontsize=11, fontweight='bold')
        ax_atl.set_ylabel('ATL')
        ax_atl.grid(True, alpha=0.3)
        ax_atl.legend(title='Ciclista (ATL Final)', bbox_to_anchor=(0.5, -0.15), loc='upper center', fontsize=7.5, frameon=True, facecolor='#ffffff', edgecolor='#cbd5e1', ncol=3)

        # Panel TSB (Forma y Zonas Fisiológicas de Fondo)
        ax_tsb = fig.add_subplot(gs[3], sharex=ax_ctl)
        ax_tsb.axhspan(15, 60, color='#10b981', alpha=0.14, zorder=1)
        ax_tsb.axhspan(5, 15, color='#38bdf8', alpha=0.14, zorder=1)
        ax_tsb.axhspan(-10, 5, color='#818cf8', alpha=0.08, zorder=1)
        ax_tsb.axhspan(-30, -10, color='#f59e0b', alpha=0.14, zorder=1)
        ax_tsb.axhspan(-70, -30, color='#ef4444', alpha=0.14, zorder=1)
        ax_tsb.axhline(0, color='#64748b', linestyle=':', linewidth=0.9, alpha=0.7, zorder=1)

        ax_tsb.text(0.99, 0.92, "Muy Fresco (> +15)", transform=ax_tsb.transAxes, ha='right', va='center', fontsize=7.0, fontweight='bold', color='#059669', alpha=0.9)
        ax_tsb.text(0.99, 0.75, "Fresco / Competición (+5 a +15)", transform=ax_tsb.transAxes, ha='right', va='center', fontsize=7.0, fontweight='bold', color='#0284c7', alpha=0.9)
        ax_tsb.text(0.99, 0.55, "Neutro / Balance (-10 a +5)", transform=ax_tsb.transAxes, ha='right', va='center', fontsize=7.0, fontweight='bold', color='#6366f1', alpha=0.9)
        ax_tsb.text(0.99, 0.35, "Fatiga Productiva (-30 a -10)", transform=ax_tsb.transAxes, ha='right', va='center', fontsize=7.0, fontweight='bold', color='#d97706', alpha=0.9)
        ax_tsb.text(0.99, 0.12, "Sobrecarga (< -30)", transform=ax_tsb.transAxes, ha='right', va='center', fontsize=7.0, fontweight='bold', color='#dc2626', alpha=0.9)

        for nombre, g in metrics_df.groupby('athlete_name'):
            g_sorted = g.sort_values('fecha').reset_index(drop=True)
            if 'tsb' in g_sorted.columns:
                g_sem = g_sorted.iloc[::7].copy()
                last_row = g_sorted.iloc[-1]
                final_tsb = last_row['tsb']
                color = color_map_pdf.get(nombre, '#3b82f6')

                ax_tsb.plot(g_sorted['fecha'], g_sorted['tsb'], linewidth=2, color=color, zorder=3, label=f"{nombre} (TSB: {final_tsb:+.1f})")
                ax_tsb.plot(g_sem['fecha'], g_sem['tsb'], marker='^', markersize=4.5, linestyle='', color=color, zorder=4)
                ax_tsb.plot(last_row['fecha'], final_tsb, marker='^', markersize=6.5, color=color, zorder=4)
                ax_tsb.annotate(f" {final_tsb:+.0f}", (last_row['fecha'], final_tsb), textcoords="offset points", xytext=(4, -2), fontsize=7.5, fontweight='bold', color=color, va='center')

        ax_tsb.set_ylim(-45, 35)
        ax_tsb.set_title('TSB por Ciclista (Zonas de Forma / Balance de Entrenamiento)', fontsize=11, fontweight='bold')
        ax_tsb.set_xlabel('Fecha')
        ax_tsb.set_ylabel('TSB')
        ax_tsb.grid(True, alpha=0.25)
        ax_tsb.legend(title='Ciclista (TSB Final)', bbox_to_anchor=(0.5, -0.15), loc='upper center', fontsize=7.5, frameon=True, facecolor='#ffffff', edgecolor='#cbd5e1', ncol=3)

        _add_footer(fig, watermark_img=watermark_img, pagina_num=2, total_paginas=2)
        pdf.savefig(fig, bbox_inches='tight')
        plt.close(fig)

    output_pdf.parent.mkdir(parents=True, exist_ok=True)
    try:
        with PdfPages(output_pdf) as pdf:
            crear_pagina_potencias(pdf)
            crear_pagina_carga(pdf)
    except PermissionError:
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        output_pdf = output_pdf.parent / f"{output_pdf.stem}_{timestamp}.pdf"
        with PdfPages(output_pdf) as pdf:
            crear_pagina_potencias(pdf)
            crear_pagina_carga(pdf)

    return output_pdf


def generar_informe_wellness_hrv(
    wellness_df: pd.DataFrame,
    output_pdf: Optional[Union[str, Path]] = None,
    logo_path: Optional[Union[str, Path]] = None
) -> Path:
    """
    Genera el informe en PDF de 2 páginas con la tabla de resumen y el gráfico
    de evolución temporal de HRV (RMSSD) y peso.
    """
    output_pdf = Path(output_pdf or (OUTPUT_DIR / 'wellness_evolucion.pdf'))
    logo_img = _buscar_logo_img(logo_path or (_ROOT_DIR / "assets" / "LOGO.svg"))
    watermark_img = _buscar_logo_img(_ROOT_DIR / "src" / "logonegro.png")

    if wellness_df.empty:
        raise ValueError("El DataFrame de wellness está vacío. No se puede generar el informe.")

    df = wellness_df.copy()
    df['date'] = pd.to_datetime(df['date'])
    df = df.sort_values(by=['athlete_name', 'date'])

    fecha_min = df['date'].min().strftime('%d/%b/%Y')
    fecha_max = df['date'].max().strftime('%d/%b/%Y')

    def crear_pagina_resumen(pdf):
        fig, ax = plt.subplots(figsize=(11, 8.5))
        fig.set_layout_engine('constrained', rect=[0, 0.045, 1, 1])
        ax.axis('off')
        fig.patch.set_facecolor('#f8fafc')

        # Título
        plt.text(0.5, 0.92, 'INFORME DE BIENESTAR (WELLNESS) DE ATLETAS',
                 transform=ax.transAxes, fontsize=18, fontweight='bold', ha='center', color='#1e293b')
        plt.text(0.5, 0.87, f'Histórico de HRV y Peso ({fecha_min} - {fecha_max}) | Generado: {datetime.now().strftime("%Y-%m-%d")}',
                 transform=ax.transAxes, fontsize=11, style='italic', ha='center', color='#64748b')

        stats = []
        for name, group in df.groupby('athlete_name'):
            records_count = len(group)
            hrv_group = group[group['hrv_rmssd'].notnull()]
            avg_hrv = round(hrv_group['hrv_rmssd'].mean(), 1) if not hrv_group.empty else '-'
            min_hrv = round(hrv_group['hrv_rmssd'].min(), 1) if not hrv_group.empty else '-'
            max_hrv = round(hrv_group['hrv_rmssd'].max(), 1) if not hrv_group.empty else '-'

            weight_group = group[group['weight'].notnull()]
            last_weight = round(weight_group.iloc[-1]['weight'], 1) if not weight_group.empty else '-'

            stats.append([name, records_count, avg_hrv, f"{min_hrv} - {max_hrv}", last_weight])

        headers = ['Ciclista', 'Días con Datos', 'Media HRV (RMSSD)', 'Rango HRV (RMSSD)', 'Último Peso (kg)']
        table = plt.table(
            cellText=stats, colLabels=headers, loc='center', cellLoc='center',
            colWidths=[0.28, 0.15, 0.18, 0.20, 0.18]
        )
        table.auto_set_font_size(False)
        table.set_fontsize(11)
        table.scale(1.1, 2.2)

        for (row, col), cell in table.get_celld().items():
            if row == 0:
                cell.set_text_props(weight='bold', color='white')
                cell.set_facecolor('#1e293b')
            else:
                cell.set_facecolor('#ffffff')
                cell.set_edgecolor('#cbd5e1')
                if row % 2 == 0:
                    cell.set_facecolor('#f1f5f9')

        _add_footer(fig, watermark_img=watermark_img, pagina_num=1, total_paginas=2)
        pdf.savefig(fig, bbox_inches='tight')
        plt.close(fig)

    def crear_pagina_grafico(pdf):
        fig, ax = plt.subplots(figsize=(11, 8.5))
        fig.set_layout_engine('constrained', rect=[0, 0.045, 1, 1])
        fig.patch.set_facecolor('#f8fafc')
        ax.set_facecolor('#ffffff')

        colors = ['#0ea5e9', '#d946ef', '#8b5cf6', '#f59e0b', '#10b981', '#ef4444', '#06b6d4', '#6366f1']
        color_idx = 0

        for name, group in df.groupby('athlete_name'):
            hrv_data = group[group['hrv_rmssd'].notnull()]
            if not hrv_data.empty:
                color = colors[color_idx % len(colors)]
                ax.plot(hrv_data['date'], hrv_data['hrv_rmssd'], marker='o', markersize=4,
                        linewidth=2, label=name, color=color)
                color_idx += 1

        ax.set_title('Evolución de HRV (RMSSD) por Ciclista', fontsize=16, fontweight='bold', pad=20, color='#1e293b')
        ax.set_xlabel('Fecha', fontsize=11, fontweight='bold', labelpad=10, color='#475569')
        ax.set_ylabel('HRV RMSSD (ms)', fontsize=11, fontweight='bold', labelpad=10, color='#475569')
        ax.grid(True, linestyle='--', alpha=0.5, color='#cbd5e1')

        for spine in ['top', 'right']:
            ax.spines[spine].set_visible(False)
        for spine in ['left', 'bottom']:
            ax.spines[spine].set_color('#94a3b8')

        ax.legend(bbox_to_anchor=(0.5, -0.15), loc='upper center', frameon=True, facecolor='#ffffff', edgecolor='#cbd5e1', ncol=2)
        fig.autofmt_xdate()

        _add_footer(fig, watermark_img=watermark_img, pagina_num=2, total_paginas=2)

        pdf.savefig(fig, bbox_inches='tight')
        plt.close(fig)

    output_pdf.parent.mkdir(parents=True, exist_ok=True)
    try:
        with PdfPages(output_pdf) as pdf:
            crear_pagina_resumen(pdf)
            crear_pagina_grafico(pdf)
    except PermissionError:
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        output_pdf = output_pdf.parent / f"{output_pdf.stem}_{timestamp}.pdf"
        with PdfPages(output_pdf) as pdf:
            crear_pagina_resumen(pdf)
            crear_pagina_grafico(pdf)

    return output_pdf


def generar_informe_etapa_pdf(
    etapa_info: Dict[str, Any],
    ciclistas_proc: List[Dict[str, Any]],
    wellness_carga_map: Optional[Dict[str, Any]] = None,
    titulo: Optional[str] = None,
    subtitulo: Optional[str] = None,
    output_pdf: Optional[Union[str, Path]] = None,
    logo_path: Optional[Union[str, Path]] = None,
) -> Path:
    """
    Genera el informe ejecutivo en PDF multipágina de la etapa con la siguiente estructura:
    1. Resumen de la etapa (KPIs, clasificación general, tabla de rendimiento y desglose horario).
    2. Gráficos de la comparativa de telemetría separados por tipo de datos:
       - Altimetría y perfil de relieve
       - Potencia (W)
       - Potencia Relativa (W/kg)
       - Frecuencia Cardíaca (bpm / ppm)
       - Trabajo Acumulado (kJ y kJ/kg)
       - Demanda Metabólica (kJ/kg/h)
       - Estrés Acumulado (TSS)
       - Velocidad de Carrera (km/h)
    3. Datos de Fisiología, Biometría y Carga de Entrenamiento:
       - Tabla de estado de forma, HRV, FC reposo y peso en la fecha de la etapa.
       - Gráfico de evolución temporal de carga (CTL/ATL/TSB) en los últimos 30 días.
       - Gráfico de evolución de HRV (RMSSD) y FC de Reposo.
    """
    if not ciclistas_proc:
        raise ValueError("No hay ciclistas procesados para generar el informe PDF.")

    logo_img = _buscar_logo_img(logo_path or (_ROOT_DIR / "assets" / "LOGO.svg"))
    watermark_img = _buscar_logo_img(_ROOT_DIR / "src" / "logonegro.png")

    # Determinar fecha y nombres
    dist_total = etapa_info.get('distancia_total_km', 0.0)
    desn_total = etapa_info.get('desnivel_pos_m', 0)
    alt_max = etapa_info.get('altitud_max', 0)

    fecha_etapa = ""
    for c in ciclistas_proc:
        if 'df_gps' in c and not c['df_gps'].empty and 'timestamp' in c['df_gps'].columns:
            ts = c['df_gps']['timestamp'].iloc[0]
            if pd.notna(ts):
                fecha_etapa = ts.strftime('%Y-%m-%d')
                break
    if not fecha_etapa:
        fecha_etapa = datetime.now().strftime('%Y-%m-%d')

    titulo_doc = titulo or f"Etapa {dist_total:.1f} km (+{desn_total}m D+)"
    subtitulo_doc = subtitulo or f"Fecha: {fecha_etapa}"

    output_pdf = Path(output_pdf or (OUTPUT_DIR / f"etapa_{fecha_etapa}.pdf"))

    # =========================================================================
    # PÁGINA 1: RESUMEN DE LA ETAPA (STAGE SUMMARY)
    # =========================================================================
    def _crear_pagina_resumen_etapa(pdf):
        fig = plt.figure(figsize=(16.5, 11.7))
        fig.set_layout_engine('constrained', rect=[0, 0.045, 1, 1])
        fig.patch.set_facecolor('#f8fafc')
        gs = fig.add_gridspec(4, 1, height_ratios=[0.9, 0.7, 3.2, 3.0])

        # Encabezado
        ax_hdr = fig.add_subplot(gs[0])
        _add_header(ax_hdr, logo_img, f"RESUMEN DE ETAPA - {titulo_doc}", subtitulo_doc)

        # Barra de KPIs Globales de Equipo
        ax_kpi = fig.add_subplot(gs[1])
        ax_kpi.axis('off')

        #np_vals = [c['stats']['np_w'] for c in ciclistas_proc if c['stats'].get('np_w', 0) > 0]
       #tss_vals = [c['stats']['tss_total'] for c in ciclistas_proc if c['stats'].get('tss_total', 0) > 0]
       #if_vals = [c['stats']['if_val'] for c in ciclistas_proc if c['stats'].get('if_val', 0) > 0]
       #kj_vals = [c['stats']['kilojulios_total'] for c in ciclistas_proc if c['stats'].get('kilojulios_total', 0) > 0]
       #kjkg_h_vals = [c['stats']['kj_kg_hora'] for c in ciclistas_proc if c['stats'].get('kj_kg_hora', 0) > 0]
      ##
     # np_med = int(round(np.mean(np_vals))) if np_vals else 0
     #  tss_med = int(round(np.mean(tss_vals))) if tss_vals else 0
    #if_med = round(float(np.mean(if_vals)), 2) if if_vals else 0.0
     #  kj_sum = int(round(np.sum(kj_vals))) if kj_vals else 0
     #  kjkg_h_med = round(float(np.mean(kjkg_h_vals)), 1) if kjkg_h_vals else 0.0
##
        kpis = [
            ("CORREDORES", f"{len(ciclistas_proc)}"),
            ("DISTANCIA", f"{dist_total:.1f} km"),
            ("DESNIVEL +", f"{desn_total} m")
           #("NP EQUIPO", f"{np_med} W"),
           #("TSS MEDIO", f"{tss_med}"),
           #("IF MEDIO", f"{if_med:.2f}"),
           #("TRABAJO TOTAL", f"{kj_sum} kJ"),
           #("TASA METABÓLICA", f"{kjkg_h_med} kJ/kg/h"),
        ]

        n_kpis = len(kpis)
        for i, (lbl, val) in enumerate(kpis):
            x_pos = (i + 0.5) / n_kpis
            bbox_props = dict(boxstyle='round,pad=0.5', facecolor='#ffffff', edgecolor='#e2e8f0', linewidth=1.2)
            ax_kpi.text(x_pos, 0.65, val, transform=ax_kpi.transAxes, fontsize=13, fontweight='bold', ha='center', va='center', color='#0f172a', bbox=bbox_props)
            ax_kpi.text(x_pos, 0.15, lbl, transform=ax_kpi.transAxes, fontsize=7.5, fontweight='bold', ha='center', va='center', color='#64748b')

        # Tabla 1: Clasificación y Rendimiento
        ax_tbl1 = fig.add_subplot(gs[2])
        ax_tbl1.axis('off')
        ax_tbl1.text(0.0, 1.05, "Clasificación y Métricas Principales de la Etapa", transform=ax_tbl1.transAxes, fontsize=12, fontweight='bold', color='#1e293b')

        filas_t1 = []
        for c in ciclistas_proc:
            st = c['stats']
            filas_t1.append([
                st.get('posicion_str', '-'),
                st.get('nombre', '-'),
                st.get('tiempo_total_str', '-'),
                f"{st.get('pot_media_w', 0)} W",
                f"{st.get('w_kg_media', 0):.2f}",
                f"{st.get('np_w', 0)} W ({st.get('if_val', 0):.2f})",
                f"{st.get('tss_total', 0)} ({st.get('tss_hora', 0):.1f}/h)",
                f"{st.get('kilojulios_total', 0)} kJ",
                f"{st.get('kj_kg', 0):.1f}",
                f"{st.get('fc_media_bpm', 0)} bpm",
                f"{st.get('vel_media_kmh', 0):.1f} km/h",
            ])

        cols_t1 = [
            "Pos", "Ciclista", "Tiempo", "Pot Med", "W/kg",
            "NP (IF)", "TSS (TSS/h)", "Trabajo", "kJ/kg", "FC Med", "Vel Med"
        ]
        
        t1 = ax_tbl1.table(cellText=filas_t1, colLabels=cols_t1, loc='center', cellLoc='center')
        t1.auto_set_font_size(False)
        t1.set_fontsize(9.0)
        t1.scale(1.0, 1.5)

        for (r, col), cell in t1.get_celld().items():
            if r == 0:
                cell.set_text_props(weight='bold', color='white')
                cell.set_facecolor('#1e293b')
            else:
                cell.set_facecolor('#ffffff' if r % 2 != 0 else '#f1f5f9')
                cell.set_edgecolor('#cbd5e1')
                if col == 1:
                    cell.set_text_props(weight='bold', color='#0f172a', ha='left')
                elif col == 0:
                    cell.set_text_props(weight='bold', color='#3b82f6')

        # Tabla 2: Desglose Horario / Demanda y Ritmo Energético
        ax_tbl2 = fig.add_subplot(gs[3])
        ax_tbl2.axis('off')
        ax_tbl2.text(0.0, 1.05, "Ritmo Energético y Demanda Metabólica por Franja Horaria (kJ / kg / h)", transform=ax_tbl2.transAxes, fontsize=12, fontweight='bold', color='#1e293b')

        # Determinar número máximo de horas entre todos los ciclistas
        max_horas = 0
        for c in ciclistas_proc:
            desglose = c.get('desglose_horas', [])
            if len(desglose) > max_horas:
                max_horas = len(desglose)

        if max_horas > 0:
            cols_t2 = ["Ciclista"] + [f"Hora {i+1}" for i in range(max_horas)]
            filas_t2 = []
            for c in ciclistas_proc:
                nom = c['stats']['nombre']
                desglose_dict = {h.get('hora_num', idx + 1): h for idx, h in enumerate(c.get('desglose_horas', []))}
                fila = [nom]
                for h_idx in range(1, max_horas + 1):
                    if h_idx in desglose_dict:
                        h = desglose_dict[h_idx]
                        fc_str = f"{h['fc_media']} bpm | " if h.get('fc_media') else ""
                        celda = (
                            f"{h.get('pot_media_w', 0)} W ({h.get('w_kg', 0):.2f} W/kg)\n"
                            f"{h.get('kj_kg_h', 0):.1f} kJ/kg/h ({h.get('kj_total', 0)} kJ)\n"
                            f"NP: {h.get('np_w', 0)} W | {fc_str}{h.get('distancia_km', 0):.1f} km"
                        )
                    else:
                        celda = "-"
                    fila.append(celda)
                filas_t2.append(fila)

            t2 = ax_tbl2.table(cellText=filas_t2, colLabels=cols_t2, loc='center', cellLoc='center')
            t2.auto_set_font_size(False)
            t2.set_fontsize(7.8)
            n_rows = len(filas_t2)
            row_scale = 1.9 if n_rows <= 3 else (1.6 if n_rows <= 5 else 1.3)
            t2.scale(1.0, row_scale)

            for (r, col), cell in t2.get_celld().items():
                if r == 0:
                    cell.set_text_props(weight='bold', color='white')
                    cell.set_facecolor('#334155')
                else:
                    cell.set_facecolor('#ffffff' if r % 2 != 0 else '#f8fafc')
                    cell.set_edgecolor('#e2e8f0')
                    if col == 0:
                        cell.set_text_props(weight='bold', color='#0f172a', ha='left')
        else:
            ax_tbl2.text(0.5, 0.5, "Información horaria no disponible para esta actividad.", transform=ax_tbl2.transAxes, ha='center', va='center', color='#94a3b8')

        _add_footer(fig, watermark_img=watermark_img, pagina_num=1, total_paginas=6)
        pdf.savefig(fig, bbox_inches='tight')
        plt.close(fig)

    # =========================================================================
    # PÁGINAS DE GRÁFICOS COMPARATIVOS POR TIPO DE DATOS
    # =========================================================================
    perfil = etapa_info.get('perfil_altimetria', [])
    d_x_etapa = np.array([p['x'] for p in perfil]) if perfil else np.array([])
    alt_y_etapa = np.array([p['y'] for p in perfil]) if perfil else np.array([])

    def _dibujar_perfil_fondo(ax):
        """Dibuja el perfil altimétrico de la etapa suavizado y coloreado en el fondo del gráfico."""
        if len(d_x_etapa) == 0 or len(alt_y_etapa) == 0:
            return None
        ax_bg = ax.twinx()
        min_alt = float(np.nanmin(alt_y_etapa))
        max_alt = float(np.nanmax(alt_y_etapa))
        rango = max_alt - min_alt if max_alt > min_alt else 100.0
        base_alt = max(0.0, min_alt - rango * 0.1)

        # Sombreado de altimetría en fondo (verde esmeralda suave / relieve)
        ax_bg.fill_between(d_x_etapa, alt_y_etapa, base_alt, color='#10b981', alpha=0.16, zorder=1)
        ax_bg.plot(d_x_etapa, alt_y_etapa, color='#059669', linewidth=1.1, alpha=0.35, zorder=1)

        # Configurar escala vertical para que la montaña quede en el fondo inferior y no tape las curvas
        ax_bg.set_ylim(bottom=base_alt, top=max_alt + rango * 1.6)
        ax_bg.set_ylabel("Altitud (m)", color='#64748b', fontsize=8.0, fontweight='bold', labelpad=6)
        ax_bg.tick_params(axis='y', labelcolor='#64748b', labelsize=7.5)
        ax_bg.grid(False)

        # Poner el eje principal (telemetría) al frente
        ax.set_zorder(ax_bg.get_zorder() + 1)
        ax.patch.set_visible(False)
        return ax_bg

    def _configurar_ejes_comparativa(ax, title: str, ylabel: str, xlabel: str = "Distancia (km)"):
        ax.set_title(title, fontsize=13, fontweight='bold', color='#1e293b', pad=10)
        ax.set_xlabel(xlabel, fontsize=10, fontweight='bold', color='#475569')
        ax.set_ylabel(ylabel, fontsize=10, fontweight='bold', color='#475569')
        ax.grid(True, linestyle='--', alpha=0.45, color='#cbd5e1')
        ax.set_facecolor('#ffffff')
        for spine in ['top']:
            ax.spines[spine].set_visible(False)
        for spine in ['left', 'bottom', 'right']:
            ax.spines[spine].set_color('#94a3b8')

    def _crear_pagina_graficos_1(pdf):
        """Página 2: 1. Potencia Absoluta (W) y 2. Potencia Relativa (W/kg) con perfil de fondo"""
        fig = plt.figure(figsize=(16.5, 11.7))
        fig.set_layout_engine('constrained', rect=[0, 0.045, 1, 1])
        fig.patch.set_facecolor('#f8fafc')
        gs = fig.add_gridspec(3, 1, height_ratios=[0.7, 3.5, 3.5])

        ax_hdr = fig.add_subplot(gs[0])
        _add_header(ax_hdr, logo_img, "Comparativa de Telemetría (1/3)", f"{titulo_doc} | Potencia Absoluta (W) y Potencia Relativa (W/kg) con Relieve Altimétrico")

        # 1. Potencia Absoluta W
        ax_pwr = fig.add_subplot(gs[1])
        _dibujar_perfil_fondo(ax_pwr)
        for c in ciclistas_proc:
            samples = c.get('samples_by_dist', [])
            if not samples:
                continue
            xs = [s['d_km'] for s in samples]
            ys = [s['pwr'] for s in samples]
            nom = c['stats']['nombre']
            col = c['stats']['color']
            p_med = c['stats'].get('pot_media_w', 0)
            np_val = c['stats'].get('np_w', 0)
            ax_pwr.plot(xs, ys, color=col, linewidth=1.8, zorder=4, label=f"{nom} (Media: {p_med} W | NP: {np_val} W)")

        _configurar_ejes_comparativa(ax_pwr, "1. Comparativa de Potencia Absoluta (Vatios)", "Potencia (W)")
        ax_pwr.legend(bbox_to_anchor=(0.5, -0.15), loc='upper center', frameon=True, facecolor='#ffffff', edgecolor='#cbd5e1', fontsize=8.5, ncol=2)

        # 2. Potencia Relativa W/kg
        ax_wkg = fig.add_subplot(gs[2], sharex=ax_pwr)
        _dibujar_perfil_fondo(ax_wkg)
        for c in ciclistas_proc:
            samples = c.get('samples_by_dist', [])
            if not samples:
                continue
            xs = [s['d_km'] for s in samples]
            ys = [s['wkg'] for s in samples]
            nom = c['stats']['nombre']
            col = c['stats']['color']
            wkg_med = c['stats'].get('w_kg_media', 0.0)
            ax_wkg.plot(xs, ys, color=col, linewidth=1.8, zorder=4, label=f"{nom} (Media: {wkg_med:.2f} W/kg)")

        ax_wkg.axhline(4.0, color='#94a3b8', linestyle=':', linewidth=1.0, alpha=0.7, zorder=3, label='Referencia 4.0 W/kg')
        ax_wkg.axhline(5.0, color='#f59e0b', linestyle=':', linewidth=1.0, alpha=0.7, zorder=3, label='Referencia 5.0 W/kg')
        _configurar_ejes_comparativa(ax_wkg, "2. Comparativa de Potencia Relativa al Peso (W / kg)", "W / kg")
        ax_wkg.legend(bbox_to_anchor=(0.5, -0.15), loc='upper center', frameon=True, facecolor='#ffffff', edgecolor='#cbd5e1', fontsize=8.5, ncol=2)

        _add_footer(fig, watermark_img=watermark_img, pagina_num=2, total_paginas=6)
        pdf.savefig(fig, bbox_inches='tight')
        plt.close(fig)

    def _crear_pagina_graficos_2(pdf):
        """Página 3: 3. Frecuencia Cardíaca (ppm) y 4. Trabajo Mecánico Acumulado (kJ) con perfil de fondo"""
        fig = plt.figure(figsize=(16.5, 11.7))
        fig.set_layout_engine('constrained', rect=[0, 0.045, 1, 1])
        fig.patch.set_facecolor('#f8fafc')
        gs = fig.add_gridspec(3, 1, height_ratios=[0.7, 3.5, 3.5])

        ax_hdr = fig.add_subplot(gs[0])
        _add_header(ax_hdr, logo_img, "Comparativa de Telemetría (2/3)", f"{titulo_doc} | Frecuencia Cardíaca (bpm) y Trabajo Mecánico Acumulado (kJ) con Relieve Altimétrico")

        # 3. FC (ppm)
        ax_hr = fig.add_subplot(gs[1])
        _dibujar_perfil_fondo(ax_hr)
        for c in ciclistas_proc:
            samples = c.get('samples_by_dist', [])
            if not samples:
                continue
            xs = [s['d_km'] for s in samples]
            ys = [s['hr'] for s in samples]
            nom = c['stats']['nombre']
            col = c['stats']['color']
            fc_med = c['stats'].get('fc_media_bpm', 0)
            fc_max = c['stats'].get('fc_max_bpm', 0)
            ax_hr.plot(xs, ys, color=col, linewidth=1.8, zorder=4, label=f"{nom} (Media: {fc_med} bpm | Máx: {fc_max} bpm)")

        _configurar_ejes_comparativa(ax_hr, "3. Comparativa de Frecuencia Cardíaca (ppm / bpm)", "Frecuencia Cardíaca (bpm)")
        ax_hr.legend(bbox_to_anchor=(0.5, -0.15), loc='upper center', frameon=True, facecolor='#ffffff', edgecolor='#cbd5e1', fontsize=8.5, ncol=2)

        # 4. Kilojulios
        ax_kj = fig.add_subplot(gs[2], sharex=ax_hr)
        _dibujar_perfil_fondo(ax_kj)
        for c in ciclistas_proc:
            samples = c.get('samples_by_dist', [])
            if not samples:
                continue
            xs = [s['d_km'] for s in samples]
            ys = [s['kj'] for s in samples]
            nom = c['stats']['nombre']
            col = c['stats']['color']
            tot_kj = c['stats'].get('kilojulios_total', 0)
            kj_kg = c['stats'].get('kj_kg', 0.0)
            ax_kj.plot(xs, ys, color=col, linewidth=2.0, zorder=4, label=f"{nom} (Total: {tot_kj} kJ | {kj_kg:.1f} kJ/kg)")

        _configurar_ejes_comparativa(ax_kj, "4. Comparativa de Trabajo Mecánico Acumulado (Kilojulios Totales & kJ/kg)", "Trabajo Acumulado (kJ)")
        ax_kj.legend(bbox_to_anchor=(0.5, -0.15), loc='upper center', frameon=True, facecolor='#ffffff', edgecolor='#cbd5e1', fontsize=8.5, ncol=2)

        _add_footer(fig, watermark_img=watermark_img, pagina_num=3, total_paginas=6)
        pdf.savefig(fig, bbox_inches='tight')
        plt.close(fig)

    def _crear_pagina_graficos_3(pdf):
        """Página 4: 5. Demanda Metabólica (kJ/kg/h) y 6. Estrés Acumulado (TSS) con perfil de fondo"""
        fig = plt.figure(figsize=(16.5, 11.7))
        fig.set_layout_engine('constrained', rect=[0, 0.045, 1, 1])
        fig.patch.set_facecolor('#f8fafc')
        gs = fig.add_gridspec(3, 1, height_ratios=[0.7, 3.5, 3.5])

        ax_hdr = fig.add_subplot(gs[0])
        _add_header(ax_hdr, logo_img, "Comparativa de Telemetría (3/3)", f"{titulo_doc} | Demanda Metabólica (kJ/kg/h) y Estrés de Carrera (TSS) con Relieve Altimétrico")

        # 5. kJ/kg/h
        ax_kjkg = fig.add_subplot(gs[1])
        _dibujar_perfil_fondo(ax_kjkg)
        for c in ciclistas_proc:
            samples = c.get('samples_by_dist', [])
            if not samples:
                continue
            xs = [s['d_km'] for s in samples]
            ys = [s['kjkg_h'] for s in samples]
            nom = c['stats']['nombre']
            col = c['stats']['color']
            tasa_med = c['stats'].get('kj_kg_hora', 0.0)
            ax_kjkg.plot(xs, ys, color=col, linewidth=1.8, zorder=4, label=f"{nom} (Media: {tasa_med:.1f} kJ/kg/h)")

        ax_kjkg.axhspan(0, 20, color='#10b981', alpha=0.08, zorder=2, label='Demanda Moderada (<20 kJ/kg/h)')
        ax_kjkg.axhspan(20, 28, color='#f59e0b', alpha=0.08, zorder=2, label='Demanda Alta (20-28 kJ/kg/h)')
        ax_kjkg.axhspan(28, 45, color='#ef4444', alpha=0.08, zorder=2, label='Demanda Extrema (>28 kJ/kg/h)')

        _configurar_ejes_comparativa(ax_kjkg, "5. Comparativa de Demanda Metabólica Instantánea (kJ / kg / h)", "Tasa Metabólica (kJ/kg/h)")
        ax_kjkg.legend(bbox_to_anchor=(0.5, -0.15), loc='upper center', frameon=True, facecolor='#ffffff', edgecolor='#cbd5e1', fontsize=8.0, ncol=2)

        # 6. TSS
        ax_tss = fig.add_subplot(gs[2], sharex=ax_kjkg)
        _dibujar_perfil_fondo(ax_tss)
        for c in ciclistas_proc:
            samples = c.get('samples_by_dist', [])
            if not samples:
                continue
            xs = [s['d_km'] for s in samples]
            ys = [s['tss'] for s in samples]
            nom = c['stats']['nombre']
            col = c['stats']['color']
            tot_tss = c['stats'].get('tss_total', 0)
            tssh = c['stats'].get('tss_hora', 0.0)
            ax_tss.plot(xs, ys, color=col, linewidth=2.0, zorder=4, label=f"{nom} (Total: {tot_tss} TSS | {tssh:.1f} TSS/h)")

        _configurar_ejes_comparativa(ax_tss, "6. Comparativa de Carga y Estrés de Carrera Acumulado (TSS)", "TSS Acumulado")
        ax_tss.legend(bbox_to_anchor=(0.5, -0.15), loc='upper center', frameon=True, facecolor='#ffffff', edgecolor='#cbd5e1', fontsize=8.5, ncol=2)

        _add_footer(fig, watermark_img=watermark_img, pagina_num=4, total_paginas=6)
        pdf.savefig(fig, bbox_inches='tight')
        plt.close(fig)

    # =========================================================================
    # PÁGINA 5: ANÁLISIS BIOMECÁNICO Y CUADRANTES DE TORQUE
    # =========================================================================
    def _crear_pagina_biomecanica_torque(pdf):
        """Página 5: Análisis Biomecánico de Pedaleo, Cuadrantes de Torque y Picos MMT"""
        fig = plt.figure(figsize=(16.5, 11.7))
        fig.set_layout_engine('constrained', rect=[0, 0.045, 1, 1])
        fig.patch.set_facecolor('#f8fafc')
        gs = fig.add_gridspec(3, 2, height_ratios=[0.7, 3.8, 2.5], width_ratios=[1.1, 1.0])

        ax_hdr = fig.add_subplot(gs[0, :])
        _add_header(ax_hdr, logo_img, "ANÁLISIS BIOMECÁNICO Y DINÁMICA DE PEDALEO", f"{titulo_doc} | Análisis de Cuadrantes (Torque vs Cadencia), Fuerza Efectiva (AEPF) y Picos MMT")

        # 1. Scatter Plot de Cuadrantes (Quadrant Analysis)
        ax_quad = fig.add_subplot(gs[1, 0])
        ax_quad.set_facecolor('#ffffff')

        cad_th = 85.0
        trq_th_vals = [c['stats'].get('cuadrantes', {}).get('trq_thresh', 42.0) for c in ciclistas_proc if 'cuadrantes' in c['stats']]
        trq_th = float(np.mean(trq_th_vals)) if trq_th_vals else 42.0

        # Sombreados para los 4 cuadrantes
        ax_quad.axvspan(cad_th, 130, ymin=trq_th/85, ymax=1.0, color='#f59e0b', alpha=0.06, label='QI: Sprint/Ataque (Alta Cad, Alto Par)')
        ax_quad.axvspan(30, cad_th, ymin=trq_th/85, ymax=1.0, color='#ec4899', alpha=0.06, label='QII: Escalada Dura (Baja Cad, Alto Par)')
        ax_quad.axvspan(30, cad_th, ymin=0, ymax=trq_th/85, color='#94a3b8', alpha=0.06, label='QIII: Recuperación (Baja Cad, Bajo Par)')
        ax_quad.axvspan(cad_th, 130, ymin=0, ymax=trq_th/85, color='#38bdf8', alpha=0.06, label='QIV: Pelotón Ágil (Alta Cad, Bajo Par)')

        # Líneas de división de umbral
        ax_quad.axvline(cad_th, color='#cbd5e1', linestyle='--', linewidth=1.2)
        ax_quad.axhline(trq_th, color='#cbd5e1', linestyle='--', linewidth=1.2)

        # Isolíneas de potencia (200W, 300W, 400W)
        cad_seq = np.linspace(35, 125, 50)
        for pot_ref, col_iso in [(200, '#94a3b8'), (300, '#0284c7'), (400, '#d97706')]:
            trq_iso = pot_ref / (cad_seq * 2 * np.pi / 60.0)
            ax_quad.plot(cad_seq, trq_iso, color=col_iso, linestyle=':', linewidth=1.0, alpha=0.6, label=f'Iso-P {pot_ref}W')

        for c in ciclistas_proc:
            pts = c['stats'].get('cuadrantes', {}).get('puntos', [])
            if pts:
                sub_pts = pts[::max(1, len(pts) // 250)]
                xs = [p['cad'] for p in sub_pts]
                ys = [p['trq'] for p in sub_pts]
                col = c['stats']['color']
                nom = c['stats']['nombre']
                ax_quad.scatter(xs, ys, color=col, alpha=0.65, s=14, edgecolors='none', label=nom)

        ax_quad.set_title("Diagrama de Cuadrantes (Coggan Quadrant Analysis)", fontsize=11, fontweight='bold', pad=8, color='#0f172a')
        ax_quad.set_xlabel("Cadencia de Pedaleo (rpm)", fontsize=9, fontweight='600', color='#475569')
        ax_quad.set_ylabel("Torque en Bielas (N·m)", fontsize=9, fontweight='600', color='#475569')
        ax_quad.set_xlim(30, 130)
        ax_quad.set_ylim(0, 85)
        ax_quad.grid(True, linestyle='--', alpha=0.3, color='#94a3b8')
        ax_quad.legend(loc='upper right', frameon=True, facecolor='#ffffff', edgecolor='#cbd5e1', fontsize=7.0, ncol=2)

        # 2. Serie Temporal de Torque y AEPF a lo largo de la etapa
        ax_trq = fig.add_subplot(gs[1, 1])
        _dibujar_perfil_fondo(ax_trq)
        for c in ciclistas_proc:
            samples = c.get('samples_by_dist', [])
            if not samples:
                continue
            xs = [s['d_km'] for s in samples]
            ys = [s.get('trq', 0.0) for s in samples]
            nom = c['stats']['nombre']
            col = c['stats']['color']
            trq_med = c['stats'].get('torque_media_nm', 0.0)
            trq_max = c['stats'].get('torque_max_nm', 0.0)
            ax_trq.plot(xs, ys, color=col, linewidth=1.8, zorder=4, label=f"{nom} (Med: {trq_med} N·m | Máx: {trq_max} N·m)")

        _configurar_ejes_comparativa(ax_trq, "Evolución de Torque en Bielas (N·m) a lo largo de la Etapa", "Torque (N·m)")
        ax_trq.legend(bbox_to_anchor=(0.5, -0.15), loc='upper center', frameon=True, facecolor='#ffffff', edgecolor='#cbd5e1', fontsize=8.0, ncol=2)

        # 3. Tabla Comparativa de Picos MMT y Cuadrantes
        ax_tbl = fig.add_subplot(gs[2, :])
        ax_tbl.axis('off')

        cols = [
            "Ciclista", "Torque Med.", "Torque Máx.", "Fuerza Pedal (AEPF)",
            "MMT 1s (Arrancada)", "MMT 5s", "MMT 30s", "QI (Sprint)", "QII (Escalada)", "QIV (Pelotón)"
        ]
        tabla_datos = []
        for c in ciclistas_proc:
            s = c['stats']
            mmt = s.get('torque_mmt', {})
            q = s.get('cuadrantes', {}).get('cuadrantes', {})
            m1 = f"{mmt.get(1, '--')} N·m" if 1 in mmt else "--"
            m5 = f"{mmt.get(5, '--')} N·m" if 5 in mmt else "--"
            m30 = f"{mmt.get(30, '--')} N·m" if 30 in mmt else "--"
            q1 = f"{q.get('q1_pct', 0)}%"
            q2 = f"{q.get('q2_pct', 0)}%"
            q4 = f"{q.get('q4_pct', 0)}%"

            tabla_datos.append([
                s['nombre'],
                f"{s.get('torque_media_nm', '--')} N·m",
                f"{s.get('torque_max_nm', '--')} N·m",
                f"{s.get('aepf_media_n', '--')} N ({s.get('kgf_media', '--')} kgf)",
                m1, m5, m30, q1, q2, q4
            ])

        table = ax_tbl.table(
            cellText=tabla_datos,
            colLabels=cols,
            cellLoc='center',
            loc='center',
            bbox=[0.0, 0.05, 1.0, 0.9]
        )
        table.auto_set_font_size(False)
        table.set_fontsize(8.5)
        for (r_idx, c_idx), cell in table.get_celld().items():
            cell.set_edgecolor('#e2e8f0')
            if r_idx == 0:
                cell.set_facecolor('#0f172a')
                cell.set_text_props(color='#f8fafc', weight='bold')
                cell.set_height(0.18)
            else:
                row_bg = '#ffffff' if r_idx % 2 != 0 else '#f8fafc'
                cell.set_facecolor(row_bg)
                cell.set_text_props(color='#1e293b')
                cell.set_height(0.14)
                if c_idx == 0:
                    cell.set_text_props(ha='left', weight='bold')

        _add_footer(fig, watermark_img=watermark_img, pagina_num=5, total_paginas=6)
        pdf.savefig(fig, bbox_inches='tight')
        plt.close(fig)

    # =========================================================================
    # PÁGINA FINAL: DATOS DE FISIOLOGÍA Y BIOMETRÍA
    # =========================================================================
    def _crear_pagina_fisiologia(pdf):
        fig = plt.figure(figsize=(16.5, 11.7))
        fig.set_layout_engine('constrained', rect=[0, 0.045, 1, 1])
        fig.patch.set_facecolor('#f8fafc')
        gs = fig.add_gridspec(4, 1, height_ratios=[0.8, 2.5, 3.2, 3.2])

        ax_hdr = fig.add_subplot(gs[0])
        _add_header(ax_hdr, logo_img, "INFORME DE FISIOLOGÍA Y BIOMETRÍA DEL EQUIPO", f"Estado Biológico, Carga de Entrenamiento (CTL/ATL/TSB) y HRV | Fecha: {fecha_etapa}")

        # Tabla de Fisiología
        ax_tbl = fig.add_subplot(gs[1])
        ax_tbl.axis('off')
        ax_tbl.text(0.0, 1.05, "Estado Fisiológico y de Carga el Día de la Etapa", transform=ax_tbl.transAxes, fontsize=12, fontweight='bold', color='#1e293b')

        filas_w = []
        for c in ciclistas_proc:
            nom = c['stats']['nombre']
            w = c.get('wellness_load', {})
            ctl_str = f"{w.get('ctl'):.1f}" if w.get('ctl') is not None else "-"
            atl_str = f"{w.get('atl'):.1f}" if w.get('atl') is not None else "-"
            tsb_str = f"{w.get('tsb'):+.1f}" if w.get('tsb') is not None else "-"
            status_str = w.get('status', {}).get('label', '-')
            hrv_str = f"{w.get('hrv_rmssd'):.1f} ms" if w.get('hrv_rmssd') is not None else "-"
            hrv_7d = f"{w.get('hrv_media_7d'):.1f} ms" if w.get('hrv_media_7d') is not None else "-"
            rhr_str = f"{w.get('resting_hr')} bpm" if w.get('resting_hr') is not None else "-"
            rhr_7d = f"{w.get('resting_hr_media_7d')} bpm" if w.get('resting_hr_media_7d') is not None else "-"
            peso_str = f"{w.get('weight'):.1f} kg" if w.get('weight') is not None else f"{c['stats']['peso_kg']} kg"
            sleep_str = f"{w.get('sleep_hours'):.1f} h" if w.get('sleep_hours') is not None else "-"

            filas_w.append([
                nom, ctl_str, atl_str, tsb_str, status_str,
                hrv_str, hrv_7d, rhr_str, rhr_7d, peso_str, sleep_str
            ])

        cols_w = [
            "Ciclista", "CTL (Fitness)", "ATL (Fatiga)", "TSB (Forma)", "Estado / Readiness",
            "RMSSD (Día)", "RMSSD (7d)", "FC Reposo", "FC Reposo (7d)", "Peso", "Sueño"
        ]

        tw = ax_tbl.table(cellText=filas_w, colLabels=cols_w, loc='center', cellLoc='center')
        tw.auto_set_font_size(False)
        tw.set_fontsize(8.5)
        tw.scale(1.0, 1.45)

        for (r, col), cell in tw.get_celld().items():
            if r == 0:
                cell.set_text_props(weight='bold', color='white')
                cell.set_facecolor('#0f172a')
            else:
                cell.set_facecolor('#ffffff' if r % 2 != 0 else '#f1f5f9')
                cell.set_edgecolor('#cbd5e1')
                if col == 0:
                    cell.set_text_props(weight='bold', color='#0f172a', ha='left')
                elif col == 3: # TSB
                    cell.set_text_props(weight='bold', color='#0284c7')

        # Gráfico 1: Evolución CTL / ATL / TSB (Últimos 30 días)
        ax_load = fig.add_subplot(gs[2])
        tiene_hist_carga = False

        # Zonas de fondo en función del TSB (Forma / Balance)
        ax_tsb = ax_load.twinx()
        ax_tsb.axhspan(15, 55, color='#10b981', alpha=0.08, zorder=1)
        ax_tsb.axhspan(5, 15, color='#38bdf8', alpha=0.10, zorder=1)
        ax_tsb.axhspan(-10, 5, color='#818cf8', alpha=0.06, zorder=1)
        ax_tsb.axhspan(-30, -10, color='#f59e0b', alpha=0.10, zorder=1)
        ax_tsb.axhspan(-70, -30, color='#ef4444', alpha=0.10, zorder=1)
        ax_tsb.axhline(0, color='#94a3b8', linestyle=':', linewidth=0.9, alpha=0.6, zorder=1)

        ax_tsb.text(0.99, 0.93, "Muy Fresco (> +15)", transform=ax_tsb.transAxes, ha='right', va='center', fontsize=7.2, fontweight='bold', color='#059669', alpha=0.85)
        ax_tsb.text(0.99, 0.76, "Fresco / Competición (+5 a +15)", transform=ax_tsb.transAxes, ha='right', va='center', fontsize=7.2, fontweight='bold', color='#0284c7', alpha=0.85)
        ax_tsb.text(0.99, 0.58, "Neutro / Balance (-10 a +5)", transform=ax_tsb.transAxes, ha='right', va='center', fontsize=7.2, fontweight='bold', color='#6366f1', alpha=0.85)
        ax_tsb.text(0.99, 0.38, "Fatiga Productiva (-30 a -10)", transform=ax_tsb.transAxes, ha='right', va='center', fontsize=7.2, fontweight='bold', color='#d97706', alpha=0.85)
        ax_tsb.text(0.99, 0.12, "Sobrecarga (< -30)", transform=ax_tsb.transAxes, ha='right', va='center', fontsize=7.2, fontweight='bold', color='#dc2626', alpha=0.85)

        ax_tsb.set_ylim(-45, 35)
        ax_tsb.set_ylabel("TSB (Zonas de Forma)", color='#64748b', fontsize=8.5, fontweight='bold', labelpad=6)
        ax_tsb.tick_params(axis='y', labelcolor='#64748b', labelsize=7.5)
        ax_tsb.grid(False)

        for c in ciclistas_proc:
            w = c.get('wellness_load', {})
            hist = w.get('historial', [])
            if hist:
                df_h = pd.DataFrame(hist).dropna(subset=['fecha'])
                if not df_h.empty and 'ctl' in df_h.columns:
                    df_h['fecha'] = pd.to_datetime(df_h['fecha'])
                    df_h = df_h.sort_values('fecha')
                    col = c['stats']['color']
                    nom = c['stats']['nombre']
                    ctl_last = df_h['ctl'].iloc[-1] if df_h['ctl'].notna().any() else 0
                    atl_last = df_h['atl'].iloc[-1] if df_h['atl'].notna().any() else 0
                    ax_load.plot(df_h['fecha'], df_h['ctl'], color=col, linewidth=2.2, label=f"{nom} (CTL: {ctl_last:.0f})")
                    ax_load.plot(df_h['fecha'], df_h['atl'], color=col, linewidth=1.5, linestyle='--', alpha=0.75, label=f"{nom} (ATL: {atl_last:.0f})")
                    tiene_hist_carga = True

        if tiene_hist_carga:
            _configurar_ejes_comparativa(ax_load, "Evolución Temporal de Carga (CTL: Línea continua | ATL: Discontinua | Fondo: Zonas TSB) - 30 Días", "Puntos de Carga / Fitness", xlabel="Fecha")
            ax_load.legend(bbox_to_anchor=(0.5, -0.15), loc='upper center', frameon=True, facecolor='#ffffff', edgecolor='#cbd5e1', fontsize=8.0, ncol=2)
            ax_load.set_zorder(ax_tsb.get_zorder() + 1)
            ax_load.patch.set_visible(False)
            fig.autofmt_xdate()
        else:
            ax_tsb.axis('off')
            ax_load.text(0.5, 0.5, "Sin datos de histórico de CTL/ATL en la API para los atletas seleccionados.", transform=ax_load.transAxes, ha='center', va='center', color='#94a3b8')
            ax_load.axis('off')

        # Gráfico 2: Evolución HRV RMSSD y FC Reposo
        ax_hrv = fig.add_subplot(gs[3])
        tiene_hist_hrv = False

        for c in ciclistas_proc:
            w = c.get('wellness_load', {})
            hist = w.get('historial', [])
            if hist:
                df_h = pd.DataFrame(hist).dropna(subset=['fecha'])
                if not df_h.empty and 'hrv' in df_h.columns and df_h['hrv'].notna().any():
                    df_h['fecha'] = pd.to_datetime(df_h['fecha'])
                    df_h = df_h.sort_values('fecha').dropna(subset=['hrv'])
                    col = c['stats']['color']
                    nom = c['stats']['nombre']
                    hrv_last = df_h['hrv'].iloc[-1]
                    ax_hrv.plot(df_h['fecha'], df_h['hrv'], color=col, marker='o', markersize=4, linewidth=1.8, label=f"{nom} (RMSSD: {hrv_last:.1f} ms)")
                    tiene_hist_hrv = True

        if tiene_hist_hrv:
            _configurar_ejes_comparativa(ax_hrv, "Evolución de Variabilidad Cardíaca HRV RMSSD (ms) - 30 Días", "HRV RMSSD (ms)", xlabel="Fecha")
            ax_hrv.legend(bbox_to_anchor=(0.5, -0.15), loc='upper center', frameon=True, facecolor='#ffffff', edgecolor='#cbd5e1', fontsize=8.0, ncol=2)
            fig.autofmt_xdate()
        else:
            ax_hrv.text(0.5, 0.5, "Sin registros de HRV en el histórico de la API para los atletas seleccionados.", transform=ax_hrv.transAxes, ha='center', va='center', color='#94a3b8')
            ax_hrv.axis('off')

        _add_footer(fig, watermark_img=watermark_img, pagina_num=6, total_paginas=6)
        pdf.savefig(fig, bbox_inches='tight')
        plt.close(fig)

    # =========================================================================
    # ENSAMBLAR PDF MULTIPÁGINA
    # =========================================================================
    output_pdf.parent.mkdir(parents=True, exist_ok=True)
    try:
        with PdfPages(output_pdf) as pdf:
            _crear_pagina_resumen_etapa(pdf)
            _crear_pagina_graficos_1(pdf)
            _crear_pagina_graficos_2(pdf)
            _crear_pagina_graficos_3(pdf)
            _crear_pagina_biomecanica_torque(pdf)
            _crear_pagina_fisiologia(pdf)
    except PermissionError:
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        output_pdf = output_pdf.parent / f"{output_pdf.stem}_{timestamp}.pdf"
        with PdfPages(output_pdf) as pdf:
            _crear_pagina_resumen_etapa(pdf)
            _crear_pagina_graficos_1(pdf)
            _crear_pagina_graficos_2(pdf)
            _crear_pagina_graficos_3(pdf)
            _crear_pagina_biomecanica_torque(pdf)
            _crear_pagina_fisiologia(pdf)

    return output_pdf

