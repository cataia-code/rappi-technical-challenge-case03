# Caso 03 — Automatización de Revisión de Compensaciones

Agente de decisión para Trust & Safety de Rappi: clasifica solicitudes de compensación
como **APROBAR / RECHAZAR / ESCALAR** con justificación auditable, para que un agente CS
las revise **en segundos** en vez de 15-25 min.

> **Stack:** Python 3.10 · LLM multi-proveedor (Groq/Gemini/OpenRouter) · scikit-learn · web estática · FastMCP

---

## Idea en una línea

Los datos deciden lo claro; el LLM decide lo ambiguo. Un **modelo de riesgo derivado de
los datos** (Capa 0) clasifica de forma determinística los casos claros (legítimo/fraude)
y **solo enruta los casos ambiguos al LLM**, que lee el texto del reclamo para desambiguar.

## Arquitectura (3 capas + backbone de datos)

```
                 ┌─ Capa 0: risk_service ─ modelo de riesgo (score + clustering)  [determinístico]
CompensationCase ┤
                 ├─ ¿bucket claro? → decisión determinística (92/150, sin LLM)
                 └─ ¿ambiguo?      → Capa 1: decision_service (LLM multi-proveedor, JSON validado)
                                     → Capa 2: guardrails reconcilian con la política
                                     → Decision (recomendación + resumen + señales)
```

- **Capa 0 — `risk_service`**: score de riesgo 0-1 ponderado por el poder discriminante
  real (eta²) de cada señal, **+** el modelo ganador de clustering
  (`AgglomerativeClustering(k=3)`, matriz numérica). Si score y cluster coinciden → bucket;
  si discrepan → AMBIGUO. 100% determinístico y auditable.
- **Capa 1 — `decision_service`**: LLM multi-proveedor con salida JSON validada, recibe el
  bucket + score + el texto del reclamo. Solo se invoca en casos ambiguos y la descripción
  del usuario se trata como dato no confiable.
- **Capa 2 — guardrails** (`feature_service`): acotan la salida del LLM a la política
  (FRAUDE no puede auto-aprobarse; LEGÍTIMO no puede rechazarse; ante duda, ESCALAR).

Ver **`docs/politicas_decision.md`** para los criterios completos y el manejo de ambigüedad.

## Organización del repo

```text
src/caso03/        Código productivo: dominio, features, scoring, LLM, servicios y pipeline.
apps/web/         Web estática y builder de `docs/index.html`.
apps/mcp/         Servidor FastMCP para exponer revisión de casos como tool.
apps/api/         Superficie FastAPI prevista para la demo/API.
experiments/      POC y experimentación: scoring, evaluación manual y pruebas LLM.
notebooks/        Notebooks de exploración, selección de modelo y evaluación.
data/             raw/interim/processed/output/labels con datasets y artefactos derivados.
docs/             GitHub Pages, políticas y handoff técnico.
scripts/          Automatizaciones operativas futuras.
tests/            Pruebas unitarias e integración del pipeline.
```

## Qué dicen los datos (resumen)

Análisis no supervisado sobre los 150 casos comparó KMeans, Gaussian Mixture,
Agglomerative y DBSCAN, con matriz numérica y numérica+categórica. Ganó
`AgglomerativeClustering(k=3)` sobre la matriz numérica (`silhouette=0.462`). Señales que
más pesan (eta²): `num_compensaciones_90d`, `flags_fraude_previos`, `antiguedad`,
`monto_compensado_90d`, `tiempo_entrega`. El GPS resultó **secundario** y `compensacion`
nunca supera `valor_orden`. Detalle en `experiments/scoring/model_selection.py`.

## Cómo correr

```powershell
# 1. Entorno (Python 3.10)
py -3.10 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

# 2. Credenciales: copiar .env.example -> .env y poner las API keys disponibles
#    (GROQ_API_KEY, GEMINI_API_KEY, OPENROUTER_API_KEY). El modo --no-llm no consume tokens.

# 3. Seleccionar y ajustar el modelo de riesgo
$env:PYTHONPATH="src"
.\.venv\Scripts\python.exe experiments\scoring\model_selection.py
.\.venv\Scripts\python.exe -m caso03.scoring.train_risk_model

# 4. Correr el agente sobre los 150 casos  ->  data/output/salida_150.xlsx
$env:PYTHONPATH="src"
.\.venv\Scripts\python.exe -m caso03.pipeline --no-llm             # entrega completa segura
.\.venv\Scripts\python.exe -m caso03.pipeline --workers 1          # con LLM para ambiguos
.\.venv\Scripts\python.exe -m caso03.pipeline --limit 15 --no-llm  # subconjunto demo

# 5. Web estática de revisión
.\.venv\Scripts\python.exe apps\web\build_page.py
# Abrir docs\index.html o servir /docs con GitHub Pages

# 6. (Bonus) Servidor MCP — expone el agente como tool
$env:PYTHONPATH="src"
.\.venv\Scripts\python.exe apps\mcp\server.py

# Tests
.\.venv\Scripts\python.exe -m pytest -q

# Validación manual opcional
.\.venv\Scripts\python.exe experiments\eval\prepare_manual_label_sample.py
# Completar data\labels\manual_30.csv a partir de la plantilla generada y luego:
.\.venv\Scripts\python.exe experiments\eval\validate_manual_labels.py
```

> **Nota de rate limit:** el free tier de Groq topa en 12k tokens/min. El ruteo selectivo
> (solo ambiguos al LLM) reduce el batch a ~60 llamadas (~5 min). El output se persiste una
> vez en Excel; la demo lo lee sin recomputar.

## Output

`data/output/salida_150.xlsx` — hoja **Casos** (150 casos con `recomendacion_agente`,
`risk_bucket`, `risk_score`, `top_contribuyentes`, `senales_dominantes`, `resumen_cs`,
`razonamiento` como justificación breve, `override_guardrail`) + hoja **Resumen**
(reparto de decisiones).

Reparto sobre los 150 (modo `--no-llm`, backbone de datos): **APROBAR 62 (41.3%) ·
RECHAZAR 30 (20.0%) · ESCALAR 58 (38.7%)**. Con presupuesto LLM disponible, correr sin
`--no-llm` resuelve por texto parte de los ambiguos y baja ESCALAR por debajo de 38.7%.

> **Nota de rate limit (importante):** el free tier de Groq tiene **dos** topes: 12k
> tokens/min y **100k tokens/día**. Un run completo con LLM consume tokens solo en los
> 58 ambiguos. El modo `--no-llm` genera el Excel completo sin gastar
> tokens (ambiguos → ESCALAR), útil cuando el presupuesto diario está agotado. Si Groq falla
> durante un run con LLM, el caso cae a ESCALAR conservando `risk_bucket`, `risk_score` y señales.

## Decisiones de diseño

- **Híbrido score + clustering, no LLM-para-todo:** los datos tienen estructura clara
  (un eje de abuso); usar el LLM en los 150 sería caro, lento y menos auditable. El LLM se
  reserva para donde aporta: el texto de los casos ambiguos.
- **Sesgo FP>FN:** rechazar a un legítimo (churn) cuesta más que aprobar un fraude puntual
  (monto acotado) → RECHAZAR conservador, la incertidumbre va a ESCALAR.
- **Fronteras de servicio (no monorepo):** se mantienen las fronteras de la referencia
  air_travel (SDK/data, MCP, decisión) pero en-proceso; sin Postgres/FastAPI para 150 filas.

## Con más tiempo

- Etiquetar a mano ~30 casos para medir precisión de RECHAZAR y afinar cortes.
- Persistir el modelo de riesgo y reentrenarlo con feedback de los CS (aprendizaje continuo).
- Caché de decisiones + batching de tokens para exprimir el rate limit.
- Exponer el pipeline tras una FastAPI/MCP real cuando el volumen (200+/día) lo justifique.
