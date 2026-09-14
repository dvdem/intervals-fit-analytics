"""
Módulo de Generación de Informes Ejecutivos en Microsoft Word (.docx).
Genera documentos nativos profesionales con tablas editables y gráficos de alta resolución:
1. Informe Ejecutivo de Etapa / Telemetría (Clasificación, Meteorología, Desglose Horario).
2. Gráficos Comparativos de Telemetría (Potencia, FC, Trabajo kJ, Cadencia, Torque).
3. Dinámica de Pedaleo y Esfuerzos Críticos (MMP con Trabajo y kJ Previos al Esfuerzo).
4. Fisiología, Bienestar (Wellness) y Carga de Entrenamiento (CTL/ATL/TSB, HRV).
"""

import io
import re
import sys
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

# python-docx
import docx
from docx import Document
from docx.enum.section import WD_ORIENTATION, WD_SECTION
from docx.enum.table import WD_ALIGN_VERTICAL, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement, parse_xml
from docx.oxml.ns import nsdecls, qn
from docx.shared import Inches, Pt, RGBColor

try:
    from config import DEFAULT_LOGO_PATH, OUTPUT_DIR
except (ImportError, ValueError):
    from ..config import DEFAULT_LOGO_PATH, OUTPUT_DIR


# =============================================================================
# HELPERS DE ESTILO XML PARA TABLAS Y CELDAS EN WORD
# =============================================================================

def _set_cell_background(cell, fill_hex: str):
    """Establece el color de fondo de una celda en formato hexadecimal (ej. '334155')."""
    tcPr = cell._tc.get_or_add_tcPr()
    shd = parse_xml(f'<w:shd {nsdecls("w")} w:fill="{fill_hex.strip("#")}"/>')
    tcPr.append(shd)


def _set_cell_padding(cell, top: int = 100, bottom: int = 100, left: int = 140, right: int = 140):
    """Establece márgenes internos (padding en dxa: 20 dxa = 1 pt) para una celda."""
    tcPr = cell._tc.get_or_add_tcPr()
    tcMar = parse_xml(
        f'<w:tcMar {nsdecls("w")}>'
        f'<w:top w:w="{top}" w:type="dxa"/>'
        f'<w:bottom w:w="{bottom}" w:type="dxa"/>'
        f'<w:left w:w="{left}" w:type="dxa"/>'
        f'<w:right w:w="{right}" w:type="dxa"/>'
        f'</w:tcMar>'
    )
    tcPr.append(tcMar)


def _set_cell_borders(cell, color: str = "CBD5E1", sz: str = "4"):
    """Establece bordes horizontales limpios y sutiles."""
    tcPr = cell._tc.get_or_add_tcPr()
    tcBorders = parse_xml(
        f'<w:tcBorders {nsdecls("w")}>'
        f'<w:top w:val="single" w:sz="{sz}" w:space="0" w:color="{color.strip("#")}"/>'
        f'<w:bottom w:val="single" w:sz="{sz}" w:space="0" w:color="{color.strip("#")}"/>'
        f'<w:left w:val="none"/>'
        f'<w:right w:val="none"/>'
        f'</w:tcBorders>'
    )
    tcPr.append(tcBorders)


def _format_table_header(row, col_names: List[str], bg_color: str = "334155", font_size_pt: float = 8.0):
    """Aplica formato de encabezado a una fila de tabla."""
    for idx, name in enumerate(col_names):
        cell = row.cells[idx]
        _set_cell_background(cell, bg_color)
        _set_cell_padding(cell, top=120, bottom=120, left=100, right=100)
        _set_cell_borders(cell, color="1E293B", sz="6")
        cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER

        p = cell.paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.space_before = Pt(0)
        p.paragraph_format.space_after = Pt(0)
        run = p.add_run(str(name))
        run.bold = True
        run.font.name = "Calibri"
        run.font.size = Pt(font_size_pt)
        run.font.color.rgb = RGBColor(255, 255, 255)


def _format_table_data_row(
    row,
    values: List[Any],
    is_even: bool = False,
    aligns: Optional[List[int]] = None,
    bold_cols: Optional[List[int]] = None,
    font_size_pt: float = 8.0,
    text_colors: Optional[Dict[int, RGBColor]] = None
):
    """Formatea una fila de datos con sombreado alterno y bordes finos."""
    bg_hex = "F8FAFC" if is_even else "FFFFFF"
    bold_cols = bold_cols or [0]

    for idx, val in enumerate(values):
        cell = row.cells[idx]
        _set_cell_background(cell, bg_hex)
        _set_cell_padding(cell, top=90, bottom=90, left=90, right=90)
        _set_cell_borders(cell, color="E2E8F0", sz="4")
        cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER

        p = cell.paragraphs[0]
        if aligns and idx < len(aligns):
            p.alignment = aligns[idx]
        else:
            p.alignment = WD_ALIGN_PARAGRAPH.LEFT if idx == 0 else WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.space_before = Pt(0)
        p.paragraph_format.space_after = Pt(0)

        run = p.add_run(str(val))
        run.font.name = "Calibri"
        run.font.size = Pt(font_size_pt)
        if idx in bold_cols:
            run.bold = True
            run.font.color.rgb = RGBColor(15, 23, 42)
        else:
            run.font.color.rgb = RGBColor(51, 65, 85)

        if text_colors and idx in text_colors:
            run.font.color.rgb = text_colors[idx]


# =============================================================================
# HELPERS DE MATPLOTLIB PARA EXPORTACIÓN EN MEMORIA
# =============================================================================

def _figura_a_buffer(fig) -> io.BytesIO:
    """Convierte una figura Matplotlib en un buffer de memoria PNG a 250 DPI."""
    buf = io.BytesIO()
    fig.savefig(buf, format='png', dpi=250, bbox_inches='tight')
    buf.seek(0)
    plt.close(fig)
    return buf


def _dibujar_perfil_fondo(ax, perfil: List[Dict[str, float]]):
    """Dibuja el perfil altimétrico de la etapa suavizado en el fondo del gráfico."""
    if not perfil:
        return None
    d_x = np.array([p['x'] for p in perfil])
    alt_y = np.array([p['y'] for p in perfil])
    if len(d_x) == 0 or len(alt_y) == 0:
        return None

    ax_bg = ax.twinx()
    min_alt = float(np.nanmin(alt_y))
    max_alt = float(np.nanmax(alt_y))
    rango = max_alt - min_alt if max_alt > min_alt else 100.0
    base_alt = max(0.0, min_alt - rango * 0.1)

    ax_bg.fill_between(d_x, alt_y, base_alt, color='#10b981', alpha=0.15, zorder=1)
    ax_bg.plot(d_x, alt_y, color='#059669', linewidth=1.1, alpha=0.35, zorder=1)
    ax_bg.set_ylim(bottom=base_alt, top=max_alt + rango * 1.6)
    ax_bg.set_ylabel("Altitud (m)", color='#64748b', fontsize=8.0, fontweight='bold', labelpad=6)
    ax_bg.tick_params(axis='y', labelcolor='#64748b', labelsize=7.5)
    ax_bg.grid(False)

    ax.set_zorder(ax_bg.get_zorder() + 1)
    ax.patch.set_visible(False)
    return ax_bg


def _configurar_ejes(ax, title: str, ylabel: str, xlabel: str = "Distancia (km)"):
    ax.set_title(title, fontsize=11, fontweight='bold', color='#1e293b', pad=8)
    ax.set_xlabel(xlabel, fontsize=8.5, fontweight='bold', color='#475569')
    ax.set_ylabel(ylabel, fontsize=8.5, fontweight='bold', color='#475569')
    ax.grid(True, linestyle='--', alpha=0.4, color='#cbd5e1')
    ax.set_facecolor('#ffffff')
    for spine in ['top']:
        ax.spines[spine].set_visible(False)
    for spine in ['left', 'bottom', 'right']:
        ax.spines[spine].set_color('#94a3b8')


# =============================================================================
# FUNCIÓN PRINCIPAL DE GENERACIÓN WORD
# =============================================================================

def generar_informe_etapa_word(
    etapa_info: Dict[str, Any],
    ciclistas_proc: List[Dict[str, Any]],
    wellness_carga_map: Optional[Dict[str, Any]] = None,
    titulo: Optional[str] = None,
    output_docx: Optional[Union[str, Path]] = None,
    logo_path: Optional[Union[str, Path]] = None
) -> Path:
    """
    Genera el informe ejecutivo completo de la etapa en formato Microsoft Word (.docx).

    Incluye:
    - Encabezado con branding Burgos BH, fecha, kilometraje y altimetría.
    - Bloque meteorológico con temperatura, humedad, viento y ráfagas.
    - Tabla de Clasificación General y Resumen de Etapa (editable).
    - Desglose Horario de Rendimiento (editable).
    - 3 Páginas de Gráficos de Telemetría Comparativa (300 DPI).
    - Análisis Biomecánico de Cuadrantes de Torque y Tabla de Dinámica de Pedaleo (MMP + kJ previos).
    - Fisiología, Bienestar y Carga de Entrenamiento (CTL/ATL/TSB, HRV) con tablas y gráficos.
    """
    if not ciclistas_proc:
        raise ValueError("No se proporcionaron ciclistas para generar el informe Word.")

    # 1. Determinar fecha y título
    fecha_etapa = None
    for c in ciclistas_proc:
        if 'df_gps' in c and not c['df_gps'].empty and 'timestamp' in c['df_gps'].columns:
            ts = c['df_gps']['timestamp'].iloc[0]
            if pd.notna(ts):
                fecha_etapa = ts.strftime('%Y-%m-%d')
                break
    if not fecha_etapa:
        fecha_etapa = datetime.now().strftime('%Y-%m-%d')

    dist_total_km = etapa_info.get('distancia_total_km', 0.0)
    desnivel_pos_m = etapa_info.get('desnivel_pos_m', 0)
    titulo_doc = titulo or f"Etapa {dist_total_km:.1f} km (+{desnivel_pos_m}m D+) | {fecha_etapa}"

    # 2. Configurar ruta de destino
    if output_docx is None:
        _slug = unicodedata.normalize('NFKD', titulo_doc).encode('ASCII', 'ignore').decode('utf-8')
        _slug = re.sub(r'[\s\-/\\|]+', '_', _slug)
        _slug = re.sub(r'[^A-Za-z0-9_]', '', _slug)
        _slug = re.sub(r'_+', '_', _slug).strip('_')[:60]
        _part = f"_{_slug}" if _slug else ""
        output_docx = OUTPUT_DIR / f"etapa_{fecha_etapa}{_part}.docx"
    else:
        output_docx = Path(output_docx)

    output_docx.parent.mkdir(parents=True, exist_ok=True)

    # 3. Inicializar Documento Word
    doc = Document()

    # Configuración de página: Horizontal A4 (Landscape) con márgenes de 0.5 pulgadas
    section = doc.sections[0]
    section.orientation = WD_ORIENTATION.LANDSCAPE
    section.page_width = Inches(11.69)
    section.page_height = Inches(8.27)
    section.top_margin = Inches(0.5)
    section.bottom_margin = Inches(0.5)
    section.left_margin = Inches(0.5)
    section.right_margin = Inches(0.5)

    # Configuración de estilos base
    style_normal = doc.styles['Normal']
    style_normal.font.name = 'Calibri'
    style_normal.font.size = Pt(9.5)
    style_normal.font.color.rgb = RGBColor(30, 41, 59)

    # Header de página en Word
    header = section.header
    hp = header.paragraphs[0]
    hp.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    hrun = hp.add_run("BURGOS BH • INTERVALS FIT ANALYTICS | INFORME EJECUTIVO DE RENDIMIENTO")
    hrun.font.name = "Calibri"
    hrun.font.size = Pt(7.5)
    hrun.font.color.rgb = RGBColor(148, 163, 184)

    # Footer de página
    footer = section.footer
    fp = footer.paragraphs[0]
    fp.alignment = WD_ALIGN_PARAGRAPH.CENTER
    frun = fp.add_run(f"Generado el {datetime.now().strftime('%Y-%m-%d %H:%M')} • Documento Confidencial de Rendimiento Deportivo")
    frun.font.name = "Calibri"
    frun.font.size = Pt(7.5)
    frun.font.color.rgb = RGBColor(148, 163, 184)

    # Resolver Logo
    logo_file = Path(logo_path) if logo_path else DEFAULT_LOGO_PATH
    if not logo_file.exists() or logo_file.suffix.lower() == '.svg':
        png_cand = logo_file.with_suffix('.png')
        if png_cand.exists():
            logo_file = png_cand

    # =========================================================================
    # SECCIÓN 1: ENCABEZADO CORPORATIVO, RESUMEN DE ETAPA Y METEOROLOGÍA
    # =========================================================================
    tbl_hdr = doc.add_table(rows=1, cols=2)
    tbl_hdr.alignment = WD_TABLE_ALIGNMENT.CENTER
    tbl_hdr.autofit = False
    tbl_hdr.columns[0].width = Inches(2.2)
    tbl_hdr.columns[1].width = Inches(8.4)

    # Celda Izquierda: Logotipo
    c_logo = tbl_hdr.cell(0, 0)
    c_logo.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
    p_logo = c_logo.paragraphs[0]
    p_logo.alignment = WD_ALIGN_PARAGRAPH.LEFT
    if logo_file.exists() and logo_file.suffix.lower() == '.png':
        try:
            p_logo.add_run().add_picture(str(logo_file), width=Inches(1.8))
        except Exception:
            p_logo.add_run("BURGOS BH").bold = True
    else:
        p_logo.add_run("BURGOS BH").bold = True

    # Celda Derecha: Título y Metadatos
    c_tit = tbl_hdr.cell(0, 1)
    c_tit.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
    p_tit = c_tit.paragraphs[0]
    p_tit.paragraph_format.space_before = Pt(0)
    p_tit.paragraph_format.space_after = Pt(2)
    run_t = p_tit.add_run(titulo_doc)
    run_t.bold = True
    run_t.font.size = Pt(15.0)
    run_t.font.color.rgb = RGBColor(88, 28, 135)

    p_sub = c_tit.add_paragraph()
    p_sub.paragraph_format.space_before = Pt(0)
    p_sub.paragraph_format.space_after = Pt(2)
    r_sub = p_sub.add_run(f"📅 Fecha: {fecha_etapa}  |  📏 Distancia: {dist_total_km:.1f} km  |  ⛰️ Desnivel: +{desnivel_pos_m} m D+  |  🚴 {len(ciclistas_proc)} Corredores")
    r_sub.font.size = Pt(9.5)
    r_sub.bold = True
    r_sub.font.color.rgb = RGBColor(71, 85, 105)

    # Clima
    clima = etapa_info.get('clima')
    if clima:
        p_w = c_tit.add_paragraph()
        p_w.paragraph_format.space_before = Pt(0)
        p_w.paragraph_format.space_after = Pt(0)
        r_w = p_w.add_run(
            f"🌤️ Clima: {clima.get('temp_media_c', '--')}°C | Humedad: {clima.get('humedad_media_pct', '--')}% | "
            f"Viento: {clima.get('viento_media_kmh', '--')} km/h ({clima.get('viento_cardinal', '--')}) | Ráfagas: {clima.get('viento_rafagas_max_kmh', '--')} km/h"
        )
        r_w.font.size = Pt(8.5)
        r_w.font.color.rgb = RGBColor(100, 116, 139)

    doc.add_paragraph().paragraph_format.space_after = Pt(4)

    # =========================================================================
    # TABLA 1: CLASIFICACIÓN GENERAL Y RESUMEN DE RENDIMIENTO
    # =========================================================================
    p_sec1 = doc.add_paragraph()
    p_sec1.paragraph_format.space_before = Pt(4)
    p_sec1.paragraph_format.space_after = Pt(3)
    r_s1 = p_sec1.add_run("1. CLASIFICACIÓN GENERAL Y RESUMEN EJECUTIVO DE ETAPA")
    r_s1.bold = True
    r_s1.font.size = Pt(11.0)
    r_s1.font.color.rgb = RGBColor(30, 41, 59)

    cols_resumen = [
        "Pos", "Ciclista", "Gap", "Tiempo Mov", "Dist (km)", "Vel (km/h)",
        "FC Med", "Pot Med", "NP (W)", "W/kg", "Cad Med", "Cad Pwd",
        "Cad 0-70", "Cad 70-90", "Cad 90+", "Trabajo (kJ)", "kJ/kg"
    ]

    tbl_resumen = doc.add_table(rows=len(ciclistas_proc) + 1, cols=len(cols_resumen))
    tbl_resumen.alignment = WD_TABLE_ALIGNMENT.CENTER
    tbl_resumen.autofit = True

    _format_table_header(tbl_resumen.rows[0], cols_resumen, bg_color="334155", font_size_pt=8.0)

    for idx, c in enumerate(ciclistas_proc):
        s = c['stats']
        row = tbl_resumen.rows[idx + 1]

        t_seg = s.get('tiempo_mov_seg', 0)
        hh = int(t_seg // 3600)
        mm = int((t_seg % 3600) // 60)
        ss = int(t_seg % 60)
        t_str = f"{hh}h {mm:02d}m {ss:02d}s" if hh > 0 else f"{mm}m {ss:02d}s"

        fc_str = f"{s.get('fc_media_bpm', 0)} bpm" if s.get('fc_media_bpm', 0) > 0 else "--"
        cad_m_str = f"{s.get('cad_media_rpm', 0)} rpm" if s.get('cad_media_rpm', 0) > 0 else "--"
        cad_p_str = f"{s.get('cad_pedaleo_rpm', 0)} rpm" if s.get('cad_pedaleo_rpm', 0) > 0 else "--"
        kj_kg_str = f"{s.get('kj_kg', 0.0):.1f}" if s.get('kj_kg') else "--"

        valores = [
            s.get('posicion_str', f"{idx+1}º"),
            s.get('nombre', f'Ciclista {idx+1}'),
            s.get('gap_lider_str', '-'),
            t_str,
            f"{s.get('distancia_km', 0.0):.1f}",
            f"{s.get('vel_media_kmh', 0.0):.1f}",
            fc_str,
            f"{s.get('pot_media_w', 0)} W",
            f"{s.get('np_w', 0)} W",
            f"{s.get('w_kg_media', 0.0):.2f}",
            cad_m_str,
            cad_p_str,
            f"{s.get('pct_cad_baja', 0.0):.0f}%",
            f"{s.get('pct_cad_optima', 0.0):.0f}%",
            f"{s.get('pct_cad_alta', 0.0):.0f}%",
            f"{s.get('kilojulios_total', 0):,} kJ".replace(',', '.'),
            kj_kg_str
        ]

        _format_table_data_row(row, valores, is_even=(idx % 2 == 1), font_size_pt=8.0)

    doc.add_paragraph().paragraph_format.space_after = Pt(4)

    # =========================================================================
    # TABLA 2: DESGLOSE HORARIO DE RENDIMIENTO
    # =========================================================================
    max_horas = max([len(c.get('tramos_horarios', [])) for c in ciclistas_proc], default=0)
    if max_horas > 0:
        p_sec2 = doc.add_paragraph()
        p_sec2.paragraph_format.space_before = Pt(4)
        p_sec2.paragraph_format.space_after = Pt(3)
        r_s2 = p_sec2.add_run("2. DESGLOSE HORARIO DE RENDIMIENTO (POTENCIA NORMALIZADA, FC Y KILOMETRAJE)")
        r_s2.bold = True
        r_s2.font.size = Pt(10.5)
        r_s2.font.color.rgb = RGBColor(30, 41, 59)

        cols_horario = ["Ciclista"] + [f"Hora {h+1}" for h in range(max_horas)]
        tbl_horario = doc.add_table(rows=len(ciclistas_proc) + 1, cols=len(cols_horario))
        tbl_horario.alignment = WD_TABLE_ALIGNMENT.CENTER
        tbl_horario.autofit = True

        _format_table_header(tbl_horario.rows[0], cols_horario, bg_color="475569", font_size_pt=8.0)

        for idx, c in enumerate(ciclistas_proc):
            tramos = c.get('tramos_horarios', [])
            fila_vals = [c['stats']['nombre']]
            for h in range(max_horas):
                if h < len(tramos):
                    th = tramos[h]
                    fc_txt = f"{th.get('fc_media_bpm')} bpm | " if th.get('fc_media_bpm', 0) > 0 else ""
                    fila_vals.append(f"NP: {th.get('np_w', 0)}W | {fc_txt}{th.get('distancia_km', 0):.1f}km")
                else:
                    fila_vals.append("-")
            _format_table_data_row(tbl_horario.rows[idx + 1], fila_vals, is_even=(idx % 2 == 1), font_size_pt=7.5)

    # =========================================================================
    # SECCIÓN 3: GRÁFICOS COMPARATIVOS DE TELEMETRÍA (250-300 DPI)
    # =========================================================================
    perfil = etapa_info.get('perfil_altimetria', [])

    doc.add_page_break()

    p_g1 = doc.add_paragraph()
    p_g1.paragraph_format.space_before = Pt(0)
    p_g1.paragraph_format.space_after = Pt(2)
    r_g1 = p_g1.add_run("3. TELEMETRÍA COMPARATIVA: POTENCIA ABSOLUTA (W) Y RELATIVA (W/kg)")
    r_g1.bold = True
    r_g1.font.size = Pt(11.0)
    r_g1.font.color.rgb = RGBColor(30, 41, 59)

    fig1 = plt.figure(figsize=(15.0, 7.2))
    fig1.set_layout_engine('constrained')
    fig1.patch.set_facecolor('#ffffff')
    gs1 = fig1.add_gridspec(2, 1, height_ratios=[1, 1])

    # 1. Potencia Absoluta
    ax_pwr = fig1.add_subplot(gs1[0])
    _dibujar_perfil_fondo(ax_pwr, perfil)
    for c in ciclistas_proc:
        samples = c.get('samples_by_dist', [])
        if samples:
            ax_pwr.plot([s['d_km'] for s in samples], [s['pwr'] for s in samples],
                        color=c['stats']['color'], linewidth=1.6, zorder=4,
                        label=f"{c['stats']['nombre']} (Media: {c['stats'].get('pot_media_w', 0)} W | NP: {c['stats'].get('np_w', 0)} W)")
    _configurar_ejes(ax_pwr, "Potencia Absoluta (Vatios)", "Potencia (W)")
    ax_pwr.legend(loc='upper right', frameon=True, facecolor='#ffffff', edgecolor='#cbd5e1', fontsize=7.5, ncol=2)

    # 2. Potencia Relativa W/kg
    ax_wkg = fig1.add_subplot(gs1[1], sharex=ax_pwr)
    _dibujar_perfil_fondo(ax_wkg, perfil)
    for c in ciclistas_proc:
        samples = c.get('samples_by_dist', [])
        if samples:
            ax_wkg.plot([s['d_km'] for s in samples], [s['wkg'] for s in samples],
                        color=c['stats']['color'], linewidth=1.6, zorder=4,
                        label=f"{c['stats']['nombre']} (Media: {c['stats'].get('w_kg_media', 0.0):.2f} W/kg)")
    ax_wkg.axhline(4.0, color='#94a3b8', linestyle=':', linewidth=0.9, alpha=0.6)
    ax_wkg.axhline(5.0, color='#f59e0b', linestyle=':', linewidth=0.9, alpha=0.6)
    _configurar_ejes(ax_wkg, "Potencia Relativa al Peso (W/kg)", "W/kg")
    ax_wkg.legend(loc='upper right', frameon=True, facecolor='#ffffff', edgecolor='#cbd5e1', fontsize=7.5, ncol=2)

    buf1 = _figura_a_buffer(fig1)
    doc.add_picture(buf1, width=Inches(10.6))

    # Gráfico 2: FC (bpm) y Trabajo Mecánico Acumulado (kJ)
    doc.add_page_break()

    p_g2 = doc.add_paragraph()
    p_g2.paragraph_format.space_before = Pt(0)
    p_g2.paragraph_format.space_after = Pt(2)
    r_g2 = p_g2.add_run("4. TELEMETRÍA COMPARATIVA: FRECUENCIA CARDÍACA (bpm) Y TRABAJO MECÁNICO ACUMULADO (kJ)")
    r_g2.bold = True
    r_g2.font.size = Pt(11.0)
    r_g2.font.color.rgb = RGBColor(30, 41, 59)

    fig2 = plt.figure(figsize=(15.0, 7.2))
    fig2.set_layout_engine('constrained')
    fig2.patch.set_facecolor('#ffffff')
    gs2 = fig2.add_gridspec(2, 1, height_ratios=[1, 1])

    # FC
    ax_hr = fig2.add_subplot(gs2[0])
    _dibujar_perfil_fondo(ax_hr, perfil)
    for c in ciclistas_proc:
        samples = c.get('samples_by_dist', [])
        if samples:
            ax_hr.plot([s['d_km'] for s in samples], [s['hr'] for s in samples],
                       color=c['stats']['color'], linewidth=1.6, zorder=4,
                       label=f"{c['stats']['nombre']} (Media: {c['stats'].get('fc_media_bpm', 0)} bpm | Máx: {c['stats'].get('fc_max_bpm', 0)} bpm)")
    _configurar_ejes(ax_hr, "Frecuencia Cardíaca (bpm)", "Frecuencia Cardíaca (bpm)")
    ax_hr.legend(loc='upper right', frameon=True, facecolor='#ffffff', edgecolor='#cbd5e1', fontsize=7.5, ncol=2)

    # Kilojulios
    ax_kj = fig2.add_subplot(gs2[1], sharex=ax_hr)
    _dibujar_perfil_fondo(ax_kj, perfil)
    for c in ciclistas_proc:
        samples = c.get('samples_by_dist', [])
        if samples:
            ax_kj.plot([s['d_km'] for s in samples], [s['kj'] for s in samples],
                       color=c['stats']['color'], linewidth=1.8, zorder=4,
                       label=f"{c['stats']['nombre']} (Total: {c['stats'].get('kilojulios_total', 0)} kJ | {c['stats'].get('kj_kg', 0.0):.1f} kJ/kg)")
    _configurar_ejes(ax_kj, "Trabajo Mecánico Acumulado (Kilojulios Totales)", "Trabajo Acumulado (kJ)")
    ax_kj.legend(loc='upper right', frameon=True, facecolor='#ffffff', edgecolor='#cbd5e1', fontsize=7.5, ncol=2)

    buf2 = _figura_a_buffer(fig2)
    doc.add_picture(buf2, width=Inches(10.6))

    # Gráfico 3: Demanda Metabólica (kJ/kg/h) y Estrés de Carrera (TSS)
    doc.add_page_break()

    p_g3 = doc.add_paragraph()
    p_g3.paragraph_format.space_before = Pt(0)
    p_g3.paragraph_format.space_after = Pt(2)
    r_g3 = p_g3.add_run("5. DEMANDA METABÓLICA (kJ/kg/h) Y ESTRÉS DE CARRERA (TSS)")
    r_g3.bold = True
    r_g3.font.size = Pt(11.0)
    r_g3.font.color.rgb = RGBColor(30, 41, 59)

    fig3 = plt.figure(figsize=(15.0, 7.2))
    fig3.set_layout_engine('constrained')
    fig3.patch.set_facecolor('#ffffff')
    gs3 = fig3.add_gridspec(2, 1, height_ratios=[1, 1])

    # Demanda Metabólica
    ax_rate = fig3.add_subplot(gs3[0])
    _dibujar_perfil_fondo(ax_rate, perfil)
    for c in ciclistas_proc:
        samples = c.get('samples_by_dist', [])
        if samples:
            ax_rate.plot([s['d_km'] for s in samples], [s['kjkg_h'] for s in samples],
                         color=c['stats']['color'], linewidth=1.5, zorder=4,
                         label=f"{c['stats']['nombre']} (Media: {c['stats'].get('kj_kg_hora', 0.0):.1f} kJ/kg/h)")
    ax_rate.axhspan(0, 20, color='#10b981', alpha=0.08, zorder=2)
    ax_rate.axhspan(20, 28, color='#f59e0b', alpha=0.08, zorder=2)
    ax_rate.axhspan(28, 45, color='#ef4444', alpha=0.08, zorder=2)
    _configurar_ejes(ax_rate, "Demanda Metabólica Instantánea (kJ / kg / h)", "Tasa Metabólica (kJ/kg/h)")
    ax_rate.legend(loc='upper right', frameon=True, facecolor='#ffffff', edgecolor='#cbd5e1', fontsize=7.5, ncol=2)

    # TSS
    ax_tss = fig3.add_subplot(gs3[1], sharex=ax_rate)
    _dibujar_perfil_fondo(ax_tss, perfil)
    for c in ciclistas_proc:
        samples = c.get('samples_by_dist', [])
        if samples:
            ax_tss.plot([s['d_km'] for s in samples], [s['tss'] for s in samples],
                        color=c['stats']['color'], linewidth=1.8, zorder=4,
                        label=f"{c['stats']['nombre']} (Total: {c['stats'].get('tss_total', 0)} TSS | {c['stats'].get('tss_hora', 0.0):.1f} TSS/h)")
    _configurar_ejes(ax_tss, "Estrés de Carrera Acumulado (TSS)", "TSS Acumulado")
    ax_tss.legend(loc='upper right', frameon=True, facecolor='#ffffff', edgecolor='#cbd5e1', fontsize=7.5, ncol=2)

    buf3 = _figura_a_buffer(fig3)
    doc.add_picture(buf3, width=Inches(10.6))

    # =========================================================================
    # SECCIÓN 4: ANÁLISIS BIOMECÁNICO Y CUADRANTES DE TORQUE
    # =========================================================================
    doc.add_page_break()

    p_bio = doc.add_paragraph()
    p_bio.paragraph_format.space_before = Pt(0)
    p_bio.paragraph_format.space_after = Pt(2)
    r_bio = p_bio.add_run("6. ANÁLISIS BIOMECÁNICO: CUADRANTES DE TORQUE (COGGAN) Y PAR EN BIELAS")
    r_bio.bold = True
    r_bio.font.size = Pt(11.0)
    r_bio.font.color.rgb = RGBColor(30, 41, 59)

    fig_bio = plt.figure(figsize=(15.0, 7.0))
    fig_bio.set_layout_engine('constrained')
    fig_bio.patch.set_facecolor('#ffffff')
    gs_b = fig_bio.add_gridspec(1, 2, width_ratios=[1.1, 1.0])

    # Cuadrantes Scatter
    ax_quad = fig_bio.add_subplot(gs_b[0])
    ax_quad.set_facecolor('#ffffff')
    cad_th = 85.0
    trq_th_vals = [c['stats'].get('cuadrantes', {}).get('trq_thresh', 42.0) for c in ciclistas_proc if 'cuadrantes' in c['stats']]
    trq_th = float(np.mean(trq_th_vals)) if trq_th_vals else 42.0

    ax_quad.axvspan(cad_th, 130, ymin=trq_th/85, ymax=1.0, color='#f59e0b', alpha=0.07, label='QI: Sprint / Ataque')
    ax_quad.axvspan(30, cad_th, ymin=trq_th/85, ymax=1.0, color='#ec4899', alpha=0.07, label='QII: Escalada Dura')
    ax_quad.axvspan(30, cad_th, ymin=0, ymax=trq_th/85, color='#94a3b8', alpha=0.07, label='QIII: Recuperación')
    ax_quad.axvspan(cad_th, 130, ymin=0, ymax=trq_th/85, color='#38bdf8', alpha=0.07, label='QIV: Pelotón Ágil')
    ax_quad.axvline(cad_th, color='#cbd5e1', linestyle='--', linewidth=1.0)
    ax_quad.axhline(trq_th, color='#cbd5e1', linestyle='--', linewidth=1.0)

    for c in ciclistas_proc:
        pts = c['stats'].get('cuadrantes', {}).get('puntos', [])
        if pts:
            sub_pts = pts[::max(1, len(pts) // 250)]
            ax_quad.scatter([p['cad'] for p in sub_pts], [p['trq'] for p in sub_pts],
                            color=c['stats']['color'], alpha=0.65, s=14, edgecolors='none', label=c['stats']['nombre'])

    ax_quad.set_title("Diagrama de Cuadrantes (Coggan Quadrant Analysis)", fontsize=10.5, fontweight='bold', pad=8, color='#0f172a')
    ax_quad.set_xlabel("Cadencia de Pedaleo (rpm)", fontsize=8.5, fontweight='bold', color='#475569')
    ax_quad.set_ylabel("Torque en Bielas (N·m)", fontsize=8.5, fontweight='bold', color='#475569')
    ax_quad.set_xlim(30, 130)
    ax_quad.set_ylim(0, 85)
    ax_quad.grid(True, linestyle='--', alpha=0.3, color='#94a3b8')
    ax_quad.legend(loc='upper right', frameon=True, facecolor='#ffffff', edgecolor='#cbd5e1', fontsize=7.0, ncol=2)

    # Serie de Torque en el tiempo
    ax_trq = fig_bio.add_subplot(gs_b[1])
    _dibujar_perfil_fondo(ax_trq, perfil)
    for c in ciclistas_proc:
        samples = c.get('samples_by_dist', [])
        if samples:
            ax_trq.plot([s['d_km'] for s in samples], [s.get('trq', 0.0) for s in samples],
                        color=c['stats']['color'], linewidth=1.6, zorder=4,
                        label=f"{c['stats']['nombre']} (Med: {c['stats'].get('torque_media_nm', 0.0)} N·m)")
    _configurar_ejes(ax_trq, "Evolución de Torque en Bielas (N·m)", "Torque (N·m)")
    ax_trq.legend(loc='upper right', frameon=True, facecolor='#ffffff', edgecolor='#cbd5e1', fontsize=7.5, ncol=2)

    buf_bio = _figura_a_buffer(fig_bio)
    doc.add_picture(buf_bio, width=Inches(10.6))

    # =========================================================================
    # SECCIÓN 5: TABLA DE ESFUERZOS CRÍTICOS (MMP) Y DESGASTE PREVIO EN KILOJULIOS
    # =========================================================================
    doc.add_page_break()

    p_mmp = doc.add_paragraph()
    p_mmp.paragraph_format.space_before = Pt(0)
    p_mmp.paragraph_format.space_after = Pt(2)
    r_mmp = p_mmp.add_run("7. DINÁMICA DE PEDALEO Y ESFUERZOS CRÍTICOS (MMP CON KILOJULIOS PREVIOS)")
    r_mmp.bold = True
    r_mmp.font.size = Pt(11.0)
    r_mmp.font.color.rgb = RGBColor(30, 41, 59)

    p_desc = doc.add_paragraph()
    p_desc.paragraph_format.space_before = Pt(0)
    p_desc.paragraph_format.space_after = Pt(3)
    r_desc = p_desc.add_run(
        "Muestra la potencia media máxima generada en las duraciones clave, el porcentaje respecto al PR histórico All-Time, "
        "los kilojulios gastados ANTES de iniciar el esfuerzo y la insignia de durabilidad bajo fatiga acumulada."
    )
    r_desc.font.size = Pt(8.5)
    r_desc.font.color.rgb = RGBColor(100, 116, 139)

    duraciones_mmp = [5, 15, 30, 60, 180, 300, 600, 1200, 1800, 3600]
    duraciones_labels = ["5s", "15s", "30s", "1m", "3m", "5m", "10m", "20m", "30m", "60m"]

    cols_mmp = ["Ciclista", "Duración", "Potencia", "W/kg", "PR All-Time", "Desgaste Previo (kJ)", "kJ/kg Previos", "% Etapa", "Contexto / Durabilidad"]
    filas_mmp_datos = []

    for c in ciclistas_proc:
        nom = c['stats']['nombre']
        peso = c['stats'].get('peso_kg', 70.0)
        mmp_dict = c['stats'].get('curva_mmp_completa', {}) or c['stats'].get('potencia_mmp', {})

        comp_all_time = {}
        comp_raw = c.get('comparativa_picos', {})
        if isinstance(comp_raw, dict):
            for item in comp_raw.get('all_time', []):
                comp_all_time[item.get('segundos')] = item
        elif isinstance(comp_raw, list):
            for item in comp_raw:
                comp_all_time[item.get('segundos')] = item

        for d_sec, d_lbl in zip(duraciones_mmp, duraciones_labels):
            item = mmp_dict.get(d_sec)
            comp = comp_all_time.get(d_sec, {})

            if item is None:
                continue

            if isinstance(item, dict):
                watts = int(round(item.get('watts', 0)))
                wkg = item.get('wkg', watts / peso)
                kj_prev = item.get('kj_previos')
                kjkg_prev = item.get('kjkg_previos')
                pct_etapa = item.get('pct_etapa')
            else:
                watts = int(round(item))
                wkg = watts / peso
                kj_prev = comp.get('kj_act')
                kjkg_prev = comp.get('kjkg_act')
                pct_etapa = None

            if watts == 0:
                continue

            # Comparación con PR
            pct_pr = comp.get('pct_pr')
            es_pr = comp.get('es_pr', False)
            pr_val = comp.get('watts_ref')
            if pr_val and pr_val > 0:
                pr_str = f"{int(round(pr_val))} W ({pct_pr:.0f}%)" if pct_pr else f"{int(round(pr_val))} W"
                if es_pr:
                    pr_str = f"🏆 {pr_str} (PR)"
            else:
                pr_str = "--"

            # Desgaste previo
            kj_str = f"{int(round(kj_prev)):,} kJ".replace(',', '.') if kj_prev is not None else "--"
            kjkg_str = f"{kjkg_prev:.1f} kJ/kg" if kjkg_prev is not None else "--"
            pct_str = f"{pct_etapa:.0f}%" if pct_etapa is not None else "--"

            # Badge durabilidad
            badge_txt = comp.get('durabilidad_badge', {}).get('texto', '-') if comp.get('durabilidad_badge') else '-'
            if badge_txt == '-':
                if kj_prev is not None and kj_prev >= 2000:
                    badge_txt = "⚡ Alta Carga"
                elif kj_prev is not None and kj_prev < 800:
                    badge_txt = "❄️ Esfuerzo Fresco"

            filas_mmp_datos.append([
                nom, d_lbl, f"{watts} W", f"{wkg:.2f} W/kg", pr_str, kj_str, kjkg_str, pct_str, badge_txt
            ])

    tbl_mmp = doc.add_table(rows=len(filas_mmp_datos) + 1, cols=len(cols_mmp))
    tbl_mmp.alignment = WD_TABLE_ALIGNMENT.CENTER
    tbl_mmp.autofit = True

    _format_table_header(tbl_mmp.rows[0], cols_mmp, bg_color="1E293B", font_size_pt=8.0)

    for idx, f_vals in enumerate(filas_mmp_datos):
        _format_table_data_row(tbl_mmp.rows[idx + 1], f_vals, is_even=(idx % 2 == 1), font_size_pt=7.5)

    # =========================================================================
    # SECCIÓN 6: FISIOLOGÍA, BIENESTAR (WELLNESS) Y CARGA CRÓNICA
    # =========================================================================
    doc.add_page_break()

    p_wel = doc.add_paragraph()
    p_wel.paragraph_format.space_before = Pt(0)
    p_wel.paragraph_format.space_after = Pt(2)
    r_wel = p_wel.add_run("8. ESTADO FISIOLÓGICO, CARGA DE ENTRENAMIENTO (CTL/ATL/TSB) Y BIENESTAR")
    r_wel.bold = True
    r_wel.font.size = Pt(11.0)
    r_wel.font.color.rgb = RGBColor(30, 41, 59)

    cols_w = [
        "Ciclista", "CTL (Fitness)", "ATL (Fatiga)", "TSB (Forma)", "Readiness",
        "RMSSD (Día)", "RMSSD (7d)", "FC Reposo", "FC Reposo (7d)", "Peso", "Sueño"
    ]

    filas_w_datos = []
    for c in ciclistas_proc:
        nom = c['stats']['nombre']
        w = c.get('wellness_load', {})
        ctl_s = f"{w.get('ctl'):.1f}" if w.get('ctl') is not None else "-"
        atl_s = f"{w.get('atl'):.1f}" if w.get('atl') is not None else "-"
        tsb_s = f"{w.get('tsb'):+.1f}" if w.get('tsb') is not None else "-"
        readiness = w.get('status', {}).get('label', '-')
        hrv_dia = f"{w.get('hrv_rmssd'):.1f} ms" if w.get('hrv_rmssd') is not None else "-"
        hrv_7d = f"{w.get('hrv_media_7d'):.1f} ms" if w.get('hrv_media_7d') is not None else "-"
        rhr_dia = f"{w.get('resting_hr')} bpm" if w.get('resting_hr') is not None else "-"
        rhr_7d = f"{w.get('resting_hr_media_7d')} bpm" if w.get('resting_hr_media_7d') is not None else "-"
        peso_s = f"{w.get('weight'):.1f} kg" if w.get('weight') is not None else f"{c['stats']['peso_kg']} kg"
        sleep_s = f"{w.get('sleep_hours'):.1f} h" if w.get('sleep_hours') is not None else "-"

        filas_w_datos.append([
            nom, ctl_s, atl_s, tsb_s, readiness, hrv_dia, hrv_7d, rhr_dia, rhr_7d, peso_s, sleep_s
        ])

    tbl_wel = doc.add_table(rows=len(filas_w_datos) + 1, cols=len(cols_w))
    tbl_wel.alignment = WD_TABLE_ALIGNMENT.CENTER
    tbl_wel.autofit = True

    _format_table_header(tbl_wel.rows[0], cols_w, bg_color="0F172A", font_size_pt=8.0)
    for idx, f_vals in enumerate(filas_w_datos):
        _format_table_data_row(tbl_wel.rows[idx + 1], f_vals, is_even=(idx % 2 == 1), font_size_pt=8.0)

    doc.add_paragraph().paragraph_format.space_after = Pt(4)

    # Gráfico de Fisiología / CTL / ATL / HRV
    fig_w = plt.figure(figsize=(15.0, 6.0))
    fig_w.set_layout_engine('constrained')
    fig_w.patch.set_facecolor('#ffffff')
    gs_w = fig_w.add_gridspec(2, 1, height_ratios=[1, 1])

    # Carga CTL / ATL
    ax_load = fig_w.add_subplot(gs_w[0])
    tiene_carga = False
    for c in ciclistas_proc:
        w = c.get('wellness_load', {})
        hist = w.get('historial', [])
        if hist:
            df_h = pd.DataFrame(hist).dropna(subset=['fecha'])
            if not df_h.empty and 'ctl' in df_h.columns:
                df_h['fecha'] = pd.to_datetime(df_h['fecha'])
                df_h = df_h.sort_values('fecha')
                nom = c['stats']['nombre']
                col = c['stats']['color']
                ctl_last = df_h['ctl'].iloc[-1] if df_h['ctl'].notna().any() else 0
                atl_last = df_h['atl'].iloc[-1] if df_h['atl'].notna().any() else 0
                ax_load.plot(df_h['fecha'], df_h['ctl'], color=col, linewidth=2.0, label=f"{nom} (CTL: {ctl_last:.0f})")
                ax_load.plot(df_h['fecha'], df_h['atl'], color=col, linewidth=1.4, linestyle='--', alpha=0.75, label=f"{nom} (ATL: {atl_last:.0f})")
                tiene_carga = True

    if tiene_carga:
        _configurar_ejes(ax_load, "Evolución Temporal de Carga (CTL: Sólida | ATL: Discontinua) - 30 Días", "Puntos de Carga / Fitness", xlabel="Fecha")
        ax_load.legend(loc='upper right', frameon=True, facecolor='#ffffff', edgecolor='#cbd5e1', fontsize=7.5, ncol=2)
    else:
        ax_load.text(0.5, 0.5, "Sin registros de histórico CTL/ATL en la API para los atletas.", transform=ax_load.transAxes, ha='center', va='center', color='#94a3b8')
        ax_load.axis('off')

    # HRV
    ax_hrv = fig_w.add_subplot(gs_w[1])
    tiene_hrv = False
    for c in ciclistas_proc:
        w = c.get('wellness_load', {})
        hist = w.get('historial', [])
        if hist:
            df_h = pd.DataFrame(hist).dropna(subset=['fecha'])
            if not df_h.empty and 'hrv' in df_h.columns and df_h['hrv'].notna().any():
                df_h['fecha'] = pd.to_datetime(df_h['fecha'])
                df_h = df_h.sort_values('fecha').dropna(subset=['hrv'])
                nom = c['stats']['nombre']
                col = c['stats']['color']
                hrv_last = df_h['hrv'].iloc[-1]
                ax_hrv.plot(df_h['fecha'], df_h['hrv'], color=col, marker='o', markersize=3.5, linewidth=1.6, label=f"{nom} (RMSSD: {hrv_last:.1f} ms)")
                tiene_hrv = True

    if tiene_hrv:
        _configurar_ejes(ax_hrv, "Variabilidad Cardíaca Nocturna HRV RMSSD (ms) - 30 Días", "HRV RMSSD (ms)", xlabel="Fecha")
        ax_hrv.legend(loc='upper right', frameon=True, facecolor='#ffffff', edgecolor='#cbd5e1', fontsize=7.5, ncol=2)
    else:
        ax_hrv.text(0.5, 0.5, "Sin registros de histórico HRV en la API para los atletas.", transform=ax_hrv.transAxes, ha='center', va='center', color='#94a3b8')
        ax_hrv.axis('off')

    buf_w = _figura_a_buffer(fig_w)
    doc.add_picture(buf_w, width=Inches(10.6))

    # Guardar documento Word
    doc.save(str(output_docx))
    return output_docx


def generar_informe_potencias_y_carga_word(
    peaks_df: pd.DataFrame,
    tabla_peaks: pd.DataFrame,
    metrics_df: pd.DataFrame,
    output_docx: Optional[Union[str, Path]] = None,
    logo_path: Optional[Union[str, Path]] = None,
    titulo: Optional[str] = None,
    subtitulo: Optional[str] = None,
    grupo_carrera: Optional[Union[int, str]] = None,
) -> Path:
    """
    Genera el documento Word (.docx) de 2 páginas con el informe de picos de potencia y evolución de carga (CTL/ATL/TSB).
    Incluye gráficos en alta resolución y tablas nativas editables con resaltado semafórico de PRs y zonas de forma.
    """
    if output_docx is None:
        label = f"_carrera_{grupo_carrera}" if grupo_carrera else ""
        output_docx = OUTPUT_DIR / f"intervals_informe{label}.docx"
    else:
        output_docx = Path(output_docx)

    output_docx.parent.mkdir(parents=True, exist_ok=True)

    # Inicializar Documento Word
    doc = Document()

    # Configuración Horizontal A4 (Landscape) con márgenes 0.5"
    section = doc.sections[0]
    section.orientation = WD_ORIENTATION.LANDSCAPE
    section.page_width = Inches(11.69)
    section.page_height = Inches(8.27)
    section.top_margin = Inches(0.5)
    section.bottom_margin = Inches(0.5)
    section.left_margin = Inches(0.5)
    section.right_margin = Inches(0.5)

    # Estilos
    style_normal = doc.styles['Normal']
    style_normal.font.name = 'Calibri'
    style_normal.font.size = Pt(9.5)
    style_normal.font.color.rgb = RGBColor(30, 41, 59)

    header = section.header
    hp = header.paragraphs[0]
    hp.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    hrun = hp.add_run("BURGOS BH • INTERVALS FIT ANALYTICS | INFORME DE POTENCIAS Y CARGA")
    hrun.font.name = "Calibri"
    hrun.font.size = Pt(7.5)
    hrun.font.color.rgb = RGBColor(148, 163, 184)

    footer = section.footer
    fp = footer.paragraphs[0]
    fp.alignment = WD_ALIGN_PARAGRAPH.CENTER
    frun = fp.add_run(f"Generado el {datetime.now().strftime('%Y-%m-%d %H:%M')} • Documento Confidencial de Rendimiento Deportivo")
    frun.font.name = "Calibri"
    frun.font.size = Pt(7.5)
    frun.font.color.rgb = RGBColor(148, 163, 184)

    # Resolver Logo
    logo_file = Path(logo_path) if logo_path else DEFAULT_LOGO_PATH
    if not logo_file.exists() or logo_file.suffix.lower() == '.svg':
        png_cand = logo_file.with_suffix('.png')
        if png_cand.exists():
            logo_file = png_cand

    # Títulos
    if titulo:
        tit_pot = titulo
        tit_carga = f"{titulo} - Carga, Fatiga y Forma"
    elif grupo_carrera:
        tit_pot = f"Informe de Potencias - Carrera {grupo_carrera}"
        tit_carga = f"Informe de Carga, Fatiga y Forma - Carrera {grupo_carrera}"
    else:
        tit_pot = "Informe de Potencias"
        tit_carga = "Informe de Carga, Fatiga y Forma"

    sub_pot = subtitulo or "Gráfico de picos relativos (30 días vs Récord Histórico PR) y tabla resumen"
    sub_carga = "Evolución de CTL (Fitness), ATL (Fatiga) y TSB (Zonas de Forma) por ciclista"

    # =========================================================================
    # PÁGINA 1: PICOS DE POTENCIA (GRÁFICO + TABLA COMPARATIVA)
    # =========================================================================
    tbl_hdr = doc.add_table(rows=1, cols=2)
    tbl_hdr.alignment = WD_TABLE_ALIGNMENT.CENTER
    tbl_hdr.autofit = False
    tbl_hdr.columns[0].width = Inches(2.2)
    tbl_hdr.columns[1].width = Inches(8.4)

    c_logo = tbl_hdr.cell(0, 0)
    c_logo.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
    p_logo = c_logo.paragraphs[0]
    p_logo.alignment = WD_ALIGN_PARAGRAPH.LEFT
    if logo_file.exists() and logo_file.suffix.lower() == '.png':
        try:
            p_logo.add_run().add_picture(str(logo_file), width=Inches(1.8))
        except Exception:
            p_logo.add_run("BURGOS BH").bold = True
    else:
        p_logo.add_run("BURGOS BH").bold = True

    c_tit = tbl_hdr.cell(0, 1)
    c_tit.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
    p_tit = c_tit.paragraphs[0]
    p_tit.paragraph_format.space_before = Pt(0)
    p_tit.paragraph_format.space_after = Pt(2)
    r_t = p_tit.add_run(tit_pot)
    r_t.bold = True
    r_t.font.size = Pt(15.0)
    r_t.font.color.rgb = RGBColor(88, 28, 135)

    p_sub = c_tit.add_paragraph()
    p_sub.paragraph_format.space_before = Pt(0)
    p_sub.paragraph_format.space_after = Pt(2)
    r_s = p_sub.add_run(sub_pot)
    r_s.font.size = Pt(9.5)
    r_s.font.color.rgb = RGBColor(71, 85, 105)

    doc.add_paragraph().paragraph_format.space_after = Pt(2)

    # Gráfico de barras de picos de potencia
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

    if not pivot_pdf.empty:
        pivot_hist = pd.DataFrame()
        if not plot_df.empty and 'all_time_wkg' in plot_df.columns:
            pivot_hist = plot_df.pivot_table(
                index='duration_label',
                columns='athlete_name',
                values='all_time_wkg',
                aggfunc='max'
            ).reindex(orden_duraciones)

        fig_pwr = plt.figure(figsize=(15.0, 4.2))
        fig_pwr.set_layout_engine('constrained')
        fig_pwr.patch.set_facecolor('#ffffff')
        ax_p = fig_pwr.add_subplot(1, 1, 1)

        pivot_pdf.plot(kind='bar', ax=ax_p, width=0.80)
        ax_p.set_title('Mejores picos de potencia relativos (W/kg) - últimos 30 días vs Récord Histórico PR', fontsize=11, fontweight='bold', color='#1e293b', pad=8)
        ax_p.set_xlabel('Duración del Esfuerzo Crítico', fontsize=8.5, fontweight='bold', color='#475569')
        ax_p.set_ylabel('Potencia Relativa (W/kg)', fontsize=8.5, fontweight='bold', color='#475569')
        ax_p.grid(axis='y', alpha=0.35, linestyle='--', color='#cbd5e1')
        ax_p.tick_params(axis='x', rotation=0, labelsize=8.5)

        if not pivot_hist.empty:
            for j, container in enumerate(ax_p.containers):
                if j < len(pivot_pdf.columns):
                    ath = pivot_pdf.columns[j]
                    for i, bar in enumerate(container):
                        if i < len(pivot_pdf.index):
                            dur = pivot_pdf.index[i]
                            h_val = pivot_hist.loc[dur, ath] if ath in pivot_hist.columns else None
                            if pd.notna(h_val) and h_val > 0:
                                x_center = bar.get_x() + bar.get_width() / 2.0
                                w_half = bar.get_width() * 0.52
                                ax_p.plot([x_center - w_half, x_center + w_half], [h_val, h_val], color='#d97706', linewidth=2.2, zorder=5)
                                b_val = bar.get_height()
                                if b_val >= h_val:
                                    ax_p.text(x_center, max(b_val, h_val) + 0.16, "PR", ha='center', va='bottom', fontsize=6.5, fontweight='bold', color='#166534')
                                else:
                                    pct = (b_val / h_val) * 100.0
                                    ax_p.text(x_center, max(b_val, h_val) + 0.12, f"{pct:.0f}%", ha='center', va='bottom', fontsize=6.0, color='#64748b')

        ax_p.legend(title='Ciclista (Línea ámbar = Récord PR Histórico)', bbox_to_anchor=(0.5, -0.18), loc='upper center', ncol=min(6, len(pivot_pdf.columns)), fontsize=8.0)
        buf_pwr = _figura_a_buffer(fig_pwr)
        doc.add_picture(buf_pwr, width=Inches(10.6))

    # Tabla de picos comparativa
    tabla_pdf = tabla_peaks.fillna('').astype(str) if not tabla_peaks.empty else pd.DataFrame()
    if not tabla_pdf.empty:
        p_tbl_title = doc.add_paragraph()
        p_tbl_title.paragraph_format.space_before = Pt(4)
        p_tbl_title.paragraph_format.space_after = Pt(3)
        r_tt = p_tbl_title.add_run("TABLA COMPARATIVA DE POTENCIAS (30 DÍAS VS RÉCORD HISTÓRICO)")
        r_tt.bold = True
        r_tt.font.size = Pt(10.0)
        r_tt.font.color.rgb = RGBColor(30, 41, 59)

        cols_table = ["Duración"] + [f"{c[0]} ({c[1]})" if isinstance(c, tuple) else str(c) for c in tabla_pdf.columns]
        tbl_word = doc.add_table(rows=len(tabla_pdf.index) + 1, cols=len(cols_table))
        tbl_word.alignment = WD_TABLE_ALIGNMENT.CENTER
        tbl_word.autofit = True

        _format_table_header(tbl_word.rows[0], cols_table, bg_color="0F172A", font_size_pt=8.0)

        for row_idx, dur in enumerate(tabla_pdf.index):
            row = tbl_word.rows[row_idx + 1]
            c0 = row.cells[0]
            _set_cell_background(c0, "F1F5F9")
            _set_cell_padding(c0, top=80, bottom=80, left=90, right=90)
            _set_cell_borders(c0, color="CBD5E1", sz="4")
            c0.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
            p0 = c0.paragraphs[0]
            p0.alignment = WD_ALIGN_PARAGRAPH.CENTER
            r0 = p0.add_run(str(dur))
            r0.bold = True
            r0.font.name = "Calibri"
            r0.font.size = Pt(8.0)
            r0.font.color.rgb = RGBColor(15, 23, 42)

            for col_idx, col_name in enumerate(tabla_pdf.columns):
                val_txt = str(tabla_pdf.loc[dur, col_name])
                cell = row.cells[col_idx + 1]

                bg_hex = "FFFFFF" if row_idx % 2 == 0 else "F8FAFC"
                txt_color = RGBColor(51, 65, 85)
                is_bold = False

                if '🏆PR' in val_txt or '100% PR' in val_txt:
                    bg_hex = "DCFCE7"
                    txt_color = RGBColor(22, 101, 52)
                    is_bold = True
                elif any(f"{p}% PR" in val_txt for p in range(95, 100)):
                    bg_hex = "ECFDF5"
                    txt_color = RGBColor(4, 120, 87)
                    is_bold = True
                elif any(f"{p}% PR" in val_txt for p in range(85, 95)):
                    bg_hex = "FEF3C7"
                    txt_color = RGBColor(146, 64, 14)
                elif any(f"{p}% PR" in val_txt for p in range(0, 85)):
                    bg_hex = "FEE2E2"
                    txt_color = RGBColor(153, 27, 27)

                _set_cell_background(cell, bg_hex)
                _set_cell_padding(cell, top=80, bottom=80, left=90, right=90)
                _set_cell_borders(cell, color="CBD5E1", sz="4")
                cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER

                p = cell.paragraphs[0]
                p.alignment = WD_ALIGN_PARAGRAPH.CENTER
                p.paragraph_format.space_before = Pt(0)
                p.paragraph_format.space_after = Pt(0)
                run = p.add_run(val_txt)
                run.font.name = "Calibri"
                run.font.size = Pt(7.5)
                run.bold = is_bold
                run.font.color.rgb = txt_color

    # =========================================================================
    # PÁGINA 2: EVOLUCIÓN DE CARGA, FATIGA Y FORMA (CTL / ATL / TSB)
    # =========================================================================
    if not metrics_df.empty:
        doc.add_page_break()

        tbl_hdr2 = doc.add_table(rows=1, cols=2)
        tbl_hdr2.alignment = WD_TABLE_ALIGNMENT.CENTER
        tbl_hdr2.autofit = False
        tbl_hdr2.columns[0].width = Inches(2.2)
        tbl_hdr2.columns[1].width = Inches(8.4)

        c_logo2 = tbl_hdr2.cell(0, 0)
        c_logo2.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
        p_logo2 = c_logo2.paragraphs[0]
        p_logo2.alignment = WD_ALIGN_PARAGRAPH.LEFT
        if logo_file.exists() and logo_file.suffix.lower() == '.png':
            try:
                p_logo2.add_run().add_picture(str(logo_file), width=Inches(1.8))
            except Exception:
                p_logo2.add_run("BURGOS BH").bold = True
        else:
            p_logo2.add_run("BURGOS BH").bold = True

        c_tit2 = tbl_hdr2.cell(0, 1)
        c_tit2.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
        p_tit2 = c_tit2.paragraphs[0]
        p_tit2.paragraph_format.space_before = Pt(0)
        p_tit2.paragraph_format.space_after = Pt(2)
        r_t2 = p_tit2.add_run(tit_carga)
        r_t2.bold = True
        r_t2.font.size = Pt(15.0)
        r_t2.font.color.rgb = RGBColor(88, 28, 135)

        p_sub2 = c_tit2.add_paragraph()
        p_sub2.paragraph_format.space_before = Pt(0)
        p_sub2.paragraph_format.space_after = Pt(2)
        r_s2 = p_sub2.add_run(sub_carga)
        r_s2.font.size = Pt(9.5)
        r_s2.font.color.rgb = RGBColor(71, 85, 105)

        doc.add_paragraph().paragraph_format.space_after = Pt(2)

        # Gráfico Multi-Panel de Carga
        nombres_metricas = sorted(metrics_df['athlete_name'].dropna().unique())
        palette = plt.cm.tab20.colors if len(nombres_metricas) > 10 else plt.cm.tab10.colors
        color_map_doc = {nombre: palette[i % len(palette)] for i, nombre in enumerate(nombres_metricas)}

        fig_load = plt.figure(figsize=(15.0, 5.0))
        fig_load.set_layout_engine('constrained')
        fig_load.patch.set_facecolor('#ffffff')
        gs_l = fig_load.add_gridspec(3, 1, height_ratios=[1, 1, 1])

        # 1. CTL
        ax_ctl = fig_load.add_subplot(gs_l[0])
        for nombre, g in metrics_df.groupby('athlete_name'):
            g_sorted = g.sort_values('fecha').reset_index(drop=True)
            last_row = g_sorted.iloc[-1]
            color = color_map_doc.get(nombre, '#3b82f6')
            ax_ctl.plot(g_sorted['fecha'], g_sorted['ctl'], linewidth=1.8, color=color, label=f"{nombre} ({last_row['ctl']:.0f})")
        ax_ctl.set_title('CTL por Ciclista (Forma / Fitness acumulado)', fontsize=9.5, fontweight='bold', color='#1e293b')
        ax_ctl.set_ylabel('CTL', fontsize=8.0, fontweight='bold', color='#475569')
        ax_ctl.grid(True, alpha=0.35, linestyle='--', color='#cbd5e1')
        ax_ctl.legend(bbox_to_anchor=(1.01, 1), loc='upper left', fontsize=7.0, frameon=True, facecolor='#ffffff', edgecolor='#cbd5e1')

        # 2. ATL
        ax_atl = fig_load.add_subplot(gs_l[1], sharex=ax_ctl)
        for nombre, g in metrics_df.groupby('athlete_name'):
            g_sorted = g.sort_values('fecha').reset_index(drop=True)
            last_row = g_sorted.iloc[-1]
            color = color_map_doc.get(nombre, '#3b82f6')
            ax_atl.plot(g_sorted['fecha'], g_sorted['atl'], linewidth=1.8, linestyle='--', color=color, label=f"{nombre} ({last_row['atl']:.0f})")
        ax_atl.set_title('ATL por Ciclista (Fatiga aguda)', fontsize=9.5, fontweight='bold', color='#1e293b')
        ax_atl.set_ylabel('ATL', fontsize=8.0, fontweight='bold', color='#475569')
        ax_atl.grid(True, alpha=0.35, linestyle='--', color='#cbd5e1')
        ax_atl.legend(bbox_to_anchor=(1.01, 1), loc='upper left', fontsize=7.0, frameon=True, facecolor='#ffffff', edgecolor='#cbd5e1')

        # 3. TSB
        ax_tsb = fig_load.add_subplot(gs_l[2], sharex=ax_ctl)
        ax_tsb.axhspan(15, 60, color='#10b981', alpha=0.12, zorder=1)
        ax_tsb.axhspan(5, 15, color='#38bdf8', alpha=0.12, zorder=1)
        ax_tsb.axhspan(-10, 5, color='#818cf8', alpha=0.08, zorder=1)
        ax_tsb.axhspan(-30, -10, color='#f59e0b', alpha=0.12, zorder=1)
        ax_tsb.axhspan(-70, -30, color='#ef4444', alpha=0.12, zorder=1)
        ax_tsb.axhline(0, color='#64748b', linestyle=':', linewidth=0.9, alpha=0.7, zorder=1)

        ax_tsb.text(0.99, 0.90, "Muy Fresco (> +15)", transform=ax_tsb.transAxes, ha='right', va='center', fontsize=6.5, fontweight='bold', color='#059669', alpha=0.9)
        ax_tsb.text(0.99, 0.72, "Fresco / Competición (+5 a +15)", transform=ax_tsb.transAxes, ha='right', va='center', fontsize=6.5, fontweight='bold', color='#0284c7', alpha=0.9)
        ax_tsb.text(0.99, 0.52, "Neutro / Balance (-10 a +5)", transform=ax_tsb.transAxes, ha='right', va='center', fontsize=6.5, fontweight='bold', color='#6366f1', alpha=0.9)
        ax_tsb.text(0.99, 0.32, "Fatiga Productiva (-30 a -10)", transform=ax_tsb.transAxes, ha='right', va='center', fontsize=6.5, fontweight='bold', color='#d97706', alpha=0.9)
        ax_tsb.text(0.99, 0.12, "Sobrecarga (< -30)", transform=ax_tsb.transAxes, ha='right', va='center', fontsize=6.5, fontweight='bold', color='#dc2626', alpha=0.9)

        for nombre, g in metrics_df.groupby('athlete_name'):
            g_sorted = g.sort_values('fecha').reset_index(drop=True)
            if 'tsb' in g_sorted.columns:
                last_row = g_sorted.iloc[-1]
                color = color_map_doc.get(nombre, '#3b82f6')
                ax_tsb.plot(g_sorted['fecha'], g_sorted['tsb'], linewidth=2.0, color=color, label=f"{nombre} ({last_row['tsb']:+.0f})")

        ax_tsb.set_title('TSB por Ciclista (Forma / Balance con Zonas Fisiológicas)', fontsize=9.5, fontweight='bold', color='#1e293b')
        ax_tsb.set_ylabel('TSB', fontsize=8.0, fontweight='bold', color='#475569')
        ax_tsb.grid(True, alpha=0.35, linestyle='--', color='#cbd5e1')
        ax_tsb.legend(bbox_to_anchor=(1.01, 1), loc='upper left', fontsize=7.0, frameon=True, facecolor='#ffffff', edgecolor='#cbd5e1')

        fig_load.autofmt_xdate()
        buf_load = _figura_a_buffer(fig_load)
        doc.add_picture(buf_load, width=Inches(10.6))

        # Tabla Resumen de Carga y Forma
        p_tbl_load = doc.add_paragraph()
        p_tbl_load.paragraph_format.space_before = Pt(4)
        p_tbl_load.paragraph_format.space_after = Pt(3)
        r_tl = p_tbl_load.add_run("RESUMEN DE ESTADO Y ZONAS DE FORMA ACTUALES")
        r_tl.bold = True
        r_tl.font.size = Pt(10.0)
        r_tl.font.color.rgb = RGBColor(30, 41, 59)

        cols_carga_res = ["Ciclista", "CTL Actual (Fitness)", "ATL Actual (Fatiga)", "TSB Actual (Forma)", "Zona / Estado Fisiológico", "Ramp Rate (7d)"]
        filas_carga = []
        for nombre, g in metrics_df.groupby('athlete_name'):
            g_sorted = g.sort_values('fecha').reset_index(drop=True)
            last = g_sorted.iloc[-1]
            tsb_val = float(last.get('tsb', 0.0))
            if tsb_val >= 15:
                zona_str = "🟢 Muy Fresco"
            elif tsb_val >= 5:
                zona_str = "🔵 Fresco / Competición"
            elif tsb_val >= -10:
                zona_str = "🟣 Neutro / Balance"
            elif tsb_val >= -30:
                zona_str = "🟠 Fatiga Productiva"
            else:
                zona_str = "🔴 Sobrecarga"

            ramp_str = f"{last.get('ramp_rate_7d'):+.1f}" if pd.notnull(last.get('ramp_rate_7d')) else "-"
            filas_carga.append([
                nombre,
                f"{float(last.get('ctl', 0.0)):.1f}",
                f"{float(last.get('atl', 0.0)):.1f}",
                f"{tsb_val:+.1f}",
                zona_str,
                ramp_str
            ])

        tbl_carga = doc.add_table(rows=len(filas_carga) + 1, cols=len(cols_carga_res))
        tbl_carga.alignment = WD_TABLE_ALIGNMENT.CENTER
        tbl_carga.autofit = True

        _format_table_header(tbl_carga.rows[0], cols_carga_res, bg_color="1E293B", font_size_pt=8.0)
        for r_idx, vals in enumerate(filas_carga):
            _format_table_data_row(tbl_carga.rows[r_idx + 1], vals, is_even=(r_idx % 2 == 1), font_size_pt=8.0)

    doc.save(str(output_docx))
    return output_docx

