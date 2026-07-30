"""Data access boundary for the decision engine.

This is the only module that knows where data comes from. Today it reads a
local Excel file. Later it can be replaced by a FastAPI call or MCP tool without
touching the decision core, as long as it returns list[CompensationCase].
"""
from __future__ import annotations

import unicodedata
from pathlib import Path

import pandas as pd

from config import HEADER_ROW, RAW_DATA, SHEET_NAME
from domain.models import CompensationCase

# Numeric columns that Excel may load as object and must be coerced.
_NUM_INT = [
    "antiguedad_usuario_dias",
    "num_compensaciones_90d",
    "tiempo_entrega_real_min",
    "flags_fraude_previos",
]
_NUM_FLOAT = [
    "valor_orden_mxn",
    "compensacion_solicitada_mxn",
    "monto_compensado_90d_mxn",
]


def _norm_text(value: object) -> str:
    """Normalize text to Unicode NFC and trim whitespace.

    The dataset is valid Unicode; mojibake seen in some Windows consoles is a
    display issue, not data corruption. Normalization keeps GPS/reason matching
    robust across sources.
    """
    return unicodedata.normalize("NFC", str(value)).strip()


def load_cases(path: Path = RAW_DATA) -> list[CompensationCase]:
    """Read the dataset and return normalized, validated cases."""
    df = pd.read_excel(path, sheet_name=SHEET_NAME, header=HEADER_ROW)
    df = df.dropna(how="all")

    for col in _NUM_INT:
        df[col] = pd.to_numeric(df[col], errors="coerce").astype("Int64")
    for col in _NUM_FLOAT:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    text_cols = [
        "caso_id", "usuario_id", "ciudad", "vertical", "restaurante",
        "entrega_confirmada_gps", "motivo_reclamo", "descripcion_reclamo",
    ]
    for col in text_cols:
        df[col] = df[col].map(_norm_text)

    cases: list[CompensationCase] = []
    for row in df.to_dict(orient="records"):
        cases.append(
            CompensationCase(
                caso_id=row["caso_id"],
                usuario_id=row["usuario_id"],
                antiguedad_usuario_dias=int(row["antiguedad_usuario_dias"]),
                ciudad=row["ciudad"],
                vertical=row["vertical"],
                restaurante=row["restaurante"],
                valor_orden_mxn=float(row["valor_orden_mxn"]),
                compensacion_solicitada_mxn=float(row["compensacion_solicitada_mxn"]),
                num_compensaciones_90d=int(row["num_compensaciones_90d"]),
                monto_compensado_90d_mxn=float(row["monto_compensado_90d_mxn"]),
                entrega_confirmada_gps=row["entrega_confirmada_gps"],
                tiempo_entrega_real_min=int(row["tiempo_entrega_real_min"]),
                flags_fraude_previos=int(row["flags_fraude_previos"]),
                motivo_reclamo=row["motivo_reclamo"],
                descripcion_reclamo=row["descripcion_reclamo"],
            )
        )
    return cases
