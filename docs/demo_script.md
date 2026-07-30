# Guion de presentación (30 min) — Caso 03

> Para la sesión con el squad de AI. Objetivo: correr el agente en vivo y responder preguntas de
> diseño — no leer slides. Cronometrado en bloques de ~5 min; recortar según el tiempo real.

## 0. Antes de empezar (setup, no cronometrado)
- `git pull` para tener el último estado.
- `./.venv/Scripts/python.exe -m pytest -q` — mostrar que la suite pasa (33 tests) si preguntan.
- Abrir `docs/index.html` en el navegador (o `python -m http.server` desde `docs/` si prefieren
  verlo servido en vez de `file://`).
- Tener `data/output/salida_150.xlsx` abierto en una pestaña aparte por si piden ver el Excel crudo.

## 1. El problema en 30 segundos (tab **Exploración**)
- "Trust & Safety recibe 200+ solicitudes/día marcadas como posible fraude. Hoy se revisan a mano,
  15-25 min c/u, criterio inconsistente entre agentes."
- Señalar los 4 stat cards: 200+/día, 15-25 min, ~67 h/día ≈ 8 agentes, 3 decisiones posibles.
- Leer el callout de sesgo de costos en voz alta — es la decisión de diseño más importante del
  proyecto y hay que decirla explícita, no dejar que la infieran.

## 2. Por qué no inventamos umbrales (tab **Exploración** → **Modelo & Métricas**)
- "El dataset no viene etiquetado. En vez de fijar cortes a ojo, dejamos que un análisis no
  supervisado los recuerde."
- Mostrar la tabla comparativa (32 combinaciones algoritmo×matriz×k) con la fila ganadora resaltada.
- Mostrar los **pesos reales** por señal (barras en Modelo & Métricas) — insistir en que no están
  hardcodeados, salen de `eta2` normalizado del modelo ganador.
- Mostrar el scatter PCA: separación visual clara de los 3 buckets.
- Punto de venta: "el GPS parecía la señal obvia y resultó secundaria; los datos lo corrigieron."

## 3. Arquitectura (tab **Arquitectura**)
- Abrir el diagrama de **Arquitectura** (modal, zoom para mostrar el detalle de las 3 capas).
- Abrir el de **Secuencia** — trazar un caso ambiguo en voz alta mientras se sigue el diagrama.
- Mencionar la sección de **Evaluación del LLM**: cobertura determinística real (61.3%), tasa de
  escalamiento real (38.7%), y ser honestos sobre que este batch corrió con `--no-llm` (por
  presupuesto de tokens) — no ocultarlo, es parte de la historia de "cómo manejamos ambigüedad
  con recursos limitados".

## 4. Dashboard de los 150 casos (tab **Dashboard**)
- Filtrar por ESCALAR, abrir un caso: mostrar el resumen + los **pasos recomendados** (esto
  responde directamente al criterio "el agente CS puede actuar sin investigación adicional").
- Abrir un caso APROBAR y uno RECHAZAR determinísticos — señalar que corrieron con 0 tokens.
- Si preguntan por manejo de ambigüedad: abrir un caso donde `risk_bucket=AMBIGUO` y mostrar cómo
  el `override_guardrail` (si aplica) documenta por qué se degradó una decisión.

## 5. Demo en vivo (tab **Demo**) — el momento fuerte
- Clic en **Regenerar** un par de veces para mostrar variedad de perfiles.
- Clic en **Probar** con un caso que dé bucket claro (APROBAR o RECHAZAR): señalar que el
  clustering corrió **en el navegador**, 0 llamadas de red, mismos pesos que la tab Modelo.
- Regenerar hasta obtener un caso AMBIGUO y Probar: mostrar el paso a paso (normalización → riesgo
  → ruteo). Si el Worker de Cloudflare **no está desplegado**, decirlo abiertamente: "acá llamaría
  a un LLM real vía un proxy serverless; el código está listo en `apps/web/worker/`, no lo
  desplegamos porque necesita una cuenta y keys propias — mientras tanto cae al mismo fallback
  conservador que usa el pipeline batch." Esto es más creíble que fingir una respuesta.
- (Si el Worker SÍ está desplegado para esta sesión: mostrar el `modelo_usado` en la respuesta y
  explicar el fallback multi-proveedor.)

## 6. Cierre — preguntas de diseño esperadas (tener la respuesta lista, no leerla)
- **"¿Por qué no LLM para todo?"** → costo/latencia/auditabilidad; los datos ya separan un núcleo
  legítimo y uno de fraude con alta confianza; el LLM se reserva para donde aporta juicio real.
- **"¿Cómo evitan que el LLM alucine?"** → guardrails de Capa 2 (`feature_service.reconcile`):
  nunca puede auto-aprobar un FRAUDE derivado de datos ni rechazar un LEGÍTIMO sin contradicción
  de GPS; toda degradación queda en `override_guardrail`, auditable caso por caso.
- **"¿Qué pasa si se acaba el rate limit de un proveedor?"** → `llm/client.py` hace fallback en
  cascada (Groq → Gemini → OpenRouter, configurable); si los tres fallan, el caso cae a ESCALAR
  fail-safe, nunca se pierde ni se inventa una decisión.
- **"¿Cómo saben que el JS de la demo no miente sobre cómo decide?"** → test de paridad real
  (`tests/test_scoring_js_parity.py`) que corre Node y compara contra Python, caso por caso.
- **"¿Qué harían con más tiempo?"** → ver la sección "Con más tiempo" del `README.md` (etiquetado
  manual, telemetría real de LLM, desplegar el Worker, sincronizar el prompt automáticamente).
