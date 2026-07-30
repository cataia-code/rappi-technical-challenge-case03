/**
 * JS port of the Python decision core (scoring/risk_service.py +
 * features/feature_service.py + services/decision_service._fast_path).
 *
 * Kept dependency-free and framework-free on purpose so it runs unmodified in
 * two places: inline in the dashboard for the live demo, and under Node for
 * the Python<->JS parity check (see tests/test_scoring_js_parity.py).
 *
 * IMPORTANT: any change to the Python decision core must be mirrored here, or
 * the parity test will fail and the live demo will silently diverge from the
 * batch pipeline.
 */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) {
    module.exports = factory();
  } else {
    root.RappiScoring = factory();
  }
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  // --- feature_service.py constants ------------------------------------
  var HIGH_FLAGS = 2;
  var HIGH_COMPENSATIONS_90D = 6;
  var HIGH_EXPOSURE_MXN = 1500.0;
  var NEW_USER_DAYS = 30;

  var GPS_CONFIRMADA = 'si - confirmada';
  var GPS_NO_CONFIRMADA = 'no confirmada';
  var GPS_NO_CONCLUYENTE = ['parcial', 'senal perdida'];
  var NON_DELIVERY_REASONS = ['orden no llego', 'orden cancelada sin reembolso'];

  // --- scoring/risk_service.py phrase table ------------------------------
  var PHRASES = {
    num_comp_90d: ['muchas compensaciones en 90d', 'pocas compensaciones en 90d'],
    flags: ['flags de fraude previos', 'sin flags de fraude'],
    tiempo_entrega: ['entrega atípicamente rápida', 'tiempo de entrega normal/alto'],
    antiguedad: ['cuenta nueva', 'cuenta con antigüedad'],
    monto_comp_90d: ['monto compensado acumulado alto', 'monto compensado bajo'],
  };

  function normalizeKey(text) {
    return String(text)
      .normalize('NFD')
      .replace(/[̀-ͯ]/g, '') // strip combining diacritical marks
      .toLowerCase()
      .trim();
  }

  /** Mirrors feature_service.compute_features(case). `raw` uses full column names. */
  function computeFeatures(raw) {
    var gps = normalizeKey(raw.entrega_confirmada_gps);
    var reason = normalizeKey(raw.motivo_reclamo);
    var isNonDelivery = NON_DELIVERY_REASONS.indexOf(reason) !== -1;
    return {
      ratio_comp_orden: Math.round((raw.compensacion_solicitada_mxn / raw.valor_orden_mxn) * 100) / 100,
      gps_contradice_reclamo: gps === GPS_CONFIRMADA && isNonDelivery,
      gps_corrobora_reclamo: gps === GPS_NO_CONFIRMADA && reason === 'orden no llego',
      gps_no_concluyente: GPS_NO_CONCLUYENTE.indexOf(gps) !== -1,
      es_usuario_nuevo: raw.antiguedad_usuario_dias <= NEW_USER_DAYS,
      reincidencia_alta: raw.num_compensaciones_90d >= HIGH_COMPENSATIONS_90D,
      flags_altos: raw.flags_fraude_previos >= HIGH_FLAGS,
      exposicion_alta: raw.monto_compensado_90d_mxn >= HIGH_EXPOSURE_MXN,
    };
  }

  /** Mirrors risk_service.assess(case) for new/ad-hoc cases (centroid proxy path;
   * the exact-training-label branch never applies to synthetic demo cases). */
  function assessRisk(raw, riskModel) {
    var feats = riskModel.features;
    var mapping = {
      num_comp_90d: raw.num_compensaciones_90d,
      flags: raw.flags_fraude_previos,
      tiempo_entrega: raw.tiempo_entrega_real_min,
      antiguedad: raw.antiguedad_usuario_dias,
      monto_comp_90d: raw.monto_compensado_90d_mxn,
    };
    var x = feats.map(function (f) { return mapping[f]; });
    var z = x.map(function (v, i) { return (v - riskModel.scaler_mean[i]) / riskModel.scaler_scale[i]; });
    var signs = feats.map(function (f) { return riskModel.signs[f]; });
    var weights = riskModel.weights;
    var oriented = z.map(function (v, i) { return v * signs[i]; });
    var abuseIndex = oriented.reduce(function (sum, v, i) { return sum + v * weights[i]; }, 0);

    var c0 = riskModel.score_cuts[0], c1 = riskModel.score_cuts[1];
    var scoreBucket = abuseIndex < c0 ? 'LEGITIMO' : (abuseIndex < c1 ? 'AMBIGUO' : 'FRAUDE');

    var centroids = riskModel.centroids;
    var bestIdx = 0, bestDist = Infinity;
    for (var ci = 0; ci < centroids.length; ci++) {
      var dist = 0;
      for (var di = 0; di < z.length; di++) {
        var diff = centroids[ci][di] - z[di];
        dist += diff * diff;
      }
      if (dist < bestDist) { bestDist = dist; bestIdx = ci; }
    }
    var clusterBucket = riskModel.cluster_to_bucket[String(bestIdx)];

    var lo = riskModel.abuse_index_min, hi = riskModel.abuse_index_max;
    var riskScore = Math.min(1, Math.max(0, (abuseIndex - lo) / (hi - lo)));
    riskScore = Math.round(riskScore * 100) / 100;

    var contrib = oriented.map(function (v, i) { return v * weights[i]; });
    var order = contrib
      .map(function (v, i) { return { i: i, abs: Math.abs(v) }; })
      .sort(function (a, b) { return b.abs - a.abs; })
      .slice(0, 3)
      .map(function (o) { return o.i; });
    var top = order.map(function (i) {
      var pair = PHRASES[feats[i]];
      return contrib[i] > 0 ? pair[0] : pair[1];
    });

    var agreement = scoreBucket === clusterBucket;
    return {
      risk_score: riskScore,
      score_bucket: scoreBucket,
      cluster_bucket: clusterBucket,
      agreement: agreement,
      resolved_bucket: agreement ? scoreBucket : 'AMBIGUO',
      top_contribuyentes: top,
    };
  }

  /** Mirrors feature_service.evaluate_guardrail(risk, features). */
  function evaluateGuardrail(risk, f) {
    var b = risk.resolved_bucket;
    if (b === 'FRAUDE') {
      return { action: 'FORBID_APPROVE', reason: 'riesgo alto derivado (score ' + risk.risk_score + ')' };
    }
    if (b === 'LEGITIMO' && !f.gps_contradice_reclamo) {
      return { action: 'FORBID_REJECT', reason: 'riesgo bajo derivado (score ' + risk.risk_score + ')' };
    }
    if (b === 'AMBIGUO' && f.gps_contradice_reclamo) {
      return { action: 'FORBID_APPROVE', reason: 'ambiguo + GPS contradice el reclamo' };
    }
    return { action: 'NONE', reason: '' };
  }

  /** Mirrors decision_service._fast_path: returns a deterministic decision for
   * clear buckets, or null when the case must go to the LLM (AMBIGUO). */
  function fastPathWithRisk(raw, risk, features) {
    var b = risk.resolved_bucket;
    if (b === 'LEGITIMO' && !features.gps_contradice_reclamo) {
      return {
        recomendacion: 'APROBAR',
        confianza: Math.round((1 - risk.risk_score) * 100) / 100,
        resumen_cs: 'Bajo riesgo (score ' + risk.risk_score + '): ' + risk.top_contribuyentes.join(', ') + '. Reclamo consistente; proceder.',
      };
    }
    if (b === 'FRAUDE') {
      return {
        recomendacion: 'RECHAZAR',
        confianza: risk.risk_score,
        resumen_cs: 'Alto riesgo (score ' + risk.risk_score + '): ' + risk.top_contribuyentes.join(', ') + '. Señales de abuso; no proceder.',
      };
    }
    return null; // AMBIGUO, or LEGITIMO with GPS contradiction -> LLM
  }

  return {
    normalizeKey: normalizeKey,
    computeFeatures: computeFeatures,
    assessRisk: assessRisk,
    evaluateGuardrail: evaluateGuardrail,
    fastPathWithRisk: fastPathWithRisk,
  };
});
