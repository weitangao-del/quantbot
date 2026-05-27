const JSON_HEADERS = {
  "content-type": "application/json; charset=utf-8",
  "access-control-allow-origin": "*",
  "access-control-allow-methods": "GET, OPTIONS",
  "access-control-allow-headers": "content-type"
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
    upstream.searchParams.set("view", view);
    upstream.searchParams.set("limit", String(limit));

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

    const normalized = normalizeDashboardPayload(payload, view);
    const response = jsonResponse(normalized, 200, {
      "cache-control": "public, max-age=45"
    });
    if (!shouldRefresh) {
      ctx.waitUntil(cache.put(cacheKey, response.clone()));
    }
    return response;
  }
};

function normalizeDashboardPayload(payload, view) {
  const history = Array.isArray(payload.history)
    ? payload.history.map(normalizeRow).sort(compareHistoryDesc)
    : [];
  const assets = Array.isArray(payload.assets)
    ? payload.assets.map(normalizeRow).sort((a, b) => toNumber(b.cny_value, 0) - toNumber(a.cny_value, 0))
    : [];
  return {
    status: "Success",
    view: payload.view || view,
    total_history_rows: toNumber(payload.total_history_rows, history.length),
    visible_history_rows: toNumber(payload.visible_history_rows, history.length),
    latest_run_id: payload.latest_run_id || (history.length ? history[0].run_id : ""),
    generated_at: payload.generated_at || new Date().toISOString(),
    history,
    assets
  };
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
