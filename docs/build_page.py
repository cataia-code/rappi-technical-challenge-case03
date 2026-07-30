"""Inyecta los 150 resultados en index.template.html -> index.html (autocontenido).

Correr: python docs/build_page.py   (tras cada corrida del pipeline)
"""
from __future__ import annotations

import base64
import json
import sys
from pathlib import Path

import pandas as pd

DOCS = Path(__file__).resolve().parent
XLSX = DOCS.parent / "data" / "output" / "salida_150.xlsx"
LOGO = DOCS.parent / "Rappi_logo.svg.webp"
FAVICON = DOCS.parent / "rappi_faticon.png"


def _data_uri(path: Path, mime: str) -> str:
    b64 = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{b64}"


def build_cases() -> list[dict]:
    df = pd.read_excel(XLSX, sheet_name="Casos")
    out = []
    for _, r in df.iterrows():
        top = str(r.get("top_contribuyentes", "") or "")
        out.append({
            "id": r["caso_id"],
            "ciu": r["ciudad"],
            "ver": r["vertical"],
            "mot": r["motivo_reclamo"],
            "rec": r["recomendacion_agente"],
            "bkt": r.get("risk_bucket", ""),
            "sc": round(float(r["risk_score"]), 2) if pd.notna(r.get("risk_score")) else None,
            "res": r["resumen_cs"],
            "top": [t.strip() for t in top.split(";") if t.strip()],
            "ant": int(r["antiguedad_usuario_dias"]),
            "n90": int(r["num_compensaciones_90d"]),
            "fl": int(r["flags_fraude_previos"]),
            "gps": r["entrega_confirmada_gps"],
            "val": round(float(r["valor_orden_mxn"])),
            "ped": round(float(r["compensacion_solicitada_mxn"])),
            "m90": round(float(r["monto_compensado_90d_mxn"])),
            "tmp": int(r["tiempo_entrega_real_min"]),
        })
    return out


def main() -> None:
    cases = build_cases()
    data = {"cases": cases}
    template = (DOCS / "index.template.html").read_text(encoding="utf-8")
    html = template.replace("/*__DATA__*/null", json.dumps(data, ensure_ascii=False))
    html = html.replace("__RAPPI_LOGO__", _data_uri(LOGO, "image/webp"))
    html = html.replace("__RAPPI_FAVICON__", _data_uri(FAVICON, "image/png"))
    (DOCS / "index.html").write_text(html, encoding="utf-8")
    print(f"index.html generado con {len(cases)} casos.")


if __name__ == "__main__":
    main()
