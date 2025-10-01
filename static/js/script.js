// ─────────────── 0) Tooltips (delegated, covers dynamic content) ───────────────
let __tooltipDelegator = null;

function enableDelegatedTooltips() {
  if (__tooltipDelegator) return; // idempotent

  __tooltipDelegator = new bootstrap.Tooltip(document.body, {
    selector: '[data-bs-toggle="tooltip"]',
    container: "body",
    boundary: "window",
    trigger: "hover",
    delay: { show: 0, hide: 0 },
    sanitize: false,
    customClass: (el) => el?.dataset?.bsCustomClass || "tooltip-lg",
  });
}

// Back-compat: callers can still call window.initTooltips(...) but it's a no-op now
window.initTooltips = () => enableDelegatedTooltips();

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

// Dynamic price slider
function updatePriceSliderRange(min, max, snap = true) {
  const el = document.getElementById("price-slider");
  if (!el?.noUiSlider) return;

  const [curMin, curMax] = el.noUiSlider
    .get()
    .map((v) => parseFloat(String(v).replace("£", "")));
  el.noUiSlider.updateOptions({ range: { min, max } }, false);

  if (snap) {
    el.noUiSlider.set([min, max]); // snap to edges
  } else {
    el.noUiSlider.set([
      Math.min(Math.max(curMin, min), max), // keep user choice, clamp
      Math.min(Math.max(curMax, min), max),
    ]);
  }
}

window.getSelectedMinutesRange = () => {
  const slider = document.getElementById("minutes-slider");
  if (!slider || !slider.noUiSlider) return { minMin: 0, maxMin: 3480 };
  const [min, max] = slider.noUiSlider
    .get()
    .map((v) => parseFloat(v.replace(" min", "")));
  return { minMin: min, maxMin: max };
};

// ─────────────── 2.5) Reset Filters ─────────────────
window.resetFilters = function () {
  // uncheck positions
  document
    .querySelectorAll('#checkboxForm input[type="checkbox"]')
    .forEach((cb) => (cb.checked = true));

  // reset minutes
  const minSlider = document.getElementById("minutes-slider");
  if (minSlider?.noUiSlider) {
    const maxMinutes = (window.tableConfig?.currentGw || 1) * 90;
    minSlider.noUiSlider.updateOptions(
      { range: { min: 0, max: maxMinutes } },
      false
    );
    minSlider.noUiSlider.set([0, maxMinutes]);
  }

  // reload table
  window.fetchData(tableConfig.sortBy, tableConfig.sortOrder);
};

// ─────────────── 3) Sort‐arrow indicator ─────────────────
window.updateSortIndicator = (sortBy, sortOrder, containerSelector = null) => {
  const root = containerSelector
    ? document.querySelector(containerSelector)
    : document;

  if (!root) return;

  const roundedTables = [
    "summary-table",
    "defence-table",
    "offence-table",
    "points-table",
    "teams-table",
    "talisman-table",
    "players-table",
  ];

  root.querySelectorAll("th[data-sort]").forEach((th) => {
    const table = th.closest("table");
    const isCurrent = th.dataset.sort === sortBy;

    if (table && roundedTables.includes(table.id)) {
      th.classList.toggle("sorted", isCurrent);
    } else {
      th.classList.remove("sorted");
    }

    th.classList.toggle("asc", isCurrent && sortOrder === "asc");
    th.classList.toggle("desc", isCurrent && sortOrder === "desc");

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
  if (!container) return;
  container.innerHTML = "";
  (data.players_images || []).forEach((pi, idx) => {
    const div = document.createElement("div"),
      img = document.createElement("img");
    div.className = `player-image-${idx + 1}`;
    img.classList.add("img-fluid", "overlap-img");
    img.loading = "lazy";
    img.alt = "Player Photo";

    // Remove 'p' prefix from photo
    const photoId = pi.photo.startsWith("p") ? pi.photo.slice(1) : pi.photo;

    // Base URL for 2025/26 season
    const baseUrl = `https://resources.premierleague.com/premierleague25/photos/players/110x140/${photoId}`;
    let retryCount = 0;
    const maxRetries = 1;

    // Set initial URL
    img.src = baseUrl;

    img.onerror = () => {
      if (retryCount < maxRetries) {
        // Retry with cache-busting
        retryCount++;
        img.src = `${baseUrl}?_=${Date.now()}`;
        console.log(
          `Retrying image load for ${photoId}, attempt ${retryCount}, url: ${baseUrl}`
        );
      } else {
        // Fallback to Photo-Missing
        img.onerror = null;
        img.src =
          "https://resources.premierleague.com/premierleague/photos/players/110x140/Photo-Missing.png";
        console.warn(
          `Failed to load image for ${photoId} after ${maxRetries} retries`
        );
      }
    };

    div.appendChild(img);
    container.appendChild(div);
  });
};

window.updateBadges = (data) => {
  const container = document.getElementById("player-images");
  if (!container) return;
  container.innerHTML = "";
  (data.players_images || []).forEach((pi, idx) => {
    const div = document.createElement("div"),
      img = document.createElement("img");
    div.className = `badge-image-${idx + 1}`;
    img.classList.add("img-fluid", "badge-width");
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

  if (loading) loading.style.display = "block";
  tbody.style.display = "none";

  // New
  const qs = new URLSearchParams({ max_show: String(cfg.maxShow) });
  if (sortBy) qs.set("sort_by", sortBy);
  if (sortOrder) qs.set("order", sortOrder);
  const url = `${cfg.url}&${qs.toString()}`;

  console.log("📡 fetchMiniLeague →", url);
  let res, data;
  try {
    res = await fetch(url);
    data = await res.json();
  } catch (e) {
    console.error("⚠️ mini-league fetch failed", e);
    if (loading) loading.style.display = "none";
    return true;
  }

  const players = data.players || [];
  console.log("🎉 mini-league players:", players);

  const maxVals = {},
    minVals = {};
  cfg.statsKeys.forEach((key) => {
    const vals = players.map((p) => p[key] || 0);
    maxVals[key] = Math.max(...vals);
    minVals[key] = Math.min(...vals);
  });

  let toRender = players;
  if (typeof cfg.maxShow === "number") {
    const topN = players.slice(0, cfg.maxShow);
    if (!topN.some((p) => p.team_id === cfg.currentEntry)) {
      const me = players.find((p) => p.team_id === cfg.currentEntry);
      if (me) topN.push(me);
    }
    toRender = topN;
  }

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
  if (loading) loading.style.display = "none";
  tbody.style.display = "";

  return true;
}

// ─────────────── 7) Generic data fetch ─────────────
async function fetchData(sortBy, sortOrder, opts = {}) {
  const { snapPrice = true } = opts;

  // New: no hard-coded fallback; trust URL or leave empty
  sortBy =
    sortBy ??
    window.tableConfig.sortBy ??
    window.tableConfig.defaultSort ??
    null;
  sortOrder =
    sortOrder ??
    window.tableConfig.sortOrder ??
    window.tableConfig.defaultOrder ??
    null;

  // Function to update sort display
  const updateSortDisplay = () => {
    const sortEl = document.getElementById("current-sort");
    const orderEl = document.getElementById("current-order");

    console.log("fetchData called with:", {
      sortBy,
      sortOrder,
      lookup: window.tableConfig.lookup,
    });

    const effectiveSortBy = sortBy || "rank";
    const effectiveOrder = (sortOrder || "asc").toLowerCase();

    if (sortEl) {
      const displayName =
        window.tableConfig.lookup?.[effectiveSortBy] || effectiveSortBy;
      sortEl.textContent = displayName;
    }
    if (orderEl) {
      orderEl.textContent = effectiveOrder === "desc" ? "" : "(asc)";
    }
  };

  updateSortDisplay(); // Try immediately

  // Retry after 100ms and 500ms if DOM elements are missing
  if (!document.getElementById("current-sort")) {
    console.log("Retrying current-sort update after 100ms");
    setTimeout(updateSortDisplay, 100);
    setTimeout(updateSortDisplay, 500); // Additional retry for slower loads
  }

  // Handle mini_league table via fetchMiniLeague
  if (await fetchMiniLeague(sortBy, sortOrder)) {
    return; // Mini-league handled
  }

  const cfg = window.tableConfig;
  const tbody = document.querySelector(cfg.tbodySelector);
  const loading = document.querySelector(cfg.loadingSelector);

  const params = { sort_by: sortBy, order: sortOrder };

  if (cfg.table !== "am") {
    const { minCost, maxCost } = getSelectedPriceRange();
    const selectedPositions = getSelectedPositions();

    if (selectedPositions && selectedPositions.length > 0) {
      params.selected_positions = selectedPositions;
    }
    params.min_cost = minCost;
    params.max_cost = maxCost;

    const { minMin, maxMin } = getSelectedMinutesRange();
    params.min_minutes = minMin;
    params.max_minutes = maxMin;
  }

  const qs = new URLSearchParams(params);
  const resp = await fetch(`${cfg.url}&${qs}`);
  const { players, players_images, is_truncated, manager, price_range } =
    await resp.json();

  if (price_range && price_range.min != null && price_range.max != null) {
    updatePriceSliderRange(
      price_range.min / 10,
      price_range.max / 10,
      snapPrice
    );
  }

  document.getElementById("entries").textContent =
    players.length === 1
      ? "1 entry"
      : ["teams", "talisman"].includes(cfg.table) || !is_truncated
      ? `${players.length} entries`
      : players.length === 100
      ? "100+ entries"
      : `${players.length} entries`;

  updateTopPlayersText(players.length, is_truncated, cfg.table);

  tbody.innerHTML = "";
  players.forEach((p, idx) => {
    const tr = document.createElement("tr");
    tr.classList.add(
      "vert-border",
      "align-middle",
      // `team-${p.team_code}`,
      `element-type-${p.element_type}`
    );

    cfg.columns.forEach((col) => {
      if (col.render) {
        tr.insertAdjacentHTML("beforeend", col.render(p, idx));
      } else {
        let val = p[col.key] ?? "";
        if (col.formatter) val = col.formatter(val);
        const dataColName = col.dataColumn || col.key;
        const dataColumnAttr = ` data-column="${dataColName}"`;
        const sortLevelAttr = col.sortLevel
          ? ` data-sort-level="${col.sortLevel}"`
          : "";

        tr.insertAdjacentHTML(
          "beforeend",
          `<td class="${
            col.className || ""
          }"${dataColumnAttr}${sortLevelAttr}>${val}</td>`
        );
      }
    });

    tbody.appendChild(tr);
    // NOTE: no per-cell tooltip init needed anymore; delegation handles it
  });

  if (cfg.table === "teams") {
    updateBadges({ players_images }); // teams table have just club badges
  } else {
    updatePlayerImages({ players_images });
  }
  updateSortIndicator(sortBy, sortOrder);

  if (loading) loading.style.display = "none";
  tbody.style.display = "";
}

// Updated updateTopPlayersText to handle "100+ top players"
function updateTopPlayersText(count, isTruncated, table) {
  const topPlayersElement = document.getElementById("top-players");
  if (topPlayersElement) {
    topPlayersElement.textContent =
      count === 1
        ? "1 top player"
        : ["teams", "talisman"].includes(table) || !isTruncated
        ? `${count} top players`
        : count === 100
        ? "100+ top players"
        : `${count} top players`;
  }
}

window.fetchData = fetchData;

// ─────────────── 8) DOMContentLoaded ─────────────────
document.addEventListener("DOMContentLoaded", () => {
  // Enable delegated tooltips once
  enableDelegatedTooltips();

  const params = new URLSearchParams(location.search);
  if (window.tableConfig) {
    if (params.has("sort_by")) tableConfig.sortBy = params.get("sort_by");
    if (params.has("order")) tableConfig.sortOrder = params.get("order");
  }

  if (window.tableConfig && window.tableConfig.url) {
    updateSortIndicator(
      window.tableConfig.sortBy,
      window.tableConfig.sortOrder
    );
  }

  // 8.3) New cell-hover highlighting
  document.querySelectorAll("table.interactive-table").forEach((table) => {
    let activeCells = [];

    function clearHighlights() {
      activeCells.forEach((cell) => {
        cell.style.backgroundColor = "";
        cell.style.color = "";
        if (cell.dataset.wasTextDanger === "true") {
          cell.classList.add("text-danger");
          delete cell.dataset.wasTextDanger;
        }
        cell.style.borderRadius = "";
      });
      activeCells = [];
    }

    function highlightCells(td) {
      clearHighlights();
      const col = td.dataset.column;
      const sortLevel = td.dataset.sortLevel;

      const primaryBg = sortLevel === "primary" ? "#D9722C" : "#203C73";
      const matchBg = sortLevel === "primary" ? "#203C73" : "#D9722C";

      // Current cell
      if (td.classList.contains("text-danger")) {
        td.dataset.wasTextDanger = "true";
        td.classList.remove("text-danger");
      }
      td.style.backgroundColor = primaryBg;
      td.style.color = "#fff";
      activeCells.push(td);

      // Partner cells: only in the same row
      const row = td.closest("tr");
      row.querySelectorAll(`td[data-column="${col}"]`).forEach((other) => {
        if (other === td) return;
        if (other.classList.contains("text-danger")) {
          other.dataset.wasTextDanger = "true";
          other.classList.remove("text-danger");
        }
        other.style.backgroundColor = matchBg;
        other.style.color = "#fff";
        activeCells.push(other);
      });
    }

    function clearHighlights2() {
      activeCells.forEach((cell) => {
        cell.style.backgroundColor = "";
        cell.style.color = "";
        if (cell.dataset.wasTextDanger === "true") {
          cell.classList.add("text-danger");
          delete cell.dataset.wasTextDanger;
        }
      });
      activeCells = [];
    }

    table.addEventListener("mouseover", (e) => {
      const cell = e.target.closest("td, th");

      // If not hovering a cell, or hovering a header <th> → clear
      if (!cell || cell.tagName === "TH") {
        clearHighlights();
        return;
      }

      // Only highlight if the cell is in the highlightable set
      if (cell.matches("td[data-column][data-sort-level]")) {
        highlightCells(cell);
      } else {
        clearHighlights();
      }
    });

    // Optional: reset when leaving the table entirely
    table.addEventListener("mouseleave", clearHighlights);
  });

  // Slider hookup
  const slider = document.getElementById("price-slider");
  if (slider && window.noUiSlider && !slider.noUiSlider) {
    noUiSlider.create(slider, {
      start: [4, 14.5],
      connect: true,
      range: { min: 4, max: 14.5 },
      step: 0.1,
      tooltips: true,
      format: wNumb({ decimals: 1, prefix: "£" }),
    });
    slider.noUiSlider.on("change", () =>
      window.fetchData(tableConfig.sortBy, tableConfig.sortOrder, {
        snapPrice: false,
      })
    );
  }

  // --- MINUTES SLIDER ---
  const minSlider = document.getElementById("minutes-slider");
  const maxMinutes = (window.tableConfig?.currentGw || 1) * 90;
  if (minSlider && window.noUiSlider && !minSlider.noUiSlider) {
    noUiSlider.create(minSlider, {
      start: [0, maxMinutes],
      connect: true,
      range: { min: 0, max: maxMinutes },
      step: 1,
      tooltips: true,
      format: wNumb({ decimals: 0 }),
    });
    minSlider.noUiSlider.on("change", () =>
      window.fetchData(tableConfig.sortBy, tableConfig.sortOrder, {
        snapPrice: false,
      })
    );
  }

  // Position-checkbox hookup
  document
    .querySelectorAll('#checkboxForm input[type="checkbox"]')
    .forEach((cb) =>
      cb.addEventListener("change", () =>
        window.fetchData(tableConfig.sortBy, tableConfig.sortOrder)
      )
    );

  // Reset button(s)
  document.querySelectorAll(".reset-filters").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.preventDefault();
      window.resetFilters();
    });
  });

  // Initial AJAX load
  if (window.tableConfig && window.tableConfig.url) {
    window.fetchData(tableConfig.sortBy, tableConfig.sortOrder);
  }
  initComponents();

  // Tooltip setup for table headers — use data-bs-title (not title)
  if (window.tableConfig && window.tableConfig.lookup) {
    document.querySelectorAll("table thead th").forEach((th) => {
      const sortKey = th.getAttribute("data-sort");
      const tip = sortKey && window.tableConfig.lookup[sortKey];
      if (tip) {
        th.removeAttribute("title"); // prevent native tooltip
        th.setAttribute("data-bs-toggle", "tooltip");
        th.setAttribute("data-bs-title", tip);
        th.setAttribute("data-bs-custom-class", "tooltip-lg");
      }
    });
  }
});

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
let lastClickTime = 0;

document.body.addEventListener("click", (e) => {
  const th = e.target.closest("thead th[data-sort]");
  if (!th) return;

  // prevent duplicate triggers (span clicks, bubbling etc.)
  e.stopPropagation();

  // debounce guard: ignore clicks <150ms apart
  const now = Date.now();
  if (now - lastClickTime < 150) {
    return;
  }
  lastClickTime = now;

  // skip manager page tables
  if (
    th.closest("#current-season-table-container") ||
    th.closest("#previous-seasons-table-container")
  ) {
    return;
  }

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

window.initManagerPage = function (configs) {
  Object.values(configs).forEach((cfg) => {
    loadTableAndChart(cfg);
  });
};

// ─────────── 11) Manager page initialiser ───────────
// Re-add the buildSortableTable helper for manager.html
function buildSortableTable(data, columns, dataKey) {
  if (!data || data.length === 0) return "<p>No data</p>";

  let html = `<table class="table text-center">
    <thead><tr>`;

  // Build table headers
  columns.forEach((col) => {
    html += `<th data-sort="${col.key}" ${col.thAttrs || ""}>${col.label}</th>`;
  });
  html += `</tr></thead><tbody>`;

  // Build table rows
  data.forEach((row) => {
    html += `<tr>`;
    columns.forEach((col) => {
      const raw = row[col.key];
      const disp = col.formatter ? col.formatter(raw) : raw;
      html += `<td>${disp != null ? disp : ""}</td>`;
    });
    html += `</tr>`;
  });

  html += `</tbody></table>`;
  return html;
}

window.initManagerPage = function (pageConfigs) {
  console.log(
    "🔄 initManagerPage: restoring manager tables & charts",
    pageConfigs
  );

  Object.values(pageConfigs).forEach((cfg) => {
    // reuse the chart + table builder function for each config
    buildManagerTableAndChart(cfg);
  });
};

// Scale toggle for log/linear
function addScaleToggle(chart, linearBtnId, logBtnId) {
  const linearBtn = document.getElementById(linearBtnId);
  const logBtn = document.getElementById(logBtnId);
  if (!linearBtn || !logBtn) return;

  linearBtn.addEventListener("click", () => {
    chart.config.options.scales.y.type = "linear";
    chart.update();
    linearBtn.classList.add("active");
    logBtn.classList.remove("active");
  });

  logBtn.addEventListener("click", () => {
    chart.config.options.scales.y.type = "logarithmic";
    chart.update();
    logBtn.classList.add("active");
    linearBtn.classList.remove("active");
  });
}

// Get rid of Tooltips instances (safe even with delegation)
function disposeTooltips(context = document) {
  context.querySelectorAll('[data-bs-toggle="tooltip"]').forEach((el) => {
    const instance = bootstrap.Tooltip.getInstance(el);
    if (instance) instance.dispose();
  });
}

// Builder function for manager tables + charts
async function buildManagerTableAndChart(cfg) {
  // Allow “chart-only” configs (no table)
  const container = cfg.tableContainerId
    ? document.getElementById(cfg.tableContainerId)
    : null;

  try {
    // 1️⃣ Data: either initialData or fetch
    let data;
    if (cfg.initialData) {
      data = Array.isArray(cfg.initialData)
        ? [...cfg.initialData]
        : cfg.initialData;
      const dir = cfg.sortOrder === "asc" ? 1 : -1;
      data.sort((a, b) => {
        const A = a[cfg.sortBy];
        const B = b[cfg.sortBy];
        if (A == null && B != null) return 1;
        if (B == null && A != null) return -1;
        if (typeof A === "number" && typeof B === "number")
          return dir * (A - B);
        return dir * String(A).localeCompare(String(B));
      });
    } else if (cfg.ajaxRoute) {
      const url = new URL(cfg.ajaxRoute, location);
      url.searchParams.set("sort_by", cfg.sortBy);
      url.searchParams.set("order", cfg.sortOrder);
      const resp = await fetch(url);
      data = await resp.json();
    } else {
      data = []; // nothing to render
    }

    // 2️⃣ TABLE (optional)
    if (container) {
      // Clean up old tooltips before replacing the table
      disposeTooltips(container);

      container.innerHTML = buildSortableTable(data, cfg.columns, cfg.dataKey);

      // Re-init popovers (tooltips are delegated globally)
      initComponents(container);

      // Header sorting (local re-render)
      const table = container.querySelector("table");
      if (table) {
        table.querySelectorAll("th[data-sort]").forEach((th) => {
          th.addEventListener("click", () => {
            const key = th.dataset.sort;
            const dir =
              cfg.sortBy === key && cfg.sortOrder === "desc" ? "asc" : "desc";
            cfg.sortBy = key;
            cfg.sortOrder = dir;
            buildManagerTableAndChart(cfg); // re-render
          });
        });

        // Add header tooltips via data attributes
        table.querySelectorAll("thead th[data-sort]").forEach((th) => {
          const sortKey = th.getAttribute("data-sort");
          const tip = cfg.columns.find((c) => c.key === sortKey)?.label;
          if (tip) {
            th.removeAttribute("title");
            th.setAttribute("data-bs-toggle", "tooltip");
            th.setAttribute("data-bs-title", tip);
            th.setAttribute("data-bs-custom-class", "tooltip-lg");
          }
        });
      }

      updateSortIndicator(
        cfg.sortBy,
        cfg.sortOrder,
        `#${cfg.tableContainerId}`
      );
    }

    // 3️⃣ CHART (always)
    const canvasEl = document.getElementById(cfg.chartId);
    if (!canvasEl) {
      console.warn(`⚠️ No <canvas> found with id="${cfg.chartId}"`);
      return;
    }

    const oldChart = Chart.getChart(cfg.chartId);
    if (oldChart) oldChart.destroy();

    const ctx = canvasEl.getContext("2d");
    const chart = new Chart(ctx, {
      data: {
        labels: data.map((r) => r[cfg.dataKey]),
        datasets: cfg.buildDatasets(data),
      },
      // Merge scales first, then options (so options can still override if needed)
      options: Object.assign({ scales: cfg.scales || {} }, cfg.options || {}),
    });

    // 4️⃣ toggles + hover (table hover only if we actually have a table)
    if (cfg.toggleBtns?.length === 2) addScaleToggle(chart, ...cfg.toggleBtns);
    if (container)
      attachTableGraphHover(
        cfg.chartId,
        `#${cfg.tableContainerId}`,
        cfg.hoverDs
      );
  } catch (err) {
    console.warn("⚠️ Manager page failed:", err);
  }
}

// Activate Poppers
function initComponents(context = document) {
  // Popovers (like the Info button)
  context.querySelectorAll('[data-bs-toggle="popover"]').forEach((el) => {
    new bootstrap.Popover(el, {
      html: true,
      boundary: "window",
      sanitize: false,
      trigger: "focus", // closes when clicking elsewhere
    });
  });
}

// Hover logic: sync table rows and chart points
function attachTableGraphHover(
  chartId,
  tableSelector,
  datasetLabelOrIndex = 0
) {
  const chart = Chart.getChart(chartId);
  if (!chart) return;

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
