// Filter. Checkboxes
window.getSelectedPositions = function () {
  const selectedPositions = [];
  document
    .querySelectorAll('#checkboxForm input[type="checkbox"]:checked')
    .forEach((checkbox) => {
      selectedPositions.push(checkbox.value);
    });
  return selectedPositions.join(","); // Returns a comma-separated string.
};

// Global function to update player images.
window.updatePlayerImages = function (data) {
  // Update player images.
  const imagesContainer = document.getElementById("player-images");

  // Clear any existing content.
  imagesContainer.innerHTML = "";

  // Try to get an existing skeleton container (if it exists in your HTML markup).
  let skeletonContainer = imagesContainer.querySelector(
    ".skeleton-loader-container"
  );
  // If none exists, create one.
  if (!skeletonContainer) {
    skeletonContainer = document.createElement("div");
    skeletonContainer.className = "skeleton-loader-container";
    // Optionally, add some placeholder content or styling.
    skeletonContainer.innerHTML = "";
    imagesContainer.appendChild(skeletonContainer);
  }

  const playersImages = data.players_images || [];
  const totalImages = playersImages.length;

  if (totalImages === 0) {
    // No images: update the loading text to "0 entries"
    document.getElementById("loading").textContent = "0 entries";
    // Do not clear the imagesContainer; leave the skeleton in place.
  } else {
    // There are images: clear the skeleton and load images.
    imagesContainer.innerHTML = ""; // Remove skeleton and any previous images.
    let imagesLoaded = 0;
    playersImages.forEach((playerImage, index) => {
      const imageDiv = document.createElement("div");
      imageDiv.className = `player-image-${index + 1}`;
      const img = document.createElement("img");
      img.classList.add("img-fluid", "overlap-img");
      // Set the image source.
      img.src = `https://resources.premierleague.com/premierleague/photos/players/110x140/p${playerImage.photo}`;
      img.setAttribute("loading", "lazy");
      img.setAttribute("alt", "Player Photo");

      // When the image loads successfully.
      img.onload = function () {
        imagesLoaded++;
        if (imagesLoaded === totalImages) {
          // Optionally, handle when all images have loaded.
        }
      };

      // If the image fails to load, use a fallback.
      img.onerror = function () {
        // Prevent infinite loop in case the fallback image fails.
        this.onerror = null;
        this.src =
          "https://resources.premierleague.com/premierleague/photos/players/110x140/Photo-Missing.png";
        // "https://resources.premierleague.com/premierleague/photos/players/250x250/Photo-Missing.png";
      };

      imageDiv.appendChild(img);
      imagesContainer.appendChild(imageDiv);
    });
  }
};

// Define updateSortIndicator globally.
window.updateSortIndicator = function (sortBy) {
  const headers = document.querySelectorAll("th");
  headers.forEach((header) => {
    header.classList.remove("sorted");
    if (header.dataset.sort === sortBy) {
      header.classList.add("sorted");
      let arrow = header.querySelector("span");
      if (!arrow) {
        arrow = document.createElement("span");
        arrow.textContent = window.currentSortOrder === "asc" ? "↑" : "↓";
        header.appendChild(arrow);
      } else {
        arrow.textContent = window.currentSortOrder === "asc" ? "↑" : "↓";
      }
    } else {
      const arrow = header.querySelector("span");
      if (arrow) {
        header.removeChild(arrow);
      }
    }
  });
};

// Define sortTable globally.
window.sortTable = function (sortBy) {
  if (window.currentSortColumn === sortBy) {
    window.currentSortOrder =
      window.currentSortOrder === "desc" ? "asc" : "desc";
  } else {
    window.currentSortColumn = sortBy;
    window.currentSortOrder = "desc";
  }
  window.updateSortIndicator(sortBy);
  if (typeof fetchData === "function") {
    fetchData(sortBy, window.currentSortOrder);
  } else {
    console.error("fetchData is not defined.");
  }
};

// DOM CONTENT LOADED
document.addEventListener("DOMContentLoaded", function () {
  // Query for each table type you might have.
  const table = document.querySelector(
    "#goals-table, #starts-table, #points-table"
  );
  if (!table) return;

  // Add hover event listener for highlighting cells.
  table.addEventListener("mouseover", function (event) {
    const target = event.target;
    const columnType = target.getAttribute("data-column");
    const sortType = target.getAttribute("data-sort");
    if (columnType && sortType) {
      const row = target.closest("tr");
      if (row) {
        const targetBg = sortType === "primary" ? "#e90052" : "#38003c";
        const matchBg = sortType === "primary" ? "#38003c" : "#e90052";
        target.dataset.originalBg = target.style.backgroundColor || "";
        target.dataset.originalColor = target.style.color || "";
        target.style.backgroundColor = targetBg;
        target.style.color = "#FFF";
        target.style.borderRadius = "3px";
        const matchingCells = row.querySelectorAll(
          `[data-column="${columnType}"]`
        );
        matchingCells.forEach((cell) => {
          if (cell !== target) {
            cell.dataset.originalBg = cell.style.backgroundColor || "";
            cell.dataset.originalColor = cell.style.color || "";
            cell.style.backgroundColor = matchBg;
            cell.style.color = "#FFF";
            cell.style.borderRadius = "3px";
          }
        });
      }
    }
  });

  // Add mouseout event listener to reset cell styles.
  table.addEventListener("mouseout", function (event) {
    const target = event.target;
    const columnType = target.getAttribute("data-column");
    if (columnType) {
      const row = target.closest("tr");
      if (row) {
        target.style.backgroundColor = target.dataset.originalBg || "";
        target.style.color = target.dataset.originalColor || "";
        target.style.borderRadius = "";
        const matchingCells = row.querySelectorAll(
          `[data-column="${columnType}"]`
        );
        matchingCells.forEach((cell) => {
          cell.style.backgroundColor = cell.dataset.originalBg || "";
          cell.style.color = cell.dataset.originalColor || "";
          cell.style.borderRadius = "";
        });
      }
    }
  });

  // Add event listeners for checkboxes.
  const checkboxes = document.querySelectorAll(
    '#checkboxForm input[type="checkbox"]'
  );
  checkboxes.forEach((checkbox) => {
    checkbox.addEventListener("change", function () {
      if (typeof fetchData === "function") {
        fetchData(window.currentSortColumn, window.currentSortOrder);
      }
    });
  });

  // Initialize the slider.
  const priceSlider = document.getElementById("price-slider");
  if (priceSlider) {
    noUiSlider.create(priceSlider, {
      start: [3, 15],
      connect: true,
      range: { min: 3, max: 15 },
      step: 0.1,
      tooltips: true,
      format: wNumb({
        decimals: 1,
        prefix: "£",
      }),
    });

    priceSlider.noUiSlider.on("change", function (values) {
      const minCost = parseFloat(values[0]);
      const maxCost = parseFloat(values[1]);
      window.currentMinCost = minCost;
      window.currentMaxCost = maxCost;
      if (typeof fetchData === "function") {
        fetchData(window.currentSortColumn, window.currentSortOrder);
      }
    });
  }

  window.getSelectedPriceRange = function () {
    const slider = document.getElementById("price-slider");
    if (
      slider &&
      slider.noUiSlider &&
      typeof slider.noUiSlider.get === "function"
    ) {
      const values = slider.noUiSlider.get();
      return {
        minCost: parseFloat(values[0].replace("£", "")),
        maxCost: parseFloat(values[1].replace("£", "")),
      };
    } else {
      return { minCost: 3, maxCost: 15 };
    }
  };

  function addHeaderHoverEffects() {
    document.querySelectorAll("th").forEach((th) => {
      th.addEventListener("mouseenter", function () {
        const sortKey = this.getAttribute("data-sort"); // Get the data-sort value
        const description =
          typeof lookup !== "undefined" && lookup[sortKey]
            ? lookup[sortKey]
            : "No description available."; // Use lookup only if it exists

        const hoverElement = document.getElementById("current-hover");
        if (hoverElement) {
          hoverElement.textContent = description;
          hoverElement.style.backgroundColor = "#EAFF04";
        }
      });

      th.addEventListener("mouseleave", function () {
        const hoverElement = document.getElementById("current-hover");
        if (hoverElement) {
          hoverElement.textContent = "Click table headers to change sort";
          // hoverElement.style.backgroundColor = "yellow";
        }
      });
    });
  }

  // Call the function to activate the hover effects
  addHeaderHoverEffects();

  // Define a global helper function to update the top players text.
  window.updateTopPlayersText = function (entryCount) {
    let topPlayersText;
    const numberWords = { 2: "Two", 3: "Three", 4: "Four" };

    if (entryCount === 0) {
      topPlayersText = "No players to display";
    } else if (entryCount === 1) {
      topPlayersText = "↑ Top Player";
    } else if (entryCount < 5) {
      const countWord = numberWords[entryCount];
      topPlayersText = `↑ Top ${countWord} Players`;
    } else {
      topPlayersText = "↑ Top Five Players";
    }

    const topPlayersElement = document.getElementById("top-players");
    if (topPlayersElement) {
      topPlayersElement.textContent = topPlayersText;
    }
  };
});
