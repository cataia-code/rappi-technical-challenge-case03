# Arquitectura — Caso 03

> Espejo en texto de la pestaña **Arquitectura** del dashboard (`apps/web/templates/dashboard.html`).
> Los tres diagramas viven como definiciones Mermaid inline en ese archivo (`const DIAGRAMS`) y se
> renderizan en un modal con zoom y descarga; acá están en Mermaid puro para revisarlos sin abrir la web.

## Tres capas, con un backbone de datos

```
                 ┌─ Capa 0 · risk_service ─ modelo de riesgo (score + clustering)   [determinístico]
CompensationCase ┤
                 ├─ ¿bucket claro? → decisión determinística (92/150, sin LLM)
                 └─ ¿ambiguo?      → Capa 1 · llm/client (multi-proveedor, JSON validado)
                                     → Capa 2 · feature_service.reconcile (guardrails)
                                     → Decision (recomendación + resumen + señales + pasos)
```

- **Capa 0 — `scoring/risk_service`**: score de riesgo 0–1 ponderado por el poder discriminante real
  (eta²) de cada señal + clustering (modelo ganador: Agglomerative k=3, ver
  `data/processed/model_selection.json`). Si score y clúster coinciden → bucket; si discrepan →
  AMBIGUO. 100% determinístico y auditable. Entrenar: `python -m scoring.train_risk_model`
  (ejecutar con `PYTHONPATH=src`).
- **Capa 1 — `llm/client` + `llm/prompts`**: LLM multi-proveedor (Groq → Gemini → OpenRouter, en ese
  orden de fallback) con salida JSON validada (`llm/schemas.py`). Solo se invoca en casos ambiguos;
  el texto del reclamo se trata como dato no confiable (defensa contra inyección de prompt).
- **Capa 2 — `features/feature_service` (guardrails)**: acota la salida del LLM a la política
  (FRAUDE no puede auto-aprobarse; LEGÍTIMO no puede rechazarse sin contradicción de GPS; ante duda,
  ESCALAR). Nunca hay un RECHAZAR determinístico por reglas solas — el sesgo es FP&gt;FN.

## Dónde vive cada pieza

| Componente | Módulo | Rol |
|---|---|---|
| Backbone de datos | `services/data_service.py` | Único punto que sabe leer el Excel; normaliza NFC y valida con Pydantic (`domain/models.py`) |
| Normalización de categóricas | `experiments/scoring/model_selection.py` | One-hot de `vertical`/`motivo_reclamo`/`entrega_confirmada_gps` para la comparación de modelos |
| Modelo de riesgo | `scoring/risk_service.py` + `scoring/artifacts/risk_model.json` | Inferencia con solo numpy, sin sklearn en producción |
| LLM | `llm/client.py`, `llm/prompts.py`, `llm/schemas.py` | Cliente OpenAI-compatible (Groq/Gemini/OpenRouter), prompt versionado, schema Pydantic |
| Orquestador | `services/decision_service.py` | Fast-path determinístico + LLM + guardrails |
| Batch | `pipeline.py` | Corre los 150 casos → `data/output/salida_150.xlsx` |
| API | `apps/api/main.py` (FastAPI) | `POST /decisions`, `POST /cases/{id}/decisions`, `GET /health` |
| MCP | `apps/mcp/server.py` (FastMCP) | Tools `review_case` / `review_payload` |
| Web | `apps/web/build_page.py` + `apps/web/templates/dashboard.html` | Genera `docs/index.html` (GitHub Pages) |
| Worker LLM | `apps/web/worker/index.js` | Proxy público para la demo: `GET /health`, `POST /` para casos ambiguos; CORS restringido a GitHub Pages |

## Diagrama de secuencia

```mermaid
sequenceDiagram
    participant U as Pipeline / API / MCP
    participant DS as data_service
    participant FS as feature_service
    participant RS as risk_service
    participant LLM as llm.client
    participant GR as guardrails
    U->>DS: load_cases()
    DS->>FS: CompensationCase normalizado
    FS->>RS: assess(case)
    RS-->>FS: RiskAssessment (bucket, score, top señales)
    alt bucket claro (LEGITIMO o FRAUDE)
        FS-->>U: Decision determinística
    else AMBIGUO
        FS->>LLM: prompt versionado + señales + texto del reclamo
        LLM-->>FS: JSON validado (schema pydantic)
        FS->>GR: reconcile(decision, guardrail)
        GR-->>U: Decision final (+ override si aplica)
    end
```

## Árbol de decisión

```mermaid
flowchart TD
    A["Caso"] --> B{"risk_bucket"}
    B -- LEGITIMO --> C{"GPS contradice el reclamo?"}
    C -- No --> D["APROBAR (determinístico)"]
    C -- Sí --> E["AMBIGUO → LLM"]
    B -- FRAUDE --> F["RECHAZAR (determinístico)"]
    B -- AMBIGUO --> E
    E --> G["LLM decide"]
    G --> H{"¿Viola un guardrail de política?"}
    H -- Sí --> I["ESCALAR (override registrado)"]
    H -- No --> J{"confianza menor al umbral?"}
    J -- Sí --> I
    J -- No --> K["Decisión del LLM"]
```
