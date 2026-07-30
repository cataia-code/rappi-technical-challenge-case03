# Evaluación del modelo y del LLM — Caso 03

> Espejo en texto de la pestaña **Arquitectura → Evaluación del LLM** del dashboard.
> Regenerado automáticamente por `apps/web/build_page.py` a partir de `data/output/salida_150.xlsx`
> y `data/processed/model_selection.json` — los números de abajo son los del último run, no una
> proyección fija. Correr `python apps/web/build_page.py` tras cada corrida del pipeline.

## Selección del modelo de clustering

`experiments/scoring/model_selection.py` comparó **KMeans, Gaussian Mixture, Agglomerative y
DBSCAN**, sobre dos matrices de features (solo numérica vs. numérica + categóricas one-hot), barriendo
k=2..6, y midió `silhouette`, `davies_bouldin` y `calinski_harabasz` en las 32 combinaciones
resultantes. Regla de selección: preferir 3 clusters efectivos (el reto define 3 buckets latentes),
desempatar por mayor silhouette.

**Ganador: Agglomerative(k=3) sobre matriz numérica** — silhouette 0.462, Davies-Bouldin 0.810,
Calinski-Harabasz 212.9. Los pesos reales por señal (normalizados por eta²) y la tabla completa de
32 combinaciones están en `data/processed/model_selection.json` y se ven en la pestaña
**Modelo & Métricas** de la web.

## Prompts versionados

`llm/prompts.py` expone `PROMPT_VERSION` — cada decisión LLM puede trazarse a la versión exacta del
prompt que la produjo. El `SYSTEM_PROMPT` está diseñado para minimizar tokens: reglas compactas,
`max_tokens=450` en la llamada, y solo se invoca en los casos que el modelo de riesgo no resuelve.

## Métricas — del último run real

Calculadas por `apps/web/build_page.py` (`build_meta`) directamente desde
`data/output/salida_150.xlsx`, no hardcodeadas:

- **Cobertura determinística**: % de los 150 casos resueltos por Capa 0 sin tocar el LLM (0 tokens).
- **Tasa de escalamiento**: % de casos que terminan en ESCALAR. Objetivo de negocio: 20–35% (si sube
  de 35% el equipo se satura; si baja de 10% el sistema está forzando binarios donde no corresponde).
- **Fidelidad de esquema**: 100% por diseño — `llm/schemas.py` valida cada respuesta del LLM con
  Pydantic; si no valida, la decisión cae a ESCALAR fail-safe en vez de propagar un JSON roto.

## Nota honesta sobre el run que generó el dashboard

El Excel actual se generó con `--no-llm` (por presupuesto de tokens): los casos AMBIGUOS cayeron al
fallback determinístico "AMBIGUO → ESCALAR" **sin invocar ningún proveedor** — por eso su confianza
registrada es un valor fijo (0.5), no una salida real de LLM, y `modelo_usado` queda vacío en las 150
filas. Con presupuesto disponible, correr `python -m caso03.pipeline` (sin `--no-llm`) resuelve por
texto una parte de esos casos ambiguos y **baja la tasa de escalamiento** — que es exactamente el
objetivo del sistema: el LLM existe para reducir cuánto llega a un humano, no para decidir todo.

La telemetría de latencia y tasa de fallback entre proveedores se captura corriendo con LLM activo;
los resultados de esas corridas van a `experiments/llm/eval_runs/`.

## Qué cuenta como "alucinación" acá

El LLM solo puede citar señales que ya se le dieron en el prompt (bucket, score, señales dominantes,
texto del reclamo) — no tiene acceso a columnas fuera de eso, así que no puede "inventar" datos que
no existen en el caso. El control de última línea son los **guardrails de Capa 2**
(`feature_service.evaluate_guardrail` / `reconcile`): si el LLM aprueba un caso que el modelo de
riesgo marcó FRAUDE, o rechaza uno que marcó LEGÍTIMO sin contradicción de GPS, la decisión se
degrada a ESCALAR y el motivo queda registrado en la columna `override_guardrail` del Excel —
auditable caso por caso, no una estadística agregada que se pueda promediar y esconder.
