import test from "node:test";
import assert from "node:assert/strict";

import worker from "../cloudflare-worker/src/index.js";

function makePayload() {
  return {
    status: "Success",
    generated_at: "2026-07-28T20:06:00+08:00",
    history: [
      {
        run_id: "20260728-200523",
        timestamp: "2026-07-28T20:05:23+08:00",
        session: "晚盘正式结算",
        record_type: "official",
        is_official_report: true,
        total_value: 127505.17,
        daily_profit: -4238.16,
      },
      {
        run_id: "20260728-120034",
        timestamp: "2026-07-28T12:00:34+08:00",
        session: "午间资产快照",
        record_type: "ad_hoc",
        is_official_report: false,
        total_value: 131083.72,
        daily_profit: -512.57,
      },
    ],
    assets: [
      {
        run_id: "20260728-200523",
        asset_name: "VOO",
        currency: "USD",
        local_value: 1000,
        cny_value: 7200,
      },
      {
        run_id: "20260728-200523",
        asset_name: "支付宝余额备用金",
        currency: "CNY",
        local_value: 12580.91,
        cny_value: 12580.91,
      },
    ],
  };
}

async function fetchDashboard(payload, url) {
  const originalFetch = globalThis.fetch;
  const originalCaches = globalThis.caches;

  globalThis.fetch = async () => Response.json(payload);
  globalThis.caches = {
    default: {
      match: async () => null,
      put: async () => undefined,
    },
  };

  try {
    const response = await worker.fetch(
      new Request(url),
      { GOOGLE_SHEET_WEBAPP_URL: "https://script.google.test/exec" },
      { waitUntil: () => undefined },
    );
    return response.json();
  } finally {
    globalThis.fetch = originalFetch;
    globalThis.caches = originalCaches;
  }
}

test("official dashboard keeps current asset rows when latest official run has sheet snapshots", async () => {
  const data = await fetchDashboard(
    makePayload(),
    "https://quantbot-dashboard-api.test/dashboard?view=official&limit=20&refresh=1",
  );

  assert.equal(data.status, "Success");
  assert.equal(data.view, "official");
  assert.equal(data.latest_run_id, "20260728-200523");
  assert.equal(data.assets.length, 2);
  assert.deepEqual(data.assets.map((asset) => asset.asset_name), [
    "支付宝余额备用金",
    "VOO",
  ]);
});

test("official dashboard excludes stale official rows outside the evening settlement window", async () => {
  const payload = makePayload();
  payload.history.unshift({
    run_id: "20260729-001708",
    timestamp: "2026-07-29T00:17:08+08:00",
    session: "晚盘正式结算",
    record_type: "official",
    is_official_report: true,
    total_value: 126989.9,
    daily_profit: -3942.39,
  });

  const data = await fetchDashboard(
    payload,
    "https://quantbot-dashboard-api.test/dashboard?view=official&limit=20&refresh=1",
  );

  assert.equal(data.latest_run_id, "20260728-200523");
  assert.equal(data.history.some((row) => row.run_id === "20260729-001708"), false);
});
