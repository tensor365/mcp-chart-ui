"""Self-contained HTML template rendered inside the mcp-ui sandboxed iframe.

The template is intentionally framework-free: ECharts (chart) and SheetJS (xlsx
export) are pulled from a CDN, everything else is vanilla JS. Server-side code
injects four JSON payloads by replacing the ``__*__`` tokens — never use
``str.format``/f-strings here because the body is full of ``{`` from CSS/JS.

Interactivity implemented:
  * tab switching (Chart / Table)
  * legend toggle, zoom and rubber-band *brush* selection (ECharts built-ins)
  * selecting points/bars/slices highlights the matching rows in the table
  * "send selection to assistant" emits an mcp-ui `prompt` action via postMessage
  * CSV and Excel download of the table
"""

HTML_TEMPLATE = r"""<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<style>
  :root {
    --bg: #ffffff; --fg: #1f2933; --muted: #6b7280; --border: #e5e7eb;
    --accent: #2563eb; --accent-soft: #eff6ff; --hl: #fff7cd;
  }
  * { box-sizing: border-box; }
  body { margin: 0; font-family: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
         color: var(--fg); background: var(--bg); }
  .wrap { padding: 14px 16px 18px; }
  header h1 { font-size: 17px; margin: 0 0 2px; }
  header .why { font-size: 12.5px; color: var(--muted); margin: 0 0 12px; }
  .tabs { display: flex; gap: 4px; border-bottom: 1px solid var(--border); margin-bottom: 12px; }
  .tab { appearance: none; border: none; background: none; cursor: pointer; font-size: 14px;
         padding: 9px 14px; color: var(--muted); border-bottom: 2px solid transparent; }
  .tab[aria-selected="true"] { color: var(--accent); border-bottom-color: var(--accent); font-weight: 600; }
  .panel { display: none; }
  .panel.active { display: block; }
  #chart { width: 100%; height: 440px; }
  .table-toolbar { display: flex; align-items: center; justify-content: space-between;
                   gap: 8px; margin-bottom: 8px; flex-wrap: wrap; }
  .table-toolbar .info { font-size: 12.5px; color: var(--muted); }
  .actions { display: flex; gap: 6px; }
  .iconbtn { display: inline-flex; align-items: center; gap: 6px; cursor: pointer;
             border: 1px solid var(--border); background: #fff; color: var(--fg);
             border-radius: 7px; padding: 6px 10px; font-size: 12.5px; }
  .iconbtn:hover { background: var(--accent-soft); border-color: var(--accent); }
  .iconbtn svg { width: 15px; height: 15px; }
  .table-scroll { max-height: 440px; overflow: auto; border: 1px solid var(--border); border-radius: 8px; }
  table { border-collapse: collapse; width: 100%; font-size: 13px; }
  thead th { position: sticky; top: 0; background: #f9fafb; text-align: left;
             padding: 8px 10px; border-bottom: 1px solid var(--border); white-space: nowrap; }
  tbody td { padding: 7px 10px; border-bottom: 1px solid #f1f3f5; white-space: nowrap; }
  tbody tr.hl { background: var(--hl); }
  tbody tr:hover { background: #f8fafc; }
  .selbar { display: none; align-items: center; gap: 10px; margin: 10px 0 0;
            padding: 8px 12px; background: var(--accent-soft); border-radius: 8px; font-size: 13px; }
  .selbar.show { display: flex; }
  .selbar button { margin-left: auto; }
  .empty { color: var(--muted); font-size: 13px; padding: 12px; }
  .warn { display: none; margin: 0 0 12px; padding: 8px 12px; font-size: 12.5px;
          background: #fff8e1; border: 1px solid #f6d97a; border-radius: 8px; color: #7a5b00; }
  .warn.show { display: block; }
  .warn ul { margin: 4px 0 0; padding-left: 18px; }
</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1 id="title"></h1>
    <p class="why" id="why"></p>
  </header>

  <div class="warn" id="warn" role="status"></div>

  <div class="tabs" role="tablist">
    <button class="tab" id="tab-chart" role="tab" aria-selected="true" aria-controls="panel-chart">📊 Graphique</button>
    <button class="tab" id="tab-table" role="tab" aria-selected="false" aria-controls="panel-table">▦ Données</button>
  </div>

  <section class="panel active" id="panel-chart" role="tabpanel">
    <div id="chart"></div>
    <div class="selbar" id="selbar">
      <span id="selcount"></span>
      <button class="iconbtn" id="send-sel" type="button">Envoyer la sélection à l'assistant</button>
      <button class="iconbtn" id="clear-sel" type="button">Effacer</button>
    </div>
  </section>

  <section class="panel" id="panel-table" role="tabpanel">
    <div class="table-toolbar">
      <span class="info" id="tableinfo"></span>
      <div class="actions">
        <button class="iconbtn" id="dl-csv" type="button" title="Télécharger en CSV">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
               stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
          CSV
        </button>
        <button class="iconbtn" id="dl-xlsx" type="button" title="Télécharger en Excel">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
               stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2"/><path d="M9 9l6 6M15 9l-6 6"/></svg>
          Excel
        </button>
      </div>
    </div>
    <div class="table-scroll" id="tablehost"></div>
  </section>
</div>

__ECHARTS_TAG__
__XLSX_TAG__
<script>
(function () {
  "use strict";

  // ---- Injected payloads -------------------------------------------------
  var TITLE       = __TITLE_JSON__;
  var REASONING   = __REASONING_JSON__;
  var CHART_TYPE  = __CHART_TYPE_JSON__;
  var X_COL       = __XCOL_JSON__;
  var GROUP_COL   = __GROUPCOL_JSON__;
  var CATEGORIES  = __CATEGORIES_JSON__;
  var SERIES_NAMES = __SERIES_NAMES_JSON__;
  var OPTION      = __OPTION_JSON__;
  var COLUMNS     = __COLUMNS_JSON__;
  var ROWS        = __ROWS_JSON__;
  var MAP_SELECTION = __MAP_SELECTION_JSON__;
  var WARNINGS    = __WARNINGS_JSON__;

  document.getElementById("title").textContent = TITLE;
  document.getElementById("why").textContent = REASONING;
  document.getElementById("tableinfo").textContent = ROWS.length + " lignes × " + COLUMNS.length + " colonnes";

  if (WARNINGS && WARNINGS.length) {
    var warn = document.getElementById("warn");
    var items = WARNINGS.map(function (w) { return "<li>" + esc(w) + "</li>"; }).join("");
    warn.innerHTML = "<strong>Note</strong><ul>" + items + "</ul>";
    warn.classList.add("show");
  }

  // ---- Tabs --------------------------------------------------------------
  var chart = null;
  var selectedRows = new Set();

  function activate(which) {
    var isChart = which === "chart";
    document.getElementById("tab-chart").setAttribute("aria-selected", isChart);
    document.getElementById("tab-table").setAttribute("aria-selected", !isChart);
    document.getElementById("panel-chart").classList.toggle("active", isChart);
    document.getElementById("panel-table").classList.toggle("active", !isChart);
    if (isChart && chart) { chart.resize(); }
    // Panel heights differ; tell the host to refit after the switch paints.
    if (typeof reportSize === "function") { setTimeout(reportSize, 50); }
  }
  document.getElementById("tab-chart").addEventListener("click", function () { activate("chart"); });
  document.getElementById("tab-table").addEventListener("click", function () { activate("table"); });

  // ---- Chart -------------------------------------------------------------
  function initChart() {
    if (typeof echarts === "undefined") {
      document.getElementById("chart").innerHTML =
        '<p class="empty">Impossible de charger ECharts (réseau du sandbox bloqué ?).</p>';
      return;
    }
    chart = echarts.init(document.getElementById("chart"));
    chart.setOption(OPTION);
    wireSelection();
    window.addEventListener("resize", function () { chart.resize(); });
  }

  // Map chart selection -> table row indices.
  function rowsFromDataIndexes(idxs) {
    // For ungrouped bar/line/area/scatter the series data is one entry per row,
    // so the dataIndex equals the row index. Histograms bin rows, so we skip.
    if (CHART_TYPE === "histogram") { return []; }
    return idxs;
  }

  function rowsForCategory(name) {
    if (X_COL === null) { return []; }
    var col = COLUMNS.indexOf(X_COL);
    if (col < 0) { return []; }
    var out = [];
    for (var i = 0; i < ROWS.length; i++) {
      if (String(ROWS[i][col]) === String(name)) { out.push(i); }
    }
    return out;
  }

  // For grouped/stacked bars the data is pivoted, so a bar corresponds to a
  // (category, group) pair rather than a single row. Match on both columns.
  function rowsForCategoryGroup(catLabel, groupLabel) {
    var xi = COLUMNS.indexOf(X_COL), gi = COLUMNS.indexOf(GROUP_COL);
    if (xi < 0 || gi < 0) { return []; }
    var out = [];
    for (var i = 0; i < ROWS.length; i++) {
      if (String(ROWS[i][xi]) === String(catLabel) &&
          String(ROWS[i][gi]) === String(groupLabel)) { out.push(i); }
    }
    return out;
  }

  function wireSelection() {
    // When chart and table aren't 1:1 (histogram, top-N aggregation), the chart
    // stays interactive (zoom/brush) but selection can't map back to rows.
    if (!MAP_SELECTION) { return; }
    // Rubber-band brush selection on cartesian charts.
    chart.on("brushSelected", function (params) {
      var rows = [];
      (params.batch || []).forEach(function (b) {
        (b.selected || []).forEach(function (s) {
          var seriesName = SERIES_NAMES[s.seriesIndex];
          (s.dataIndex || []).forEach(function (di) {
            if (GROUP_COL !== null) {
              rows = rows.concat(rowsForCategoryGroup(CATEGORIES[di], seriesName));
            } else if (CHART_TYPE !== "histogram") {
              rows.push(di);
            }
          });
        });
      });
      setSelection(rows);
    });
    // Click on a pie slice / bar / point.
    chart.on("click", function (params) {
      if (CHART_TYPE === "pie") {
        setSelection(rowsForCategory(params.name));
      } else if (GROUP_COL !== null && typeof params.dataIndex === "number") {
        setSelection(rowsForCategoryGroup(CATEGORIES[params.dataIndex], params.seriesName));
      } else if (typeof params.dataIndex === "number") {
        setSelection(rowsFromDataIndexes([params.dataIndex]));
      }
    });
  }

  function setSelection(rowIdxs) {
    selectedRows = new Set(rowIdxs);
    var bar = document.getElementById("selbar");
    if (selectedRows.size > 0) {
      bar.classList.add("show");
      document.getElementById("selcount").textContent =
        selectedRows.size + " point(s) sélectionné(s)";
    } else {
      bar.classList.remove("show");
    }
    refreshRowHighlight();
  }

  document.getElementById("clear-sel").addEventListener("click", function () {
    if (chart) { chart.dispatchAction({ type: "brush", areas: [] }); }
    setSelection([]);
  });

  document.getElementById("send-sel").addEventListener("click", function () {
    var idxs = Array.from(selectedRows).sort(function (a, b) { return a - b; });
    var sample = idxs.slice(0, 50).map(function (i) {
      var obj = {}; COLUMNS.forEach(function (c, j) { obj[c] = ROWS[i][j]; }); return obj;
    });
    postAction("prompt", {
      prompt: "J'ai sélectionné " + idxs.length + " ligne(s) dans le graphique « " +
              TITLE + " ». Voici les données sélectionnées : " + JSON.stringify(sample)
    });
  });

  // ---- Table (progressive rendering to bound the DOM) --------------------
  var TABLE_CHUNK = 200;
  var renderedRows = 0;
  var tbodyEl = null;
  var sentinelEl = null;
  var tableObserver = null;

  function renderTable() {
    var host = document.getElementById("tablehost");
    if (ROWS.length === 0) { host.innerHTML = '<p class="empty">Aucune donnée.</p>'; return; }

    var head = "<table><thead><tr>";
    COLUMNS.forEach(function (c) { head += "<th>" + esc(c) + "</th>"; });
    head += "</tr></thead><tbody></tbody></table>";
    host.innerHTML = head;
    host.insertAdjacentHTML("beforeend", '<div id="table-sentinel" style="height:1px"></div>');
    tbodyEl = host.querySelector("tbody");
    sentinelEl = document.getElementById("table-sentinel");
    renderedRows = 0;
    renderMoreRows();

    // Append the next chunk whenever the sentinel scrolls into view.
    if (tableObserver) { tableObserver.disconnect(); }
    if ("IntersectionObserver" in window) {
      tableObserver = new IntersectionObserver(function (entries) {
        if (entries[0].isIntersecting) { renderMoreRows(); applyHighlight(); }
      }, { root: host });
      tableObserver.observe(sentinelEl);
    } else {
      while (renderedRows < ROWS.length) { renderMoreRows(); }
    }
  }

  function renderMoreRows() {
    var end = Math.min(renderedRows + TABLE_CHUNK, ROWS.length);
    var html = "";
    for (var i = renderedRows; i < end; i++) {
      html += '<tr data-row="' + i + '">';
      for (var j = 0; j < ROWS[i].length; j++) {
        html += "<td>" + esc(ROWS[i][j] === null ? "" : ROWS[i][j]) + "</td>";
      }
      html += "</tr>";
    }
    tbodyEl.insertAdjacentHTML("beforeend", html);
    renderedRows = end;
    if (renderedRows >= ROWS.length && tableObserver) {
      tableObserver.disconnect();
      if (sentinelEl) { sentinelEl.remove(); sentinelEl = null; }
    }
  }

  // Toggle the .hl class on currently-rendered rows.
  function applyHighlight() {
    var trs = document.querySelectorAll("#tablehost tbody tr");
    trs.forEach(function (tr) {
      var i = Number(tr.getAttribute("data-row"));
      tr.classList.toggle("hl", selectedRows.has(i));
    });
  }

  // Ensure selected rows are rendered (they may be past the current chunk),
  // then highlight.
  function refreshRowHighlight() {
    if (selectedRows.size) {
      var maxSel = Math.max.apply(null, Array.from(selectedRows));
      while (renderedRows <= maxSel && renderedRows < ROWS.length) { renderMoreRows(); }
    }
    applyHighlight();
  }

  function esc(v) {
    return String(v).replace(/[&<>"]/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c];
    });
  }

  // ---- Downloads ---------------------------------------------------------
  function safeName() {
    return (TITLE || "data").replace(/[^\w.-]+/g, "_").slice(0, 60) || "data";
  }

  function toCSV() {
    function cell(v) {
      var s = v === null ? "" : String(v);
      if (/[",\n]/.test(s)) { s = '"' + s.replace(/"/g, '""') + '"'; }
      return s;
    }
    var lines = [COLUMNS.map(cell).join(",")];
    ROWS.forEach(function (r) { lines.push(r.map(cell).join(",")); });
    return "\ufeff" + lines.join("\r\n"); // BOM so Excel reads UTF-8
  }

  function triggerBlobDownload(blob, filename) {
    try {
      var url = URL.createObjectURL(blob);
      var a = document.createElement("a");
      a.href = url; a.download = filename;
      document.body.appendChild(a); a.click(); a.remove();
      setTimeout(function () { URL.revokeObjectURL(url); }, 1500);
    } catch (e) {
      // Sandbox without allow-downloads: hand the file to the host instead.
      var reader = new FileReader();
      reader.onload = function () { postAction("link", { url: reader.result }); };
      reader.readAsDataURL(blob);
    }
  }

  document.getElementById("dl-csv").addEventListener("click", function () {
    triggerBlobDownload(new Blob([toCSV()], { type: "text/csv;charset=utf-8" }), safeName() + ".csv");
  });

  document.getElementById("dl-xlsx").addEventListener("click", function () {
    if (typeof XLSX === "undefined") {
      alert("Export Excel indisponible (SheetJS non chargé) — utilisez CSV.");
      return;
    }
    var aoa = [COLUMNS].concat(ROWS.map(function (r) {
      return r.map(function (v) { return v === null ? "" : v; });
    }));
    var ws = XLSX.utils.aoa_to_sheet(aoa);
    var wb = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(wb, ws, "Données");
    var out = XLSX.write(wb, { bookType: "xlsx", type: "array" });
    triggerBlobDownload(
      new Blob([out], { type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" }),
      safeName() + ".xlsx"
    );
  });

  // ---- mcp-ui action helper ---------------------------------------------
  function postAction(type, payload) {
    if (window.parent) {
      window.parent.postMessage({ type: type, payload: payload }, "*");
    }
  }

  // ---- Auto-fit height ---------------------------------------------------
  // Tell the host how tall the content is so it sizes the iframe (no scrollbar).
  // mcp-ui hosts honour `ui-size-change`; hosts that read the DOM height get it
  // for free since the body grows to its content (no fixed/100vh height).
  function reportSize() {
    var h = Math.ceil(document.documentElement.getBoundingClientRect().height);
    if (h > 0) { postAction("ui-size-change", { height: h }); }
  }

  if (typeof ResizeObserver !== "undefined") {
    var ro = new ResizeObserver(function () { reportSize(); });
    ro.observe(document.documentElement);
  } else {
    window.addEventListener("resize", reportSize);
  }

  // ---- Boot --------------------------------------------------------------
  renderTable();
  initChart();
  // Report after layout settles (and again shortly after, once the chart paints).
  requestAnimationFrame(reportSize);
  setTimeout(reportSize, 300);
})();
</script>
</body>
</html>
"""
