const test = require("node:test");
const assert = require("node:assert/strict");

const {
  buildAumSeries,
  filterHistoryByDays,
  normalizeRows,
  sortHistory,
} = require("../web/data-utils.js");

test("buildAumSeries filters incomplete midday snapshots that collapse AUM", () => {
  const history = sortHistory(normalizeRows([
    {
      run_id: "20260615-180057",
      timestamp: "2026-06-15T18:00:57+08:00",
      session: "晚盘正式结算",
      record_type: "official",
      total_value: 133273.52,
      beta_core_value: 73317.44,
      alpha_satellite_value: 5699.22,
      defense_value: 30323.19,
      liquidity_value: 23933.67,
      liquidity_weight: 0.1796,
      is_official_report: true,
    },
    {
      run_id: "20260615-120039",
      timestamp: "2026-06-15T12:00:39+08:00",
      session: "午间资产快照",
      record_type: "ad_hoc",
      total_value: 29620.66,
      beta_core_value: 0,
      alpha_satellite_value: 5686.99,
      defense_value: 0,
      liquidity_value: 23933.67,
      liquidity_weight: 0.808006,
      is_official_report: false,
    },
    {
      run_id: "20260615-060032",
      timestamp: "2026-06-15T06:00:32+08:00",
      session: "早盘资产快照",
      record_type: "ad_hoc",
      total_value: 131371.62,
      beta_core_value: 71854.01,
      alpha_satellite_value: 5583.11,
      defense_value: 30000.83,
      liquidity_value: 23933.67,
      liquidity_weight: 0.1822,
      is_official_report: false,
    },
  ]));

  const series = buildAumSeries(history);
  assert.equal(series.length, 2);
  assert.deepEqual(series.map((row) => row.run_id), [
    "20260615-180057",
    "20260615-060032",
  ]);
});

test("buildAumSeries keeps normal intraday snapshots", () => {
  const history = sortHistory(normalizeRows([
    {
      run_id: "20260614-180032",
      timestamp: "2026-06-14T18:00:32+08:00",
      session: "晚盘正式结算",
      record_type: "official",
      total_value: 131281.58,
      beta_core_value: 72000,
      alpha_satellite_value: 5300,
      defense_value: 30000,
      liquidity_value: 23981.58,
      liquidity_weight: 0.1827,
      is_official_report: true,
    },
    {
      run_id: "20260614-120100",
      timestamp: "2026-06-14T12:01:00+08:00",
      session: "午间资产快照",
      record_type: "ad_hoc",
      total_value: 131284.76,
      beta_core_value: 71970,
      alpha_satellite_value: 5333,
      defense_value: 30000,
      liquidity_value: 23981.76,
      liquidity_weight: 0.1827,
      is_official_report: false,
    },
    {
      run_id: "20260614-060105",
      timestamp: "2026-06-14T06:01:05+08:00",
      session: "早盘资产快照",
      record_type: "ad_hoc",
      total_value: 131280.4,
      beta_core_value: 71960,
      alpha_satellite_value: 5339,
      defense_value: 30000,
      liquidity_value: 23981.4,
      liquidity_weight: 0.1827,
      is_official_report: false,
    },
  ]));

  const series = buildAumSeries(history);
  assert.equal(series.length, 3);
  assert.deepEqual(series.map((row) => row.run_id), [
    "20260614-180032",
    "20260614-120100",
    "20260614-060105",
  ]);
});

test("buildAumSeries filters an incomplete newest ad hoc snapshot using the previous healthy row", () => {
  const history = sortHistory(normalizeRows([
    {
      run_id: "20260616-120000",
      timestamp: "2026-06-16T12:00:00+08:00",
      session: "午间资产快照",
      record_type: "ad_hoc",
      total_value: 29750,
      beta_core_value: 0,
      alpha_satellite_value: 5800,
      defense_value: 0,
      liquidity_value: 23950,
      liquidity_weight: 0.805,
      is_official_report: false,
    },
    {
      run_id: "20260616-060000",
      timestamp: "2026-06-16T06:00:00+08:00",
      session: "早盘资产快照",
      record_type: "ad_hoc",
      total_value: 132000,
      beta_core_value: 72000,
      alpha_satellite_value: 6000,
      defense_value: 30000,
      liquidity_value: 24000,
      liquidity_weight: 0.1818,
      is_official_report: false,
    },
  ]));

  const series = buildAumSeries(history);
  assert.equal(series.length, 1);
  assert.equal(series[0].run_id, "20260616-060000");
});

test("filterHistoryByDays keeps official records inside the selected day window", () => {
  const history = sortHistory([
    { run_id: "latest", timestamp: "2026-06-15T18:00:00+08:00" },
    { run_id: "day-29", timestamp: "2026-05-17T18:00:00+08:00" },
    { run_id: "day-31", timestamp: "2026-05-15T18:00:00+08:00" },
  ]);

  const series = filterHistoryByDays(history, 30);

  assert.deepEqual(series.map((row) => row.run_id), ["latest", "day-29"]);
});

test("filterHistoryByDays returns all records when the range is all", () => {
  const history = sortHistory([
    { run_id: "latest", timestamp: "2026-06-15T18:00:00+08:00" },
    { run_id: "old", timestamp: "2025-12-01T18:00:00+08:00" },
  ]);

  assert.equal(filterHistoryByDays(history, "all").length, 2);
});
