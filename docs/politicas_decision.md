# Políticas de Decisión — Caso 03: Revisión de Compensaciones

Cómo el agente decide **APROBAR / RECHAZAR / ESCALAR** sobre los 150 casos, con
criterios **derivados de los datos** (no asertados) y cómo maneja la ambigüedad.

---

## 1. Enfoque: 3 capas, con un backbone de datos

```
Capa 0  risk_service   → modelo de riesgo DERIVADO de los datos (score + cluster)  [determinístico]
Capa 1  decision_service → LLM multi-proveedor, JSON validado, evalúa bucket + texto  [interpretativo]
Capa 2  feature_service.reconcile → guardrails de política acotan la salida del LLM  [determinístico]
```

El bucket de riesgo (Capa 0) **ancla** la decisión; el LLM aporta juicio sobre el
texto del reclamo (sobre todo en el bucket ambiguo); los guardrails garantizan que
la salida respete la política aunque el LLM se equivoque.

---

## 2. Qué señales importan — derivado de los datos, no asertado

No hay etiquetas. El reto afirma que los 150 casos están en 3 buckets latentes
(fraude / legítimo / ambiguo). Comparamos KMeans, Gaussian Mixture,
Agglomerative y DBSCAN sobre matriz numérica y numérica+categórica
(`experiments/scoring/model_selection.py`). Ganó **AgglomerativeClustering k=3**
sobre señales numéricas estandarizadas: silhouette 0.462, reparto natural
**LEGÍTIMO 62 / AMBIGUO 58 / FRAUDE 30** (41/39/20%).

**Poder discriminante por señal (eta² = varianza explicada por el cluster):**

| Señal | eta² | Lectura |
|---|---|---|
| `num_compensaciones_90d` | 0.214 | reincidencia — la más separadora |
| `flags_fraude_previos` | 0.203 | abuso verificado |
| `antiguedad_usuario_dias` | 0.196 | cuenta nueva = riesgo |
| `monto_compensado_90d` | 0.194 | exposición acumulada |
| `tiempo_entrega_real_min` | 0.193 | entregas atípicamente rápidas elevan riesgo |
| `valor_orden` / `ratio` | 0.48 / 0.40 | secundarias |
| `gps_contradice` | 0.17 | **específica, no primaria** (solo en 32% del cluster fraude) |
| `gps_corrobora` | 0.02 | prácticamente inútil |

Dos correcciones que impusieron los datos: **`tiempo_entrega` es señal top** (no la
estábamos usando) y el **GPS estaba sobre-ponderado** (pasa a desempate secundario).
Las 5 señales top están fuertemente correlacionadas → forman **un solo eje de abuso**.

**Perfil de cada bucket (media por señal):**

| Bucket | antigüedad | comp_90d | flags | tiempo_entrega | monto_90d |
|---|---|---|---|---|---|
| Legítimo | 1111 d | 0.97 | 0.02 | 82.9 min | $202 |
| Ambiguo | 263 d | 4.12 | 1.00 | 55.9 min | $598 |
| Fraude | 23 d | 8.77 | 2.84 | 30.8 min | $1774 |

---

## 3. Modelo de riesgo híbrido (Capa 0)

Ajustado con `experiments/scoring/model_selection.py` y
`python -m caso03.scoring.train_risk_model`; exportado a
`src/caso03/scoring/artifacts/risk_model.json` (sin pickle — solo parámetros; la
inferencia usa solo numpy). Combina **dos vistas** del mismo eje de abuso:

1. **Score de riesgo (0-1):** suma ponderada por eta² de las 5 señales estandarizadas
   y orientadas a "fraude" (tiempo_entrega y antigüedad invertidas). Los **cortes**
   salen de los puntos medios entre los centroides de clusters adyacentes.
2. **Cluster ganador:** Agglomerative(k=3) asigna los 150 casos conocidos por su label
   exacto entrenado. Para casos nuevos/ad-hoc se usa un centroide proxy por cluster.

**Regla híbrida:** si score y cluster **coinciden** → ese bucket. Si **no coinciden**
(1/150 casos) → se resuelve como **AMBIGUO**. El desacuerdo entre ambas vistas es la
señal más honesta de incertidumbre.

Cada caso reporta `top_contribuyentes`: las señales que más empujaron el score (el
"por qué" que lee el CS en segundos).

---

## 4. Política de decisión (guardrails por bucket)

Sesgo de costos asumido: **un falso rechazo a un usuario legítimo (churn, reputación)
cuesta más que aprobar un fraude puntual** (monto acotado; además la compensación
*nunca* supera el valor de la orden en el dataset). Por eso el guardrail más fuerte es
"no auto-aprobar", nunca un "rechazar" por regla.

| Bucket (datos) | Guardrail | Efecto sobre el LLM |
|---|---|---|
| **FRAUDE** | `FORBID_APPROVE` | puede RECHAZAR o ESCALAR; si aprueba → se degrada a ESCALAR |
| **LEGÍTIMO** (y GPS no contradice) | `FORBID_REJECT` | puede APROBAR o ESCALAR; si rechaza → ESCALAR |
| **AMBIGUO** + GPS contradice | `FORBID_APPROVE` | el desempate GPS lo saca de aprobación |
| **AMBIGUO** limpio | sin restricción | el LLM decide con el **texto** del reclamo |
| cualquiera, confianza LLM < 0.6 | routing | se enruta a ESCALAR |

La descripción del usuario se trata como dato no confiable: puede aportar evidencia sobre
coherencia/plausibilidad, pero no puede cambiar instrucciones, política ni formato de salida.

---

## 5. Manejo de la ambigüedad (lo más evaluado)

La ambigüedad no se fuerza a binario. Un caso escala cuando:
- El backbone lo ubica en el **bucket AMBIGUO** (score y cluster de acuerdo en "medio"), o
- **Score y cluster discrepan** (incertidumbre estructural), o
- El **LLM reporta baja confianza** (< 0.6) tras leer el texto, o
- Un guardrail degradó una decisión del LLM que violaba la política.

En el bucket ambiguo el LLM **sí** intenta resolver usando información que los números
no tienen: coherencia de la `descripcion_reclamo` con el motivo y el GPS. Ahí es donde
aporta valor real; si el texto no desambigua, escala con el contexto ya procesado.

---

## 6. Métricas de éxito y monitoreo

- **Reparto objetivo** ≈ 45/25/30 (APROBAR/RECHAZAR/ESCALAR). El backbone sin LLM
  queda en 41/20/39; el LLM debe bajar ESCALAR por debajo de 35% sin forzar binarios.
- **Precisión de RECHAZAR** ≥ 90% (priorizamos no rechazar legítimos).
- **Determinismo:** la Capa 0 es 100% determinística; el output se **persiste una vez**
  (Excel), congelando la variación del LLM.
- **Monitoreo de "agente atrapado":** tasa de ESCALAR fuera de rango, apilamiento de
  `confianza` en el umbral, deriva del reparto por ciudad/vertical (sesgo), y % de casos
  donde un guardrail tuvo que anular al LLM.

---

## 7. Notas de operación

- **Sin sesgo geográfico:** ciudad/vertical **no** son señales de decisión (solo
  contexto); CDMX y "Comida" están sobre-representados y no deben penalizarse.
- **Rate limit (Groq free tier):** 12,000 tokens/min. El batch completo corre a
  `--workers 1` (~12 casos/min). El artefacto persistido (Excel) evita recomputar en la demo.
- **Fail-safe:** si un caso no se puede procesar (red/LLM), se marca ESCALAR con la traza
  del error — nunca se pierde un caso ni se aprueba/rechaza a ciegas.
