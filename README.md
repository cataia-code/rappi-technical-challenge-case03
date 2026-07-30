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

Ver **`docs/politicas_decision.md`** para los criterios completos y el manejo de ambigüedad, y
**`docs/arquitectura.md`** / **`docs/evaluacion_modelo.md`** para el detalle técnico (diagramas
Mermaid, prompts versionados, métricas reales del último run) que también se ve en la web.

## Web (`docs/index.html`, publicada por GitHub Pages)

Un solo archivo autocontenido (assets embebidos en base64), con 5 pestañas:

- **Exploración** — por qué se compararon modelos en vez de fijar umbrales a mano, y qué corrigió
  la intuición (GPS secundario, ratio comp/orden nunca &gt;1).
- **Modelo & Métricas** — las 32 combinaciones algoritmo×matriz×k probadas, el ganador resaltado,
  los pesos reales por señal, y una proyección PCA de los 150 casos coloreada por bucket.
- **Arquitectura** — 3 diagramas Mermaid (arquitectura, secuencia, árbol de decisión) en un modal
  con zoom y descarga, más las métricas de evaluación del LLM del último run real.
- **Dashboard** — los 150 casos, filtrables, con el detalle de cada decisión y —para los
  escalados— los pasos concretos que el LLM (o el fallback) recomienda revisar.
- **Demo** — genera un caso sintético y corre el modelo de riesgo **en el navegador** (mismos
  pesos que Modelo & Métricas); si el caso es ambiguo, intenta una llamada real a un LLM vía un
  Cloudflare Worker (código en `apps/web/worker/`, **no desplegado** por defecto — ver esa
  carpeta para desplegarlo con tus propias API keys). Sin el Worker desplegado, el demo sigue
  siendo 100% funcional: muestra el mismo aviso honesto que usaría en producción cuando el LLM
  no está disponible, en vez de fingir una respuesta.

## Organización del repo

```text
src/              Código productivo: dominio, features, scoring, LLM, servicios y pipeline.
apps/web/         Fuente de la web: template, builder y assets (`assets/images`).
apps/mcp/         Servidor FastMCP para exponer revisión de casos como tool.
apps/api/         Superficie FastAPI para health-check y revisión de casos.
challenge/        Enunciado original del reto y anexos de entrada.
config/           Plantillas de configuración local, sin secretos reales.
experiments/      Experimentación reproducible: scoring y evaluación manual.
data/             raw/processed/labels con datos versionados; output/ se genera localmente.
docs/             Salida publicada por GitHub Pages (`index.html`) y documentación técnica.
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

# 2. Credenciales: copiar config\env.example -> .env y poner las API keys disponibles
#    (GROQ_API_KEY, GEMINI_API_KEY, OPENROUTER_API_KEY). El modo --no-llm no consume tokens.

# 3. Seleccionar y ajustar el modelo de riesgo
$env:PYTHONPATH="src"
.\.venv\Scripts\python.exe experiments\scoring\model_selection.py
.\.venv\Scripts\python.exe -m scoring.train_risk_model

# 4. Correr el agente sobre los 150 casos  ->  data/output/salida_150.xlsx
$env:PYTHONPATH="src"
.\.venv\Scripts\python.exe -m pipeline --no-llm             # entrega completa segura
.\.venv\Scripts\python.exe -m pipeline --workers 1          # con LLM para ambiguos
.\.venv\Scripts\python.exe -m pipeline --limit 15 --no-llm  # subconjunto demo

# 5. Web estática de revisión
.\.venv\Scripts\python.exe apps\web\build_page.py
# Fuente: apps\web\templates\dashboard.html. Salida publicada: docs\index.html.

# 6. (Bonus) Servidor MCP — expone el agente como tool
$env:PYTHONPATH="src"
.\.venv\Scripts\python.exe apps\mcp\server.py

# 7. API HTTP local
$env:PYTHONPATH="src"
.\.venv\Scripts\uvicorn.exe apps.api.main:app --reload

# Tests
.\.venv\Scripts\python.exe -m pytest -q
# La suite falla si la cobertura baja de 80% (`pyproject.toml` + CI).
# CI/CD: `.github/workflows/ci.yml` ejecuta instalación, tests con coverage y build web.

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
`razonamiento` como justificación breve, `override_guardrail`, `modelo_usado` cuando responde un
LLM, y `pasos_recomendados` — 2-4 pasos concretos que el LLM escribe solo para los casos que
terminan en ESCALAR, o un checklist genérico si nunca llegó a tocar un LLM) + hoja **Resumen**
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
- **Fronteras de servicio, en-proceso:** `apps/api` (FastAPI) y `apps/mcp` (FastMCP) son
  adaptadores delgados sobre el mismo `DecisionService` — sin base de datos ni cola de mensajes
  para 150-200 filas/día; el motor de decisión no sabe ni le importa qué lo invoca.
- **Prompts versionados, no un string suelto:** `llm/prompts.py::PROMPT_VERSION` viaja con cada
  corrida (visible en la web y en `experiments/llm/eval_runs/`), para poder comparar qué versión
  del prompt produjo qué decisiones.
- **El demo en vivo corre el modelo de riesgo en JS, no solo en Python:** `apps/web/assets/js/scoring.js`
  es un port 1:1 de `risk_service.py`, verificado contra Python con un test de paridad real
  (`tests/test_scoring_js_parity.py`, corre con Node) — la demo no podría mentir sobre cómo
  decide sin que ese test lo detecte.

## Con más tiempo

- Etiquetar a mano ~30 casos para medir precisión de RECHAZAR y afinar cortes.
- Persistir el modelo de riesgo y reentrenarlo con feedback de los CS (aprendizaje continuo).
- Caché de decisiones + batching de tokens para exprimir el rate limit.
- Desplegar el Cloudflare Worker (`apps/web/worker/`) para que el demo llame a un LLM real de
  punta a punta, y agregar telemetría real de latencia/alucinación por proveedor (hoy el batch
  de referencia corrió con `--no-llm`, así que esas métricas no existen todavía — ver
  `docs/evaluacion_modelo.md`).
- Sincronizar automáticamente el prompt entre `llm/prompts.py` y `apps/web/worker/index.js` (hoy
  es una copia manual con un aviso en el código; un JSON/JS compartido lo eliminaría).
