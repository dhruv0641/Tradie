/**
 * AI Trader Autonomous System - Operator Web Dashboard Client
 * Interfaces with FastAPI Control Backend endpoints (Sprint S22.02)
 */

// Configuration and state
const API_BASE = '/api';
let pollIntervalId = null;
let currentKillSwitchActive = false;

function getOperatorToken() {
  return localStorage.getItem('ai_trader_operator_token') || 'operator-secret-token';
}

function setOperatorToken(token) {
  if (token && token.trim()) {
    localStorage.setItem('ai_trader_operator_token', token.trim());
  }
}

// Utility: Format currency in INR (₹)
function formatINR(amount) {
  const num = parseFloat(amount || 0);
  return new Intl.NumberFormat('en-IN', {
    style: 'currency',
    currency: 'INR',
    maximumFractionDigits: 2,
  }).format(num);
}

// Utility: Fetch JSON with optional auth header
async function apiFetch(endpoint, options = {}) {
  const headers = options.headers || {};
  if (options.requireAuth) {
    headers['Authorization'] = `Bearer ${getOperatorToken()}`;
  }
  const res = await fetch(`${API_BASE}${endpoint}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...headers,
    },
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || `HTTP ${res.status}`);
  }
  return res.json();
}

// Update Dashboard Panels from API responses
async function refreshDashboard() {
  try {
    const [account, trading, ai, risk, health] = await Promise.all([
      apiFetch('/account'),
      apiFetch('/trading'),
      apiFetch('/ai'),
      apiFetch('/risk'),
      apiFetch('/health'),
    ]);

    renderAccount(account);
    renderTrading(trading);
    renderAI(ai);
    renderRisk(risk);
    renderHealth(health);
  } catch (err) {
    console.error('Failed refreshing dashboard:', err);
  }
}

function renderAccount(data) {
  const elCapital = document.getElementById('val-capital');
  const elDailyPnl = document.getElementById('val-daily-pnl');
  const elTotalPnl = document.getElementById('val-total-pnl');
  const elDrawdown = document.getElementById('val-drawdown');
  const cardDailyPnl = document.getElementById('card-daily-pnl');

  if (elCapital) elCapital.textContent = formatINR(data.current_capital);
  if (elDailyPnl) {
    const pnl = parseFloat(data.daily_pnl || 0);
    elDailyPnl.textContent = `${pnl >= 0 ? '+' : ''}${formatINR(pnl)}`;
    if (cardDailyPnl) {
      cardDailyPnl.className = `metric-card ${pnl >= 0 ? 'positive' : 'danger'}`;
    }
  }
  if (elTotalPnl) {
    const totalPnl = parseFloat(data.total_pnl || 0);
    elTotalPnl.textContent = `${totalPnl >= 0 ? '+' : ''}${formatINR(totalPnl)}`;
  }
  if (elDrawdown) {
    elDrawdown.textContent = `${formatINR(data.drawdown_amount)} (${data.drawdown_pct.toFixed(2)}%)`;
  }
}

function renderTrading(data) {
  const tbodyPos = document.getElementById('tbody-positions');
  const tbodyOrders = document.getElementById('tbody-orders');

  if (tbodyPos) {
    if (!data.positions || data.positions.length === 0) {
      tbodyPos.innerHTML = '<tr><td colspan="6" class="empty-state">No open positions. Portfolio flat.</td></tr>';
    } else {
      tbodyPos.innerHTML = data.positions
        .map(
          (p) => `
        <tr>
          <td><strong>${p.instrument}</strong></td>
          <td><span class="badge ${p.quantity > 0 ? 'badge-success' : 'badge-danger'}">${p.quantity > 0 ? 'LONG' : 'SHORT'}</span></td>
          <td>${Math.abs(p.quantity)}</td>
          <td>${formatINR(p.average_entry_price)}</td>
          <td>${formatINR(p.current_market_price)}</td>
          <td style="color: ${parseFloat(p.unrealized_pnl) >= 0 ? 'var(--color-success)' : 'var(--color-danger)'};">
            ${parseFloat(p.unrealized_pnl) >= 0 ? '+' : ''}${formatINR(p.unrealized_pnl)}
          </td>
        </tr>
      `
        )
        .join('');
    }
  }

  if (tbodyOrders) {
    if (!data.open_orders || data.open_orders.length === 0) {
      tbodyOrders.innerHTML = '<tr><td colspan="6" class="empty-state">No active working orders.</td></tr>';
    } else {
      tbodyOrders.innerHTML = data.open_orders
        .map(
          (o) => `
        <tr>
          <td style="font-size:0.75rem;">${o.client_order_id}</td>
          <td><strong>${o.instrument}</strong></td>
          <td><span class="badge ${o.direction === 'BUY' ? 'badge-success' : 'badge-danger'}">${o.direction}</span></td>
          <td>${o.quantity}</td>
          <td>${o.limit_price ? formatINR(o.limit_price) : 'MKT'}</td>
          <td><span class="badge badge-accent">${o.status}</span></td>
        </tr>
      `
        )
        .join('');
    }
  }
}

function renderAI(data) {
  const elRegime = document.getElementById('badge-regime');
  const elModelVer = document.getElementById('badge-model-version');
  const containerSignals = document.getElementById('container-agent-signals');

  if (elRegime) elRegime.textContent = data.regime_label;
  if (elModelVer) elModelVer.textContent = data.active_model_version;

  if (containerSignals && data.agent_signals) {
    containerSignals.innerHTML = data.agent_signals
      .map(
        (s) => `
      <div style="display:flex; justify-content:space-between; align-items:center; padding:0.4rem 0; border-bottom:1px solid var(--border-subtle);">
        <div>
          <span style="font-weight:600; font-size:0.85rem;">${s.agent_id}</span>
          <div style="font-size:0.75rem; color:var(--text-muted);">${s.reason || 'Signals evaluated'}</div>
        </div>
        <div style="display:flex; align-items:center; gap:0.5rem;">
          <span class="badge ${s.direction === 'BUY' ? 'badge-success' : s.direction === 'SELL' ? 'badge-danger' : 'badge-warning'}">
            ${s.direction}
          </span>
          <span style="font-family:var(--font-mono); font-size:0.8rem; color:var(--text-secondary);">
            ${(s.confidence * 100).toFixed(0)}%
          </span>
        </div>
      </div>
    `
      )
      .join('');
  }
}

function renderRisk(data) {
  const elKillSwitch = document.getElementById('badge-kill-switch');
  const elStreak = document.getElementById('val-streak');
  const elExposurePct = document.getElementById('val-exposure-pct');
  const barExposure = document.getElementById('bar-exposure');
  const elDailyRiskPct = document.getElementById('val-daily-risk-pct');
  const barDailyRisk = document.getElementById('bar-daily-risk');
  const btnEmergencyStop = document.getElementById('btn-emergency-stop');
  const btnResetStop = document.getElementById('btn-reset-stop');

  currentKillSwitchActive = data.kill_switch_active;

  if (elKillSwitch) {
    if (data.kill_switch_active) {
      elKillSwitch.className = 'badge badge-danger';
      elKillSwitch.textContent = 'TRADING HALTED (KILL SWITCH)';
      if (btnEmergencyStop) btnEmergencyStop.style.display = 'none';
      if (btnResetStop) btnResetStop.style.display = 'flex';
    } else {
      elKillSwitch.className = 'badge badge-success';
      elKillSwitch.textContent = 'OPERATIONAL (NOMINAL)';
      if (btnEmergencyStop) btnEmergencyStop.style.display = 'flex';
      if (btnResetStop) btnResetStop.style.display = 'none';
    }
  }

  if (elStreak) {
    elStreak.textContent = `${data.consecutive_losses} Losses ${data.session_paused ? '(SESSION PAUSED)' : ''}`;
    elStreak.style.color = data.session_paused ? 'var(--color-danger)' : 'var(--text-primary)';
  }

  const expPct = parseFloat(data.max_exposure_limit) > 0 ? (parseFloat(data.current_exposure) / parseFloat(data.max_exposure_limit)) * 100 : 0;
  if (elExposurePct) elExposurePct.textContent = `${formatINR(data.current_exposure)} / ${formatINR(data.max_exposure_limit)} (${expPct.toFixed(1)}%)`;
  if (barExposure) barExposure.style.width = `${Math.min(100, expPct)}%`;

  const riskPct = parseFloat(data.daily_risk_limit) > 0 ? (parseFloat(data.daily_risk_used) / parseFloat(data.daily_risk_limit)) * 100 : 0;
  if (elDailyRiskPct) elDailyRiskPct.textContent = `${formatINR(data.daily_risk_used)} / ${formatINR(data.daily_risk_limit)} (${riskPct.toFixed(1)}%)`;
  if (barDailyRisk) barDailyRisk.style.width = `${Math.min(100, riskPct)}%`;
}

function renderHealth(data) {
  const elSysStatus = document.getElementById('badge-system-health');
  const elDiagGrid = document.getElementById('grid-diagnostics');

  if (elSysStatus) {
    elSysStatus.className = `badge ${data.status === 'healthy' ? 'badge-success' : data.status === 'degraded' ? 'badge-warning' : 'badge-danger'}`;
    elSysStatus.textContent = data.status.toUpperCase();
  }

  if (elDiagGrid && data.components) {
    elDiagGrid.innerHTML = Object.entries(data.components)
      .map(
        ([key, c]) => `
      <div class="diag-card">
        <div class="diag-name">${c.name}</div>
        <span class="badge ${c.status === 'healthy' ? 'badge-success' : c.status === 'degraded' ? 'badge-warning' : 'badge-danger'}">
          ${c.status.toUpperCase()}
        </span>
        <div style="font-size:0.7rem; color:var(--text-muted); margin-top:0.3rem;">${c.message}</div>
      </div>
    `
      )
      .join('');
  }
}

// 1-Click Emergency STOP execution (< 2s SLA per FRD-DASH-7)
async function triggerEmergencyStop(optionType) {
  const reason = optionType === 'liquidate'
    ? 'EMERGENCY STOP: Immediate market liquidation and halt triggered by operator'
    : 'MANUAL STOP: Halt new entries and cancel working orders';

  try {
    const res = await apiFetch('/control/stop', {
      method: 'POST',
      requireAuth: true,
      body: JSON.stringify({ reason }),
    });

    closeModal('modal-emergency-stop');
    alert(`Emergency STOP executed successfully: ${res.status.toUpperCase()}`);
    await refreshDashboard();
  } catch (err) {
    alert(`Failed executing STOP trigger: ${err.message}`);
  }
}

// Emergency STOP Reset
async function triggerEmergencyReset() {
  const token = document.getElementById('reset-token-input').value;
  if (token) setOperatorToken(token);

  try {
    const res = await apiFetch('/control/reset', {
      method: 'POST',
      requireAuth: true,
      body: JSON.stringify({ reason: 'Operator authorized resume' }),
    });

    closeModal('modal-reset-stop');
    alert(`Emergency Kill Switch reset: Status is now ${res.status.toUpperCase()}`);
    await refreshDashboard();
  } catch (err) {
    alert(`Failed resetting Kill Switch: ${err.message}`);
  }
}

// Modal management
function openModal(id) {
  const el = document.getElementById(id);
  if (el) el.classList.add('active');
}

function closeModal(id) {
  const el = document.getElementById(id);
  if (el) el.classList.remove('active');
}

// Event Listeners setup
document.addEventListener('DOMContentLoaded', () => {
  // Emergency STOP button triggers modal
  const btnEmergency = document.getElementById('btn-emergency-stop');
  if (btnEmergency) {
    btnEmergency.addEventListener('click', () => openModal('modal-emergency-stop'));
  }

  // Reset button triggers modal
  const btnReset = document.getElementById('btn-reset-stop');
  if (btnReset) {
    btnReset.addEventListener('click', () => openModal('modal-reset-stop'));
  }

  // Settings / Token button
  const btnSettings = document.getElementById('btn-settings');
  if (btnSettings) {
    btnSettings.addEventListener('click', () => {
      const cur = getOperatorToken();
      const updated = prompt('Enter Operator Authorization Token:', cur);
      if (updated !== null) {
        setOperatorToken(updated);
        alert('Token updated.');
      }
    });
  }

  // Initial load and start 2s polling
  refreshDashboard();
  pollIntervalId = setInterval(refreshDashboard, 2000);
});
