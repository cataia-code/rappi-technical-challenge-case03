"""Dashboard de revisión para el agente CS (Capa 2).

Lee el Excel enriquecido (salida del pipeline) y permite revisar cada caso
"en 5 segundos": semáforo + risk_score + 2-3 señales dominantes + resumen.

Correr:  streamlit run app/streamlit_app.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from caso03.config import OUTPUT_DIR  # noqa: E402

OUTPUT = OUTPUT_DIR / "salida_150.xlsx"

SEMAFORO = {"APROBAR": "🟢", "RECHAZAR": "🔴", "ESCALAR": "🟡"}
COLOR = {"APROBAR": "#1a7f37", "RECHAZAR": "#cf222e", "ESCALAR": "#bf8700"}

st.set_page_config(page_title="Caso 03 — Revisión de Compensaciones", layout="wide")


@st.cache_data
def load(path: Path) -> pd.DataFrame:
    return pd.read_excel(path, sheet_name="Casos")


st.title("🛡️ Revisión de Compensaciones — Trust & Safety")

if not OUTPUT.exists():
    st.warning(f"No existe {OUTPUT}. Corré primero: `python -m caso03.pipeline`")
    st.stop()

df = load(OUTPUT)

# --- Reparto de decisiones ---------------------------------------------------
total = len(df)
counts = df["recomendacion_agente"].value_counts()
c1, c2, c3, c4 = st.columns(4)
c1.metric("Total casos", total)
for col, rec in zip((c2, c3, c4), ["APROBAR", "ESCALAR", "RECHAZAR"]):
    n = int(counts.get(rec, 0))
    col.metric(f"{SEMAFORO[rec]} {rec}", n, f"{n / total * 100:.0f}%")

# --- Filtros -----------------------------------------------------------------
with st.sidebar:
    st.header("Filtros")
    f_rec = st.multiselect("Recomendación", sorted(df.recomendacion_agente.unique()))
    f_bucket = st.multiselect("Bucket de riesgo", sorted(df.risk_bucket.dropna().unique()))
    f_ciudad = st.multiselect("Ciudad", sorted(df.ciudad.unique()))

view = df.copy()
if f_rec:
    view = view[view.recomendacion_agente.isin(f_rec)]
if f_bucket:
    view = view[view.risk_bucket.isin(f_bucket)]
if f_ciudad:
    view = view[view.ciudad.isin(f_ciudad)]

st.caption(f"Mostrando {len(view)} de {total} casos")

# --- Tabla resumida ----------------------------------------------------------
cols_tabla = [
    "caso_id", "recomendacion_agente", "risk_bucket", "risk_score",
    "confianza", "resumen_cs",
]
st.dataframe(view[cols_tabla], use_container_width=True, hide_index=True)

# --- Detalle por caso --------------------------------------------------------
st.divider()
st.subheader("Detalle del caso")
caso = st.selectbox("Elegí un caso", view.caso_id.tolist())
if caso:
    r = df[df.caso_id == caso].iloc[0]
    rec = r.recomendacion_agente
    st.markdown(
        f"### {SEMAFORO[rec]} <span style='color:{COLOR[rec]}'>{rec}</span>",
        unsafe_allow_html=True,
    )
    a, b = st.columns(2)
    with a:
        st.markdown("**Resumen para CS**")
        st.info(r.resumen_cs)
        st.markdown(f"**Bucket de riesgo (datos):** {r.risk_bucket}  ·  **score:** {r.risk_score}")
        st.markdown(f"**Señales que más pesan:** {r.top_contribuyentes}")
        st.markdown(f"**Señales dominantes (LLM):** {r.senales_dominantes}")
        if str(r.override_guardrail).strip():
            st.warning(f"⚙️ Guardrail: {r.override_guardrail}")
    with b:
        st.markdown("**Datos del caso**")
        st.write({
            "usuario_id": r.usuario_id,
            "antigüedad (días)": int(r.antiguedad_usuario_dias),
            "ciudad / vertical": f"{r.ciudad} / {r.vertical}",
            "valor orden / comp. pedida": f"${r.valor_orden_mxn:.0f} / ${r.compensacion_solicitada_mxn:.0f}",
            "compensaciones 90d": int(r.num_compensaciones_90d),
            "monto compensado 90d": f"${r.monto_compensado_90d_mxn:.0f}",
            "flags previos": int(r.flags_fraude_previos),
            "GPS": r.entrega_confirmada_gps,
            "tiempo entrega (min)": int(r.tiempo_entrega_real_min),
            "motivo": r.motivo_reclamo,
        })
        with st.expander("Descripción y razonamiento"):
            st.markdown(f"**Reclamo:** {r.descripcion_reclamo}")
            st.markdown(f"**Razonamiento:** {r.razonamiento}")

# --- Descarga ----------------------------------------------------------------
st.divider()
with open(OUTPUT, "rb") as fh:
    st.download_button(
        "⬇️ Descargar Excel (150 casos)", fh, file_name="salida_150.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
