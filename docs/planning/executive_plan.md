# Plan Ejecutivo — Caso 03: Automatización de Revisión de Compensaciones

> Rappi AI Solution Builder · Trust & Safety · Agente de decisión APROBAR / RECHAZAR / ESCALAR
> Stack elegido: **LLM multi-proveedor con JSON validado** + guardrails determinísticos · Demo: **web estática + MCP/API + export Excel**

---

## Context — por qué este trabajo

T&S recibe **200+ solicitudes/día** marcadas como posible fraude. Hoy un agente CS revisa cada una a mano (historial, GPS, patrón de reclamos): **15–25 min/caso**, criterio inconsistente entre agentes. Resultado: compensaciones legítimas demoradas *y* fraude que se cuela por falta de tiempo. Construimos un agente que emite una recomendación fundamentada + un resumen que el CS revisa **en segundos**, sobre los 150 casos del dataset `Caso3_Compensaciones`. Lo que más se evalúa: **cómo maneja la ambigüedad** (escalar con criterio, no por default).

---

## 1. Resumen ejecutivo (el problema en 3 líneas)

1. Automatizar el triage de 200+ casos/día de posible fraude en compensaciones, hoy 100% manual y lento.
2. El agente decide **APROBAR / RECHAZAR / ESCALAR** con justificación auditable y las 2–3 señales dominantes visibles.
3. El valor no está en el fraude obvio ni el legítimo obvio — está en **enrutar la incertidumbre a ESCALAR con contexto ya procesado**, no en forzar un binario.

---

## 2. Marco de negocio (los números cierran)

**Costo actual:** 200 casos/día × 20 min (punto medio) = **4.000 min/día ≈ 66,7 horas-persona/día ≈ 8,3 agentes** dedicados solo a este triage.

**¿Qué error cuesta más — FP o FN?** (Marco: "positivo" = detectar fraude)
- **Falso Positivo** = RECHAZAR a un usuario legítimo. Costo: churn de un usuario con LTV alto, caída de CSAT, riesgo reputacional/legal. **Difícil de revertir** (el usuario molesto se va).
- **Falso Negativo** = APROBAR un fraude. Costo: el monto pagado, **acotado** (comp. entre $70–$692 MXN, y *nunca* supera el valor de la orden — ver §3). Riesgo real: si es sistemático, invita abuso organizado que escala.
- **Decisión de política:** el FP unitario suele costar más que el FN unitario (payout chico y acotado vs. LTV perdido). Por eso **la barra de RECHAZAR es conservadora** (alta precisión: solo se rechaza con evidencia fuerte) y **la incertidumbre va a ESCALAR, no a RECHAZAR**. Esto ataca directamente el criterio "no fuerza decisión binaria donde no la hay".

**Margen de tolerancia al escalamiento:** meta **20–30%**. A 25% = 50 casos/día; con contexto pre-procesado el CS los cierra en ~5 min (vs 20) → ~4,2 h ≈ **1 agente**. El equipo aguanta hasta ~35% antes de saturarse → ése es el umbral de alarma.

**Qué ocurre en cada escenario:**
| Escenario | Acción del sistema | Toque humano |
|---|---|---|
| APROBAR | Marca para compensar + resumen 1-línea | Spot-check por muestreo (~1 min) |
| RECHAZAR | Marca no-proceder + evidencia de fraude | Spot-check + apelable por usuario |
| ESCALAR | Cola humana **con** señales + resumen ya redactados | Revisión enfocada ~5 min |

---

## 3. Análisis exploratorio del dataset (150 casos, 15 señales)

**Hallazgo que mata un supuesto ingenuo:** `compensacion_solicitada` es **siempre ≤ `valor_orden`** (ratio mediana 0,83; máx 1,00; **0 casos** de sobre-reclamo). ⇒ "monto desproporcionado" **NO** es señal utilizable aquí; usar el ratio como hard-stop sería un error. Defendible ante auditoría.

**Nota de calidad de datos:** el Excel trae *mojibake* (Bogotá, São Paulo, "Sí" mal codificados). El pipeline debe **normalizar encoding** al leer, o las reglas por GPS/ciudad fallan silenciosamente.

**Top 5 señales predictivas de fraude (con justificación):**
| # | Señal | Por qué predice fraude |
|---|---|---|
| 1 | `flags_fraude_previos` (0–4; **48 casos ≥2**) | Marca directa de abuso histórico verificado; la señal más limpia. |
| 2 | `num_compensaciones_90d` (0–14; **42 casos ≥6**) | Reincidencia: pedir compensación cada pocos días es patrón de farmeo. |
| 3 | `entrega_confirmada_gps` × `motivo_reclamo` | **Cross-check de coherencia**: GPS "Sí-confirmada" + "Orden no llegó" = contradicción (fraude); "NO confirmada" + "Orden no llegó" = corrobora (legítimo). La joya interpretable. |
| 4 | `monto_compensado_90d` (hasta **$2.764**) | Exposición acumulada; monto alto ya cobrado eleva el riesgo aunque cada caso parezca menor. |
| 5 | `antiguedad_usuario_dias` (**23 usuarios ≤30d**) | Cuenta nueva + reclamo temprano = perfil clásico de cuenta desechable. |

Señal semántica auxiliar: `descripcion_reclamo` (texto libre) — coherencia con `motivo`, menciones de salud/alergia (sensibilidad), lenguaje de guion. Es la entrada natural del razonamiento LLM.

**Distribución estimada (heurística de sanidad, no etiquetas):** ~**48** casos con señal fuerte de fraude (flags≥2), un núcleo legítimo claro (histórico limpio + GPS coherente), y una **banda media ambigua de ~90–100 casos** — que es precisamente donde el agente debe brillar. Objetivo de reparto: **~45% APROBAR / ~25% RECHAZAR / ~30% ESCALAR** (a calibrar en Fase 1).

**3 casos ancla reales del dataset:**
- **RECHAZAR** — `COMP-0011`: antig 42d, 9 comps/90d, $880 compensado, **4 flags**, GPS **Sí-confirmada**, motivo "cancelada sin reembolso". Reincidencia + flags + GPS contradice el reclamo.
- **APROBAR** — `COMP-0001`: antig **1590d**, 2 comps/90d, $104 compensado, **0 flags**, GPS "NO confirmada", "Producto incorrecto". Cliente veterano, histórico limpio, GPS no contradice.
- **ESCALAR** — `COMP-0012`: antig 373d, 5 comps/90d, 1 flag, GPS "Sí-confirmada", "Producto incorrecto" ("el refresco no es el que pedí"). Señales mixtas, monto bajo, reclamo plausible → humano con contexto.

---

## 4. Arquitectura de decisión — 3 capas (LLM-first)

**Capa 0 — Feature engineering + guardrails determinísticos (pre-LLM).**
Se calculan en Python *antes* de llamar al modelo y se inyectan en el prompt como hechos, no como texto crudo: `ratio_comp_orden`, `flag_gps_contradice_motivo` (bool), `es_usuario_nuevo`, `reincidencia_bucket`, `exposicion_90d`. Dos **hard-stops** que pueden anular al LLM (auditoría/legal):
- *Hard-approve* candidato: `flags=0` ∧ `num_comp≤2` ∧ GPS coherente ∧ monto bajo → nunca RECHAZAR.
- *Hard-review*: `flags≥3` ∨ `num_comp≥8` → nunca APROBAR sin pasar por RECHAZAR/ESCALAR.
Esto acota el no-determinismo del LLM y da una red de seguridad defendible.

**Capa 1 — Motor de decisión LLM con JSON validado (núcleo).**
Un prompt estructurado por caso recibe las señales + features de Capa 0 + `descripcion_reclamo`, evalúa coherencia GPS↔motivo, patrón histórico y plausibilidad del texto, y devuelve **JSON validado**: `{justificacion, recomendacion, confianza(0–1), senales_dominantes[2-3], resumen_cs}`. Controles de rigor: `temperature=0`, salida estructurada, descripción del usuario tratada como dato no confiable, y regla de enrutamiento: **si confianza < umbral → ESCALAR** (la incertidumbre no se fuerza a binario).

**Capa 2 — Interpretabilidad ("el CS entiende en 5 segundos").**
Cada caso muestra: semáforo (verde/rojo/ámbar), **las 2–3 señales que dominaron**, y un **resumen de 1 línea**. Ej.: *"RECHAZAR — 4 flags previos + 9 reclamos/90d + GPS confirma entrega que el usuario niega."*

---

## 5. Matriz de decisión (si X → Y porque Z)

| # | Condición (X) | Decisión (Y) | Razón (Z) |
|---|---|---|---|
| 1 | `flags=0` ∧ `num_comp≤2` ∧ GPS no contradice motivo ∧ monto bajo | **APROBAR** | Perfil limpio y coherente; el costo de un FP (churn) supera el payload chico. |
| 2 | GPS "Sí-confirmada" ∧ motivo ∈ {"Orden no llegó","cancelada sin reembolso"} ∧ (`flags≥2` ∨ `num_comp≥6`) | **RECHAZAR** | Contradicción dura GPS↔reclamo **+** patrón de abuso: evidencia fuerte y auditable. |
| 3 | `flags≥3` ∨ `num_comp≥8` ∨ `monto_compensado_90d` muy alto | **RECHAZAR / ESCALAR** | Reincidencia extrema; nunca auto-APROBAR. ESCALAR si el reclamo actual es plausible. |
| 4 | `usuario_nuevo (≤30d)` ∧ `num_comp≥3` | **ESCALAR** | Cuenta nueva con reclamos tempranos = perfil desechable, pero sin histórico para condenar. |
| 5 | Señales mixtas (1 flag, GPS parcial/perdida, monto medio, texto plausible) | **ESCALAR** | Ambigüedad genuina; humano con contexto pre-procesado, no un binario forzado. |
| 6 | GPS "NO confirmada" ∧ motivo "Orden no llegó" ∧ histórico limpio | **APROBAR** | El GPS **corrobora** que la entrega falló; reclamo consistente. |

---

## 6. Por qué este stack (y no otro)

- **LLM acotado (elegido):** el valor está en la banda ambigua y en leer `descripcion_reclamo`; la evaluación semántica captura coherencia que las reglas puras no ven, y produce el `resumen_cs` "listo para revisar". Trade-off asumido: menor determinismo y llamadas externas → **mitigado** con `temperature=0`, salida JSON validada, parser estricto y los **guardrails de Capa 0** (hard-stops) que mantienen la auditabilidad que legal exige.
- **Por qué no reglas puras:** no interpretan el texto libre ni redactan resúmenes; frágiles ante casos nuevos.
- **Por qué no no-code:** difícil versionar/testear el scoring fino y el prompt; peor para demo reproducible en vivo.
- **Sesgo:** CDMX (27) y "Comida" (79) están sobre-representados. **No** se usa ciudad/vertical como señal de decisión (solo contexto) para no penalizar geografías; se reporta el reparto de decisiones por ciudad/vertical para auditar disparidad.

---

## 7. Métricas de éxito

- **Reparto de decisiones** cercano a 45/25/30 (APROBAR/RECHAZAR/ESCALAR); **alarma si ESCALAR > 35%** (satura al equipo) **o < 10%** (fuerza binarios).
- **Precisión de RECHAZAR** (validación manual sobre muestra): objetivo ≥ 90% — priorizamos no rechazar legítimos.
- **Cobertura auto-resuelta:** ≥ 65% (APROBAR+RECHAZAR) para liberar horas.
- **Concordancia con revisión manual** en un set de ~30 casos etiquetados a mano (Fase 1).
- **Determinismo:** misma entrada → misma salida en 3 corridas (verificación de estabilidad).

---

## 8. Preguntas de negocio respondidas

- **Si escalo el 25%, ¿cuántas horas-persona libero?** De 66,7 h/día, se automatizan 150 casos × 20 min = **50 h/día liberadas directamente**; los 50 escalados bajan de 20→~5 min (–12,5 h). Toque humano nuevo ≈ 4–6 h/día → se libera el equivalente a **~7–8 agentes**, dejando ~1 dedicado a la cola ESCALAR.
- **Impacto FP vs FN:** FP (rechazar legítimo) = churn + CSAT + riesgo reputacional, difícil de revertir → **más caro por unidad**. FN (aprobar fraude) = payout acotado ($70–$692), tolerable puntual pero peligroso si es sistemático. ⇒ RECHAZAR conservador, incertidumbre a ESCALAR.
- **¿Cómo monitoreo si el agente "está atrapado"?** Dashboard con: tasa de ESCALAR (alarma fuera de 10–35%), distribución de `confianza` (si se apila en el umbral → mal calibrado), deriva del reparto por ciudad/vertical (sesgo), y % de casos donde el hard-stop de Capa 0 tuvo que anular al LLM (si sube → prompt degradado).

---

## 9. Roadmap ejecutable (5 días)

- **Fase 0 — Exploración + hipótesis (2 h):** limpieza/encoding, perfilado de señales, confirmar buckets y umbrales candidatos. *Entrega:* notebook + hipótesis de señales.
- **Fase 1 — Políticas + validación manual (1 día):** cerrar matriz de decisión y umbrales, etiquetar ~30 casos a mano como ground-truth y calibrar el umbral de confianza→ESCALAR. *Entrega:* `docs/politicas_decision.md` + set etiquetado.
- **Fase 2 — Implementar el agente (1,5 días):** Capa 0 (features + guardrails), Capa 1 (prompt con salida JSON validada + reintentos), Capa 2 (señales dominantes + resumen). Correr los 150 casos → Excel/CSV enriquecido. *Entrega:* agente end-to-end.
- **Fase 3 — Testing + edge cases + docs (1 día):** validar contra el set etiquetado, probar edge cases (GPS "Señal perdida"/"Parcial", monto máximo, usuario nuevo), test de determinismo, README de 1 página. *Entrega:* métricas + doc.
- **Fase 4 — Demo + pulido (0,5 día):** web estática en `docs/` (tabla filtrable + detalle por caso + export), MCP en `apps/mcp/` y superficie API en `apps/api/`. *Entrega:* demo desplegable.

---

## 10. Archivos a crear (fase de build, tras aprobación)

```
src/caso03/
  services/data_service.py    # lectura + normalización de encoding
  features/feature_service.py # Capa 0: features derivadas + guardrails
  llm/                        # Capa 1: prompt, cliente multi-proveedor, schema JSON
  scoring/                    # modelo de riesgo data-driven + artefacto JSON
  pipeline.py                 # corre los 150 casos → Excel
apps/
  web/                        # Capa 2: dashboard estático + build a docs/index.html
  mcp/                        # servidor FastMCP
  api/                        # superficie FastAPI prevista
docs/
  politicas_decision.md       # criterios y manejo de ambigüedad
tests/                        # guardrails, scoring, LLM client y pipeline
```
Reutilizar: `pandas` para I/O, la matriz de §5 como fuente única de umbrales (constantes en `features.py`), y los 3 casos ancla de §3 como fixtures de test.

---

## 11. Verificación (cómo se prueba end-to-end)

1. `$env:PYTHONPATH="src"; .\.venv\Scripts\python.exe -m caso03.pipeline --no-llm` → genera `data/output/salida_150.xlsx` con los 150 casos, `recomendacion_agente` lleno, justificación y señales.
2. Chequear reparto de decisiones (≈45/25/30) y que ningún caso quede `PENDIENTE`.
3. Correr `tests/` — guardrails de Capa 0 y determinismo (misma entrada → misma salida).
4. Validar contra el set de ~30 casos etiquetados: precisión de RECHAZAR ≥90%, concordancia global.
5. `.\.venv\Scripts\python.exe apps\web\build_page.py` → abrir `docs/index.html` y revisar 5 casos (uno por decisión). **Prueba de "5 segundos":** ¿el CS entiende cada decisión con el semáforo + 2–3 señales + resumen, sin abrir el detalle?
6. Ensayo de demo en vivo sobre el dataset completo.
