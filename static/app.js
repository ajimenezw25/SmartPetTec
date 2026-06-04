/**
 * SmartPetHome — Frontend JavaScript
 * ===================================
 * Plain vanilla JS. No frameworks, no build tools.
 * Uses fetch() to call Flask /api/* endpoints.
 *
 * Module pattern: window.SPH = { ... }
 * Each page init function is called from the HTML template
 * using data-page attributes on <body>.
 */

(function () {
  "use strict";

  // ── Generic API fetch wrapper ─────────────────────────────

  async function api(method, url, body) {
    const opts = {
      method: method,
      headers: { "Content-Type": "application/json", "X-Requested-With": "XMLHttpRequest" },
      credentials: "same-origin",
    };
    if (body !== undefined) opts.body = JSON.stringify(body);
    try {
      const resp = await fetch(url, opts);
      const json = await resp.json();
      return json;
    } catch (e) {
      return { ok: false, error: String(e) };
    }
  }

  // ── Toast notifications ───────────────────────────────────

  function showToast(message, type) {
    type = type || "info"; // info | success | error | warning
    const container = document.getElementById("toast-container");
    if (!container) return;
    const toast = document.createElement("div");
    toast.className = "toast toast-" + type;
    toast.textContent = message;
    container.appendChild(toast);
    setTimeout(() => toast.classList.add("toast-visible"), 10);
    setTimeout(() => {
      toast.classList.remove("toast-visible");
      setTimeout(() => toast.remove(), 400);
    }, 4000);
  }

  // ── MQTT status indicator ────────────────────────────────

  async function updateMqttStatus() {
    const el = document.getElementById("mqtt-status");
    if (!el) return;
    const res = await api("GET", "/api/mqtt/status");
    if (res.ok) {
      el.textContent = res.data.connected ? "● MQTT" : "○ MQTT";
      el.className   = "mqtt-indicator " + (res.data.connected ? "mqtt-on" : "mqtt-off");
      el.title       = res.data.connected
        ? "Connected to " + res.data.host
        : "MQTT not connected";
    }
  }

  // ── Dashboard ─────────────────────────────────────────────

  function _dashboardError(message) {
    ["device-status-list", "recent-alerts-list", "recent-feedings-list"].forEach(id => {
      const el = document.getElementById(id);
      if (el && el.textContent.trim() === "Loading…" || (el && el.innerHTML.includes("Loading"))) {
        el.innerHTML = `<p class="text-muted">${message}</p>`;
      }
    });
  }

  async function loadDashboardSummary() {
    const res = await api("GET", "/api/dashboard/summary");
    if (!res.ok) {
      _dashboardError("Could not load dashboard data.");
      return;
    }
    const d = res.data;

    setText("stat-pets",    d.total_pets);
    setText("stat-devices", d.total_devices);
    setText("stat-alerts",  d.total_alerts);

    // Device status list
    renderDeviceStatusList(d.device_statuses || []);

    // Recent alerts
    renderRecentAlerts(d.recent_alerts || []);

    // Recent feedings
    renderRecentFeedings(d.recent_feedings || []);

    // MQTT
    const mqttEl = document.getElementById("dashboard-mqtt");
    if (mqttEl) {
      mqttEl.textContent = d.mqtt_connected ? "✓ Connected" : "✗ Not connected";
      mqttEl.className   = d.mqtt_connected ? "badge badge-green" : "badge badge-gray";
    }
  }

  function setText(id, val) {
    const el = document.getElementById(id);
    if (el) el.textContent = val;
  }

  function renderDeviceStatusList(devices) {
    const el = document.getElementById("device-status-list");
    if (!el) return;
    if (!devices.length) {
      el.innerHTML = '<div class="empty-state"><p>No devices registered.</p></div>';
      return;
    }
    el.innerHTML = devices.map(d => {
      const statusClass = d.status === "online" ? "badge-green" : "badge-gray";
      return `<div class="status-row">
        <span class="status-name">${esc(d.device_name)}</span>
        <span class="badge ${statusClass}">${esc(d.status)}</span>
        <span class="status-type">${esc((d.device_types || {}).name || "")}</span>
        <span class="status-time">${d.last_seen_at ? formatDate(d.last_seen_at) : "—"}</span>
      </div>`;
    }).join("");
  }

  function renderRecentAlerts(alerts) {
    const el = document.getElementById("recent-alerts-list");
    if (!el) return;
    if (!alerts.length) {
      el.innerHTML = '<p class="text-muted">✅ No unresolved alerts.</p>';
      return;
    }
    el.innerHTML = alerts.map(a => {
      const sev = a.severity === "critical" ? "badge-red" : a.severity === "warning" ? "badge-yellow" : "badge-info";
      return `<div class="alert-item alert-item--${esc(a.severity)}">
        <span class="badge ${sev}">${esc(a.severity)}</span>
        <span class="alert-title">${esc(a.title)}</span>
        <span class="alert-time">${formatDate(a.created_at)}</span>
      </div>`;
    }).join("");
  }

  // Human-readable labels for meaningful feeder event types
  const FEEDER_EVENT_LABELS = {
    "low_food_detected": "🔴 Low food detected",
    "food_level_ok":     "✅ Food level OK",
    "manual_dispense":   "🍽️ Manual feed sent",
  };

  function renderRecentFeedings(feedings) {
    const el = document.getElementById("recent-feedings-list");
    if (!el) return;
    if (!feedings.length) {
      el.innerHTML = '<p class="text-muted">No feeding events yet.</p>';
      return;
    }
    el.innerHTML = `<table class="data-table">
      <thead><tr><th>Time</th><th>Event</th><th>Dispensed</th></tr></thead>
      <tbody>${feedings.map(f => {
        const eventType  = (f.metadata || {}).event_type || null;
        const eventLabel = eventType
          ? (FEEDER_EVENT_LABELS[eventType] || esc(eventType))
          : `<span class="badge badge-${esc(f.status_color || "green")}">${esc(f.status_color || "green")}</span>`;
        const dispensed  = f.dispensed_grams != null ? f.dispensed_grams + "g" : "—";
        return `<tr>
          <td>${formatDate(f.created_at)}</td>
          <td>${eventLabel}</td>
          <td>${dispensed}</td>
        </tr>`;
      }).join("")}</tbody>
    </table>`;
  }

  // ── Device Detail / Command Center ────────────────────────

  async function initDeviceDetail(deviceId) {
    if (!deviceId) return;

    // Load device + commands
    const res = await api("GET", `/api/devices/${deviceId}`);
    if (!res.ok) { showToast("Could not load device: " + res.error, "error"); return; }

    renderCommandButtons(deviceId, res.data.commands || [], res.data);
    await refreshDeviceEvents(deviceId);
  }

  function renderCommandButtons(deviceId, commands, device) {
    const container = document.getElementById("command-buttons");
    if (!container) return;
    if (!commands.length) {
      container.innerHTML = '<p class="text-muted">No commands available for this device type.</p>';
      return;
    }

    container.innerHTML = commands.map(cmd => {
      const hasParams = cmd.params && cmd.params.length > 0;
      const paramsHtml = hasParams ? cmd.params.map(p => {
        if (p.type === "select") {
          return `<label>${esc(p.label)}<select name="${esc(p.name)}">
            ${p.options.map(o => `<option value="${esc(o)}">${esc(o)}</option>`).join("")}
          </select></label>`;
        }
        return `<label>${esc(p.label)}<input type="${esc(p.type)}" name="${esc(p.name)}" placeholder="${esc(p.label)}" ${p.required ? "required" : ""}></label>`;
      }).join("") : "";

      return `<div class="command-card">
        <div class="command-label">${esc(cmd.label)}</div>
        ${hasParams ? `<div class="command-params" id="params-${esc(cmd.command)}">${paramsHtml}</div>` : ""}
        <button class="btn btn-sm btn-primary" onclick="SPH.runCommand('${esc(deviceId)}','${esc(cmd.command)}','${esc(cmd.command)}')">
          Send
        </button>
      </div>`;
    }).join("");
  }

  async function runCommand(deviceId, command, paramContainerId) {
    // Gather params from the command card's input fields
    const paramContainer = document.getElementById("params-" + paramContainerId);
    const params = {};
    if (paramContainer) {
      paramContainer.querySelectorAll("input,select").forEach(el => {
        if (el.name) params[el.name] = isNaN(el.value) ? el.value : Number(el.value);
      });
    }

    const ackEl = document.getElementById("ack-log");
    if (ackEl) {
      ackEl.insertAdjacentHTML("afterbegin",
        `<div class="ack-row ack-pending">⏳ Sending "${command}"…</div>`);
    }

    const res = await api("POST", `/api/devices/${deviceId}/command`, { command, params });
    if (!res.ok) {
      showToast("Command failed: " + res.error, "error");
      return;
    }

    const commandId = res.data.command_id;
    showToast(res.data.queued ? `Command "${command}" sent!` : `Command queued (MQTT offline)`, res.data.queued ? "success" : "warning");

    if (commandId) {
      pollAck(deviceId, commandId, 5);
    }
  }

  async function pollAck(deviceId, commandId, retries) {
    if (retries <= 0) return;
    await sleep(2000);
    const res = await api("GET", `/api/devices/${deviceId}/ack/${commandId}`);
    const ackEl = document.getElementById("ack-log");
    if (res.ok && res.data.status !== "pending") {
      const status  = res.data.status;
      const isGood  = (status === "success" || status === "ok");
      const icon    = isGood ? "✅" : "❌";
      const cssClass = isGood ? "ack-success" : "ack-" + status;
      if (ackEl) {
        ackEl.insertAdjacentHTML("afterbegin",
          `<div class="ack-row ${cssClass}">${icon} ACK: ${esc(res.data.message || status)} (${commandId.slice(0,8)})</div>`);
      }
    } else {
      pollAck(deviceId, commandId, retries - 1);
    }
  }

  async function refreshDeviceEvents(deviceId) {
    const el = document.getElementById("telemetry-panel");
    if (!el) return;
    el.innerHTML = '<p class="text-muted">Loading…</p>';
    const res = await api("GET", `/api/devices/${deviceId}/events?limit=10`);
    if (!res.ok) { el.innerHTML = '<p class="text-muted">Could not load events.</p>'; return; }
    if (!res.data.length) { el.innerHTML = '<p class="text-muted">No events yet. Waiting for telemetry…</p>'; return; }

    el.innerHTML = `<table class="data-table">
      <thead><tr><th>Time</th><th>Data</th></tr></thead>
      <tbody>${res.data.map(e => {
        const time = formatDate(e.detected_at || e.created_at);
        const summary = buildEventSummary(e);
        return `<tr><td>${time}</td><td>${summary}</td></tr>`;
      }).join("")}</tbody>
    </table>`;
  }

  function buildEventSummary(e) {
    // Generic summary — show interesting non-null fields
    const skip = new Set(["device_id","owner_id","created_at","detected_at","id","metadata","feeder_config_id"]);
    const parts = Object.entries(e)
      .filter(([k,v]) => !skip.has(k) && v !== null && v !== undefined && v !== "")
      .map(([k,v]) => `<span class="event-kv"><b>${esc(k.replace(/_/g," "))}</b>: ${esc(String(v))}</span>`);
    return parts.length ? parts.join(" · ") : "<span class='text-muted'>—</span>";
  }

  // ── Alerts (JS-powered mark/resolve) ──────────────────────

  // Build one alert card HTML string from an API alert object.
  // Uses inline onclick via window.SPH so listeners survive innerHTML replacement.
  function renderAlertCard(a) {
    const badgeColor = a.severity === "critical" ? "red"
                     : a.severity === "warning"  ? "yellow"
                     : "info";
    const deviceLine = a.devices
      ? `<p class="alert-device">📡 ${esc(a.devices.device_name)} (${esc(a.devices.serial_number)})</p>`
      : "";
    return `
      <div class="alert-card alert-card--${esc(a.severity)}" id="alert-card-${esc(a.id)}">
        <div class="alert-card-header">
          <span class="badge badge-${badgeColor}">${esc(a.severity.toUpperCase())}</span>
          <span class="alert-type-label">${esc(a.alert_type)}</span>
          <span class="alert-time">${formatDate(a.created_at)}</span>
        </div>
        <h4 class="alert-card-title">${esc(a.title)}</h4>
        <p class="alert-card-message">${esc(a.message)}</p>
        ${deviceLine}
        <div class="alert-card-actions">
          <button class="btn btn-sm btn-outline"
                  onclick="SPH.markAlertRead('${esc(a.id)}', this)">Mark Read</button>
          <button class="btn btn-sm btn-success"
                  onclick="SPH.resolveAlert('${esc(a.id)}', this)">Resolve</button>
        </div>
      </div>`;
  }

  // Re-fetch both alert lists and re-render the Alerts page sections.
  // Safe to call on any page — exits immediately if not on the alerts page.
  async function refreshAlerts() {
    if (document.body.dataset.page !== "alerts") return;

    const [unresolvedRes, resolvedRes] = await Promise.all([
      api("GET", "/api/alerts"),
      api("GET", "/api/alerts?resolved=true"),
    ]);

    // ── Unresolved section ──────────────────────────────────
    if (unresolvedRes.ok) {
      const alerts = unresolvedRes.data || [];

      const countEl = document.getElementById("unresolved-count");
      if (countEl) countEl.textContent = alerts.length;

      // Also update dashboard badge if present (shared counter)
      const statEl = document.getElementById("stat-alerts");
      if (statEl) statEl.textContent = alerts.length;

      const body = document.getElementById("unresolved-body");
      if (body) {
        if (alerts.length === 0) {
          body.innerHTML = '<div class="empty-state"><p>No unresolved alerts. All systems nominal!</p></div>';
        } else {
          body.innerHTML = `<div class="alert-cards">${alerts.map(renderAlertCard).join("")}</div>`;
        }
      }
    }

    // ── Recently Resolved section ───────────────────────────
    if (resolvedRes.ok) {
      const alerts = resolvedRes.data || [];
      const body   = document.getElementById("resolved-body");
      if (body) {
        if (alerts.length === 0) {
          body.innerHTML = '<div class="empty-state"><p>No resolved alerts yet.</p></div>';
        } else {
          const rows = alerts.map(a => `
            <tr class="row-muted">
              <td>${esc(a.title)}</td>
              <td>${esc(a.severity)}</td>
              <td>${esc(a.alert_type)}</td>
              <td>${formatDate(a.resolved_at)}</td>
            </tr>`).join("");
          body.innerHTML = `
            <table class="data-table">
              <thead><tr><th>Title</th><th>Severity</th><th>Type</th><th>Resolved At</th></tr></thead>
              <tbody>${rows}</tbody>
            </table>`;
        }
      }
    }
  }

  async function markAlertRead(alertId, btn) {
    const res = await api("POST", `/api/alerts/${alertId}/read`);
    if (res.ok) {
      const card = btn.closest(".alert-card");
      if (card) card.classList.add("row-muted");
      showToast("Alert marked as read.", "success");
    } else {
      showToast("Error: " + res.error, "error");
    }
  }

  async function resolveAlert(alertId, btn) {
    // Immediately hide the card for instant visual feedback
    const card = btn.closest(".alert-card");
    if (card) card.style.display = "none";

    const res = await api("POST", `/api/alerts/${alertId}/resolve`);
    if (res.ok) {
      showToast("Alert resolved.", "success");
      // Re-fetch and re-render both sections so count + resolved table update
      await refreshAlerts();
    } else {
      // Restore card visibility if the request failed
      if (card) card.style.display = "";
      showToast("Error: " + res.error, "error");
    }
  }

  // ── Utilities ─────────────────────────────────────────────

  function esc(str) {
    return String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function formatDate(iso) {
    if (!iso) return "—";
    try {
      return new Date(iso).toLocaleString(undefined, {
        year: "numeric", month: "2-digit", day: "2-digit",
        hour: "2-digit", minute: "2-digit",
      });
    } catch { return iso; }
  }

  function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

  // ── Auto-init on page load ────────────────────────────────

  document.addEventListener("DOMContentLoaded", function () {
    const page = document.body.dataset.page;

    // MQTT status (all pages)
    updateMqttStatus();
    setInterval(updateMqttStatus, 15000);

    if (page === "dashboard") {
      loadDashboardSummary();
      setInterval(loadDashboardSummary, 30000);
    }

    if (page === "device-detail") {
      const deviceId = document.body.dataset.deviceId;
      if (deviceId) {
        initDeviceDetail(deviceId);
        setInterval(() => refreshDeviceEvents(deviceId), 20000);
      }
    }

    if (page === "alerts") {
      // Auto-refresh alerts every 30 s so new ones appear without manual reload
      setInterval(refreshAlerts, 30000);
    }
  });

  // ── Public API ────────────────────────────────────────────
  window.SPH = {
    runCommand,
    markAlertRead,
    resolveAlert,
    refreshAlerts,
    refreshDeviceEvents,
    loadDashboardSummary,
    showToast,
    api,
  };

})();
