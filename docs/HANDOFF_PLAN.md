# HANDOFF TÉCNICO — Caso 03 · Upgrade integral

> Documento de continuación para otro agente. Contiene: estado real, convenciones,
> arquitectura del código, y el **plan por fases con criterios de "listo" y "cuándo pasar
> a la siguiente"**. Léelo completo antes de tocar nada.

Fecha de corte: 2026-07-30. Repo remoto: `https://github.com/cataia-code/rappi-technical-challenge-case03` (público, rama `main`).

---

## 0. Convenciones de trabajo (OBLIGATORIO)

- **Commits**: cortos, en inglés, con prefijo tipo Conventional Commits (`feat:`, `fix:`,
  `refactor:`, `chore:`, `docs:`, `test:`). **NO** agregar `Co-Authored-By` ni trailers largos.
- **Push**: a `origin main` tras cada fase (o sub-fase) con su commit. El usuario quiere ver avance en el repo.
- **Identidad git ya configurada** en el repo (`cataia-code` / `briyidcatalinacruzostos@gmail.com`), `core.autocrlf=true`.
- **Python**: intérprete del venv en `./.venv/Scripts/python.exe` (Windows). Correr desde la **raíz** del proyecto.
- **Tests**: `./.venv/Scripts/python.exe -m pytest -q` (pytest ya tiene `pythonpath=["src"]` en `pyproject.toml`).
- **Pipeline**: `PYTHONPATH=src ./.venv/Scripts/python.exe -m caso03.pipeline [--no-llm] [--limit N] [--workers K]`.
- **Build de la web**: `./.venv/Scripts/python.exe apps/web/build_page.py` → genera `docs/index.html` (autocontenido; GitHub Pages sirve desde `/docs`).
- **Secretos**: `.env` está gitignored. **Nunca** commitear API keys. El repo es **público**.
- **Idioma del producto**: español (UI, prompts, docstrings). Código/commits en inglés.
- **NO revertir** ediciones externas previas (defensas de prompt-injection, etc.).

### Acciones pendientes del USUARIO (no las puede hacer el agente)
- Agregar `GEMINI_API_KEY` y `OPENROUTER_API_KEY` a `.env` (y como *secrets* del Cloudflare Worker en Fase 6).
- **Rotar `GROQ_API_KEY`** (quedó expuesta en un transcript anterior).
- Configurar GitHub Pages (Settings → Pages → Deploy from branch `main` `/docs`).

---

## 1. Decisiones bloqueadas (ya respondidas por el usuario)

1. **LLM del demo → Cloudflare Worker** (proxy serverless). Keys server-side, rotación multi-proveedor.
2. **Clustering → ADOPTAR EL GANADOR** de la selección como modelo productivo; re-correr los 150 (las decisiones pueden cambiar).
3. **Restructura de carpetas → completa** (ya hecha en Fase 1).
4. **Superficies → conservar MCP + FastAPI, eliminar Streamlit** (Streamlit ya eliminado).

---

## 2. Estado actual (qué está HECHO)

### Commits en `main`
- `31f405b chore: baseline import of case 03 compensation agent`
- `a1770d1 refactor: restructure into src/apps/experiments layout`
- `846279d feat: multi-provider LLM client with fallback`

### Fase 1b — abstracción multi-proveedor
- Cerrada localmente en `846279d feat: multi-provider LLM client with fallback`.
- Incluye `src/caso03/llm/{client.py, prompts.py, schemas.py}`, `tests/test_llm_client.py`,
  `modelo_usado` en `Decision`, y `LLM_PROVIDER_ORDER` con fallback Groq/Gemini/OpenRouter.
- **Estado de tests: 22 passed** (verificado tras el commit).

### Fase 1 — COMPLETA (restructura + limpieza + multi-proveedor)
Estructura actual real:
```
src/caso03/
  __init__.py
  config.py                 # Settings multi-proveedor (groq/gemini/openrouter) + iter_providers()
  pipeline.py               # orquestador batch (sin cambios de lógica)
  domain/models.py          # CompensationCase, Decision (+ campo modelo_usado), Recommendation, GpsStatus
  features/feature_service.py   # compute_features + guardrails (evaluate_guardrail/reconcile)
  scoring/
    risk_service.py         # assess(case) -> RiskAssessment  (inferencia SOLO numpy)
    train_risk_model.py     # (ex analysis/fit_risk_model.py) — SE REESCRIBE en Fase 2
    artifacts/risk_model.json
  llm/
    prompts.py              # PROMPT_VERSION + SYSTEM_PROMPT + build_user_prompt()
    schemas.py              # LLMDecisionPayload (validación pydantic)
    client.py               # LLMClient: fallback en cascada, OpenAI SDK, 3 base_urls
  services/
    decision_service.py     # orquesta: fast-path + LLM (usa llm/*) + guardrails
    data_service.py         # load_cases() (Excel -> CompensationCase, NFC)
    report_service.py       # build_dataframe/build_summary/write_excel (+ col modelo_usado)
apps/
  web/{build_page.py, index.template.html}   # build -> docs/index.html
  mcp/server.py             # FastMCP (revisar_caso / revisar_datos)
  api/                      # VACÍO — crear FastAPI en Fase 6
experiments/
  scoring/explore_signals.py
  eval/{prepare_manual_label_sample.py, validate_manual_labels.py}
  llm/{prompt_versions,sample_outputs,eval_runs}/   # dirs vacíos
data/{raw,interim,processed,output,labels}/
docs/{index.html (generado), politicas_decision.md, HANDOFF_PLAN.md}
notebooks/  scripts/        # VACÍOS — poblar en Fases 2/7
tests/  (22 tests verdes)
```
Eliminados: `app/streamlit_app.py`, `streamlit` y `groq` de requirements (ahora `openai==1.59.6`).
Duplicado del dataset en raíz: **untracked/ignorado** (sigue en disco porque estaba abierto en Excel; la copia canónica es `data/raw/`). Lock `~$...xlsx` ignorado.

### Detalle clave: abstracción multi-proveedor (ya implementada)
- `config.Settings.iter_providers()` → `list[(name, api_key, model)]` filtrado por `LLM_PROVIDER_ORDER` y por keys presentes.
- `llm.client.LLMClient.complete(system, user)` recorre proveedores; ante error/rate-limit de uno, pasa al siguiente; devuelve `LLMResponse(content, model_used="groq:llama-...")`.
- `_BASE_URLS`: groq=`https://api.groq.com/openai/v1`, gemini=`https://generativelanguage.googleapis.com/v1beta/openai/`, openrouter=`https://openrouter.ai/api/v1`.
- `openai` se importa **perezosamente** dentro de los métodos (no requerido en `--no-llm`).
- `decision_service.decide_llm` setea `decision.modelo_usado = resp.model_used`.

---

## 3. Arquitectura del modelo de riesgo (para portar a JS en Fase 6)

`scoring/risk_service.assess(case)` hace, con SOLO numpy:
1. Vector crudo de 5 features numéricas (orden = `risk_model.json["features"]`):
   `[num_compensaciones_90d, flags_fraude_previos, tiempo_entrega_real_min, antiguedad_usuario_dias, monto_compensado_90d_mxn]`.
2. Estandariza: `z = (x - scaler_mean) / scaler_scale`.
3. `abuse_index = (z * signs) @ weights`.
4. `score_bucket`: por `score_cuts=[c0,c1]` → `<c0` LEGITIMO, `<c1` AMBIGUO, else FRAUDE.
5. `cluster_bucket`: centroide KMeans más cercano (argmin dist² a `centroids`), mapeado por `cluster_to_bucket`.
6. `risk_score = clip((abuse_index - abuse_index_min)/(max-min), 0, 1)` redondeado a 2.
7. `resolved_bucket = score_bucket if (score_bucket==cluster_bucket) else "AMBIGUO"`  ← **el desacuerdo entre ambos métodos = señal de ambigüedad → al LLM**.
8. `top_contribuyentes`: top-3 por `|oriented*weights|`, frase por dirección (`_PHRASES`).

`risk_model.json` (schema actual — **cambiará en Fase 2** al adoptar el ganador; hoy es KMeans-5-numérico):
```
features[5], signs{}, scaler_mean[5], scaler_scale[5], weights[5], eta2{},
centroids[3][5], cluster_to_bucket{"0":"LEGITIMO","1":"FRAUDE","2":"AMBIGUO"},
score_cuts[2], abuse_index_min, abuse_index_max
```
> **La ruta del artefacto** en `risk_service.py` es `Path(__file__).parent/"artifacts"/"risk_model.json"` (junto al módulo, en `scoring/artifacts/`). Cachéada con `@lru_cache`.

---

## 4. Requerimientos originales del usuario (checklist — NO perder ninguno)

1. **Análisis exploratorio** (notebook): por qué KMeans y no otros; normalizar categóricas (vertical, entrega_confirmada_gps, motivo_reclamo) antes de los modelos; mostrar gráficos del mejor modelo (silhouette/kmeans) **dentro de la web con el mismo estilo actual**; sección "Exploración" con "No inventamos umbrales. Los sacamos de los datos."; **mostrar los pesos reales por feature del modelo de clustering**.
2. **Arquitectura**: diagramas de operación (dónde están API, MCP, LLM, modelo ganador, normalización/limpieza) en **ventanas emergentes**; "Tres capas + backbone de datos"; **diagrama de arquitectura, de secuencia y árbol de decisión** en **Mermaid**, no inline sino en modal con **zoom, descargar** (estilo `https://cataia-code.github.io/bancolombia-technical-challenge-a/`); mostrar **cómo se evalúa el LLM, prompts versionados**, y **métricas técnicas** del clustering y del LLM (fidelidad, alucinación, cumplimiento, latencia). Objetivo: el LLM **minimiza los casos escalados a humano**.
3. **Limpieza/resultados**: quitar carpetas/archivos sin uso (Streamlit ✔); correr el modelo ganador + prompt final sobre todos los casos → dashboard como ahora; **escalados: el LLM genera recomendación paso a paso** (qué revisar en concreto y qué impidió el veredicto), fundamentada y **sencilla**; mantener el resumen para aprobados/rechazados/escalados; **dashboard**: barras de features que más pesan **rellenas según valor 0–1**, sin solapar nombres/líneas; **flaticon más grande**; **prompts que minimizan tokens**.
4. **Demo en vivo real**: una **fila** con todas las columnas reales, datos **sintéticos aleatorios** que permitan caos aprobar/rechazar/escalar; botones **Regenerar** (nuevos datos) y **Probar** (proceso real): 1) normaliza categóricas, 2) pasa al modelo de clustering, 3) según valor va o no al LLM, 4) muestra qué decide el LLM + resumen con pasos, como el dashboard. Usa los **modelos cargados en la web** (pesos) + LLM vía API. Multi-proveedor (groq/gemini/openrouter); decir qué modelo usó.
5. **Web multi-pestaña** (no una sola): Exploración · Modelo/Métricas · Arquitectura · Dashboard · Demo, **mismo estilo**. + restructura de carpetas (✔ hecha).

---

## 5. PLAN POR FASES

> Regla general de "cuándo pasar a la siguiente": una fase se cierra cuando (a) `pytest -q`
> está verde, (b) su verificación específica pasa, (c) hay commit + push. No arrastrar deuda.

### FASE 1 — Restructura + multi-proveedor + limpieza  ✅
- **Estado**: cerrada localmente. Falta push si el repo remoto aún no refleja `a1770d1` y `846279d`.
- **DoD**: 22 tests verdes; commits listos para push.

---

### FASE 2 — Re-análisis DS + selección de modelo (ADOPTAR GANADOR)
**Objetivo**: comparar algoritmos de clustering con y sin categóricas codificadas, elegir el mejor por métricas, **adoptarlo como productivo**, re-exportar `risk_model.json`, re-correr los 150, y exportar datos de gráficos para la web.

**Empezar cuando**: Fase 1 commiteada.

**Tareas técnicas**:
1. Añadir a `requirements.txt`: `matplotlib` (solo notebooks/experimentos) y `scipy` si hace falta. Instalar en venv.
2. `experiments/scoring/model_selection.py`:
   - Cargar casos con `caso03.services.data_service.load_cases`.
   - Construir DOS matrices de features:
     - **A (numéricas)**: las 5 actuales, `StandardScaler`.
     - **B (numéricas + categóricas)**: one-hot de `vertical` y `motivo_reclamo`; `entrega_confirmada_gps` como one-hot (4 valores: `SÍ - confirmada`, `NO confirmada`, `Señal perdida`, `Parcial`). Escalar numéricas; dejar dummies 0/1. Reusar normalización de texto de `features.feature_service._clave` para robustez de matching.
   - Comparar algoritmos: `KMeans` (barrer k=2..6), `GaussianMixture`, `AgglomerativeClustering`, `DBSCAN` (barrer eps). Para cada (matriz, algo, k): calcular `silhouette_score`, `davies_bouldin_score`, `calinski_harabasz_score`.
   - Imprimir tabla comparativa y **elegir ganador** (regla: mayor silhouette con k=3 preferido por el enunciado —"3 buckets"—; documentar la regla). Guardar resultados a `experiments/llm/eval_runs/` o `data/processed/model_selection.json`.
   - **Importante para negocio**: el clustering debe seguir mapeando a LEGITIMO/AMBIGUO/FRAUDE por el `abuse_index` (eje de abuso orientado). Si el ganador usa categóricas, definir cómo se orientan/pesan (mantener el enfoque eta²-weighted o el que corresponda) y documentarlo.
3. Reescribir `src/caso03/scoring/train_risk_model.py` para:
   - Entrenar el **ganador** y exportar `risk_model.json` con schema extendido. Si incluye categóricas, agregar al JSON: `categorical_encoders` (mapa columna→categorías→índice one-hot), el orden completo de features, y **pesos reales por feature** (para mostrarlos). Mantener compatibilidad con `risk_service.assess` o **actualizar `assess` en consecuencia** (y su port JS futuro).
   - Ejecutar: `python -m caso03.scoring.train_risk_model`.
4. **Actualizar `scoring/risk_service.assess`** si el schema cambió (encoding de categóricas, nuevos vectores). Mantener la semántica `resolved_bucket` (desacuerdo → AMBIGUO) o el criterio de ambigüedad que se decida (documentar).
5. Exportar **JSON de gráficos para la web** (p.ej. `apps/web/model_charts.json` o inyectado por `build_page.py`): arrays para render SVG in-page — silhouette por k (todos los algos), dispersión 2D vía PCA por cluster (coords), tabla de métricas comparativas, y **pesos reales por feature** del ganador. (matplotlib solo para notebooks; **la web NO usa matplotlib**, replica el estilo SVG/CSS existente.)
6. `notebooks/00_data_exploration.ipynb`…`04_evaluation.ipynb`: exploración, feature analysis (incl. categóricas), experimentos de clustering, prompt tests, evaluación. Usar `NotebookEdit`.
7. Re-correr pipeline con LLM si hay presupuesto, o `--no-llm` como fallback: `PYTHONPATH=src python -m caso03.pipeline` → `data/output/salida_150.xlsx`. Rebuild web.

**GOTCHAS de Fase 2 (romperán tests — hay que actualizarlos)**:
- `tests/test_pipeline.py::test_pipeline_no_llm_produce_150_decisiones_con_scoring` **assert exacto `{APROBAR:60, ESCALAR:59, RECHAZAR:31}`** — cambiará. Actualizar al nuevo reparto (o afirmar suma=150 y rangos).
- `tests/test_feature_service.py::test_risk_buckets_de_los_anclas` asume `COMP-0011=FRAUDE, COMP-0001=LEGITIMO, COMP-0012=AMBIGUO`. Verificar/actualizar contra el nuevo modelo.
- Guardrails (`evaluate_guardrail`) dependen del bucket; revisar que sigan coherentes.

**DoD Fase 2**: `model_selection.py` corre e imprime métricas; `risk_model.json` regenerado por el ganador; `assess` consistente; 150 recomputados; tests actualizados y verdes; JSON de gráficos generado; notebooks commiteados. Commit `feat: model selection + adopt winning clustering model` (+ `test:` para asserts).

---

### FASE 3 — Web multi-pestaña + Exploración + Modelo & Métricas
**Objetivo**: convertir `apps/web/index.template.html` (single-scroll) en **pestañas** manteniendo estilo; agregar secciones Exploración y Modelo & Métricas con los gráficos reales de Fase 2.

**Empezar cuando**: Fase 2 tiene el JSON de gráficos + pesos reales.

**Contexto del template (real)**: un solo `<style>` inline (tokens en `:root`), un solo `<script>` vanilla. Sin framework, sin librería de charts. Data inyectada en `const DASHBOARD_DATA = /*__DATA__*/null;` (línea ~416). Barras eta² actuales: `.bar-row{grid-template-columns:150px 1fr 46px}` → **el solape es la columna de label de 150px** (no el fill; el fill `width:${v*100}%` ya es correcto para 0–1). Colores decisión duplicados en JS `DEC_COLOR` (sincronizar con tokens `:root`).

**Tareas técnicas**:
1. Tabs: nav con 5 items (Exploración · Modelo & Métricas · Arquitectura · Dashboard · Demo). Implementar show/hide de `<section>` con JS vanilla (clase `.active`), preservar smooth-scroll/`.reveal` y `#tip` tooltip. Mantener tokens/fonts.
2. `build_page.py`: inyectar además el JSON de gráficos de Fase 2 (nuevo placeholder, p.ej. `/*__MODEL__*/null`).
3. Sección **Exploración**: copy "No inventamos umbrales. Los sacamos de los datos." + hallazgos del dataset + por qué híbrido score+LLM. Gráficos SVG desde el JSON.
4. Sección **Modelo & Métricas**: tabla comparativa de algoritmos (silhouette/DB/CH), barras, **pesos reales por feature** del ganador (arreglar solape: label column `auto`/`minmax` o label arriba de la barra, permitir wrap), perfiles de cluster, dispersión 2D PCA.
5. Rebuild y revisar en navegador.

**DoD Fase 3**: 5 pestañas navegables; Exploración y Modelo con datos reales; barras sin solape; estilo consistente; commit `feat: multi-tab web + exploration & model-metrics sections`.

---

### FASE 4 — Arquitectura + diagramas Mermaid en modales + evaluación LLM
**Objetivo**: sección Arquitectura con 3 diagramas Mermaid en **modal** (zoom, descargar SVG/PNG, cerrar) + contenido de evaluación LLM y métricas.

**Tareas técnicas**:
1. **Componente modal/lightbox** (net-new; hoy no existe ninguno). Tarjeta → abre popup. Requisitos: overlay, cerrar (Esc/click fuera/botón), **zoom** (botones + rueda o transform scale), **descargar** el SVG del diagrama (y opcional PNG vía canvas). **Evitar** que un `alert/confirm` bloquee.
2. **Mermaid**: vendorizar `mermaid.min.js` **inline** en el template (mantener autocontenido; GitHub Pages permite CDN pero preferimos inline por consistencia/offline). Render on-demand al abrir el modal.
3. Tres diagramas (definir en Mermaid):
   - **Arquitectura**: 3 capas + backbone de datos; ubicar API (FastAPI), MCP, LLM (multi-proveedor), modelo ganador, y **dónde ocurre normalización/limpieza** (`data_service` NFC, `feature_service._clave`, encoding categórico).
   - **Secuencia**: CompensationCase → features/normalización → risk_service (score+cluster) → ¿ambiguo? → LLM (Worker) → guardrails → Decision.
   - **Árbol de decisión**: LEGITIMO/FRAUDE determinístico vs AMBIGUO→LLM; guardrails FORBID_APPROVE/FORBID_REJECT; routing por confianza.
4. Contenido: **prompts versionados** (`PROMPT_VERSION` de `llm/prompts.py`), cómo se evalúa el LLM, y **métricas** — cluster (silhouette/DB/CH de Fase 2) y LLM (fidelidad al schema JSON, tasa de alucinación, % override de guardrails, latencia, **tasa de escalamiento**). Mensaje: el LLM minimiza escalados a humano.
5. Docs espejo: `docs/arquitectura.md`, `docs/evaluacion_modelo.md`.

**DoD Fase 4**: 3 modales Mermaid con zoom/descarga funcionando; contenido de evaluación con números reales; commit `feat: architecture section with mermaid modals + llm evaluation`.

---

### FASE 5 — Dashboard: pulido + recomendación paso a paso para escalados
**Objetivo**: LLM genera pasos accionables para escalados; pulir dashboard.

**Tareas técnicas**:
1. **Schema/prompt**: agregar `pasos_recomendados: list[str]` a `Decision` (models.py) y a `LLMDecisionPayload` (llm/schemas.py). En `llm/prompts.py`, extender SYSTEM_PROMPT para que, **solo en ESCALAR**, devuelva `pasos_recomendados` (3–5 pasos cortos: qué revisar en concreto y qué impidió el veredicto). **Minimizar tokens** (redacción compacta; `max_tokens` sigue acotado). Subir `PROMPT_VERSION`.
2. `decision_service._parse`: mapear `pasos_recomendados`. `report_service`: nueva columna. `escalate_without_llm`: pasos genéricos template.
3. **Web** `renderDetail()`: bloque tras `.res` mostrando los pasos (lista) en escalados. Mantener `resumen_cs` para los tres desenlaces.
4. **Pulido**: barras "features que más pesan" **rellenas 0–1** sin solape (grid label `auto`/wrap; reusar `.bar-fill{width:%}`); **flaticon más grande** (aumentar tamaño del favicon/marca en nav y/o donde el usuario lo pidió); sincronizar `DEC_COLOR` (JS) con tokens `:root`.
5. Re-correr pipeline (para poblar `pasos_recomendados`) y rebuild.

**GOTCHA**: cambiar el prompt puede alterar decisiones; re-verificar reparto y tests.

**DoD Fase 5**: escalados muestran pasos; barras y flaticon corregidos; tests verdes; commit `feat: step-by-step escalation recommendations + dashboard polish`.

---

### FASE 6 — Demo en vivo (clustering en navegador + Worker LLM) + FastAPI + MCP
**Objetivo**: demo real ejecutable desde GitHub Pages.

**Tareas técnicas**:
1. **Port JS del scoring** (`apps/web/` JS): replicar `risk_service.assess` en JS leyendo `risk_model.json` (ya inyectado por build): estandarización, encoding categórico (si el ganador lo usa), `abuse_index`, score_bucket, centroide más cercano, `resolved_bucket`, `risk_score`, top_contribuyentes. **Debe dar EXACTAMENTE lo mismo que Python** (ver test de paridad).
2. **Sección Demo**: fila con TODAS las columnas reales (schema `CompensationCase`). Botón **Regenerar** → genera fila sintética aleatoria **sesgada** para alcanzar los 3 desenlaces (variar num_comp_90d, flags, antigüedad, montos, GPS/motivo coherentes/contradictorios). Botón **Probar** → 1) normaliza/codifica en JS, 2) corre clustering JS, 3) muestra bucket/score y si enruta al LLM, 4) si enruta: `fetch` al **Worker** → decisión + resumen + `pasos` + `modelo_usado`; si no: decisión determinística en JS. Estilo igual al dashboard.
3. **Cloudflare Worker** `apps/web/worker/{index.js, wrangler.toml}`:
   - Secrets: `GROQ_API_KEY`, `GEMINI_API_KEY`, `OPENROUTER_API_KEY`, `LLM_PROVIDER_ORDER`.
   - Espeja SYSTEM_PROMPT + build_user_prompt + `PROMPT_VERSION` (copiar de `llm/prompts.py`; mantener sincronía — considerar exportar el prompt a un `.json`/`.js` compartido para no duplicar).
   - Fallback multi-proveedor (mismo orden), `response_format json_object`, devuelve `{...decision, modelo_usado}`.
   - **CORS**: permitir el origin de GitHub Pages (`https://cataia-code.github.io`). Manejar preflight OPTIONS.
   - Dev local: `wrangler dev` (usar `.dev.vars` con las keys — gitignored).
   - En la web, endpoint configurable (constante JS con la URL del Worker desplegado; mientras no exista, degradar con mensaje claro "LLM no configurado").
4. **FastAPI** `apps/api/{main.py, routes.py, schemas.py}`: `POST /decidir` reusa `DecisionService.decide` sobre un `CompensationCase`. `GET /health`. Agregar `fastapi`+`uvicorn` a requirements. (El Worker puede llamar proveedores directo; FastAPI es la superficie Python para arquitectura/tests.)
5. **MCP**: ya movido a `apps/mcp/server.py`; verificar que corre (`python apps/mcp/server.py`).
6. **Test de paridad Py↔JS**: fijar N casos, calcular en Python (`assess`) y en JS (node ejecutando el port sobre el mismo `risk_model.json`), comparar `risk_score`/`bucket`. Puede ser un test que corra node vía subprocess, o exportar vectores esperados a JSON y validar en un pequeño script node en CI manual.

**DoD Fase 6**: Regenerar/Probar producen APROBAR/RECHAZAR/ESCALAR; Worker responde LLM real (con keys) mostrando modelo; FastAPI `/decidir` OK; MCP corre; paridad Py↔JS verificada; commit(s) `feat: live demo (browser clustering + worker llm)`, `feat: fastapi surface`.

---

### FASE 7 — Tests, docs, build final, verificación
**Tareas**:
1. Tests: `test_api.py` (FastAPI TestClient), `test_mcp.py` (import/smoke), paridad scoring, y ampliar `test_llm_client.py` (retry por RateLimitError). Todos verdes.
2. Docs: `README.md` (1 página actualizada: nuevo layout, cómo correr, multi-proveedor, demo), `docs/demo_script.md` (guion de la presentación de 30 min), `scripts/*.ps1` (`run_pipeline.ps1`, `run_api.ps1`, `run_mcp.ps1`, `build_page.ps1`, `validate_output.py`). Actualizar `PLAN_EJECUTIVO_CASO03.md` o marcarlo histórico.
3. Build final `apps/web/build_page.py` → recorrer 5 pestañas, 3 modales Mermaid, correr demo contra `wrangler dev`.
4. Verificación end-to-end (§6). Commit `docs:`/`test:`/`chore:` y push final.

---

## 6. Verificación end-to-end (checklist final)
1. `./.venv/Scripts/python.exe -m pytest -q` → todo verde.
2. `python -m experiments.scoring.model_selection` → tabla de métricas; `python -m caso03.scoring.train_risk_model` → `risk_model.json` regenerado.
3. `PYTHONPATH=src python -m caso03.pipeline` → `salida_150.xlsx`; reparto coherente; ningún caso sin recomendación; escalados con `pasos_recomendados`.
4. `python apps/web/build_page.py` → abrir `docs/index.html`: 5 pestañas, 3 modales Mermaid (zoom/descarga), barras de pesos sin solape, flaticon más grande.
5. `wrangler dev` en `apps/web/worker/`; en la web Regenerar/Probar hasta ver los 3 desenlaces; el LLM real responde y muestra el modelo.
6. `uvicorn apps.api.main:app` → `POST /decidir`; `python apps/mcp/server.py` responde.

## 7. Riesgos / gotchas transversales
- **Adoptar el ganador rompe asserts** de reparto y de anclas (Fase 2) — actualizarlos.
- **GitHub Pages sirve `/docs`** — el build DEBE escribir `docs/index.html` (ya configurado en `build_page.py`).
- **Repo público** — jamás commitear `.env`/keys. `.dev.vars` del Worker debe ir gitignored.
- **Worker CORS** — sin CORS correcto el demo falla en el navegador.
- **Paridad Py↔JS** — divergencias de redondeo/encoding cambian buckets; testear.
- **Excel abierto** bloquea borrar el duplicato raíz; ya está ignorado, no re-agregarlo.
- **Mermaid inline** agranda el HTML; aceptable (ya se embeben logo/favicon base64).
- **Presupuesto de tokens**: correr LLM sobre 150 gasta cuota; usar fallback multi-proveedor y `--no-llm` cuando aplique.
