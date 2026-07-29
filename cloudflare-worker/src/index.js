const JSON_HEADERS = {
  "content-type": "application/json; charset=utf-8",
  "access-control-allow-origin": "*",
  "access-control-allow-methods": "GET, OPTIONS",
  "access-control-allow-headers": "content-type"
};

const SCHEDULED_RUNS = {
  "0 16 * * *": {
    slot: "ad_hoc_0000",
    label: "Beijing 00:00"
  },
  "0 22 * * *": {
    slot: "ad_hoc_0600",
    label: "Beijing 06:00"
  },
  "0 4 * * *": {
    slot: "ad_hoc_1200",
    label: "Beijing 12:00"
  },
  "0 10 * * *": {
    slot: "official_1800",
    label: "Beijing 18:00"
  }
};

export default {
  async fetch(request, env, ctx) {
    if (request.method === "OPTIONS") {
      return new Response(null, { headers: JSON_HEADERS });
    }

    if (request.method !== "GET") {
      return jsonResponse({ status: "Error", message: "Method not allowed" }, 405);
    }

    const url = new URL(request.url);
    if (url.pathname !== "/" && url.pathname !== "/dashboard") {
      return jsonResponse({ status: "Error", message: "Not found" }, 404);
    }

    const sourceUrl = env.GOOGLE_SHEET_WEBAPP_URL;
    if (!sourceUrl) {
      return jsonResponse({ status: "Error", message: "Missing GOOGLE_SHEET_WEBAPP_URL" }, 500);
    }

    const view = safeView(url.searchParams.get("view") || env.DEFAULT_VIEW || "official");
    const limit = safeLimit(url.searchParams.get("limit") || env.DEFAULT_LIMIT || "120");
    const shouldRefresh = url.searchParams.has("refresh");
    const cacheKey = new Request(`${url.origin}${url.pathname}?view=${view}&limit=${limit}`);
    const cache = caches.default;
    const cached = shouldRefresh ? null : await cache.match(cacheKey);
    if (cached) {
      return cached;
    }

    const upstream = new URL(sourceUrl);
    upstream.searchParams.set("view", "all");
    upstream.searchParams.set("limit", String(Math.max(limit, 240)));

    const upstreamResponse = await fetch(upstream.toString(), {
      headers: { "accept": "application/json" },
      cf: { cacheTtl: 0, cacheEverything: false }
    });

    if (!upstreamResponse.ok) {
      return jsonResponse({
        status: "Error",
        message: "Google Sheet source returned an error",
        upstream_status: upstreamResponse.status
      }, 502);
    }

    const rawText = await upstreamResponse.text();
    let payload;
    try {
      payload = JSON.parse(rawText);
    } catch (error) {
      return jsonResponse({
        status: "Error",
        message: "Google Sheet source did not return JSON"
      }, 502);
    }

    const normalized = normalizeDashboardPayload(payload, view, limit);
    const response = jsonResponse(normalized, 200, {
      "cache-control": "public, max-age=45"
    });
    if (!shouldRefresh) {
      ctx.waitUntil(cache.put(cacheKey, response.clone()));
    }
    return response;
  },

  async scheduled(controller, env, ctx) {
    const scheduledRun = SCHEDULED_RUNS[controller.cron];
    if (!scheduledRun) {
      console.log(`No quantbot mapping for cron ${controller.cron}`);
      return;
    }

    ctx.waitUntil(triggerMonitorRun(scheduledRun, controller.cron, env));
  }
};

function normalizeDashboardPayload(payload, view, limit) {
  const allHistory = Array.isArray(payload.history)
    ? payload.history.map(normalizeRow).sort(compareHistoryDesc)
    : [];
  const filteredAllHistory = view === "official"
    ? allHistory.filter(isOfficialHistoryRow)
    : allHistory;
  const filteredHistory = filteredAllHistory.slice(0, limit);

  let assets = [];
  if (filteredHistory.length) {
    const latestRunId = filteredHistory[0].run_id;
    assets = parseEmbeddedAssets(filteredHistory[0]);
    if (assets.length === 0) {
      assets = sheetAssetsForRun(payload.assets, latestRunId, payload.latest_run_id);
    }
    assets = assets.sort((a, b) => toNumber(b.cny_value, 0) - toNumber(a.cny_value, 0));
  }
  return {
    status: "Success",
    view,
    total_history_rows: allHistory.length,
    visible_history_rows: filteredAllHistory.length,
    latest_run_id: filteredHistory.length ? filteredHistory[0].run_id : "",
    generated_at: payload.generated_at || new Date().toISOString(),
    history: filteredHistory,
    assets
  };
}

function sheetAssetsForRun(assets, runId, latestRunId) {
  if (!Array.isArray(assets) || !assets.length || !runId) {
    return [];
  }

  const normalizedAssets = assets.map(normalizeRow);
  const matchingAssets = normalizedAssets.filter((asset) => String(asset.run_id || "") === String(runId));
  if (matchingAssets.length) {
    return matchingAssets;
  }

  if (String(latestRunId || "") === String(runId)) {
    return normalizedAssets;
  }

  return [];
}

function parseEmbeddedAssets(row) {
  const raw = row.asset_snapshots_json;
  if (!raw) {
    return [];
  }
  if (Array.isArray(raw)) {
    return raw.map(normalizeRow);
  }
  try {
    const parsed = JSON.parse(String(raw));
    return Array.isArray(parsed) ? parsed.map(normalizeRow) : [];
  } catch (error) {
    return [];
  }
}

function compareHistoryDesc(a, b) {
  const aTime = historySortValue(a);
  const bTime = historySortValue(b);
  return bTime - aTime;
}

function historySortValue(row) {
  const timeValue = Date.parse(row.timestamp || row.date || row.Date || "");
  if (Number.isFinite(timeValue)) {
    return timeValue;
  }
  const runId = String(row.run_id || "");
  const numericRunId = Number(runId.replace(/[^0-9]/g, ""));
  if (Number.isFinite(numericRunId)) {
    return numericRunId;
  }
  return 0;
}

function normalizeRow(row) {
  const normalized = {};
  for (const [key, value] of Object.entries(row || {})) {
    normalized[key] = normalizeValue(value);
  }
  return normalized;
}

function normalizeValue(value) {
  if (value === "" || value === undefined) {
    return null;
  }
  if (typeof value !== "string") {
    return value;
  }
  const trimmed = value.trim();
  if (trimmed === "") {
    return null;
  }
  if (trimmed === "TRUE" || trimmed === "true") {
    return true;
  }
  if (trimmed === "FALSE" || trimmed === "false") {
    return false;
  }
  const numeric = Number(trimmed);
  if (Number.isFinite(numeric) && trimmed !== "") {
    return numeric;
  }
  return value;
}

function safeView(value) {
  return value === "all" ? "all" : "official";
}

function isOfficialHistoryRow(row) {
  if (!isOfficialSettlementTime(row)) {
    return false;
  }
  if (row.is_official_report === true) {
    return true;
  }
  if (row.schedule_slot === "official_1800" || row.schedule_slot === "official_0900") {
    return true;
  }
  if (String(row.record_type || "").toLowerCase() === "official") {
    return true;
  }
  if (row.is_official_report !== null && row.is_official_report !== undefined) {
    return false;
  }
  if (row.session === "晚盘正式结算") {
    return true;
  }
  if (row.session === "早盘市场汇报") {
    return true;
  }
  const hour = historyHour(row);
  return hour === 18 || hour === 9;
}

function isOfficialSettlementTime(row) {
  const hour = timestampHour(row);
  if (hour === null) {
    return true;
  }
  return hour === 9 || (hour >= 18 && hour <= 22);
}

function safeLimit(value) {
  const limit = Number(value);
  if (!Number.isFinite(limit)) {
    return 120;
  }
  return Math.min(Math.max(Math.trunc(limit), 1), 500);
}

function toNumber(value, fallback) {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : fallback;
}

function jsonResponse(body, status = 200, headers = {}) {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      ...JSON_HEADERS,
      ...headers
    }
  });
}

function historyHour(row) {
  const parsed = Date.parse(row.timestamp || row.date || "");
  if (!Number.isFinite(parsed)) {
    return null;
  }
  return (new Date(parsed).getUTCHours() + 8) % 24;
}

function timestampHour(row) {
  const rawTimestamp = row.timestamp || row.Timestamp;
  if (!rawTimestamp) {
    return null;
  }
  const parsed = Date.parse(rawTimestamp);
  if (!Number.isFinite(parsed)) {
    return null;
  }
  return (new Date(parsed).getUTCHours() + 8) % 24;
}

async function triggerMonitorRun(run, cron, env) {
  const token = env.GITHUB_WORKFLOW_TOKEN;
  const owner = env.GITHUB_OWNER;
  const repo = env.GITHUB_REPO;
  const workflowFile = env.GITHUB_WORKFLOW_FILE || "main.yml";
  const ref = env.GITHUB_WORKFLOW_REF || "main";

  if (!token || !owner || !repo) {
    throw new Error("Missing GitHub workflow dispatch configuration in Cloudflare Worker");
  }

  const response = await fetch(
    `https://api.github.com/repos/${owner}/${repo}/actions/workflows/${workflowFile}/dispatches`,
    {
      method: "POST",
      headers: {
        "accept": "application/vnd.github+json",
        "authorization": `Bearer ${token}`,
        "content-type": "application/json",
        "user-agent": "quantbot-dashboard-api"
      },
      body: JSON.stringify({
        ref,
        inputs: {
          run_slot: run.slot,
          trigger_source: `cloudflare:${run.label}:${cron}`
        }
      })
    }
  );

  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`GitHub dispatch failed (${response.status}): ${errorText}`);
  }

  console.log(`Triggered ${repo} workflow for ${run.slot} via ${cron}`);
}
