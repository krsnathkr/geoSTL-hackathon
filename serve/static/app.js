const palette = {
  sidewalk_present: "#2f855a",
  sidewalk_missing: "#d94841",
  sidewalk_unclear: "#718096",
  curb_ramp_missing: "#ff8f00",
  obstruction: "#c05621",
  pothole: "#805ad5",
  construction: "#dd6b20",
  poor_condition: "#b7791f",
  blocked_path: "#9b2c2c",
  hazard: "#6b46c1",
  surface_hazard: "#8b5cf6",
};

const map = L.map("map", { zoomControl: true }).setView([40.005, -105.265], 14);
const markersLayer = L.layerGroup().addTo(map);
const sequencesLayer = L.layerGroup().addTo(map);

L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
  attribution: "&copy; OpenStreetMap contributors",
  maxZoom: 19,
}).addTo(map);

let detections = [];

// ── Tabs ──────────────────────────────────────────────
document.querySelectorAll(".tab-btn").forEach((btn) => {
  btn.addEventListener("click", () => switchTab(btn.dataset.tab));
});

function switchTab(tabName) {
  document.querySelectorAll(".tab-btn").forEach((b) => b.classList.remove("active"));
  document.querySelectorAll(".tab-content").forEach((c) => c.classList.add("hidden"));
  document.querySelector(`.tab-btn[data-tab="${tabName}"]`).classList.add("active");
  document.getElementById(`tab-${tabName}`).classList.remove("hidden");
}

// ── Data loading ──────────────────────────────────────
async function loadData() {
  const [detectionsResponse, metricsResponse, sequencesResponse, comparisonResponse] = await Promise.all([
    fetch("/api/detections"),
    fetch("/api/metrics"),
    fetch("/api/sequences"),
    fetch("/api/comparison"),
  ]);

  const detectionCollection = await detectionsResponse.json();
  const metrics = await metricsResponse.json();
  const sequenceCollection = await sequencesResponse.json();
  const comparison = await comparisonResponse.json();

  detections = detectionCollection.features || [];
  renderFilters(detectionCollection.metadata?.detection_types || []);
  renderStatus(detectionCollection, metrics, sequenceCollection, comparison);
  renderSequences(sequenceCollection.features || []);
  renderDetections();
  renderMetrics(metrics);
  renderComparison(comparison);
}

function renderFilters(types) {
  const list = document.getElementById("filters-list");
  const orderedTypes = (types.length ? types : [...new Set(detections.map((f) => f.properties.detection_type))]).sort();
  list.innerHTML = orderedTypes
    .map(
      (type) =>
        `<label style="--dot:${palette[type] || "#64748b"}">
          <input type="checkbox" value="${type}" checked />
          ${type.replaceAll("_", " ")}
        </label>`
    )
    .join("");
  list.querySelectorAll('input[type="checkbox"]').forEach((input) => {
    input.addEventListener("change", renderDetections);
  });
}

function renderStatus(detectionCollection, metrics, sequenceCollection, comparison) {
  const pill = document.getElementById("status-pill");
  const ready = [
    detectionCollection.metadata?.status,
    metrics.status,
    sequenceCollection.metadata?.status,
    comparison.status,
  ].filter((value) => value === "ready").length;
  pill.textContent = `${ready}/4 ready`;
}

// ── Sequences: break polylines where consecutive points jump far ──
function haversineM(lat1, lon1, lat2, lon2) {
  const R = 6371000;
  const toRad = (d) => (d * Math.PI) / 180;
  const dLat = toRad(lat2 - lat1);
  const dLon = toRad(lon2 - lon1);
  const a =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.sin(dLon / 2) ** 2;
  return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
}

function renderSequences(features) {
  sequencesLayer.clearLayers();
  const MAX_GAP_M = 150;
  features.forEach((feature) => {
    const coords = feature.geometry.coordinates.map(([lon, lat]) => [lat, lon]);
    let segment = [];
    for (let i = 0; i < coords.length; i++) {
      if (segment.length > 0) {
        const [pLat, pLon] = segment[segment.length - 1];
        const [cLat, cLon] = coords[i];
        if (haversineM(pLat, pLon, cLat, cLon) > MAX_GAP_M) {
          if (segment.length > 1) {
            L.polyline(segment, { color: "#1f6f5f", weight: 3, opacity: 0.55 }).addTo(sequencesLayer);
          }
          segment = [];
        }
      }
      segment.push(coords[i]);
    }
    if (segment.length > 1) {
      L.polyline(segment, { color: "#1f6f5f", weight: 3, opacity: 0.55 }).addTo(sequencesLayer);
    }
  });
}

function selectedTypes() {
  return new Set(
    [...document.querySelectorAll('input[type="checkbox"]:checked')].map((input) => input.value)
  );
}

function renderDetections() {
  markersLayer.clearLayers();
  const visibleTypes = selectedTypes();
  const bounds = [];

  detections
    .filter((feature) => visibleTypes.has(feature.properties.detection_type))
    .forEach((feature) => {
      const [lon, lat] = feature.geometry.coordinates;
      bounds.push([lat, lon]);

      const marker = L.circleMarker([lat, lon], {
        radius: 7,
        color: palette[feature.properties.detection_type] || "#334155",
        weight: 2,
        fillOpacity: 0.85,
      });

      marker.on("click", () => showDetail(feature));
      marker.bindTooltip(
        `${feature.properties.obs_name || "Unnamed"} (${feature.properties.detection_type})`
      );
      marker.addTo(markersLayer);
    });

  if (bounds.length) {
    map.fitBounds(bounds, { padding: [28, 28] });
  }
}

// ── Detail panel ──────────────────────────────────────
function showDetail(feature) {
  switchTab("detail");
  document.getElementById("detail-empty").classList.add("hidden");
  document.getElementById("detail-card").classList.remove("hidden");

  const p = feature.properties;
  document.getElementById("detail-name").textContent = p.obs_name || "Unknown";

  const badge = document.getElementById("detail-type-badge");
  badge.textContent = (p.detection_type || "").replaceAll("_", " ");
  const color = palette[p.detection_type] || "#64748b";
  badge.style.background = color + "1a";
  badge.style.color = color;

  document.getElementById("detail-condition").textContent = p.obs_condition || "—";
  document.getElementById("detail-confidence").textContent =
    p.confidence != null ? `${(p.confidence * 100).toFixed(0)}%` : "—";
  document.getElementById("detail-presence").textContent = p.sidewalk_presence || "—";
  document.getElementById("detail-width").textContent = p.sidewalk_width_m != null ? p.sidewalk_width_m : "n/a";
  document.getElementById("detail-curb-ramp").textContent = p.curb_ramp_status || "—";
  document.getElementById("detail-obstructions").textContent = p.obstructions || "none";
  document.getElementById("detail-hazards").textContent = p.hazards || "none";
  document.getElementById("detail-crossings").textContent = p.crossing_features || "none";
  document.getElementById("detail-transport").textContent =
    p.transport_name || p.transport_id || "No match";

  document.getElementById("detail-description").textContent = p.obs_description || "";

  const clipUri = p.clip_s3_uri || "";
  const clipNode = document.getElementById("detail-clip");
  const videoNode = document.getElementById("detail-video");
  clipNode.textContent = "";
  videoNode.style.display = "none";
  videoNode.src = "";

  if (clipUri) {
    fetch(`/api/clip-url?uri=${encodeURIComponent(clipUri)}`)
      .then((r) => r.json())
      .then(({ url }) => {
        videoNode.src = url;
        videoNode.style.display = "block";
      })
      .catch(() => {
        clipNode.textContent = clipUri;
      });
  } else {
    clipNode.textContent = "No clip available";
  }
}

// ── Metrics ──────────────────────────────────────────
function renderMetrics(metrics) {
  document.getElementById("metrics-summary").innerHTML = `
    <div class="stat-card">
      <div class="stat-label">Total Detections</div>
      <div class="stat-value">${metrics.total_detections ?? 0}</div>
    </div>
    <div class="stat-card">
      <div class="stat-label">Discrepancies</div>
      <div class="stat-value">${metrics.discrepancy_count ?? 0}</div>
    </div>
    <div class="stat-card">
      <div class="stat-label">FP / km²</div>
      <div class="stat-value">${metrics.fp_per_km2 ?? "—"}</div>
    </div>
    <div class="stat-card">
      <div class="stat-label">RMSE (m)</div>
      <div class="stat-value">${metrics.rmse_m ?? "—"}</div>
    </div>
  `;

  const typeCounts = metrics.type_counts || {};
  const qualityTypes = Object.keys(metrics).filter(
    (key) => metrics[key] && typeof metrics[key] === "object" && "precision" in metrics[key]
  );

  Plotly.newPlot(
    "counts-chart",
    [
      {
        type: "bar",
        x: Object.keys(typeCounts).map((k) => k.replaceAll("_", " ")),
        y: Object.values(typeCounts),
        marker: { color: Object.keys(typeCounts).map((key) => palette[key] || "#64748b") },
      },
    ],
    {
      margin: { l: 36, r: 8, t: 28, b: 60 },
      title: { text: "Detection Counts", font: { size: 13, family: "Space Grotesk, Avenir Next, sans-serif" } },
      paper_bgcolor: "rgba(0,0,0,0)",
      plot_bgcolor: "rgba(0,0,0,0)",
      xaxis: { tickfont: { size: 10 }, tickangle: -35 },
      yaxis: { gridcolor: "rgba(0,0,0,0.06)" },
    },
    { displayModeBar: false, responsive: true }
  );

  Plotly.newPlot(
    "quality-chart",
    qualityTypes.map((type) => ({
      type: "bar",
      name: type.replaceAll("_", " "),
      x: ["precision", "recall", "f1"],
      y: ["precision", "recall", "f1"].map((m) => metrics[type]?.[m] ?? 0),
      marker: { color: palette[type] },
    })),
    {
      barmode: "group",
      margin: { l: 36, r: 8, t: 28, b: 36 },
      title: { text: "Quality Metrics", font: { size: 13, family: "Space Grotesk, Avenir Next, sans-serif" } },
      paper_bgcolor: "rgba(0,0,0,0)",
      plot_bgcolor: "rgba(0,0,0,0)",
      yaxis: { range: [0, 1], gridcolor: "rgba(0,0,0,0.06)" },
      legend: { font: { size: 10 } },
    },
    { displayModeBar: false, responsive: true }
  );
}

// ── Comparison ────────────────────────────────────────
function renderComparison(comparison) {
  document.getElementById("comparison-summary").innerHTML = `
    <div class="stat-card">
      <div class="stat-label">Video</div>
      <div class="stat-value">${comparison.video_discrepancies ?? 0}</div>
    </div>
    <div class="stat-card">
      <div class="stat-label">Baseline</div>
      <div class="stat-value">${comparison.baseline_discrepancies ?? 0}</div>
    </div>
    <div class="stat-card">
      <div class="stat-label">Delta</div>
      <div class="stat-value">${comparison.delta ?? 0}</div>
    </div>
    <div class="stat-card">
      <div class="stat-label">Conf. Delta</div>
      <div class="stat-value">${comparison.confidence_delta ?? "—"}</div>
    </div>
  `;

  const rows = comparison.by_type || [];
  Plotly.newPlot(
    "comparison-chart",
    [
      {
        type: "bar",
        name: "Video",
        x: rows.map((r) => r.detection_type.replaceAll("_", " ")),
        y: rows.map((r) => r.video_count),
        marker: { color: "#1f6f5f" },
      },
      {
        type: "bar",
        name: "Baseline",
        x: rows.map((r) => r.detection_type.replaceAll("_", " ")),
        y: rows.map((r) => r.baseline_count),
        marker: { color: "#94a3b8" },
      },
    ],
    {
      barmode: "group",
      margin: { l: 36, r: 8, t: 28, b: 60 },
      title: { text: "Video vs Baseline", font: { size: 13, family: "Space Grotesk, Avenir Next, sans-serif" } },
      paper_bgcolor: "rgba(0,0,0,0)",
      plot_bgcolor: "rgba(0,0,0,0)",
      xaxis: { tickfont: { size: 10 }, tickangle: -35 },
      yaxis: { gridcolor: "rgba(0,0,0,0.06)" },
      legend: { font: { size: 11 } },
    },
    { displayModeBar: false, responsive: true }
  );

  const table = document.getElementById("comparison-table");
  if (!rows.length) {
    table.innerHTML = '<div class="empty-state">No comparison data available.</div>';
    return;
  }

  table.innerHTML = `
    <div class="comparison-row header">
      <div>Type</div><div>Video</div><div>Base</div><div>Delta</div>
    </div>
    ${rows
      .map(
        (row) => `
        <div class="comparison-row">
          <div>${row.detection_type.replaceAll("_", " ")}</div>
          <div>${row.video_count}</div>
          <div>${row.baseline_count}</div>
          <div>${row.delta}</div>
        </div>`
      )
      .join("")}
  `;
}

loadData().catch((error) => {
  document.getElementById("status-pill").textContent = "Error";
  console.error(error);
});
