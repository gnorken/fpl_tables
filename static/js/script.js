window.initTooltips = () => {
  document.querySelectorAll('[data-bs-toggle="tooltip"]').forEach((el) => {
    // Avoid double-initialising the same tooltip
    if (!el.getAttribute("data-bs-original-title")) {
      new bootstrap.Tooltip(el);
    }
  });
};

// ─────────────── 1) Header update ──────────────────
function updateHeader(mgr) {
  console.groupCollapsed("🔔 updateHeader called");
  console.trace();
  console.groupEnd();

  const flagEl = document.querySelector("#flag");
  if (flagEl)
    flagEl.innerHTML = `<span class="fi fi-${mgr.country_code}"></span>`;
  const nameEls = document.querySelectorAll("#header-team-name h1.mb-0");
  if (nameEls[0])
    nameEls[0].textContent = `${mgr.first_name} ${mgr.last_name}'s `;
  if (nameEls[1]) nameEls[1].textContent = mgr.team_name;
}

// ─────────────── 2) Filter helpers ─────────────────
window.getSelectedPositions = () =>
  Array.from(
    document.querySelectorAll('#checkboxForm input[type="checkbox"]:checked')
  )
    .map((cb) => cb.value)
    .join(",");

window.getSelectedPriceRange = () => {
  const slider = document.getElementById("price-slider");
  if (!slider || !slider.noUiSlider) return { minCost: 3, maxCost: 15 };
  const [min, max] = slider.noUiSlider
    .get()
    .map((v) => parseFloat(v.replace("£", "")));
  return { minCost: min, maxCost: max };
};

// ─────────────── 3) Sort‐arrow indicator ────────────
// ─────────────── 3) Sort‐arrow indicator ─────────────────
window.updateSortIndicator = (sortBy, sortOrder) => {
  // only these table‐IDs get the rounded‐corner “sorted” class
  const roundedTables = [
    "defence-table",
    "offence-table",
    "points-table",
    "per-90-table",
    "teams-table",
  ];

  document.querySelectorAll("th[data-sort]").forEach((th) => {
    const table = th.closest("table");
    const isCurrent = th.dataset.sort === sortBy;

    // only toggle `sorted` if this <th> lives in one of the roundedTables
    if (table && roundedTables.includes(table.id)) {
      th.classList.toggle("sorted", isCurrent);
    } else {
      // ensure it's removed on non‑rounded tables
      th.classList.remove("sorted");
    }

    // still toggle asc/desc everywhere
    th.classList.toggle("asc", isCurrent && sortOrder === "asc");
    th.classList.toggle("desc", isCurrent && sortOrder === "desc");

    // arrow logic stays global
    const old = th.querySelector(".sort-arrow");
    if (old) old.remove();
    if (isCurrent) {
      const arrow = document.createElement("span");
      arrow.className = "sort-arrow";
      arrow.textContent = sortOrder === "asc" ? "▲" : "▼";
      th.appendChild(arrow);
    }
  });
};

// ─────────────── 4) Top-players text ─────────────────
window.updateTopPlayersText = (entryCount) => {
  let text;
  if (entryCount === 0) text = "Nothing to display";
  else if (entryCount === 1) text = "↑ Only one";
  else if (entryCount < 5) {
    const words = { 2: "Two", 3: "Three", 4: "Four" }[entryCount];
    text = `↑ Top ${words}`;
  } else text = "↑ Top Five";
  const el = document.getElementById("top-players");
  if (el) el.textContent = text;
};

// ─────────────── 5) Image & badge updaters ───────────
window.updatePlayerImages = (data) => {
  const container = document.getElementById("player-images");
  container.innerHTML = "";
  (data.players_images || []).forEach((pi, idx) => {
    const div = document.createElement("div"),
      img = document.createElement("img");
    div.className = `player-image-${idx + 1}`;
    img.classList.add("img-fluid", "overlap-img");
    img.loading = "lazy";
    img.alt = "Player Photo";
    img.src = `https://resources.premierleague.com/premierleague/photos/players/110x140/${pi.photo}`;
    img.onerror = () => {
      img.onerror = null;
      img.src =
        "https://resources.premierleague.com/premierleague/photos/players/110x140/Photo-Missing.png";
    };
    div.appendChild(img);
    container.appendChild(div);
  });
};

window.updateBadges = (data) => {
  const container = document.getElementById("player-images");
  container.innerHTML = "";
  (data.players_images || []).forEach((pi, idx) => {
    const div = document.createElement("div"),
      img = document.createElement("img");
    div.className = `badge-image-${idx + 1}`;
    img.classList.add("img-fluid", "overlap-badge");
    img.loading = "lazy";
    img.alt = "Club Badge";
    img.src = `https://resources.premierleague.com/premierleague/badges/100/t${pi.team_code}@x2.png`;
    img.onerror = () => {
      img.onerror = null;
      img.src =
        "https://resources.premierleague.com/premierleague/photos/players/110x140/Photo-Missing.png";
    };
    div.appendChild(img);
    container.appendChild(div);
  });
};

// ─────────────── 6) Mini-league branch ───────────────
async function fetchMiniLeague(sortBy, sortOrder) {
  const cfg = window.tableConfig;
  if (!cfg || cfg.table !== "mini_league") return false;

  const tbody = document.querySelector(cfg.tbodySelector);
  const loading = document.querySelector(cfg.loadingSelector);
  if (!tbody) return false;

  // 1) Show spinner, hide table
  if (loading) loading.style.display = "block";
  tbody.style.display = "none";

  // 2) Fire the request
  const url = `${cfg.url}&sort_by=${sortBy}&order=${sortOrder}&max_show=${cfg.maxShow}`;
  console.log("📡 fetchMiniLeague →", url);
  let res, data;
  try {
    res = await fetch(url);
    data = await res.json();
  } catch (e) {
    console.error("⚠️ mini-league fetch failed", e);
    if (loading) loading.style.display = "none";
    return true; // bail out to prevent the generic fetch from running
  }

  // 3) Grab the players array (and manager, if you care)
  const players = data.players || [];
  console.log("🎉 mini-league players:", players);

  // 4) Build a quick map of max/min for each stat (for highlighting)
  const maxVals = {},
    minVals = {};
  cfg.statsKeys.forEach((key) => {
    const vals = players.map((p) => p[key] || 0);
    maxVals[key] = Math.max(...vals);
    minVals[key] = Math.min(...vals);
  });

  // 5) “Top N + current” logic
  let toRender = players;
  if (typeof cfg.maxShow === "number") {
    const topN = players.slice(0, cfg.maxShow);
    if (!topN.some((p) => p.team_id === cfg.currentEntry)) {
      const me = players.find((p) => p.team_id === cfg.currentEntry);
      if (me) topN.push(me);
    }
    toRender = topN;
  }

  // 6) Render rows
  tbody.innerHTML = "";
  toRender.forEach((team) => {
    const tr = document.createElement("tr");
    tr.classList.add("text-center", "align-middle");
    if (team.team_id === cfg.currentEntry) {
      tr.classList.add("highlight-current");
    }

    cfg.columns.forEach((col) => {
      let cellHtml;
      if (col.render) {
        cellHtml = col.render(team);
      } else {
        const raw = team[col.key] ?? 0;
        const disp = col.formatter ? col.formatter(raw) : raw;
        const classes = [col.className || ""].filter(Boolean);
        // mark best/ worst if desired
        const best = cfg.invertKeys.includes(col.key)
          ? raw === minVals[col.key]
          : raw === maxVals[col.key];
        if (best) classes.push("highlight");

        cellHtml = `<td class="${classes.join(" ").trim()}">${disp}</td>`;
      }
      tr.insertAdjacentHTML("beforeend", cellHtml);
    });

    tbody.appendChild(tr);
  });

  updateSortIndicator(cfg.sortBy, cfg.sortOrder);
  // 7) Hide spinner, show table
  if (loading) loading.style.display = "none";
  tbody.style.display = "";

  return true;
}

// ─────────────── 7) Generic data fetch ─────────────
async function fetchData(sortBy, sortOrder) {
  if (await fetchMiniLeague(sortBy, sortOrder)) return;

  // 1) update sort‐info bar
  const sortEl = document.getElementById("current-sort");
  const orderEl = document.getElementById("current-order");
  if (sortEl)
    sortEl.textContent = window.tableConfig.lookup?.[sortBy] || sortBy;
  if (orderEl) orderEl.textContent = sortOrder === "desc" ? "" : "(ascending)";

  const cfg = window.tableConfig;
  const tbody = document.querySelector(cfg.tbodySelector);
  const loading = document.querySelector(cfg.loadingSelector);

  // 2) Always include sort & order
  const params = {
    sort_by: sortBy,
    order: sortOrder,
  };

  // 3) Only add filters if we're NOT on the Assistant Managers page. Could use this for other pages without slider.
  if (cfg.table !== "am") {
    const { minCost, maxCost } = getSelectedPriceRange();
    const selectedPositions = getSelectedPositions();

    if (selectedPositions && selectedPositions.length > 0) {
      params.selected_positions = selectedPositions;
    }

    params.min_cost = minCost;
    params.max_cost = maxCost;
  }

  // 4) Build the query string and fetch
  const qs = new URLSearchParams(params);
  const resp = await fetch(`${cfg.url}&${qs}`);

  const { players, players_images, manager } = await resp.json();

  console.log("AJAX manager:", manager);
  console.log("currentManagerId:", window.currentManagerId);
  // only redraw header if manager really changed
  // if (manager && manager.id !== window.currentManagerId) {
  //   updateHeader(manager);
  //   window.currentManagerId = manager.id;
  // }

  document.getElementById("entries").textContent =
    players.length === 1 ? "1 entry" : `${players.length} entries`;
  updateTopPlayersText(players.length);

  // 5) clear out old rows
  tbody.innerHTML = "";

  // 6) for each player, build a <tr>…
  players.forEach((p, idx) => {
    const tr = document.createElement("tr");
    tr.classList.add(
      "vert-border",
      "align-middle",
      `team-${p.team_code}`,
      `element-type-${p.element_type}`
    );

    cfg.columns.forEach((col) => {
      if (col.render) {
        // your custom renderer (rank + name, etc.)
        tr.insertAdjacentHTML("beforeend", col.render(p, idx));
      } else {
        let val = p[col.key] ?? "";
        if (col.formatter) val = col.formatter(val);

        // build the data-attributes
        // use either col.dataColumn (if you set one) or fall back to col.key
        const dataColName = col.dataColumn || col.key;
        const dataColumnAttr = ` data-column="${dataColName}"`;

        // emit sortLevel if defined
        const sortLevelAttr = col.sortLevel
          ? ` data-sort-level="${col.sortLevel}"`
          : "";

        // put it all together
        tr.insertAdjacentHTML(
          "beforeend",
          `<td class="${
            col.className || ""
          }"${dataColumnAttr}${sortLevelAttr}>${val}</td>`
        );
      }
    });

    tbody.appendChild(tr);

    // 🪛 Initialise tooltips on new rows
    window.initTooltips();
  });

  if (window.tableConfig.table === "teams") {
    updateBadges({ players_images });
  } else {
    updatePlayerImages({ players_images });
  }
  updateSortIndicator(sortBy, sortOrder);

  if (loading) loading.style.display = "none";
  tbody.style.display = "";
}
// expose globally
window.fetchData = fetchData;

// ─────────────── 8) DOMContentLoaded ─────────────────
document.addEventListener("DOMContentLoaded", () => {
  // 8.1) Pull sort/order from URL if present
  const params = new URLSearchParams(location.search);
  if (window.tableConfig) {
    if (params.has("sort_by")) tableConfig.sortBy = params.get("sort_by");
    if (params.has("order")) tableConfig.sortOrder = params.get("order");
  }

  // 8.1.1) Immediately reflect that in the headers
  // only run the *global* arrow logic for pages with tableConfig.url
  if (window.tableConfig && window.tableConfig.url) {
    updateSortIndicator(
      window.tableConfig.sortBy,
      window.tableConfig.sortOrder
    );
  }

  // 8.2) Header-hover descriptions
  const hoverEl = document.getElementById("current-hover");
  if (hoverEl) {
    const defaultText = hoverEl.textContent;
    document.querySelectorAll("th[data-sort]").forEach((th) => {
      const key = th.dataset.sort;
      const tip = window.tableConfig.lookup?.[key] || th.textContent.trim();
      th.addEventListener("mouseenter", () => (hoverEl.textContent = tip));
      th.addEventListener(
        "mouseleave",
        () => (hoverEl.textContent = defaultText)
      );
    });
  }

  // 8.3) Cell-hover highlighting
  document.querySelectorAll("table.interactive-table").forEach((table) => {
    table.addEventListener("mouseover", (e) => {
      //console.log("🐭 hover event on", e.target);
      const td = e.target.closest("td[data-column][data-sort-level]");
      if (!td) return;
      //console.log("→ matched a td:", td);
      const col = td.dataset.column;
      const sortLevel = td.dataset.sortLevel;
      const row = td.closest("tr");
      const primaryBg = sortLevel === "primary" ? "#e90052" : "#38003c";
      const matchBg = sortLevel === "primary" ? "#38003c" : "#e90052";

      // highlight hovered
      td.dataset.origBg = td.style.backgroundColor;
      td.dataset.origColor = td.style.color;
      td.style.backgroundColor = primaryBg;
      td.style.color = "#fff";
      td.style.borderRadius = "3px";

      // highlight partner(s)
      row.querySelectorAll(`td[data-column="${col}"]`).forEach((other) => {
        if (other === td) return;
        other.dataset.origBg = other.style.backgroundColor;
        other.dataset.origColor = other.style.color;
        other.style.backgroundColor = matchBg;
        other.style.color = "#fff";
        other.style.borderRadius = "3px";
      });
    });

    table.addEventListener("mouseout", (e) => {
      const td = e.target.closest("td[data-column]");
      if (!td) return;
      const col = td.dataset.column;
      const row = td.closest("tr");

      // restore hovered
      td.style.backgroundColor = td.dataset.origBg || "";
      td.style.color = td.dataset.origColor || "";
      td.style.borderRadius = "";

      // restore partner(s)
      row.querySelectorAll(`td[data-column="${col}"]`).forEach((other) => {
        other.style.backgroundColor = other.dataset.origBg || "";
        other.style.color = other.dataset.origColor || "";
        other.style.borderRadius = "";
      });
    });
  });

  // 8.4) Price-slider hookup
  const slider = document.getElementById("price-slider");
  if (slider && window.noUiSlider && !slider.noUiSlider) {
    noUiSlider.create(slider, {
      start: [3, 15],
      connect: true,
      range: { min: 3, max: 15 },
      step: 0.1,
      tooltips: true,
      format: wNumb({ decimals: 1, prefix: "£" }),
    });
    slider.noUiSlider.on("change", () =>
      window.fetchData(tableConfig.sortBy, tableConfig.sortOrder)
    );
  }

  // 8.5) Position-checkbox hookup
  document
    .querySelectorAll('#checkboxForm input[type="checkbox"]')
    .forEach((cb) =>
      cb.addEventListener("change", () =>
        window.fetchData(tableConfig.sortBy, tableConfig.sortOrder)
      )
    );

  // 8.6) Initial AJAX load
  if (window.tableConfig && window.tableConfig.url) {
    window.fetchData(tableConfig.sortBy, tableConfig.sortOrder);
  }

  // 🆕 Manager page initialiser
  // if (window.pageConfigs) {
  //   initManagerPage(window.pageConfigs);
  // }
});

// Tooltip for table headers (only for AJAX-driven tables with tableConfig)
if (window.tableConfig && window.tableConfig.lookup) {
  document.querySelectorAll("table thead th").forEach((th) => {
    const sortKey = th.getAttribute("data-sort");
    if (sortKey && window.tableConfig.lookup[sortKey]) {
      th.setAttribute("title", window.tableConfig.lookup[sortKey]);
      th.setAttribute("data-bs-toggle", "tooltip");
    }
  });
}

// ──────────── 9) popstate (back/forward) ─────────────
window.addEventListener("popstate", () => {
  const p = new URLSearchParams(location.search);
  const s = p.get("sort_by") || tableConfig.sortBy;
  const o = p.get("order") || tableConfig.sortOrder;
  tableConfig.sortBy = s;
  tableConfig.sortOrder = o;
  window.fetchData(s, o);
});

// ─────────── 10) Header‐click sorting ────────────────
// only fire on THEAD <th> elements
document.body.addEventListener("click", (e) => {
  const th = e.target.closest("thead th[data-sort]");
  if (!th || !window.tableConfig) return;

  const key = th.dataset.sort;
  const dir =
    window.tableConfig.sortBy === key && window.tableConfig.sortOrder === "desc"
      ? "asc"
      : "desc";

  window.tableConfig.sortBy = key;
  window.tableConfig.sortOrder = dir;

  // update URL
  const u = new URL(location);
  u.searchParams.set("sort_by", key);
  u.searchParams.set("order", dir);
  history.pushState(null, "", u);

  // re-fetch
  window.fetchData(key, dir);
});

//─────────── 11) Table and Graph ────────────────
function initManagerPage(configs) {
  Object.values(configs).forEach((config) => {
    loadTableAndChart(config);
  });
}

async function loadTableAndChart(config) {
  console.log(
    "🖐 container element:",
    document.getElementById(config.tableContainerId),
    document.getElementById(config.chartId)
  );

  // Fetch data from backend
  console.log("🔄 Loading", config.ajaxRoute);
  const res = await fetch(config.ajaxRoute);
  const data = await res.json();
  console.log("✅ Got data for", config.ajaxRoute, data);

  // Build table HTML
  const tableHtml = buildSortableTable(data, config.columns, config.dataKey);
  document.getElementById(config.tableContainerId).innerHTML = tableHtml;

  // Hover event listener for current season chart
  if (config.chartId === "currentSeasonChart") {
    const rows = document.querySelectorAll(
      `#${config.tableContainerId} table tbody tr`
    );

    rows.forEach((row, i) => {
      row.addEventListener("mouseenter", (e) => {
        // Find Current Season chart
        const chart = Chart.getChart("currentSeasonChart");
        if (!chart) return;

        // Find OR dataset index
        const orDatasetIndex = chart.data.datasets.findIndex(
          (ds) => ds.label === "Overall Rank"
        );
        if (orDatasetIndex === -1) return;

        // Activate the OR point only
        const active = [{ datasetIndex: orDatasetIndex, index: i }];
        chart.setActiveElements(active);
        chart.tooltip.setActiveElements(active, { x: e.offsetX, y: e.offsetY });
        chart.update();

        row.classList.add("table-active");
      });

      row.addEventListener("mouseleave", () => {
        const chart = Chart.getChart("currentSeasonChart");
        if (chart) {
          chart.setActiveElements([]);
          chart.tooltip.setActiveElements([], { x: 0, y: 0 });
          chart.update();
        }
        row.classList.remove("table-active");
      });
    });
  }

  // ✅ Special case: Current Season Chart (green/red bars)
  if (config.chartId === "currentSeasonChart") {
    const gwData = data.map((d) => d.gw);
    const orData = data.map((d) => d.or);
    const gwrData = data.map((d) => d.gwr);
    const gwpData = data.map((d) => d.gwp);

    buildCurrentSeasonChart(gwData, orData, gwrData, gwpData);
  } else {
    // Build Chart.js graph (generic charts)
    const ctx = document.getElementById(config.chartId);
    renderChart(ctx, data, config);
  }

  // Add table ↔ graph hover interactivity (kept for all)
  attachTableGraphHover(config.chartId, config.tableContainerId, data);
}

// Hover logic for table and graph
function attachTableGraphHover(chartId, tableId, data) {
  const chart = Chart.getChart(chartId);
  const rows = document.querySelectorAll(`#${tableId} tbody tr`);

  rows.forEach((row, index) => {
    row.addEventListener("mouseenter", () => {
      chart.setActiveElements([{ datasetIndex: 0, index }]);
      chart.update();
    });
    row.addEventListener("mouseleave", () => {
      chart.setActiveElements([]);
      chart.update();
    });
  });
}

// Build the graph and table for manager.html
function buildSortableTable(data, columns, dataKey) {
  if (!data || data.length === 0) return "<p>No data</p>";

  let html = `<table class="table table-striped table-sm text-center">
    <thead><tr>`;

  // headers
  columns.forEach((col) => {
    const sortKey = col.toLowerCase().replace(/[^a-z0-9]/g, "");
    html += `<th data-sort="${sortKey}">${col}</th>`;
  });

  html += `</tr></thead><tbody>`;

  // rows
  data.forEach((row) => {
    html += `<tr>`;
    columns.forEach((colLabel) => {
      // default mapping: lowercase & strip non-alphanumerics
      let key = colLabel.toLowerCase().replace(/[^a-z0-9]/g, "");
      // special case: "#" header maps to "#:" in your JSON
      if (colLabel === "#") key = "#:";
      else if (colLabel === "£") key = "£"; // squad value column
      const val = row[key];
      html += `<td>${val != null ? val : ""}</td>`;
    });
    html += `</tr>`;
  });

  html += `</tbody></table>`;
  return html;
}

// Render chart for manager.html
function renderChart(ctx, data, config) {
  if (!ctx || !data) return;

  const labels = data.map((row) => row[config.dataKey]);
  const values = data.map((row) => {
    // pick one numeric column to graph; adapt later
    return row.points || row.percentile || row.gwp || 0;
  });

  new Chart(ctx, {
    type: config.chartType,
    data: {
      labels: labels,
      datasets: [
        {
          label: "Data",
          data: values,
          borderColor: "purple",
          backgroundColor: "rgba(128,0,128,0.4)",
          fill: false,
        },
      ],
    },
    options: {
      responsive: true,
      plugins: { legend: { display: false } },
    },
  });
}
