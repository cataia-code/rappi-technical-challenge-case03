"""data_service — la costura del SDK (acceso a datos).

Es el ÚNICO punto que sabe de dónde vienen los datos. Hoy: un Excel local.
Mañana, sin tocar el núcleo de decisión, se puede reemplazar por una llamada
a una FastAPI o a un tool MCP (misma firma: devuelve list[CompensationCase]).
Ese desacople es la frontera que muestra la referencia air_travel — aquí
vive en-proceso en vez de en un microservicio.
"""
from __future__ import annotations

import unicodedata
from pathlib import Path

import pandas as pd

from caso03.config import HEADER_ROW, RAW_DATA, SHEET_NAME
from caso03.domain.models import CompensationCase

# Columnas numéricas que deben forzarse a número (el Excel las trae como object)
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
    """Normaliza texto a Unicode NFC y colapsa espacios.

    Los datos vienen en Unicode correcto (ej. 'Señal perdida'); el '�' que se
    ve en consola es un artefacto de display de Windows, no corrupción. Aun así
    normalizamos para que los match por GPS/motivo sean robustos.
    """
    return unicodedata.normalize("NFC", str(value)).strip()


def load_cases(path: Path = RAW_DATA) -> list[CompensationCase]:
    """Lee el dataset y devuelve casos normalizados y validados."""
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
