"""Render the web dashboard template into the GitHub Pages entry point.

Run after each pipeline execution:
    python apps/web/build_page.py
"""
from __future__ import annotations

import base64
import json
import re
from pathlib import Path

import pandas as pd

WEB = Path(__file__).resolve().parent          # apps/web
ROOT = WEB.parents[1]                           # project root
XLSX = ROOT / "data" / "output" / "salida_150.xlsx"
LOGO = WEB / "assets" / "images" / "Rappi_logo.svg.webp"
FAVICON = WEB / "assets" / "images" / "rappi_faticon.png"
TEMPLATE = WEB / "templates" / "dashboard.html"
MODEL_SELECTION = ROOT / "data" / "processed" / "model_selection.json"
PROMPTS_MODULE = ROOT / "src" / "llm" / "prompts.py"
OUT = ROOT / "docs" / "index.html"              # GitHub Pages output (/docs)


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


def load_model_selection() -> dict:
    return json.loads(MODEL_SELECTION.read_text(encoding="utf-8"))


def prompt_version() -> str:
    text = PROMPTS_MODULE.read_text(encoding="utf-8")
    m = re.search(r'PROMPT_VERSION\s*=\s*"([^"]+)"', text)
    return m.group(1) if m else "unknown"


def build_meta(cases: list[dict]) -> dict:
    total = len(cases) or 1
    escalated = sum(1 for c in cases if c["rec"] == "ESCALAR")
    return {
        "prompt_version": prompt_version(),
        "det_pct": round((total - escalated) / total * 100, 1),
        "esc_pct": round(escalated / total * 100, 1),
    }


def main() -> None:
    cases = build_cases()
    data = {"cases": cases, "meta": build_meta(cases)}
    model = load_model_selection()
    template = TEMPLATE.read_text(encoding="utf-8")
    html = template.replace("/*__DATA__*/null", json.dumps(data, ensure_ascii=False))
    html = html.replace("/*__MODEL__*/null", json.dumps(model, ensure_ascii=False))
    html = html.replace("__RAPPI_LOGO__", _data_uri(LOGO, "image/webp"))
    html = html.replace("__RAPPI_FAVICON__", _data_uri(FAVICON, "image/png"))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(html, encoding="utf-8")
    print(f"{OUT} generated with {len(cases)} cases and model-selection metrics.")


if __name__ == "__main__":
    main()
