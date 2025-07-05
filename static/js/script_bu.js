// 1) Helpers for filters
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

// 2) Sort indicator
window.updateSortIndicator = (sortBy, sortOrder) => {
  console.log("🔔 updateSortIndicator", sortBy, sortOrder);
  document.querySelectorAll("th[data-sort]").forEach((th) => {
    const isCurrent = th.dataset.sort === sortBy;
    th.classList.toggle("sorted", isCurrent);
    th.classList.toggle("asc", isCurrent && sortOrder === "asc");
    th.classList.toggle("desc", isCurrent && sortOrder === "desc");

    // remove old arrow if present
    const old = th.querySelector(".sort-arrow");
    if (old) old.remove();

    // if this is the active column, append a <span> arrow
    if (isCurrent) {
      const arrow = document.createElement("span");
      arrow.className = "sort-arrow";
      arrow.textContent = sortOrder === "asc" ? "↑" : "↓";
      th.appendChild(arrow);
    }
  });
};

// 3) Top-players text
window.updateTopPlayersText = (entryCount) => {
  let text;
  if (entryCount === 0) {
    text = "Nothing to display";
  } else if (entryCount === 1) {
    text = "↑ Only one";
  } else if (entryCount < 5) {
    const words = { 2: "Two", 3: "Three", 4: "Four" }[entryCount];
    text = `↑ Top ${words}`;
  } else {
    text = "↑ Top Five";
  }
  const el = document.getElementById("top-players");
  if (el) el.textContent = text;
};

// 4) Image & badge updaters
window.updatePlayerImages = (data) => {
  const imagesContainer = document.getElementById("player-images");
  imagesContainer.innerHTML = "";
  const playersImages = data.players_images || [];
  if (playersImages.length === 0) {
    document.getElementById("loading").textContent = "0 entries";
    return;
  }
  playersImages.forEach((pi, idx) => {
    const div = document.createElement("div");
    div.className = `player-image-${idx + 1}`;
    const img = document.createElement("img");
    img.classList.add("img-fluid", "overlap-img");
    img.loading = "lazy";
    img.alt = "Player Photo";
    img.src = `https://resources.premierleague.com/premierleague/photos/players/110x140/${pi.photo}`;
    img.onerror = function () {
      this.onerror = null;
      this.src =
        "https://resources.premierleague.com/premierleague/photos/players/110x140/Photo-Missing.png";
    };
    div.appendChild(img);
    imagesContainer.appendChild(div);
  });
};

window.updateBadges = (data) => {
  const imagesContainer = document.getElementById("player-images");
  imagesContainer.innerHTML = "";
  const playersImages = data.players_images || [];
  if (playersImages.length === 0) {
    document.getElementById("loading").textContent = "0 entries";
    return;
  }
  playersImages.forEach((pi, idx) => {
    const div = document.createElement("div");
    div.className = `badge-image-${idx + 1}`;
    const img = document.createElement("img");
    img.classList.add("img-fluid", "overlap-badge");
    img.loading = "lazy";
    img.alt = "Club Badge";
    img.src = `https://resources.premierleague.com/premierleague/badges/100/t${pi.team_code}@x2.png`;
    img.onerror = function () {
      this.onerror = null;
      this.src =
        "https://resources.premierleague.com/premierleague/photos/players/110x140/Photo-Missing.png";
    };
    div.appendChild(img);
    imagesContainer.appendChild(div);
  });
};

// ─────────────── Mini-League Branch ───────────────
async function fetchMiniLeague(sortBy, sortOrder) {
  const cfg = window.tableConfig;
  if (!cfg) return false;

  const tbodyEl = document.querySelector(cfg.tbodySelector);
  const loadingEl = document.querySelector(cfg.loadingSelector);
  if (!tbodyEl) return false;

  // 1) Update sort-info bar
  const sortEl = document.getElementById("current-sort");
  const orderEl = document.getElementById("current-order");
  if (sortEl) sortEl.textContent = cfg.lookup[sortBy] || sortBy;
  if (orderEl) orderEl.textContent = sortOrder === "desc" ? "" : "(ascending)";

  // 2) Show spinner, hide table
  loadingEl && (loadingEl.style.display = "block");
  tbodyEl.style.display = "none";

  // 3) Build URL + Fetch mini-league data (including max_show)
  const fetchUrl = [
    cfg.url,
    `sort_by=${sortBy}`,
    `order=${sortOrder}`,
    `max_show=${cfg.maxShow}`,
  ].join("&");
  const res = await fetch(fetchUrl);
  const data = await res.json();
  const players = data.players || [];

  // 4) Compute max/min for highlights
  const maxVals = {},
    minVals = {};
  cfg.statsKeys.forEach((k) => {
    const vals = players.map((p) => p[k] || 0);
    maxVals[k] = Math.max(...vals);
    minVals[k] = Math.min(...vals);
  });

  // 4.5) “Top N + current team” logic
  let toRender = players;
  if (typeof cfg.maxShow === "number") {
    const topN = players.slice(0, cfg.maxShow);
    if (!topN.some((p) => p.team_id === cfg.currentEntry)) {
      const me = players.find((p) => p.team_id === cfg.currentEntry);
      if (me) {
        me.isCurrent = true; // for any special styling
        topN.push(me);
      }
    }
    toRender = topN;
  }

  // 5) Render rows
  tbodyEl.innerHTML = "";
  toRender.forEach((team) => {
    const tr = document.createElement("tr");
    tr.classList.add("vert-border", "text-center", "align-middle");

    // ✅ Highlight by matching IDs directly
    if (team.team_id === cfg.currentEntry) {
      tr.classList.add("highlight-current");
    }

    cfg.columns.forEach((col) => {
      if (col.render) {
        // custom cell renderer
        tr.insertAdjacentHTML("beforeend", col.render(team));
      } else {
        // standard key→cell
        const raw = team[col.key] ?? 0;
        const disp = col.formatter ? col.formatter(raw) : raw;
        const classes = [];

        // highlight logic
        const isBest = cfg.invertKeys.includes(col.key)
          ? raw === minVals[col.key]
          : raw === maxVals[col.key];
        if (isBest) classes.push("highlight");

        if (col.extraClass) classes.push(col.extraClass);
        if (col.className) classes.push(col.className);

        const td = document.createElement("td");
        td.className = classes.join(" ");
        td.textContent = disp;
        tr.appendChild(td);
      }
    });

    tbodyEl.appendChild(tr);
  });

  // 6) Hide spinner & show table
  loadingEl && (loadingEl.style.display = "none");
  tbodyEl.style.display = "";

  return true;
}

// 5) Unified fetcher
window.fetchData = async (sortBy, sortOrder) => {
  // Mini-League shortcut
  if (await fetchMiniLeague(sortBy, sortOrder)) {
    return;
  }

  // Teams / AM / default logic
  const teamId = window.teamId;
  const table = window.tableType;
  const { minCost, maxCost } = window.getSelectedPriceRange();
  const selectedPositions = window.getSelectedPositions();

  document.getElementById("loading").style.display = "block";
  document.getElementById("player-table-body").style.display = "none";

  const qs = new URLSearchParams({
    team_id: teamId,
    table,
    sort_by: sortBy,
    order: sortOrder,
    selected_positions: selectedPositions,
    min_cost: minCost,
    max_cost: maxCost,
    // Pass your JS maxShow value here:
    max_show: window.tableConfig.maxShow,
  });

  try {
    const res = await fetch(`/get-sorted-players?${qs.toString()}`);
    const payload = await res.json();

    // ←―――――――― Capture the full payload so handleUrlChange can see it
    window._lastFetchedData = payload;

    const { players, players_images, manager } = payload;

    document.getElementById("entries").textContent =
      players.length === 1 ? "1 entry" : `${players.length} entries`;
    window.updateTopPlayersText(players.length);

    const body = document.getElementById("player-table-body");
    body.innerHTML = "";
    if (table === "teams") {
      window.updateBadges({ players_images });
    } else if (table === "am") {
      window.updatePlayerImages({ players_images });
    } else {
      players.forEach((p) => {
        const tr = document.createElement("tr");
        body.appendChild(tr);
      });
      window.updatePlayerImages({ players_images });
    }

    updateSortIndicator(sortBy, sortOrder);
  } catch (err) {
    console.error("Error fetching data:", err);
  } finally {
    document.getElementById("loading").style.display = "none";
    document.getElementById("player-table-body").style.display = "";
  }
};

// 6) Sorting helper
window.sortTable = (sortBy) => {
  if (window.tableConfig) {
    // Mini-league path
    if (window.tableConfig.sortBy === sortBy) {
      window.tableConfig.sortOrder =
        window.tableConfig.sortOrder === "desc" ? "asc" : "desc";
    } else {
      window.tableConfig.sortBy = sortBy;
      window.tableConfig.sortOrder = "desc";
    }
    window.fetchData(window.tableConfig.sortBy, window.tableConfig.sortOrder);
    return;
  }

  // Legacy path
  if (window.currentSortColumn === sortBy) {
    window.currentSortOrder =
      window.currentSortOrder === "desc" ? "asc" : "desc";
  } else {
    window.currentSortColumn = sortBy;
    window.currentSortOrder = "desc";
  }
  window.fetchData(window.currentSortColumn, window.currentSortOrder);
};

// 7) DOM ready
document.addEventListener("DOMContentLoaded", () => {
  // ─── hover helpers for sort‐info on any page ────────────────────────
  const hoverEl = document.getElementById("current-hover");
  if (hoverEl) {
    const defaultText = hoverEl.textContent;
    document.querySelectorAll("th[data-sort]").forEach((th) => {
      const key = th.dataset.sort;
      const tip = window.tableConfig?.lookup?.[key] || th.textContent.trim();
      th.addEventListener("mouseenter", () => {
        hoverEl.textContent = tip;
      });
      th.addEventListener("mouseleave", () => {
        hoverEl.textContent = defaultText;
      });
    });
  }

  const slider = document.getElementById("price-slider");
  if (slider && window.noUiSlider) {
    noUiSlider.create(slider, {
      start: [3, 15],
      connect: true,
      range: { min: 3, max: 15 },
      step: 0.1,
      tooltips: true,
      format: wNumb({ decimals: 1, prefix: "£" }),
    });
    slider.noUiSlider.on("change", () =>
      window.fetchData(window.currentSortColumn, window.currentSortOrder)
    );
  }

  document
    .querySelectorAll('#checkboxForm input[type="checkbox"]')
    .forEach((cb) =>
      cb.addEventListener("change", () =>
        window.fetchData(window.currentSortColumn, window.currentSortOrder)
      )
    );
});
