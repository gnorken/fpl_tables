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

// ─────────────── 3) Sort‐arrow indicator ─────────────────
window.updateSortIndicator = (sortBy, sortOrder, containerSelector = null) => {
  // pick the root: either your container or the full document
  const root = containerSelector
    ? document.querySelector(containerSelector)
    : document;

  if (!root) return;

  // still only those “rounded” tables get the fancy sorted‐corner class
  const roundedTables = [
    "defence-table",
    "offence-table",
    "points-table",
    "per-90-table",
    "teams-table",
  ];

  // scope all our work to inside the root
  root.querySelectorAll("th[data-sort]").forEach((th) => {
    const table = th.closest("table");
    const isCurrent = th.dataset.sort === sortBy;

    // only toggle `sorted` if this <th> lives in one of the roundedTables
    if (table && roundedTables.includes(table.id)) {
      th.classList.toggle("sorted", isCurrent);
    } else {
      // ensure it's removed on non‑rounded tables
      th.classList.remove("sorted");
    }

    // toggle asc/desc everywhere
    th.classList.toggle("asc", isCurrent && sortOrder === "asc");
    th.classList.toggle("desc", isCurrent && sortOrder === "desc");

    // arrow logic, also scoped
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
  if (!th) return;

  // ── NEW GUARD: skip manager page tables ──
  if (
    th.closest("#current-season-table-container") ||
    th.closest("#previous-seasons-table-container")
  ) {
    return; // let the manager’s own header‑click logic handle these
  }

  // ── existing guard ──
  if (!window.tableConfig?.url) return;

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

// Given a Chart.js instance and two button IDs, wire up a linear/log toggle.
function addScaleToggle(chart, linearBtnId, logBtnId) {
  const linearBtn = document.getElementById(linearBtnId);
  const logBtn = document.getElementById(logBtnId);
  if (!linearBtn || !logBtn) return;

  linearBtn.addEventListener("click", () => {
    // mutate the _config_ object, not just chart.options
    if (chart.config.options.scales?.y) {
      chart.config.options.scales.y.type = "linear";
      chart.update();
      linearBtn.classList.add("active");
      logBtn.classList.remove("active");
    }
  });

  logBtn.addEventListener("click", () => {
    if (chart.config.options.scales?.y) {
      chart.config.options.scales.y.type = "logarithmic";
      chart.update();
      logBtn.classList.add("active");
      linearBtn.classList.remove("active");
    }
  });
}

// Hover logic for all table/graph combos
function attachTableGraphHover(
  chartId,
  tableSelector,
  datasetLabelOrIndex = 0
) {
  const chart = Chart.getChart(chartId);
  if (!chart) return;

  // Determine which dataset to highlight
  const datasetIndex =
    typeof datasetLabelOrIndex === "string"
      ? chart.data.datasets.findIndex((ds) => ds.label === datasetLabelOrIndex)
      : datasetLabelOrIndex;
  if (datasetIndex < 0) return;

  const rows = document.querySelectorAll(`${tableSelector} table tbody tr`);

  // Table → Chart
  rows.forEach((row, i) => {
    row.addEventListener("mouseenter", (e) => {
      row.classList.add("table-active");
      const active = [{ datasetIndex, index: i }];
      chart.setActiveElements(active);
      chart.tooltip.setActiveElements(active, { x: e.offsetX, y: e.offsetY });
      chart.update();
    });
    row.addEventListener("mouseleave", () => {
      row.classList.remove("table-active");
      chart.setActiveElements([]);
      chart.tooltip.setActiveElements([], { x: 0, y: 0 });
      chart.update();
    });
  });

  // Chart → Table
  chart.options.onHover = (event, elements) => {
    rows.forEach((r) => r.classList.remove("table-active"));
    if (elements.length) {
      const idx = elements[0].index;
      if (rows[idx]) rows[idx].classList.add("table-active");
      event.native.target.style.cursor = "pointer";
    } else {
      event.native.target.style.cursor = "default";
    }
  };
}

//─────────── Build the graph and table for manager.html ────────────────
function buildSortableTable(data, columns, dataKey) {
  if (!data || data.length === 0) return "<p>No data</p>";

  let html = `<table class="table table-striped table-sm text-center">
    <thead><tr>`;

  // headers
  columns.forEach((col) => {
    // use the key for sorting
    html += `<th data-sort="${col.key}">${col.label}</th>`;
  });

  html += `</tr></thead><tbody>`;

  // rows
  data.forEach((row) => {
    html += `<tr>`;
    columns.forEach((col) => {
      // get raw value and optionally format it
      const raw = row[col.key];
      const disp = col.formatter ? col.formatter(raw) : raw;
      html += `<td>${disp != null ? disp : ""}</td>`;
    });
    html += `</tr>`;
  });

  html += `</tbody></table>`;
  return html;
}

// YOLO
async function loadTableAndChart(cfg) {
  console.log(
    "▶️ loadTableAndChart()",
    cfg.tableContainerId,
    cfg.chartId,
    cfg.ajaxRoute
  );

  // 1) fetch or clone + sort into `data`
  let data;
  if (cfg.initialData) {
    data = Array.isArray(cfg.initialData)
      ? [...cfg.initialData]
      : cfg.initialData;
    const dir = cfg.sortOrder === "asc" ? 1 : -1;
    data.sort((a, b) => {
      const A = a[cfg.sortBy],
        B = b[cfg.sortBy];
      if (A == null && B != null) return 1;
      if (B == null && A != null) return -1;
      if (typeof A === "number" && typeof B === "number") return dir * (A - B);
      return dir * String(A).localeCompare(String(B));
    });
    console.log("ℹ️ using initialData for", cfg.chartId, data);
  } else {
    const url = new URL(cfg.ajaxRoute, location);
    url.searchParams.set("sort_by", cfg.sortBy);
    url.searchParams.set("order", cfg.sortOrder);
    data = await fetch(url).then((r) => r.json());
    console.log("📦 fetched data for", cfg.chartId, data);
  }

  // 2) render one unified table
  const container = document.getElementById(cfg.tableContainerId);
  container.innerHTML = buildSortableTable(data, cfg.columns, cfg.dataKey);

  // 2.1) update ▲/▼ arrows just within this table
  updateSortIndicator(cfg.sortBy, cfg.sortOrder, `#${cfg.tableContainerId}`);

  // 2.2) re‑bind header clicks for sorting
  document
    .querySelectorAll(`#${cfg.tableContainerId} table th[data-sort]`)
    .forEach((th) => {
      th.onclick = () => {
        const col = th.dataset.sort;
        cfg.sortOrder =
          cfg.sortBy === col && cfg.sortOrder === "desc" ? "asc" : "desc";
        cfg.sortBy = col;
        loadTableAndChart(cfg);
      };
    });

  console.log(
    "📝 table injected into",
    cfg.tableContainerId,
    document.querySelectorAll(`#${cfg.tableContainerId} table tbody tr`).length,
    "rows"
  );

  // 3) destroy old chart (if any) and rebuild
  const old = Chart.getChart(cfg.chartId);
  if (old) {
    old.destroy();
    console.log("🗑 destroyed existing chart:", cfg.chartId);
  }

  const ctx = document.getElementById(cfg.chartId).getContext("2d");
  const chart = new Chart(ctx, {
    data: {
      labels: data.map((r) => r[cfg.dataKey]),
      datasets: cfg.buildDatasets(data),
    },
    options: Object.assign({ scales: cfg.scales }, cfg.options || {}),
  });
  console.log("✅ chart created:", chart.id);

  // 4) wire up toggle + hover
  addScaleToggle(chart, ...cfg.toggleBtns);
  attachTableGraphHover(cfg.chartId, `#${cfg.tableContainerId}`, cfg.hoverDs);
}

// helper to destroy old + build new chart
function buildOrUpdateChart(data, cfg) {
  const old = Chart.getChart(cfg.chartId);
  if (old) old.destroy();

  const ctx = document.getElementById(cfg.chartId).getContext("2d");
  const chart = new Chart(ctx, {
    data: {
      labels: data.map((r) => r[cfg.dataKey]),
      datasets: cfg.buildDatasets(data),
    },
    options: Object.assign({ scales: cfg.scales }, cfg.options || {}),
  });

  addScaleToggle(chart, ...cfg.toggleBtns);
  attachTableGraphHover(
    cfg.chartId,
    cfg.split
      ? `#${cfg.split.containers[0]}` // hover against first half
      : `#${cfg.tableContainerId}`,
    cfg.hoverDs
  );
}

function initManagerPage(configs) {
  Object.values(configs).forEach((cfg) => loadTableAndChart(cfg));
}
