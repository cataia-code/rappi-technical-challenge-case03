# Arquitectura — Caso 03

> Espejo en texto de las pestañas **Arquitectura** y **Escalamiento** del dashboard
> (`apps/web/templates/dashboard.html`). Los diagramas viven como definiciones Mermaid inline en ese
> archivo (`const DIAGRAMS`) y se renderizan en un modal con zoom y descarga; acá están en Mermaid
> puro para revisarlos sin abrir la web.

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

---

## Evolución propuesta: escalar a un agente multimodal, no a un LLM de texto

**Estado: diseño propuesto, todavía no implementado.** Hoy la Capa 1 recibe únicamente texto
(bucket, score, señales dominantes y `descripcion_reclamo`). Eso resuelve la mayoría de los casos
ambiguos, pero tiene un techo: un reclamo de "producto dañado" o "me enviaron otra cosa" es mucho
más fácil de verificar con una foto que con una frase, y el flag de GPS hoy es un estado agregado
(confirmada / no confirmada / parcial / señal perdida) — no la traza real del repartidor.

La propuesta evoluciona la Capa 1 de "LLM que lee un resumen de texto" a un **agente multimodal**
que puede consultar evidencia real antes de decidir, sin tocar Capa 0 (el modelo de riesgo sigue
siendo el mismo backbone determinístico) ni Capa 2 (los guardrails siguen acotando la salida igual):

- **Visión sobre la imagen del usuario**: si el reclamo incluye una foto, un modelo con visión
  (Gemini / GPT-4V / Claude) la analiza y contrasta contra el catálogo del pedido.
- **Traza real de GPS**: consulta la base de datos de tracking del repartidor — distancia mínima
  alcanzada al domicilio, tiempo detenido cerca de la dirección — en vez del flag agregado.
- **Historial ampliado**: reclamos previos del mismo usuario con foto adjunta, conversaciones de
  soporte anteriores.

Por qué esto reduce aún más el escalamiento a humano: hoy, un caso con relato plausible pero sin
forma de verificarlo objetivamente tiende a ESCALAR (ante la duda, no se fuerza un binario). Con
evidencia visual y de tracking real, una parte de esos casos deja de ser ambigua — la foto o la
traza GPS los resuelve directamente, y el humano solo ve lo que sigue siendo genuinamente incierto
incluso con más evidencia.

### Arquitectura evolucionada

```mermaid
flowchart TB
    subgraph Backbone["📊 Backbone de datos"]
        RAW[("🧾 Excel / API · caso")] --> DS["⚙️ data_service<br/>normaliza NFC + valida (pydantic)"]
    end
    DS --> FS["🛡️ features/feature_service<br/>señales derivadas + guardrails"]
    DS --> RS["🧠 scoring/risk_service<br/>modelo de riesgo (Capa 0, sin cambios)"]
    RS --> DEC{"¿bucket claro?"}
    DEC -- "sí · determinístico" --> OUT1["✅ Decision<br/>0 tokens"]
    DEC -- "no · AMBIGUO" --> AGENT["🤖 Agente multimodal<br/>(Capa 1 evolucionada)"]
    IMG[("📷 Imagen adjunta<br/>del reclamo")] -.-> AGENT
    GPSDB[("📍 Base de datos<br/>de tracking GPS")] -.-> AGENT
    HIST[("🗂️ Historial de<br/>reclamos previos")] -.-> AGENT
    AGENT --> GR["🛡️ feature_service.reconcile<br/>guardrails Capa 2 (sin cambios)"]
    GR --> OUT2["📝 Decision + resumen + pasos<br/>+ evidencia consultada"]
    OUT1 --> API["🔌 apps/api · FastAPI"]
    OUT2 --> API
    OUT1 --> WEBAPP["🖥️ apps/web · dashboard"]
    OUT2 --> WEBAPP
    classDef agent fill:#FF441F,color:#fff,stroke:#E0360F,stroke-width:2px
    classDef evidence fill:#FFE9E2,color:#2E2C36,stroke:#FF441F,stroke-width:1.5px
    classDef done fill:#E7F5EC,color:#14663a,stroke:#1F9D57
    class AGENT agent
    class IMG,GPSDB,HIST evidence
    class OUT1,OUT2 done
```

### Secuencia — caso ambiguo con foto adjunta

```mermaid
sequenceDiagram
    participant U as 👤 Usuario (app Rappi)
    participant API as 🔌 apps/api
    participant RS as 🧠 risk_service
    participant AG as 🤖 Agente multimodal
    participant VIS as 👁️ Modelo de visión
    participant GPS as 📍 GPS tracking DB
    U->>API: 📷 reclamo + foto del producto
    API->>RS: assess(case)
    RS-->>API: bucket AMBIGUO, score, señales
    API->>AG: caso + señales + foto + descripción
    AG->>VIS: 🔍 analizar foto vs. catálogo del pedido
    VIS-->>AG: "producto SÍ coincide" / "SÍ hay daño visible"
    AG->>GPS: 📍 consultar traza real del repartidor
    GPS-->>AG: distancia mínima, tiempo detenido cerca del domicilio
    AG->>AG: 🧩 combina evidencia visual + GPS + texto
    AG-->>API: ✅ veredicto + justificación fundamentada en evidencia
    API-->>U: 📝 decisión + resumen para CS
```

### Árbol de decisión evolucionado

```mermaid
flowchart TD
    A["🟡 Caso AMBIGUO"] --> B{"📷 ¿Tiene foto adjunta?"}
    B -- Sí --> C["👁️ Modelo de visión analiza la foto"]
    C --> D{"¿Evidencia visual es concluyente?"}
    D -- "Sí, confirma daño/error" --> E["✅ APROBAR (evidencia directa)"]
    D -- "Sí, contradice el reclamo" --> F["❌ RECHAZAR (evidencia directa)"]
    D -- No concluyente --> G
    B -- No --> G{"📍 ¿Traza GPS disponible?"}
    G -- Sí --> H["Consultar distancia mínima y tiempo cerca del domicilio"]
    H --> I{"¿Traza corrobora o contradice?"}
    I -- Corrobora --> E
    I -- Contradice --> F
    I -- No concluyente --> J["🤖 Agente decide por texto (como hoy)"]
    G -- No --> J
    J --> K{"¿Viola un guardrail de política?"}
    K -- Sí --> L["🔁 ESCALAR (override registrado)"]
    K -- No --> M["📝 Decisión del agente"]
    classDef approve fill:#E7F5EC,color:#14663a,stroke:#1F9D57
    classDef reject fill:#FBE6E6,color:#932528,stroke:#D93A3A
    classDef escalate fill:#FBF0D6,color:#8a6200,stroke:#E8A400
    class E approve
    class F reject
    class L escalate
```

### Cómo el agente analiza una imagen del reclamo

```mermaid
flowchart LR
    U["📤 Usuario sube foto<br/>del producto/paquete"] --> PRE["🖼️ Preprocesa la imagen<br/>(orientación, recorte, calidad mínima)"]
    PRE --> VIS["👁️ Modelo de visión<br/>(Gemini / GPT-4V / Claude)"]
    CAT[("🛒 Catálogo del pedido<br/>foto de referencia + descripción")] -.-> VIS
    VIS --> ATTR["🔍 Extrae atributos:<br/>objeto detectado · ¿daño visible? · color/modelo"]
    ATTR --> CMP{"¿Coincide con lo que se pidió?"}
    CMP -- "Sí, coincide y sin daño" --> R1["✅ Evidencia visual: reclamo NO se sostiene"]
    CMP -- "No coincide / daño visible" --> R2["❌ Evidencia visual: reclamo SÍ se sostiene"]
    CMP -- "Imagen borrosa / no concluyente" --> R3["🤔 Evidencia visual: no concluyente"]
    R1 --> COMB["🧩 Se combina con señales de riesgo + GPS + texto"]
    R2 --> COMB
    R3 --> COMB
    COMB --> OUT["📝 Veredicto final con justificación basada en evidencia"]
    classDef vision fill:#FF441F,color:#fff,stroke:#E0360F,stroke-width:2px
    classDef good fill:#E7F5EC,color:#14663a,stroke:#1F9D57
    classDef bad fill:#FBE6E6,color:#932528,stroke:#D93A3A
    classDef unclear fill:#FBF0D6,color:#8a6200,stroke:#E8A400
    class VIS vision
    class R1 good
    class R2 bad
    class R3 unclear
```

### Qué falta para implementarlo

- Elegir un proveedor de visión (Gemini, GPT-4V, Claude) y sumarlo a `llm/client.py`.
- Definir el contrato de subida de imagen en el formulario de reclamo (tamaño, formatos, dónde se
  almacena).
- Exponer un endpoint de lectura sobre la base de datos de tracking GPS real (hoy solo existe el
  flag agregado en `entrega_confirmada_gps`).
- Extender `domain/models.py` / `llm/schemas.py` para que la `Decision` registre qué evidencia
  (imagen, traza GPS) se consultó y qué concluyó, no solo el veredicto final.
