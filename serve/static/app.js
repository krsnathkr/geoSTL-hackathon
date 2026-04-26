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
        `<label><input type="checkbox" value="${type}" checked /> ${type.replaceAll("_", " ")}</label>`
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

function renderSequences(features) {
  sequencesLayer.clearLayers();
  features.forEach((feature) => {
    const coordinates = feature.geometry.coordinates.map(([lon, lat]) => [lat, lon]);
    L.polyline(coordinates, {
      color: "#1f6f5f",
      weight: 3,
      opacity: 0.35,
    }).addTo(sequencesLayer);
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
        fillOpacity: 0.8,
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

function showDetail(feature) {
  document.getElementById("detail-empty").classList.add("hidden");
  document.getElementById("detail-card").classList.remove("hidden");
  document.getElementById("detail-name").textContent = feature.properties.obs_name || "Unknown";
  document.getElementById("detail-type").textContent = feature.properties.detection_type || "";
  document.getElementById("detail-condition").textContent = feature.properties.obs_condition || "";
  document.getElementById("detail-confidence").textContent = feature.properties.confidence ?? "";
  document.getElementById("detail-presence").textContent =
    feature.properties.sidewalk_presence || "";
  document.getElementById("detail-width").textContent =
    feature.properties.sidewalk_width_m ?? "n/a";
  document.getElementById("detail-curb-ramp").textContent =
    feature.properties.curb_ramp_status || "";
  document.getElementById("detail-obstructions").textContent =
    feature.properties.obstructions || "[]";
  document.getElementById("detail-hazards").textContent =
    feature.properties.hazards || "[]";
  document.getElementById("detail-crossings").textContent =
    feature.properties.crossing_features || "[]";
  document.getElementById("detail-transport").textContent =
    feature.properties.transport_name || feature.properties.transport_id || "No matched transport segment";
  document.getElementById("detail-description").textContent =
    feature.properties.obs_description || "";

  const clipUri = feature.properties.clip_s3_uri || "";
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
    clipNode.textContent = "No clip";
  }
}

function renderMetrics(metrics) {
  document.getElementById("metrics-summary").innerHTML = `
    <div>Total detections: ${metrics.total_detections ?? 0}</div>
    <div>Discrepancies: ${metrics.discrepancy_count ?? 0}</div>
    <div>FP/km²: ${metrics.fp_per_km2 ?? "n/a"}</div>
    <div>RMSE (m): ${metrics.rmse_m ?? "n/a"}</div>
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
        x: Object.keys(typeCounts),
        y: Object.values(typeCounts),
        marker: { color: Object.keys(typeCounts).map((key) => palette[key] || "#64748b") },
      },
    ],
    {
      margin: { l: 36, r: 12, t: 24, b: 36 },
      title: { text: "Detection Counts", font: { size: 16 } },
      paper_bgcolor: "rgba(0,0,0,0)",
      plot_bgcolor: "rgba(0,0,0,0)",
    },
    { displayModeBar: false, responsive: true }
  );

  Plotly.newPlot(
    "quality-chart",
    qualityTypes.map((type) => ({
      type: "bar",
      name: type,
      x: ["precision", "recall", "f1"],
      y: ["precision", "recall", "f1"].map((metric) => metrics[type]?.[metric] ?? 0),
      marker: { color: palette[type] },
    })),
    {
      barmode: "group",
      margin: { l: 36, r: 12, t: 24, b: 36 },
      title: { text: "Quality Metrics", font: { size: 16 } },
      paper_bgcolor: "rgba(0,0,0,0)",
      plot_bgcolor: "rgba(0,0,0,0)",
      yaxis: { range: [0, 1] },
    },
    { displayModeBar: false, responsive: true }
  );
}

function renderComparison(comparison) {
  document.getElementById("comparison-summary").innerHTML = `
    <div>Video discrepancies: ${comparison.video_discrepancies ?? 0}</div>
    <div>Baseline discrepancies: ${comparison.baseline_discrepancies ?? 0}</div>
    <div>Delta: ${comparison.delta ?? 0}</div>
    <div>Confidence delta: ${comparison.confidence_delta ?? "n/a"}</div>
  `;

  const rows = comparison.by_type || [];
  Plotly.newPlot(
    "comparison-chart",
    [
      {
        type: "bar",
        name: "Video",
        x: rows.map((row) => row.detection_type),
        y: rows.map((row) => row.video_count),
        marker: { color: "#1f6f5f" },
      },
      {
        type: "bar",
        name: "Baseline",
        x: rows.map((row) => row.detection_type),
        y: rows.map((row) => row.baseline_count),
        marker: { color: "#94a3b8" },
      },
    ],
    {
      barmode: "group",
      margin: { l: 36, r: 12, t: 24, b: 36 },
      title: { text: "Video vs Baseline", font: { size: 16 } },
      paper_bgcolor: "rgba(0,0,0,0)",
      plot_bgcolor: "rgba(0,0,0,0)",
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
      <div>Type</div>
      <div>Video</div>
      <div>Base</div>
      <div>Delta</div>
    </div>
    ${rows
      .map(
        (row) => `
          <div class="comparison-row">
            <div>${row.detection_type}</div>
            <div>${row.video_count}</div>
            <div>${row.baseline_count}</div>
            <div>${row.delta}</div>
          </div>
        `
      )
      .join("")}
  `;
}

document.querySelectorAll('input[type="checkbox"]').forEach((input) => {
  input.addEventListener("change", renderDetections);
});

loadData().catch((error) => {
  document.getElementById("status-pill").textContent = "Error";
  document.getElementById("metrics-summary").textContent = error.message;
});
