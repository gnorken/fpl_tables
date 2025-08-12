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

window.getSelectedMinutesRange = () => {
  const slider = document.getElementById("minutes-slider");
  if (!slider || !slider.noUiSlider) return { minMin: 0, maxMin: 3420 };
  const [min, max] = slider.noUiSlider
    .get()
    .map((v) => parseFloat(v.replace(" min", "")));
  return { minMin: min, maxMin: max };
};

// ─────────────── 3) Sort‐arrow indicator ─────────────────
window.updateSortIndicator = (sortBy, sortOrder, containerSelector = null) => {
  const root = containerSelector
    ? document.querySelector(containerSelector)
    : document;

  if (!root) return;

  const roundedTables = [
    "defence-table",
    "offence-table",
    "points-table",
    "per-90-table",
    "teams-table",
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
  if (!container) return;
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

  if (loading) loading.style.display = "block";
  tbody.style.display = "none";

  const url = `${cfg.url}&sort_by=${sortBy}&order=${sortOrder}&max_show=${cfg.maxShow}`;
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
async function fetchData(sortBy, sortOrder) {
  if (await fetchMiniLeague(sortBy, sortOrder)) return;

  const sortEl = document.getElementById("current-sort");
  const orderEl = document.getElementById("current-order");
  if (sortEl)
    sortEl.textContent = window.tableConfig.lookup?.[sortBy] || sortBy;
  if (orderEl) orderEl.textContent = sortOrder === "desc" ? "" : "(asc)";

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

    // ← NEW: minutes filter
    const { minMin, maxMin } = getSelectedMinutesRange();
    // console.log("🔍 Minutes slider values:", minMin, maxMin);
    params.min_minutes = minMin;
    params.max_minutes = maxMin;
  }

  const qs = new URLSearchParams(params);
  const resp = await fetch(`${cfg.url}&${qs}`);
  const { players, players_images, is_truncated, manager } = await resp.json();

  // Update #entries element to show "100+ entries" when truncated
  const table = cfg.table; // e.g., "defence", "offence", "points", "talisman", "teams", "mini_league"
  document.getElementById("entries").textContent =
    players.length === 1
      ? "1 entry"
      : ["teams", "talisman"].includes(table) || !is_truncated
      ? `${players.length} entries`
      : players.length === 100
      ? "100+ entries"
      : `${players.length} entries`;

  updateTopPlayersText(players.length, is_truncated, table);

  tbody.innerHTML = "";
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

  // Current hover
  // const hoverEl = document.getElementById("current-hover");
  // if (hoverEl) {
  //   const defaultText = hoverEl.textContent;
  //   document.querySelectorAll("th[data-sort]").forEach((th) => {
  //     const key = th.dataset.sort;
  //     const tip = window.tableConfig.lookup?.[key] || th.textContent.trim();
  //     th.addEventListener("mouseenter", () => (hoverEl.textContent = tip));
  //     th.addEventListener(
  //       "mouseleave",
  //       () => (hoverEl.textContent = defaultText)
  //     );
  //   });
  // }

  // 8.3) Cell-hover highlighting (text-danger handling)
  // document.querySelectorAll("table.interactive-table").forEach((table) => {
  //   let activeCells = [];
  //   table.addEventListener("mouseover", (e) => {
  //     const td = e.target.closest("td[data-column][data-sort-level]");
  //     if (!td) return;

  //     const col = td.dataset.column;
  //     const sortLevel = td.dataset.sortLevel;
  //     const row = td.closest("tr");

  //     if (activeCells.length) {
  //       activeCells.forEach((cell) => {
  //         cell.style.backgroundColor = "";
  //         cell.style.color = "";
  //         if (cell.dataset.wasTextDanger === "true") {
  //           cell.classList.add("text-danger");
  //           delete cell.dataset.wasTextDanger;
  //         }
  //         cell.style.borderRadius = "";
  //       });
  //       activeCells = [];
  //     }

  //     const primaryBg = sortLevel === "primary" ? "#e90052" : "#38003c";
  //     const matchBg = sortLevel === "primary" ? "#38003c" : "#e90052";

  //     if (td.classList.contains("text-danger")) {
  //       td.dataset.wasTextDanger = "true";
  //       td.classList.remove("text-danger");
  //     }
  //     td.style.backgroundColor = primaryBg;
  //     td.style.color = "#fff";
  //     td.style.borderRadius = "3px";
  //     activeCells.push(td);

  //     row.querySelectorAll(`td[data-column="${col}"]`).forEach((other) => {
  //       if (other === td) return;
  //       if (other.classList.contains("text-danger")) {
  //         other.dataset.wasTextDanger = "true";
  //         other.classList.remove("text-danger");
  //       }
  //       other.style.backgroundColor = matchBg;
  //       other.style.color = "#fff";
  //       other.style.borderRadius = "3px";
  //       activeCells.push(other);
  //     });
  //   });

  //   table.addEventListener("mouseleave", () => {
  //     if (activeCells.length) {
  //       activeCells.forEach((cell) => {
  //         cell.style.backgroundColor = "";
  //         cell.style.color = "";
  //         if (cell.dataset.wasTextDanger === "true") {
  //           cell.classList.add("text-danger");
  //           delete cell.dataset.wasTextDanger;
  //         }
  //         cell.style.borderRadius = "";
  //       });
  //       activeCells = [];
  //     }
  //   });
  // });

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

      const primaryBg = sortLevel === "primary" ? "#e90052" : "#38003c";
      const matchBg = sortLevel === "primary" ? "#38003c" : "#e90052";

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

    function clearHighlights() {
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

  // compute max minutes from currentGw
  // const maxMinutes = (window.tableConfig.currentGw || 1) * 90;

  // --- MINUTES SLIDER ---
  const minSlider = document.getElementById("minutes-slider");
  if (minSlider && window.noUiSlider && !minSlider.noUiSlider) {
    noUiSlider.create(minSlider, {
      start: [0, 3420],
      connect: true,
      range: { min: 0, max: 3420 },
      step: 100,
      tooltips: true,
      format: wNumb({ decimals: 0 }),
    });
    minSlider.noUiSlider.on("change", () =>
      window.fetchData(tableConfig.sortBy, tableConfig.sortOrder)
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

  // Initial AJAX load
  if (window.tableConfig && window.tableConfig.url) {
    window.fetchData(tableConfig.sortBy, tableConfig.sortOrder);
  }
  initComponents();

  // Tooltip setup for table headers
  if (window.tableConfig && window.tableConfig.lookup) {
    document.querySelectorAll("table thead th").forEach((th) => {
      const sortKey = th.getAttribute("data-sort");
      if (sortKey && window.tableConfig.lookup[sortKey]) {
        th.setAttribute("title", window.tableConfig.lookup[sortKey]);
        th.setAttribute("data-bs-toggle", "tooltip");
      }
    });
  }
  window.initTooltips();
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

// Get rid of Tooltips instances
function disposeTooltips(context = document) {
  context.querySelectorAll('[data-bs-toggle="tooltip"]').forEach((el) => {
    const instance = bootstrap.Tooltip.getInstance(el);
    if (instance) instance.dispose();
  });
}

// Builder function for manager tables + charts
async function buildManagerTableAndChart(cfg) {
  // print("▶️ Building table & chart for:", cfg.tableContainerId);

  const container = document.getElementById(cfg.tableContainerId);
  if (!container) return;

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
    } else {
      const url = new URL(cfg.ajaxRoute, location);
      url.searchParams.set("sort_by", cfg.sortBy);
      url.searchParams.set("order", cfg.sortOrder);
      const resp = await fetch(url);
      data = await resp.json();
    }

    // Clean up old tooltips before replacing the table
    disposeTooltips(container);

    // 2️⃣ Build table
    container.innerHTML = buildSortableTable(data, cfg.columns, cfg.dataKey);

    // 3️⃣ Manually dispose tooltips & re-init
    container.querySelectorAll('[data-bs-toggle="tooltip"]').forEach((el) => {
      const instance = bootstrap.Tooltip.getInstance(el);
      if (instance) instance.dispose();
    });

    // Re-initialise tooltips and popovers
    window.initTooltips(container);
    initComponents(container); // popovers

    // 4️⃣ Header sorting
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
    }

    // 5️⃣ Update sort indicator
    updateSortIndicator(cfg.sortBy, cfg.sortOrder, `#${cfg.tableContainerId}`);

    // 6️⃣ Rebuild chart
    const oldChart = Chart.getChart(cfg.chartId);
    if (oldChart) oldChart.destroy();

    // Safely grab the canvas
    const canvasEl = document.getElementById(cfg.chartId);
    if (!canvasEl) {
      console.warn(`⚠️ No <canvas> found with id="${cfg.chartId}"`);
      return;
    }

    // Build new one
    const ctx = canvasEl.getContext("2d");
    const chart = new Chart(ctx, {
      data: {
        labels: data.map((r) => r[cfg.dataKey]),
        datasets: cfg.buildDatasets(data),
      },
      options: Object.assign({ scales: cfg.scales }, cfg.options || {}),
    });

    // 7️⃣ Toggle & hover
    addScaleToggle(chart, ...cfg.toggleBtns);
    attachTableGraphHover(cfg.chartId, `#${cfg.tableContainerId}`, cfg.hoverDs);
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
