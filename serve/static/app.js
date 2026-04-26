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

const map = L.map("map", { zoomControl: true }).setView([37.768, -122.412], 14);
const markersLayer = L.layerGroup().addTo(map);
const sequencesLayer = L.layerGroup().addTo(map);
const camerasLayer = L.layerGroup().addTo(map);

L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
  attribution: "&copy; OpenStreetMap contributors",
  maxZoom: 19,
}).addTo(map);

let detections = [];
let _followupPollTimer = null;
let _currentDetectionId = null;
let _reviewedIds = new Set();

// ── Live cameras ──────────────────────────────────────
function makeCameraIcon() {
  return L.divIcon({
    className: "",
    html: '<div class="camera-marker"><div class="camera-marker-pulse"></div><div class="camera-marker-dot"></div></div>',
    iconSize: [30, 30],
    iconAnchor: [15, 15],
    popupAnchor: [0, -18],
  });
}

function renderCameras(cameras) {
  camerasLayer.clearLayers();
  cameras.forEach((cam) => {
    if (cam.lat == null || cam.lon == null) return;
    const marker = L.marker([cam.lat, cam.lon], { icon: makeCameraIcon() });
    marker.on("click", () => openCameraPanel(cam));
    marker.bindTooltip(`📹 ${cam.name}`, { direction: "top", offset: [0, -18] });
    camerasLayer.addLayer(marker);
  });
}

function openCameraPanel(cam) {
  document.getElementById("camera-panel-name").textContent = cam.name;

  const iframe = document.getElementById("camera-iframe");
  iframe.src = cam.embed_url || "";

  const tsEl = document.getElementById("camera-analysis-timestamp");
  tsEl.textContent = cam.analyzed_at
    ? `Last analyzed ${new Date(cam.analyzed_at).toLocaleTimeString()}`
    : "Not yet analyzed";

  const bodyEl = document.getElementById("camera-analysis-body");
  if (!cam.analysis) {
    bodyEl.innerHTML = '<div class="empty-state">Analysis pending — first run in progress…</div>';
  } else {
    const a = cam.analysis;
    const lists = (arr) => (Array.isArray(arr) && arr.length ? arr.join(", ") : "none");
    bodyEl.innerHTML = `
      <div class="detail-row">
        <span class="detail-label">Condition</span>
        <span class="camera-condition-badge">${a.condition || "unknown"}</span>
      </div>
      <div class="detail-row">
        <span class="detail-label">Sidewalk</span>
        <span class="detail-value">${a.sidewalk_presence || "—"}</span>
      </div>
      <div class="detail-row">
        <span class="detail-label">Width</span>
        <span class="detail-value">${a.sidewalk_width_m != null ? a.sidewalk_width_m + " m" : "—"}</span>
      </div>
      <div class="detail-row">
        <span class="detail-label">Curb Ramp</span>
        <span class="detail-value">${a.curb_ramp_status || "—"}</span>
      </div>
      <div class="detail-row">
        <span class="detail-label">Hazards</span>
        <span class="detail-value">${lists(a.hazards)}</span>
      </div>
      <div class="detail-row">
        <span class="detail-label">Obstructions</span>
        <span class="detail-value">${lists(a.obstructions)}</span>
      </div>
      <div class="detail-description-block">
        <span class="detail-label">Description</span>
        <p class="detail-description">${a.description || ""}</p>
      </div>
    `;
  }

  document.getElementById("camera-panel").classList.remove("hidden");
  switchTab("live");
}

function closeCameraPanel() {
  document.getElementById("camera-panel").classList.add("hidden");
  document.getElementById("camera-iframe").src = "";
}

document.getElementById("camera-panel-close").addEventListener("click", closeCameraPanel);

async function fetchAndRenderCameras() {
  try {
    const resp = await fetch("/api/cameras");
    if (!resp.ok) return;
    const data = await resp.json();
    renderCameras(data.cameras || []);
  } catch (_) {
    // silently skip on network blip
  }
}

function startCameraPolling() {
  fetchAndRenderCameras();
  setInterval(fetchAndRenderCameras, 30_000);
}

// ── Tabs ──────────────────────────────────────────────
document.querySelectorAll(".tab-btn").forEach((btn) => {
  btn.addEventListener("click", () => switchTab(btn.dataset.tab));
});

function switchTab(tabName) {
  document.querySelectorAll(".tab-btn").forEach((b) => b.classList.remove("active"));
  document.querySelectorAll(".tab-content").forEach((c) => c.classList.add("hidden"));
  document.querySelector(`.tab-btn[data-tab="${tabName}"]`).classList.add("active");
  document.getElementById(`tab-${tabName}`).classList.remove("hidden");
  queueTabPlotResize(tabName);
}

function queueTabPlotResize(tabName) {
  const tab = document.getElementById(`tab-${tabName}`);
  if (!tab || typeof Plotly === "undefined") {
    return;
  }

  const resizePlots = () => {
    tab.querySelectorAll(".js-plotly-plot").forEach((plot) => Plotly.Plots.resize(plot));
  };

  requestAnimationFrame(() => {
    resizePlots();
    window.setTimeout(resizePlots, 60);
  });
}

// ── Human review ──────────────────────────────────────
async function loadReviews() {
  try {
    const resp = await fetch("/api/reviews");
    const data = await resp.json();
    _reviewedIds = new Set(Object.keys(data.reviews || {}));
  } catch (e) {
    _reviewedIds = new Set();
  }
}

function _resetReviewUI() {
  document.getElementById("review-badge").classList.add("hidden");
  document.getElementById("review-existing").classList.add("hidden");
  document.getElementById("review-existing").innerHTML = "";
  document.getElementById("review-form").style.display = "";
  document.getElementById("review-status").value = "confirmed";
  document.getElementById("review-type").value = "";
  document.getElementById("review-condition").value = "";
  document.getElementById("review-notes").value = "";
  document.getElementById("review-clear-btn").classList.add("hidden");
}

function _loadExistingReview(detectionId) {
  if (!detectionId) return;
  fetch(`/api/events/${encodeURIComponent(detectionId)}/review`)
    .then(r => r.ok ? r.json() : null)
    .then(review => { if (review) _renderReview(review); })
    .catch(() => {});
}

function _renderReview(review) {
  document.getElementById("review-badge").classList.remove("hidden");
  document.getElementById("review-clear-btn").classList.remove("hidden");
  document.getElementById("review-status").value = review.review_status || "confirmed";
  document.getElementById("review-type").value = review.override_type || "";
  document.getElementById("review-condition").value = review.override_condition || "";
  document.getElementById("review-notes").value = review.notes || "";
  const el = document.getElementById("review-existing");
  el.innerHTML = `<div class="review-summary">
    <span class="review-status-badge review-status-${review.review_status}">${review.review_status}</span>
    <span class="muted">${new Date(review.reviewed_at).toLocaleString()}</span>
    ${review.notes ? `<p class="review-note">${review.notes}</p>` : ""}
  </div>`;
  el.classList.remove("hidden");
}

function _wireReviewButtons(detectionId) {
  ["review-submit-btn", "review-clear-btn"].forEach(id => {
    const el = document.getElementById(id);
    const clone = el.cloneNode(true);
    el.parentNode.replaceChild(clone, el);
  });

  document.getElementById("review-submit-btn").addEventListener("click", () => {
    if (detectionId !== _currentDetectionId) return;
    const payload = {
      review_status: document.getElementById("review-status").value,
      override_type: document.getElementById("review-type").value || null,
      override_condition: document.getElementById("review-condition").value || null,
      notes: document.getElementById("review-notes").value || null,
    };
    fetch(`/api/events/${encodeURIComponent(detectionId)}/review`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    })
      .then(r => r.json())
      .then(async () => {
        await loadReviews();
        renderDetections();
        _loadExistingReview(detectionId);
      })
      .catch(err => console.error("Review save failed:", err));
  });

  document.getElementById("review-clear-btn").addEventListener("click", () => {
    if (detectionId !== _currentDetectionId) return;
    fetch(`/api/events/${encodeURIComponent(detectionId)}/review`, { method: "DELETE" })
      .then(async () => {
        await loadReviews();
        renderDetections();
        _resetReviewUI();
        _wireReviewButtons(detectionId);
      })
      .catch(err => console.error("Review delete failed:", err));
  });
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
  await loadReviews();
  renderFilters(detectionCollection.metadata?.detection_types || []);
  renderStatus(detectionCollection, metrics, sequenceCollection, comparison);
  renderSequences(sequenceCollection.features || []);
  renderDetections();
  renderMetrics(metrics);
  renderComparison(comparison);
  queueTabPlotResize("detail");
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

      const detId = feature.properties.detection_id || feature.properties.obs_id;
      const isReviewed = _reviewedIds.has(detId);
      const marker = L.circleMarker([lat, lon], {
        radius: 7,
        color: isReviewed ? "#fff" : (palette[feature.properties.detection_type] || "#334155"),
        weight: isReviewed ? 4 : 2,
        fillColor: palette[feature.properties.detection_type] || "#334155",
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

  // ── Follow-up block ──────────────────────────────────
  // Use detection_id if present; fall back to obs_id so the button always works
  // even with geojson generated before detection_id was added to export.py.
  _currentDetectionId = p.detection_id || p.obs_id || null;
  _resetFollowupUI();
  _loadExistingFollowup(_currentDetectionId);
  _wireUploadButton(_currentDetectionId);
  _resetReviewUI();
  _loadExistingReview(_currentDetectionId);
  _wireReviewButtons(_currentDetectionId);
}

function _resetFollowupUI() {
  if (_followupPollTimer) {
    clearInterval(_followupPollTimer);
    _followupPollTimer = null;
  }
  document.getElementById("followup-existing").classList.add("hidden");
  document.getElementById("followup-existing").innerHTML = "";
  document.getElementById("followup-upload-area").style.display = "";
  document.getElementById("followup-status").classList.add("hidden");
  document.getElementById("followup-status").textContent = "";
  document.getElementById("followup-video").style.display = "none";
  document.getElementById("followup-video").src = "";
  document.getElementById("followup-results").classList.add("hidden");
  document.getElementById("followup-results").innerHTML = "";
  document.getElementById("followup-badge").classList.add("hidden");
  document.getElementById("followup-file-input").value = "";
}

function _loadExistingFollowup(detectionId) {
  if (!detectionId) return;
  fetch(`/api/events/${encodeURIComponent(detectionId)}/followup`)
    .then((r) => r.json())
    .then((data) => {
      if (data.status === "done" && data.result) {
        _renderFollowupResult(data.result);
      }
    })
    .catch(() => {});
}

function _wireUploadButton(detectionId) {
  if (!detectionId) return;
  const btn = document.getElementById("followup-upload-btn");
  const input = document.getElementById("followup-file-input");

  const newBtn = btn.cloneNode(true);
  btn.parentNode.replaceChild(newBtn, btn);
  const newInput = input.cloneNode(true);
  input.parentNode.replaceChild(newInput, input);

  newBtn.addEventListener("click", () => newInput.click());
  newInput.addEventListener("change", () => {
    const file = newInput.files[0];
    if (!file || detectionId !== _currentDetectionId) return;
    _startFollowupUpload(detectionId, file);
  });
}

function _startFollowupUpload(detectionId, file) {
  const statusEl = document.getElementById("followup-status");
  statusEl.textContent = "Uploading…";
  statusEl.classList.remove("hidden");
  document.getElementById("followup-upload-area").style.display = "none";

  const formData = new FormData();
  formData.append("file", file);

  fetch(`/api/events/${encodeURIComponent(detectionId)}/followup-video`, {
    method: "POST",
    body: formData,
  })
    .then((r) => r.json())
    .then(({ job_id }) => {
      _pollFollowupJob(detectionId, job_id);
    })
    .catch((err) => {
      statusEl.textContent = `Upload failed: ${err.message}`;
      document.getElementById("followup-upload-area").style.display = "";
    });
}

const STATUS_LABELS = {
  queued: "Queued…",
  uploading: "Uploading to S3…",
  embedding: "Running Marengo (embedding)…",
  describing: "Running Pegasus (describing)…",
  done: "Done",
  error: "Error",
};

function _pollFollowupJob(detectionId, jobId) {
  const statusEl = document.getElementById("followup-status");

  _followupPollTimer = setInterval(() => {
    if (detectionId !== _currentDetectionId) {
      clearInterval(_followupPollTimer);
      return;
    }
    fetch(`/api/events/${encodeURIComponent(detectionId)}/followup?job_id=${encodeURIComponent(jobId)}`)
      .then((r) => r.json())
      .then((job) => {
        statusEl.textContent = STATUS_LABELS[job.status] || job.status;
        if (job.status === "done") {
          clearInterval(_followupPollTimer);
          statusEl.classList.add("hidden");
          _renderFollowupResult(job.result);
        } else if (job.status === "error") {
          clearInterval(_followupPollTimer);
          statusEl.textContent = `Error: ${job.error || "unknown"}`;
          document.getElementById("followup-upload-area").style.display = "";
        }
      })
      .catch(() => {});
  }, 2000);
}

function _renderFollowupResult(result) {
  document.getElementById("followup-badge").classList.remove("hidden");
  document.getElementById("followup-upload-area").style.display = "none";

  const pegasus = result.pegasus || {};

  const lists = (arr) =>
    Array.isArray(arr) && arr.length ? arr.join(", ") : "none";

  const resultsEl = document.getElementById("followup-results");
  resultsEl.innerHTML = `
    <div class="followup-grid">
      <div class="detail-row"><span class="detail-label">Condition</span><span class="detail-value">${pegasus.condition || "—"}</span></div>
      <div class="detail-row"><span class="detail-label">Sidewalk</span><span class="detail-value">${pegasus.sidewalk_presence || "—"}</span></div>
      <div class="detail-row"><span class="detail-label">Width (m)</span><span class="detail-value">${pegasus.sidewalk_width_m ?? "n/a"}</span></div>
      <div class="detail-row"><span class="detail-label">Curb Ramp</span><span class="detail-value">${pegasus.curb_ramp_status || "—"}</span></div>
      <div class="detail-row"><span class="detail-label">Obstructions</span><span class="detail-value">${lists(pegasus.obstructions)}</span></div>
      <div class="detail-row"><span class="detail-label">Hazards</span><span class="detail-value">${lists(pegasus.hazards)}</span></div>
    </div>
    ${pegasus.description ? `<p class="followup-desc">${pegasus.description}</p>` : ""}
    <div class="followup-actions">
      <button id="followup-similar-btn" class="followup-btn followup-btn-secondary">Find similar locations</button>
      <button id="followup-delete-btn" class="followup-btn followup-btn-danger">Delete &amp; re-upload</button>
    </div>
    <div id="followup-similar-results" class="hidden"></div>
  `;
  resultsEl.classList.remove("hidden");

  if (result.clip_s3_uri) {
    fetch(`/api/clip-url?uri=${encodeURIComponent(result.clip_s3_uri)}`)
      .then((r) => r.json())
      .then(({ url }) => {
        const vid = document.getElementById("followup-video");
        vid.src = url;
        vid.style.display = "block";
      })
      .catch(() => {});
  }

  document.getElementById("followup-similar-btn").addEventListener("click", () => {
    _loadSimilar(_currentDetectionId);
  });

  document.getElementById("followup-delete-btn").addEventListener("click", () => {
    const detectionId = _currentDetectionId;
    if (!detectionId) return;
    fetch(`/api/events/${encodeURIComponent(detectionId)}/followup`, { method: "DELETE" })
      .then((r) => r.json())
      .then(() => {
        _resetFollowupUI();
        _wireUploadButton(detectionId);
      })
      .catch((err) => console.error("Delete failed:", err));
  });
}

function _loadSimilar(detectionId) {
  const btn = document.getElementById("followup-similar-btn");
  if (btn) btn.disabled = true;
  const container = document.getElementById("followup-similar-results");
  container.innerHTML = "Searching…";
  container.classList.remove("hidden");

  fetch(`/api/events/${encodeURIComponent(detectionId)}/similar?k=5`)
    .then((r) => r.json())
    .then(({ hits }) => {
      if (!hits || !hits.length) {
        container.innerHTML = "<span class='muted'>No similar locations found.</span>";
        return;
      }
      container.innerHTML = hits
        .map(
          (h) =>
            `<div class="similar-hit">
              <span class="detail-label">${h.sequence_id || "—"}</span>
              <span class="muted">${h.lat != null ? `${h.lat.toFixed(5)}, ${h.lon != null ? h.lon.toFixed(5) : ""}` : ""}</span>
              <span class="similar-score">score ${(h.score || 0).toFixed(3)}</span>
            </div>`
        )
        .join("");
    })
    .catch((err) => {
      container.innerHTML = `<span class='muted'>Error: ${err.message}</span>`;
    });
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
      autosize: true,
      margin: { l: 36, r: 8, t: 28, b: 56 },
      title: { text: "Detection Counts", font: { size: 13, family: "Space Grotesk, Avenir Next, sans-serif" } },
      paper_bgcolor: "rgba(0,0,0,0)",
      plot_bgcolor: "rgba(0,0,0,0)",
      xaxis: { tickfont: { size: 10 }, tickangle: -28, automargin: true },
      yaxis: { gridcolor: "rgba(0,0,0,0.06)", automargin: true },
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
      autosize: true,
      margin: { l: 36, r: 8, t: 28, b: 72 },
      title: { text: "Quality Metrics", font: { size: 13, family: "Space Grotesk, Avenir Next, sans-serif" } },
      paper_bgcolor: "rgba(0,0,0,0)",
      plot_bgcolor: "rgba(0,0,0,0)",
      xaxis: { automargin: true },
      yaxis: { range: [0, 1], gridcolor: "rgba(0,0,0,0.06)", automargin: true },
      legend: {
        orientation: "h",
        x: 0,
        xanchor: "left",
        y: -0.24,
        yanchor: "top",
        font: { size: 9 },
      },
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
      autosize: true,
      margin: { l: 36, r: 8, t: 28, b: 56 },
      title: { text: "Video vs Baseline", font: { size: 13, family: "Space Grotesk, Avenir Next, sans-serif" } },
      paper_bgcolor: "rgba(0,0,0,0)",
      plot_bgcolor: "rgba(0,0,0,0)",
      xaxis: { tickfont: { size: 10 }, tickangle: -28, automargin: true },
      yaxis: { gridcolor: "rgba(0,0,0,0.06)", automargin: true },
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

startCameraPolling();
