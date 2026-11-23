"""Zero-dependency OOXML (.xlsx) writer and reader using stdlib zipfile + ElementTree.

Supports multiple sheets, numeric/Decimal/string/bool/date cells, and genuine Excel
formula injection (<f>...</f>) for Tier 2 validation/rejection tests.
"""

from __future__ import annotations

import datetime as dt
import io
import zipfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape

_EXCEL_EPOCH = dt.date(1899, 12, 30)
_NS_MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_NS_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_NS_PKG_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
_NS_CT = "http://schemas.openxmlformats.org/package/2006/content-types"


@dataclass(frozen=True)
class FormulaCell:
    """Explicit OOXML formula cell (<f>formula</f>) with optional cached value."""

    formula: str
    cached_value: int | float | str | None = None


@dataclass(frozen=True)
class XlsxSheet:
    """Worksheet definition for build_xlsx_bytes."""

    name: str
    rows: Sequence[Sequence[Any]]


def _col_letter(idx_1based: int) -> str:
    chars: list[str] = []
    n = idx_1based
    while n > 0:
        n, rem = divmod(n - 1, 26)
        chars.append(chr(ord("A") + rem))
    return "".join(reversed(chars))


def _col_index(col_ref: str) -> int:
    idx = 0
    for ch in col_ref:
        if "A" <= ch <= "Z":
            idx = idx * 26 + (ord(ch) - ord("A") + 1)
    return idx


def _split_cell_ref(ref: str) -> tuple[int, int]:
    letters = []
    digits = []
    for ch in ref:
        if ch.isalpha():
            letters.append(ch.upper())
        elif ch.isdigit():
            digits.append(ch)
    return int("".join(digits)), _col_index("".join(letters))


def _excel_serial_date(value: dt.date | dt.datetime) -> float:
    if isinstance(value, dt.datetime):
        delta = value.date() - _EXCEL_EPOCH
        frac = (value.hour * 3600 + value.minute * 60 + value.second) / 86400.0
        return float(delta.days) + frac
    return float((value - _EXCEL_EPOCH).days)


def _xml_safe_text(text: str) -> str:
    return escape(text, {'"': "&quot;", "'": "&apos;"})


def _render_cell(
    ref: str,
    val: Any,
    *,
    allow_formula_strings: bool,
) -> str:
    if val is None:
        return ""
    if isinstance(val, FormulaCell):
        formula = val.formula.lstrip("=")
        cached = (
            f"<v>{_xml_safe_text(str(val.cached_value))}</v>"
            if val.cached_value is not None
            else ""
        )
        return f'<c r="{ref}"><f>{_xml_safe_text(formula)}</f>{cached}</c>'
    if isinstance(val, str) and allow_formula_strings and val.startswith("=") and len(val) > 1:
        formula = val[1:]
        return f'<c r="{ref}"><f>{_xml_safe_text(formula)}</f></c>'
    if isinstance(val, bool):
        return f'<c r="{ref}" t="b"><v>{1 if val else 0}</v></c>'
    if isinstance(val, (int, float, Decimal)):
        return f'<c r="{ref}"><v>{val}</v></c>'
    if isinstance(val, (dt.datetime, dt.date)):
        serial = _excel_serial_date(val)
        return f'<c r="{ref}" s="1"><v>{serial}</v></c>'
    text = str(val)
    space_attr = ' xml:space="preserve"' if (text.startswith(" ") or text.endswith(" ")) else ""
    return f'<c r="{ref}" t="inlineStr"><is><t{space_attr}>{_xml_safe_text(text)}</t></is></c>'


def _build_worksheet_xml(rows: Sequence[Sequence[Any]], *, allow_formula_strings: bool) -> str:
    row_xml: list[str] = []
    for r_idx, row in enumerate(rows, start=1):
        cells_xml: list[str] = []
        for c_idx, val in enumerate(row, start=1):
            if val is None:
                continue
            ref = f"{_col_letter(c_idx)}{r_idx}"
            cell = _render_cell(ref, val, allow_formula_strings=allow_formula_strings)
            if cell:
                cells_xml.append(cell)
        row_xml.append(f'<row r="{r_idx}">{"".join(cells_xml)}</row>')

    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<worksheet xmlns="{_NS_MAIN}">'
        f"<sheetData>{''.join(row_xml)}</sheetData>"
        "</worksheet>"
    )


def build_xlsx_bytes(
    sheets: Sequence[XlsxSheet] | Mapping[str, Sequence[Sequence[Any]]],
    *,
    allow_formula_strings: bool = True,
) -> bytes:
    """Build a valid OOXML .xlsx archive in memory with zero external dependencies."""
    if isinstance(sheets, Mapping):
        sheet_list = [XlsxSheet(name=k, rows=v) for k, v in sheets.items()]
    else:
        sheet_list = list(sheets)

    if not sheet_list:
        sheet_list = [XlsxSheet(name="Sheet1", rows=[])]

    content_types_overrides = [
        (
            '<Override PartName="/xl/workbook.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.'
            'spreadsheetml.sheet.main+xml"/>'
        ),
        (
            '<Override PartName="/xl/styles.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.'
            'spreadsheetml.styles+xml"/>'
        ),
    ]
    workbook_sheets_xml: list[str] = []
    workbook_rels_xml: list[str] = []

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for idx, sheet in enumerate(sheet_list, start=1):
            safe_name = sheet.name[:31] or f"Sheet{idx}"
            sheet_path = f"xl/worksheets/sheet{idx}.xml"
            zf.writestr(
                sheet_path,
                _build_worksheet_xml(
                    sheet.rows,
                    allow_formula_strings=allow_formula_strings,
                ).encode("utf-8"),
            )
            content_types_overrides.append(
                f'<Override PartName="/{sheet_path}" '
                'ContentType="application/vnd.openxmlformats-officedocument.'
                'spreadsheetml.worksheet+xml"/>'
            )
            workbook_sheets_xml.append(
                f'<sheet name="{_xml_safe_text(safe_name)}" sheetId="{idx}" r:id="rId{idx}"/>'
            )
            workbook_rels_xml.append(
                f'<Relationship Id="rId{idx}" '
                'Type="http://schemas.openxmlformats.org/officeDocument/2006/'
                'relationships/worksheet" '
                f'Target="worksheets/sheet{idx}.xml"/>'
            )

        style_rid = len(sheet_list) + 1
        workbook_rels_xml.append(
            f'<Relationship Id="rId{style_rid}" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" '
            'Target="styles.xml"/>'
        )

        content_types_xml = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<Types xmlns="{_NS_CT}">'
            '<Default Extension="rels" '
            'ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            f"{''.join(content_types_overrides)}"
            "</Types>"
        )
        zf.writestr("[Content_Types].xml", content_types_xml.encode("utf-8"))

        root_rels_xml = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<Relationships xmlns="{_NS_PKG_REL}">'
            '<Relationship Id="rId1" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/'
            'relationships/officeDocument" '
            'Target="xl/workbook.xml"/>'
            "</Relationships>"
        )
        zf.writestr("_rels/.rels", root_rels_xml.encode("utf-8"))

        workbook_xml = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<workbook xmlns="{_NS_MAIN}" xmlns:r="{_NS_REL}">'
            f"<sheets>{''.join(workbook_sheets_xml)}</sheets>"
            "</workbook>"
        )
        zf.writestr("xl/workbook.xml", workbook_xml.encode("utf-8"))

        wb_rels = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<Relationships xmlns="{_NS_PKG_REL}">'
            f"{''.join(workbook_rels_xml)}"
            "</Relationships>"
        )
        zf.writestr("xl/_rels/workbook.xml.rels", wb_rels.encode("utf-8"))

        styles_xml = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<styleSheet xmlns="{_NS_MAIN}">'
            '<fonts count="1"><font><sz val="11"/><name val="Calibri"/></font></fonts>'
            '<fills count="2"><fill><patternFill patternType="none"/></fill>'
            '<fill><patternFill patternType="gray125"/></fill></fills>'
            '<borders count="1"><border>'
            "<left/><right/><top/><bottom/><diagonal/>"
            "</border></borders>"
            '<cellStyleXfs count="1">'
            '<xf numFmtId="0" fontId="0" fillId="0" borderId="0"/>'
            "</cellStyleXfs>"
            '<cellXfs count="2">'
            '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
            '<xf numFmtId="14" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>'
            "</cellXfs>"
            "</styleSheet>"
        )
        zf.writestr("xl/styles.xml", styles_xml.encode("utf-8"))

    return buf.getvalue()


def _parse_shared_strings(zf: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in zf.namelist():
        return []
    root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
    out: list[str] = []
    for si in root.findall(f"{{{_NS_MAIN}}}si"):
        parts = [t.text or "" for t in si.iter(f"{{{_NS_MAIN}}}t")]
        out.append("".join(parts))
    return out


def _workbook_sheet_targets(zf: zipfile.ZipFile) -> list[tuple[str, str]]:
    wb_root = ET.fromstring(zf.read("xl/workbook.xml"))
    rels_root = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
    rel_map: dict[str, str] = {}
    for rel in rels_root:
        rid = rel.attrib.get("Id")
        target = rel.attrib.get("Target", "")
        if rid:
            norm = target.lstrip("/")
            if not norm.startswith("xl/"):
                norm = f"xl/{norm}"
            rel_map[rid] = norm

    sheets: list[tuple[str, str]] = []
    for sheet_el in wb_root.findall(f".//{{{_NS_MAIN}}}sheet"):
        name = sheet_el.attrib.get("name", "Sheet")
        rid = sheet_el.attrib.get(f"{{{_NS_REL}}}id", "")
        if rid in rel_map:
            sheets.append((name, rel_map[rid]))
    return sheets


def read_xlsx_sheets(data: bytes) -> dict[str, list[list[Any]]]:
    """Read an .xlsx archive back into {sheet_name: rows} using stdlib only."""
    result: dict[str, list[list[Any]]] = {}
    with zipfile.ZipFile(io.BytesIO(data), "r") as zf:
        sst = _parse_shared_strings(zf)
        for name, target in _workbook_sheet_targets(zf):
            ws_root = ET.fromstring(zf.read(target))
            rows_dict: dict[int, dict[int, Any]] = {}
            max_row = 0
            for row_el in ws_root.findall(f".//{{{_NS_MAIN}}}row"):
                r_num = int(row_el.attrib.get("r", max_row + 1))
                max_row = max(max_row, r_num)
                row_cells = rows_dict.setdefault(r_num, {})
                col_cursor = 1
                for c_el in row_el.findall(f"{{{_NS_MAIN}}}c"):
                    ref = c_el.attrib.get("r")
                    if ref:
                        _, col_idx = _split_cell_ref(ref)
                    else:
                        col_idx = col_cursor
                    col_cursor = col_idx + 1
                    ctype = c_el.attrib.get("t", "")
                    f_el = c_el.find(f"{{{_NS_MAIN}}}f")
                    v_el = c_el.find(f"{{{_NS_MAIN}}}v")
                    is_el = c_el.find(f"{{{_NS_MAIN}}}is")

                    val: Any = None
                    if f_el is not None:
                        val = f"={f_el.text or ''}"
                    elif ctype == "inlineStr" and is_el is not None:
                        val = "".join(t.text or "" for t in is_el.iter(f"{{{_NS_MAIN}}}t"))
                    elif ctype == "s" and v_el is not None and v_el.text is not None:
                        val = sst[int(v_el.text)]
                    elif ctype == "b" and v_el is not None and v_el.text is not None:
                        val = v_el.text == "1"
                    elif v_el is not None and v_el.text is not None:
                        raw = v_el.text
                        try:
                            val = int(raw) if "." not in raw else float(raw)
                        except ValueError:
                            val = raw
                    row_cells[col_idx] = val

            sheet_rows: list[list[Any]] = []
            for r in range(1, max_row + 1):
                cells = rows_dict.get(r, {})
                max_col = max(cells.keys(), default=0)
                sheet_rows.append([cells.get(c) for c in range(1, max_col + 1)])
            result[name] = sheet_rows
    return result


def read_xlsx_formulas(data: bytes) -> list[tuple[str, str, str]]:
    """Return list of (sheet_name, cell_ref, formula_text) present in an .xlsx file."""
    found: list[tuple[str, str, str]] = []
    with zipfile.ZipFile(io.BytesIO(data), "r") as zf:
        for name, target in _workbook_sheet_targets(zf):
            ws_root = ET.fromstring(zf.read(target))
            for c_el in ws_root.findall(f".//{{{_NS_MAIN}}}c"):
                f_el = c_el.find(f"{{{_NS_MAIN}}}f")
                if f_el is not None:
                    found.append((name, c_el.attrib.get("r", ""), f_el.text or ""))
    return found
