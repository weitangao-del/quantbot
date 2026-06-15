(function (root, factory) {
  const api = factory();
  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  }
  root.QuantbotDataUtils = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  const DROP_RATIO = 0.55;
  const NEIGHBOR_STABILITY_RATIO = 1.18;

  function normalizeRows(rows) {
    return (rows || []).map((row) => {
      const normalized = {};
      Object.keys(row || {}).forEach((key) => {
        normalized[key] = row[key] === "" ? null : row[key];
      });
      return normalized;
    });
  }

  function toNumber(value, fallback = 0) {
    const numeric = Number(value);
    return Number.isFinite(numeric) ? numeric : fallback;
  }

  function historyScore(row) {
    const timestamp = Date.parse(row.timestamp || row.date || row.Date || "");
    if (Number.isFinite(timestamp)) return timestamp;
    const runId = String(row.run_id || "");
    const numericRunId = Number(runId.replace(/[^0-9]/g, ""));
    return Number.isFinite(numericRunId) ? numericRunId : 0;
  }

  function sortHistory(history) {
    return (history || []).slice().sort((a, b) => historyScore(b) - historyScore(a));
  }

  function buildAumSeries(history) {
    const rows = sortHistory(history);
    return rows.filter((row, index) => isReliableAumRow(row, rows, index));
  }

  function filterHistoryByDays(history, days) {
    const rows = sortHistory(history);
    if (days === "all" || days === null || days === undefined) return rows;

    const dayCount = Math.max(Math.trunc(toNumber(days, 0)), 1);
    const latestTime = rows.map(historyScore).find((value) => value > 0);
    if (!latestTime) return rows;

    const threshold = latestTime - (dayCount - 1) * 24 * 60 * 60 * 1000;
    return rows.filter((row) => historyScore(row) >= threshold);
  }

  function isReliableAumRow(row, history, index) {
    const totalValue = rowTotal(row);
    if (totalValue <= 0) return false;
    if (!looksLikeIncompleteAdHocSnapshot(row)) return true;

    const newer = history[index - 1];
    const older = history[index + 1];
    const newerTotal = rowTotal(newer);
    const olderTotal = rowTotal(older);

    if (
      newerTotal > 0 &&
      olderTotal > 0 &&
      totalsAreStable(newerTotal, olderTotal) &&
      totalValue < Math.min(newerTotal, olderTotal) * DROP_RATIO
    ) {
      return false;
    }

    const referenceTotal = Math.max(newerTotal, olderTotal);
    if (referenceTotal > 0 && totalValue < referenceTotal * DROP_RATIO) {
      return false;
    }

    return true;
  }

  function looksLikeIncompleteAdHocSnapshot(row) {
    if (!row) return false;
    if (row.is_official_report === true) return false;
    if (String(row.record_type || "").toLowerCase() === "official") return false;

    const betaValue = toNumber(row.beta_core_value);
    const defenseValue = toNumber(row.defense_value);
    const liquidityWeight = toNumber(row.liquidity_weight);
    const alphaWeight = toNumber(row.alpha_satellite_weight);

    return betaValue === 0 && defenseValue === 0 && liquidityWeight >= 0.7 && alphaWeight <= 0.35;
  }

  function totalsAreStable(left, right) {
    const floor = Math.max(Math.min(left, right), 1);
    return Math.max(left, right) / floor <= NEIGHBOR_STABILITY_RATIO;
  }

  function rowTotal(row) {
    if (!row) return 0;
    return toNumber(row.total_value ?? row.Total_Value, 0);
  }

  return {
    buildAumSeries,
    filterHistoryByDays,
    historyScore,
    normalizeRows,
    sortHistory,
    toNumber,
  };
});
