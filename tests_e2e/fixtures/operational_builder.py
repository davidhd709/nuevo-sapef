"""Synthetic operational dataset builders for IMP-1..IMP-4, IMP-6, bulk OT, and SYN-1 geo.

Generates deterministic OOXML .xlsx payloads with authentic SAPEF quirks (KÜNIX,
SCHRÉDER, MH, 01/01/1900, atypical powers >1000W, SIN-IDENTIFICAR, multi-luminaire
PQRS, 4-file OT migration, warehouse luminaires, and password-less user imports).
"""

from __future__ import annotations

import datetime as dt
import hashlib
from collections.abc import Mapping, Sequence
from typing import Any

from fixtures.xlsx_builder import XlsxSheet, build_xlsx_bytes

MONTELIBANO_BBOX: tuple[float, float, float, float] = (7.950, -75.450, 8.010, -75.390)
ALCALA_BBOX: tuple[float, float, float, float] = (4.660, -75.800, 4.690, -75.770)

MAINTENANCE_12_COMPONENTS: tuple[str, ...] = (
    "conexion_red",
    "conexion_interna",
    "base_fotocelda",
    "fotocelda",
    "bombillo",
    "socket",
    "arrancador",
    "condensador",
    "balasta",
    "tubo",
    "collarin",
    "conectores_perforacion",
)


def generate_coordinates(
    sede_codigo: str,
    count: int,
    *,
    seed: int = 2026,
) -> list[tuple[float, float]]:
    """Generate deterministic (latitud, longitud) points inside Montelíbano or Alcalá bbox."""
    min_lat, min_lng, max_lat, max_lng = (
        MONTELIBANO_BBOX if sede_codigo.lower() == "montelibano" else ALCALA_BBOX
    )
    coords: list[tuple[float, float]] = []
    for idx in range(count):
        digest = hashlib.sha256(f"{seed}:{sede_codigo}:{idx}".encode()).digest()
        u_lat = int.from_bytes(digest[:8], "big") / float(1 << 64)
        u_lng = int.from_bytes(digest[8:16], "big") / float(1 << 64)
        lat = round(min_lat + (max_lat - min_lat) * u_lat, 6)
        lng = round(min_lng + (max_lng - min_lng) * u_lng, 6)
        coords.append((lat, lng))
    return coords


def build_maintenance_components(
    *,
    all_ok: bool = True,
    overrides: dict[str, bool] | None = None,
) -> dict[str, bool]:
    """Return the canonical 12-component maintenance checklist dict."""
    result = dict.fromkeys(MAINTENANCE_12_COMPONENTS, all_ok)
    if overrides:
        for key, val in overrides.items():
            if key in result:
                result[key] = bool(val)
    return result


def build_imp1_luminarias_xlsx(
    prefix: str,
    *,
    sede_codigo: str = "montelibano",
    count: int = 10,
    include_quirks: bool = True,
    barrio_names: Sequence[str] | None = None,
    seed: int = 101,
) -> bytes:
    """Build IMP-1 SAPEF luminaires Excel with brand/tech/date/power quirks."""
    barrios = list(barrio_names or (["El Centro", "San Felipe", "La Paz"]
                                     if sede_codigo == "montelibano"
                                     else ["Centro", "El Prado", "La Floresta"]))
    coords = generate_coordinates(sede_codigo, count, seed=seed)
    headers = [
        "codigo",
        "codigo_externo",
        "barrio",
        "latitud",
        "longitud",
        "estado",
        "marca",
        "tecnologia",
        "potencia",
        "tipo_intervencion",
        "fecha_instalacion",
        "fecha_mision",
        "fecha_baja",
        "poste",
        "es_rural",
    ]
    rows: list[list[Any]] = [headers]

    quirk_profiles = [
        ("KÜNIX", "MH", 1947, dt.date(1900, 1, 1), "121"),
        ("SCHRÉDER", "Led", 70, dt.date(2024, 5, 14), "121"),
        ("SHRÉDER", "LED", 4893, dt.date(1900, 1, 1), "121"),
        ("LEDVANCE", "SODIO", 150, dt.date(2023, 8, 20), "124"),
        ("PHILIPS", "METAL_HALIDE", 12138, dt.date(2025, 1, 10), "121"),
    ]

    for idx in range(count):
        lat, lng = coords[idx]
        barrio = barrios[idx % len(barrios)]
        code = f"{prefix}-LUM-{idx + 1:04d}"
        ext_code = f"MAT-{prefix}-{idx + 1:04d}"
        if include_quirks and idx < len(quirk_profiles):
            marca, tech, pot, f_inst, estado = quirk_profiles[idx]
        else:
            marca = "PHILIPS" if idx % 2 == 0 else "SCHREDER"
            tech = "LED"
            pot = 70 if idx % 2 == 0 else 100
            f_inst = dt.date(2025, 3, (idx % 28) + 1)
            estado = "121"

        rows.append(
            [
                code,
                ext_code,
                barrio,
                lat,
                lng,
                estado,
                marca,
                tech,
                pot,
                "RECIBO_INICIAL" if estado == "121" else "BODEGA",
                f_inst,
                dt.date(1900, 1, 1) if include_quirks and idx == 0 else dt.date(2024, 1, 15),
                dt.date(1900, 1, 1) if include_quirks and idx in {0, 1} else None,
                f"P-{idx + 1:03d}",
                idx % 5 == 0,
            ]
        )

    return build_xlsx_bytes([XlsxSheet(name="Luminarias", rows=rows)])


def build_imp2_pqrs_xlsx(
    prefix: str,
    luminaire_codes: Sequence[str],
    *,
    include_wildcard: bool = True,
    include_multi_luminaire: bool = True,
) -> bytes:
    """Build IMP-2 SAPEF PQRS Excel (1 row per PQRS x luminaire) with dedup & wildcard."""
    headers = [
        "numero_origen",
        "fecha_registro",
        "canal",
        "prioridad",
        "estado_pqrs",
        "identificacion_ciudadano",
        "nombre_ciudadano",
        "telefono",
        "correo",
        "luminaria_codigo",
        "reparada",
        "fecha_reparacion",
        "observacion",
    ]
    rows: list[list[Any]] = [headers]
    codes = list(luminaire_codes) or [f"{prefix}-LUM-0001", f"{prefix}-LUM-0002"]

    if include_multi_luminaire and len(codes) >= 2:
        for lum_code in codes[:2]:
            rows.append(
                [
                    f"{prefix}-PQR-1001",
                    dt.date(2026, 6, 1),
                    "WHATSAPP",
                    1,
                    "302",
                    f"CC-{prefix}-01",
                    "María Pérez Gómez",
                    "3001112233",
                    f"{prefix.lower()}.maria@example.test",
                    lum_code,
                    False,
                    dt.date(1900, 1, 1),
                    "Sector sin iluminación nocturna",
                ]
            )

    if include_wildcard:
        rows.append(
            [
                f"{prefix}-PQR-1002",
                dt.date(2026, 6, 3),
                "PRESENCIAL",
                2,
                "301",
                f"CC-{prefix}-01",
                "Maria Perez Gomez",
                "3001112233",
                f"{prefix.lower()}.maria@example.test",
                "SIN-IDENTIFICAR",
                False,
                None,
                "Poste sin placa legible",
            ]
        )

    rows.append(
        [
            f"{prefix}-PQR-1003",
            dt.date(2026, 5, 20),
            "TELEFONO",
            0,
            "303",
            f"CC-{prefix}-02",
            "Carlos Julio Díaz",
            "3114445566",
            f"{prefix.lower()}.carlos@example.test",
            codes[-1],
            True,
            dt.date(2026, 5, 22),
            "Reparada con cambio de fotocelda",
        ]
    )
    return build_xlsx_bytes([XlsxSheet(name="PQRS", rows=rows)])


def build_imp3_ordenes_4files(
    prefix: str,
    luminaire_codes: Sequence[str],
    *,
    include_orphan_row: bool = False,
) -> dict[str, bytes]:
    """Build IMP-3 4 historical SAPEF work-order Excels (mant, exp, mod, reub)."""
    codes = list(luminaire_codes) or [
        f"{prefix}-LUM-0001",
        f"{prefix}-LUM-0002",
        f"{prefix}-LUM-0003",
        f"{prefix}-LUM-0004",
    ]
    c1 = codes[0]
    c2 = codes[1 % len(codes)]
    c3 = codes[2 % len(codes)]
    c4 = codes[3 % len(codes)]

    mant_rows: list[list[Any]] = [
        [
            "id_origen",
            "luminaria_codigo",
            "fecha_programada",
            "fecha_cierre",
            "estado",
            "sitio_arreglo",
            "quien_recibe",
            "requiere_desmonte",
            *MAINTENANCE_12_COMPONENTS,
        ],
        [
            f"{prefix}-MNT-001",
            c1,
            dt.date(2026, 5, 10),
            dt.date(2026, 5, 11),
            "203",
            "Calle 10 # 5-20",
            "Junta Comunal",
            False,
            *([True] * 12),
        ],
    ]
    if include_orphan_row:
        mant_rows.append(
            [
                f"{prefix}-MNT-ORPHAN",
                f"{prefix}-LUM-INEXISTENTE",
                dt.date(2026, 5, 12),
                None,
                "201",
                "Calle 99",
                "N/A",
                False,
                *([False] * 12),
            ]
        )

    exp_rows = [
        [
            "id_origen",
            "luminaria_instalada_codigo",
            "fecha_programada",
            "fecha_cierre",
            "estado",
            "tipo_expansion",
            "barrio",
            "poste",
        ],
        [
            f"{prefix}-EXP-001",
            c2,
            dt.date(2026, 5, 15),
            dt.date(2026, 5, 16),
            "203",
            "COMPLEMENTARIA",
            "El Centro",
            "POSTE-EXP-01",
        ],
    ]

    mod_rows = [
        [
            "id_origen",
            "luminaria_instalada_codigo",
            "luminaria_desmontada_codigo",
            "fecha_programada",
            "fecha_cierre",
            "estado",
            "tipo_modernizacion",
            "barrio",
        ],
        [
            f"{prefix}-MOD-001",
            c3,
            c1,
            dt.date(2026, 5, 18),
            dt.date(2026, 5, 19),
            "203",
            "PRIORITARIA",
            "San Felipe",
        ],
    ]

    reub_rows = [
        [
            "id_origen",
            "luminaria_instalada_codigo",
            "luminaria_desmontada_codigo",
            "fecha_programada",
            "fecha_cierre",
            "estado",
            "destino_desmontada",
            "barrio",
        ],
        [
            f"{prefix}-REU-001",
            c4,
            c2,
            dt.date(2026, 5, 20),
            dt.date(2026, 5, 21),
            "203",
            "124",
            "La Paz",
        ],
    ]

    return {
        "mantenimientos.xlsx": build_xlsx_bytes([XlsxSheet("Mantenimientos", mant_rows)]),
        "expansiones.xlsx": build_xlsx_bytes([XlsxSheet("Expansiones", exp_rows)]),
        "modernizaciones.xlsx": build_xlsx_bytes([XlsxSheet("Modernizaciones", mod_rows)]),
        "reubicaciones.xlsx": build_xlsx_bytes([XlsxSheet("Reubicaciones", reub_rows)]),
    }


def build_imp4_inventario_xlsx(
    prefix: str,
    warehouse_codes: Sequence[str] | None = None,
) -> bytes:
    """Build IMP-4 inventory Excel with materials, kardex movements, and warehouse luminaires."""
    codes = list(warehouse_codes or [f"{prefix}-BOD-01", f"{prefix}-BOD-02"])
    materiales = [
        ["codigo", "categoria", "descripcion", "unidad", "existencias", "existencias_minimas"],
        [f"{prefix}-MAT-01", "ELECTRICO", "Fotocelda electrónica 120-277V", "UND", 25, 10],
        [f"{prefix}-MAT-02", "CABLE", "Cable concéntrico 2x12", "MTS", 100, 30],
    ]
    movimientos = [
        ["material_codigo", "tipo", "cantidad", "descripcion", "uuid_origen"],
        [f"{prefix}-MAT-01", "ENTRADA_ALMACEN", 25, "Saldo inicial importado", f"{prefix}-KDX-1"],
        [f"{prefix}-MAT-02", "ENTRADA_ALMACEN", 100, "Saldo inicial importado", f"{prefix}-KDX-2"],
    ]
    bodega = [
        ["luminaria_codigo", "estado_codigo", "observacion"],
        [codes[0], "124", "Bodega buena verificada"],
        [codes[-1], "123", "Bodega de baja por revisión"],
    ]
    return build_xlsx_bytes(
        [
            XlsxSheet("Materiales", materiales),
            XlsxSheet("Movimientos", movimientos),
            XlsxSheet("Bodega", bodega),
        ]
    )


def build_imp6_base_config_xlsx(prefix: str, *, sede_codigo: str = "alcala") -> bytes:
    """Build IMP-6 base config & users Excel (strictly NO passwords)."""
    zonas_barrios = [
        ["sede_codigo", "zona", "barrio"],
        [sede_codigo, f"{prefix}-ZONA-1", f"{prefix}-Barrio-A"],
        [sede_codigo, f"{prefix}-ZONA-1", f"{prefix}-Barrio-B"],
    ]
    usuarios = [
        ["nombre_usuario", "nombre_completo", "identificacion", "correo", "rol_codigo", "sedes"],
        [
            f"{prefix.lower()}_tecnico",
            "Técnico Migrado Sin Clave",
            f"99{abs(hash(prefix)) % 1000000:06d}",
            f"{prefix.lower()}.tec@example.test",
            "TECNICO",
            sede_codigo,
        ],
    ]
    return build_xlsx_bytes(
        [
            XlsxSheet("ZonasBarrios", zonas_barrios),
            XlsxSheet("Usuarios", usuarios),
        ]
    )


def build_bulk_ot_xlsx(
    tipo: str,
    rows: Sequence[Mapping[str, Any]],
    *,
    include_invalid_row: bool = False,
) -> bytes:
    """Build bulk OT Excel for POST /api/v1/ordenes/cargue-masivo/{tipo}."""
    tipo_norm = tipo.lower()
    if tipo_norm == "expansion":
        headers = ["luminaria_codigo", "tipo_expansion", "barrio", "poste", "latitud", "longitud"]
        sheet_rows: list[list[Any]] = [headers]
        for r in rows:
            sheet_rows.append(
                [
                    r.get("luminaria_codigo"),
                    r.get("tipo_expansion", "COMPLEMENTARIA"),
                    r.get("barrio", "El Centro"),
                    r.get("poste", "P-BULK-01"),
                    r.get("latitud", 7.9801),
                    r.get("longitud", -75.4171),
                ]
            )
        if include_invalid_row:
            sheet_rows.append(
                [
                    "LUM-INVALIDA-999",
                    "COMPLEMENTARIA",
                    "BARRIO_INEXISTENTE_XYZ",
                    "P-ERR",
                    7.98,
                    -75.41,
                ]
            )
    else:
        headers = [
            "luminaria_instalada_codigo",
            "luminaria_desmontada_codigo",
            "tipo",
            "barrio",
            "poste",
            "destino_desmontada",
        ]
        sheet_rows = [headers]
        for r in rows:
            sheet_rows.append(
                [
                    r.get("luminaria_instalada_codigo"),
                    r.get("luminaria_desmontada_codigo"),
                    r.get("tipo", "PRIORITARIA"),
                    r.get("barrio", "El Centro"),
                    r.get("poste", "P-BULK-02"),
                    r.get("destino_desmontada", "124"),
                ]
            )
        if include_invalid_row:
            sheet_rows.append(
                [
                    "LUM-NO-EXISTE",
                    "LUM-NO-EXISTE-2",
                    "PRIORITARIA",
                    "BARRIO_INEXISTENTE",
                    "P-ERR",
                    "999",
                ]
            )

    return build_xlsx_bytes([XlsxSheet(name=tipo_norm.capitalize(), rows=sheet_rows)])
