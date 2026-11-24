"""Entregables del módulo comercial (§11.12): Word, HTML imprimible, Excel y PDF.

Todos se construyen desde un mismo `Documento` (secciones con párrafos y tablas) que arma el
servicio con las cifras de los análisis: así el oficio, el anexo y el informe dan la misma cifra
que el tablero (coherencia obligatoria).
"""

import datetime as dt
import html
import io
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from docx import Document as DocumentoWord
from docx.shared import Pt
from fpdf import FPDF
from openpyxl import Workbook
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter


@dataclass
class Tabla:
    encabezados: list[str]
    filas: list[list[Any]]


@dataclass
class Seccion:
    titulo: str
    parrafos: list[str] = field(default_factory=list)
    tabla: Tabla | None = None


@dataclass
class Documento:
    titulo: str
    subtitulo: str
    secciones: list[Seccion]
    pie: str = (
        "Generado por SAPEF. Cifras calculadas sobre los archivos entregados por el operador."
    )


def formato(valor: Any) -> str:
    """Números al estilo colombiano (1.234.567,89); fechas ISO; None como guion."""
    if valor is None:
        return "—"
    if isinstance(valor, bool):
        return "Sí" if valor else "No"
    if isinstance(valor, int):
        return f"{valor:,}".replace(",", ".")
    if isinstance(valor, (Decimal, float)):
        texto = f"{Decimal(str(valor)):,.2f}"
        return texto.replace(",", "§").replace(".", ",").replace("§", ".")
    if isinstance(valor, (dt.date, dt.datetime)):
        return valor.isoformat()[:10]
    return str(valor)


# --- Word -----------------------------------------------------------------------------------------


def a_docx(doc: Documento) -> bytes:
    word = DocumentoWord()
    estilo = word.styles["Normal"]
    estilo.font.name = "Calibri"
    estilo.font.size = Pt(10)
    word.add_heading(doc.titulo, level=0)
    word.add_paragraph(doc.subtitulo)
    for seccion in doc.secciones:
        word.add_heading(seccion.titulo, level=1)
        for parrafo in seccion.parrafos:
            word.add_paragraph(parrafo)
        if seccion.tabla and seccion.tabla.filas:
            tabla = word.add_table(rows=1, cols=len(seccion.tabla.encabezados))
            tabla.style = "Light Grid Accent 1"
            for i, encabezado in enumerate(seccion.tabla.encabezados):
                tabla.rows[0].cells[i].text = encabezado
            for fila in seccion.tabla.filas:
                celdas = tabla.add_row().cells
                for i, valor in enumerate(fila):
                    celdas[i].text = formato(valor)
    word.add_paragraph(doc.pie).italic = True
    salida = io.BytesIO()
    word.save(salida)
    return salida.getvalue()


# --- HTML imprimible ------------------------------------------------------------------------------


def a_html(doc: Documento) -> str:
    partes = [
        "<!doctype html><html lang='es'><head><meta charset='utf-8'>",
        f"<title>{html.escape(doc.titulo)}</title>",
        "<style>body{font-family:Segoe UI,Arial,sans-serif;font-size:12px;margin:24px;color:#111}"
        "h1{font-size:20px}h2{font-size:15px;margin-top:22px;border-bottom:1px solid #ccc}"
        "table{border-collapse:collapse;width:100%;margin:8px 0}"
        "th,td{border:1px solid #bbb;padding:3px 6px;text-align:left}"
        "td.n{text-align:right}th{background:#f3f3f3}"
        "@media print{body{margin:0}}</style></head><body>",
        f"<h1>{html.escape(doc.titulo)}</h1><p>{html.escape(doc.subtitulo)}</p>",
    ]
    for seccion in doc.secciones:
        partes.append(f"<h2>{html.escape(seccion.titulo)}</h2>")
        partes.extend(f"<p>{html.escape(p)}</p>" for p in seccion.parrafos)
        if seccion.tabla and seccion.tabla.filas:
            partes.append("<table><thead><tr>")
            partes.extend(f"<th>{html.escape(e)}</th>" for e in seccion.tabla.encabezados)
            partes.append("</tr></thead><tbody>")
            for fila in seccion.tabla.filas:
                partes.append("<tr>")
                for valor in fila:
                    clase = " class='n'" if isinstance(valor, (int, float, Decimal)) else ""
                    partes.append(f"<td{clase}>{html.escape(formato(valor))}</td>")
                partes.append("</tr>")
            partes.append("</tbody></table>")
    partes.append(f"<p><em>{html.escape(doc.pie)}</em></p></body></html>")
    return "".join(partes)


# --- PDF ------------------------------------------------------------------------------------------

_REEMPLAZOS = {
    "—": "-",
    "–": "-",
    "“": '"',
    "”": '"',
    "‘": "'",
    "’": "'",
    "≥": ">=",
    "≤": "<=",
    "…": "...",
    "•": "-",
    "→": "->",
    "×": "x",
    "÷": "/",
    "€": "EUR",
    " ": " ",
}


def _latin1(texto: str) -> str:
    for origen, destino in _REEMPLAZOS.items():
        texto = texto.replace(origen, destino)
    return texto.encode("latin-1", "replace").decode("latin-1")


class _Pdf(FPDF):
    def __init__(self, titulo: str, pie: str) -> None:
        super().__init__(orientation="L", format="A4")
        self._titulo = titulo
        self._pie = pie
        self.set_auto_page_break(auto=True, margin=15)
        self.set_margins(12, 12, 12)

    def header(self) -> None:
        self.set_font("Helvetica", "B", 9)
        self.set_text_color(90)
        self.cell(0, 6, _latin1(self._titulo), new_x="LMARGIN", new_y="NEXT")
        self.set_text_color(0)

    def footer(self) -> None:
        self.set_y(-12)
        self.set_font("Helvetica", "I", 7)
        self.set_text_color(110)
        self.cell(0, 5, _latin1(f"{self._pie}  ·  Página {self.page_no()}"), align="C")


def a_pdf(doc: Documento) -> bytes:
    pdf = _Pdf(doc.titulo, doc.pie)
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 16)
    pdf.multi_cell(0, 8, _latin1(doc.titulo), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)
    pdf.multi_cell(0, 5, _latin1(doc.subtitulo), new_x="LMARGIN", new_y="NEXT")
    for numero, seccion in enumerate(doc.secciones, start=1):
        pdf.ln(3)
        pdf.set_font("Helvetica", "B", 12)
        pdf.multi_cell(0, 6, _latin1(f"{numero}. {seccion.titulo}"), new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 9)
        for parrafo in seccion.parrafos:
            pdf.multi_cell(0, 4.5, _latin1(parrafo), new_x="LMARGIN", new_y="NEXT")
        if seccion.tabla and seccion.tabla.filas:
            pdf.set_font("Helvetica", "", 7)
            with pdf.table(
                first_row_as_headings=True,
                line_height=4,
                text_align="LEFT",
                borders_layout="SINGLE_TOP_LINE",
            ) as tabla:
                fila = tabla.row()
                for encabezado in seccion.tabla.encabezados:
                    fila.cell(_latin1(encabezado))
                for valores in seccion.tabla.filas:
                    fila = tabla.row()
                    for valor in valores:
                        fila.cell(_latin1(formato(valor)))
    return bytes(pdf.output())


# --- Excel ----------------------------------------------------------------------------------------


def a_xlsx(hojas: dict[str, Tabla]) -> bytes:
    libro = Workbook()
    libro.remove(libro.active)  # type: ignore[arg-type]
    for nombre, tabla in hojas.items():
        hoja = libro.create_sheet(nombre[:31])
        hoja.append(tabla.encabezados)
        for celda in hoja[1]:
            celda.font = Font(bold=True)
        for fila in tabla.filas:
            hoja.append(
                [
                    float(v)
                    if isinstance(v, Decimal)
                    else v.isoformat()[:10]
                    if isinstance(v, (dt.date, dt.datetime))
                    else v
                    for v in fila
                ]
            )
        for i, encabezado in enumerate(tabla.encabezados, start=1):
            hoja.column_dimensions[get_column_letter(i)].width = max(
                12, min(40, len(encabezado) + 4)
            )
        hoja.freeze_panes = "A2"
    if not libro.sheetnames:
        libro.create_sheet("Vacío").append(["Sin datos"])
    salida = io.BytesIO()
    libro.save(salida)
    return salida.getvalue()
