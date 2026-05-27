function doPost(e) {
  const payload = JSON.parse(e.postData.contents);
  const ss = SpreadsheetApp.openById("1Dfrxjr5spKcaxAsxOoh9R_p5hzn8y5I-d86AdEgH9GE");

  appendDynamicRow_(ss, "History", {
    run_id: payload.run_id,
    timestamp: payload.timestamp,
    date: payload.date,
    schedule_slot: payload.schedule_slot,
    schedule_cron: payload.schedule_cron,
    github_event_name: payload.github_event_name,
    session: payload.session,
    record_type: payload.record_type,
    is_official_report: payload.is_official_report,
    total_value: payload.total_value,
    daily_profit: payload.daily_profit,
    daily_change_pct: payload.daily_change_pct,
    beta_core_value: payload.beta_core_value,
    beta_core_profit: payload.beta_core_profit,
    beta_core_weight: payload.beta_core_weight,
    beta_core_diff: payload.beta_core_diff,
    beta_core_status: payload.beta_core_status,
    alpha_satellite_value: payload.alpha_satellite_value,
    alpha_satellite_profit: payload.alpha_satellite_profit,
    alpha_satellite_weight: payload.alpha_satellite_weight,
    alpha_satellite_diff: payload.alpha_satellite_diff,
    alpha_satellite_status: payload.alpha_satellite_status,
    defense_value: payload.defense_value,
    defense_profit: payload.defense_profit,
    defense_weight: payload.defense_weight,
    defense_diff: payload.defense_diff,
    defense_status: payload.defense_status,
    liquidity_value: payload.liquidity_value,
    liquidity_profit: payload.liquidity_profit,
    liquidity_weight: payload.liquidity_weight,
    liquidity_diff: payload.liquidity_diff,
    liquidity_status: payload.liquidity_status,
    bucket_snapshot_json: payload.bucket_snapshot_json,
    asset_snapshots_json: payload.asset_snapshots_json,
    striking_alerts_json: payload.striking_alerts_json,
  });

  const assets = payload.asset_snapshots || [];
  assets.forEach((asset) => {
    appendDynamicRow_(ss, "AssetSnapshots", {
      run_id: payload.run_id,
      timestamp: payload.timestamp,
      date: payload.date,
      session: payload.session,
      record_type: payload.record_type,
      is_official_report: payload.is_official_report,
      asset_id: asset.asset_id,
      asset_name: asset.asset_name,
      bucket: asset.bucket,
      bucket_label: asset.bucket_label,
      source: asset.source,
      currency: asset.currency,
      quantity: asset.quantity,
      local_value: asset.local_value,
      cny_value: asset.cny_value,
      daily_profit: asset.daily_profit,
      daily_change_pct: asset.daily_change_pct,
    });
  });

  return ContentService
    .createTextOutput(JSON.stringify({
      status: "Success",
      history_rows_added: 1,
      asset_rows_added: assets.length,
      run_id: payload.run_id,
    }))
    .setMimeType(ContentService.MimeType.JSON);
}

function doGet(e) {
  const ss = SpreadsheetApp.openById("1Dfrxjr5spKcaxAsxOoh9R_p5hzn8y5I-d86AdEgH9GE");
  const limit = Number(e.parameter.limit || 120);
  const view = e.parameter.view || "official";
  const allHistory = readSheetObjects_(ss, "History");
  const filteredHistory = view === "all" ? allHistory : allHistory.filter(isOfficialHistoryRow_);
  const history = filteredHistory.sort(compareHistoryDesc_).slice(0, limit);
  const latestRunId = history.length ? history[0].run_id : "";
  const assets = readSheetObjects_(ss, "AssetSnapshots").filter((row) => row.run_id === latestRunId);
  const payload = {
    status: "Success",
    generated_at: new Date().toISOString(),
    view,
    total_history_rows: allHistory.length,
    visible_history_rows: history.length,
    latest_run_id: latestRunId,
    history,
    assets,
  };
  const json = JSON.stringify(payload);
  const callback = e.parameter.callback;

  if (callback) {
    return ContentService
      .createTextOutput(`${callback}(${json});`)
      .setMimeType(ContentService.MimeType.JAVASCRIPT);
  }

  return ContentService
    .createTextOutput(json)
    .setMimeType(ContentService.MimeType.JSON);
}

function isOfficialHistoryRow_(row) {
  if (row.is_official_report === true || row.is_official_report === "TRUE" || row.is_official_report === "true") {
    return true;
  }
  if (String(row.record_type || "").toLowerCase() === "official") {
    return true;
  }
  if (row.is_official_report !== "" && row.is_official_report !== undefined && row.is_official_report !== null) {
    return false;
  }
  return row.session === "早盘市场汇报" || row.session === "晚盘市场汇报";
}

function compareHistoryDesc_(a, b) {
  return historyScore_(b) - historyScore_(a);
}

function historyScore_(row) {
  const timestamp = row.timestamp || row.date || row.Date || "";
  const time = new Date(timestamp).getTime();
  if (!Number.isNaN(time)) {
    return time;
  }
  const runId = String(row.run_id || "").replace(/\D/g, "");
  const numericRunId = Number(runId);
  return Number.isFinite(numericRunId) ? numericRunId : 0;
}

function appendDynamicRow_(ss, sheetName, rowObject) {
  const sheet = ss.getSheetByName(sheetName) || ss.insertSheet(sheetName);
  const keys = Object.keys(rowObject);
  const lastColumn = Math.max(sheet.getLastColumn(), 1);
  let headers = sheet.getRange(1, 1, 1, lastColumn).getValues()[0].filter(String);

  if (headers.length === 0) {
    headers = keys;
    sheet.getRange(1, 1, 1, headers.length).setValues([headers]);
  } else {
    const missingHeaders = keys.filter((key) => !headers.includes(key));
    if (missingHeaders.length > 0) {
      headers = headers.concat(missingHeaders);
      sheet.getRange(1, 1, 1, headers.length).setValues([headers]);
    }
  }

  const row = headers.map((header) => rowObject[header] ?? "");
  sheet.appendRow(row);
}

function readSheetObjects_(ss, sheetName) {
  const sheet = ss.getSheetByName(sheetName);
  if (!sheet || sheet.getLastRow() < 2) {
    return [];
  }

  const values = sheet.getRange(1, 1, sheet.getLastRow(), sheet.getLastColumn()).getValues();
  const headers = values[0].map(String);
  return values.slice(1).filter((row) => row.some((cell) => cell !== "")).map((row) => {
    const object = {};
    headers.forEach((header, index) => {
      object[header] = row[index];
    });
    return object;
  });
}
