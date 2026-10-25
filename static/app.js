// Blue Knight Gate — Client Application
// Brand: Blue Knight Net (https://t.me/BlueKnight_Net)

let gateData = null;

// --- Toast Feedback ---
function showToast(text) {
  const toast = document.getElementById('bkToast');
  if (!toast) return;
  toast.innerText = text;
  toast.classList.add('show');
  setTimeout(() => {
    toast.classList.remove('show');
  }, 2200);
}

// --- Clipboard Copy ---
function copyTextToClipboard(text) {
  if (!text) return;
  const successMsg = 'Copied to clipboard!';

  if (navigator.clipboard && window.isSecureContext) {
    navigator.clipboard.writeText(text).then(() => {
      showToast(successMsg);
    }).catch(() => {
      fallbackCopy(text, successMsg);
    });
  } else {
    fallbackCopy(text, successMsg);
  }
}

function fallbackCopy(text, msg) {
  const textArea = document.createElement('textarea');
  textArea.value = text;
  textArea.style.position = 'fixed';
  textArea.style.opacity = '0';
  document.body.appendChild(textArea);
  textArea.focus();
  textArea.select();
  try {
    document.execCommand('copy');
    showToast(msg);
  } catch (err) {
    showToast('Failed to copy');
  }
  document.body.removeChild(textArea);
}

// --- QR Code Modal ---
function openQr(text, title) {
  if (!text) return;
  const modal = document.getElementById('qrModal');
  const wrapper = document.getElementById('qrcodeWrapper');
  const titleEl = document.getElementById('qrModalTitle');
  if (!modal || !wrapper) return;

  if (titleEl && title) {
    titleEl.innerText = title;
  } else if (titleEl) {
    titleEl.innerText = 'Scan QR Code';
  }

  wrapper.innerHTML = '';
  const img = document.createElement('img');
  img.src = `/knight/api/qr?data=${encodeURIComponent(text)}`;
  img.alt = 'QR Code';
  img.width = 240;
  img.height = 240;
  wrapper.appendChild(img);

  modal.classList.add('active');
}

function closeQr() {
  document.getElementById('qrModal')?.classList.remove('active');
}

document.getElementById('qrCloseBtn')?.addEventListener('click', closeQr);
document.getElementById('qrModal')?.addEventListener('click', (e) => {
  if (e.target.id === 'qrModal') closeQr();
});
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') closeQr();
});

// --- Theme Switcher (Dark Cinema / Cozy Warm) ---
function applyTheme(theme) {
  const isCozy = (theme === 'cozy');
  const targetTheme = isCozy ? 'cozy' : 'dark';

  document.documentElement.setAttribute('data-theme', targetTheme);
  document.body.setAttribute('data-theme', targetTheme);

  if (isCozy) {
    document.body.classList.add('theme-cozy');
  } else {
    document.body.classList.remove('theme-cozy');
  }

  const toggleBtn = document.getElementById('themeToggleBtn');
  const toggleLabel = document.getElementById('themeToggleLabel');
  if (toggleBtn) {
    toggleBtn.setAttribute('data-theme', targetTheme);
    toggleBtn.setAttribute('aria-pressed', isCozy ? 'true' : 'false');
    toggleBtn.classList.toggle('is-cozy', isCozy);
  }
  if (toggleLabel) {
    toggleLabel.textContent = isCozy ? 'Cozy' : 'Dark';
  }
}

function initTheme() {
  const savedTheme = localStorage.getItem('bk-theme') || localStorage.getItem('bk_gate_theme') || 'dark';
  applyTheme(savedTheme);
}

function toggleTheme() {
  const current = document.documentElement.getAttribute('data-theme') || (document.body.classList.contains('theme-cozy') ? 'cozy' : 'dark');
  const nextTheme = (current === 'cozy') ? 'dark' : 'cozy';
  applyTheme(nextTheme);
  try {
    localStorage.setItem('bk-theme', nextTheme);
    localStorage.setItem('bk_gate_theme', nextTheme);
  } catch {}
  showToast(nextTheme === 'cozy' ? 'Theme: Cozy Tavern' : 'Theme: Cinema Dark');
}

document.getElementById('themeToggleBtn')?.addEventListener('click', toggleTheme);
initTheme();

// --- Event Delegation for Copy & QR Buttons ---
document.addEventListener('click', (e) => {
  const btn = e.target.closest('button, a');
  if (!btn) return;

  const action = btn.getAttribute('data-action');
  if (!action) return;

  if (action === 'copy-input') {
    const targetId = btn.getAttribute('data-target');
    const input = document.getElementById(targetId);
    if (input) copyTextToClipboard(input.value);
  } else if (action === 'qr-input') {
    const targetId = btn.getAttribute('data-target');
    const input = document.getElementById(targetId);
    if (input) openQr(input.value, 'Subscription QR');
  } else if (action === 'copy-text') {
    const raw = btn.getAttribute('data-text');
    if (raw) copyTextToClipboard(decodeURIComponent(raw));
  } else if (action === 'qr-text') {
    const raw = btn.getAttribute('data-text');
    const title = btn.getAttribute('data-title') || 'Scan QR Code';
    if (raw) openQr(decodeURIComponent(raw), title);
  }
});

// --- SPA Hash Router (Home, Sub, Node) ---
function handleRouting() {
  let hash = window.location.hash || '#/home';
  if (hash === '#' || hash === '') hash = '#/home';
  const page = hash.replace(/^#\/?/, '').split('?')[0].toLowerCase() || 'home';

  let validPage = 'home';
  if (page === 'subs' || page === 'sub') {
    validPage = 'subs';
  } else if (page === 'nodes' || page === 'node') {
    validPage = 'nodes';
  } else if (page === 'usage' || page === 'traffic') {
    validPage = 'usage';
  }

  // Toggle active view
  document.querySelectorAll('.view-page').forEach(el => {
    el.classList.remove('active');
  });

  let targetViewId = 'viewHome';
  if (validPage === 'subs') targetViewId = 'viewSubs';
  else if (validPage === 'nodes') targetViewId = 'viewNodes';
  else if (validPage === 'usage') targetViewId = 'viewUsage';

  const targetView = document.getElementById(targetViewId);
  if (targetView) targetView.classList.add('active');

  // Toggle header, mobile bar, and drawer nav links
  document.querySelectorAll('.nav-link, .mob-link, .drawer-nav-item').forEach(el => {
    if (el.getAttribute('data-page') === validPage) {
      el.classList.add('active');
    } else {
      el.classList.remove('active');
    }
  });

  toggleDrawer(false);
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

window.addEventListener('hashchange', handleRouting);

// --- Mobile Drawer Controls ---
const hamburgerBtn = document.getElementById('hamburgerBtn');
const mobileDrawer = document.getElementById('mobileDrawer');

function toggleDrawer(open) {
  if (!hamburgerBtn || !mobileDrawer) return;
  const isOpen = (typeof open === 'boolean') ? open : !mobileDrawer.classList.contains('open');
  mobileDrawer.classList.toggle('open', isOpen);
  hamburgerBtn.classList.toggle('active', isOpen);
  hamburgerBtn.setAttribute('aria-expanded', isOpen ? 'true' : 'false');
  mobileDrawer.setAttribute('aria-hidden', isOpen ? 'false' : 'true');
}

hamburgerBtn?.addEventListener('click', (e) => {
  e.stopPropagation();
  toggleDrawer();
});

// Close drawer on clicking any link inside it
mobileDrawer?.querySelectorAll('a').forEach(link => {
  link.addEventListener('click', () => toggleDrawer(false));
});

// Close drawer on click outside
document.addEventListener('click', (e) => {
  if (mobileDrawer?.classList.contains('open')) {
    if (!mobileDrawer.contains(e.target) && !hamburgerBtn?.contains(e.target)) {
      toggleDrawer(false);
    }
  }
});

// Close drawer on Escape key
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape' && mobileDrawer?.classList.contains('open')) {
    toggleDrawer(false);
  }
});

// Helper to escape HTML characters
function escapeHtml(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

// Render dynamic node cards
function renderNodes(nodes, locationStr) {
  const container = document.getElementById('nodesContainer');
  if (!container) return;

  // Filter out any invalid or hysteria nodes
  const activeNodes = (nodes || []).filter(n => {
    if (!n || !n.uri) return false;
    const lowerType = (n.type || '').toLowerCase();
    return !lowerType.includes('hy2') && !lowerType.includes('hysteria');
  });

  if (activeNodes.length === 0) {
    container.innerHTML = `
      <div class="no-nodes-msg">
        <p>No active proxy nodes found. Please verify engine status.</p>
      </div>
    `;
    return;
  }

  let html = '';
  activeNodes.forEach((node, index) => {
    const rawUri = node.uri;
    const name = node.name || `💞t.me/BlueKnight_Net - Node ${index + 1}`;
    const lowerType = (node.type || '').toLowerCase();

    // Determine protocol badge
    let protoLabel = 'VLESS';
    let protoClass = 'badge-proto-vless';
    if (lowerType.includes('vmess')) {
      protoLabel = 'VMess';
      protoClass = 'badge-proto-vmess';
    } else if (lowerType.includes('trojan')) {
      protoLabel = 'Trojan';
      protoClass = 'badge-proto-trojan';
    } else if (lowerType.includes('shadowsocks') || lowerType.startsWith('ss')) {
      protoLabel = 'Shadowsocks';
      protoClass = 'badge-proto-ss';
    } else if (lowerType.includes('wireguard') || lowerType.includes('wg')) {
      protoLabel = 'WireGuard';
      protoClass = 'badge-proto-wg';
    } else if (lowerType.includes('tuic')) {
      protoLabel = 'TUIC';
      protoClass = 'badge-proto-tuic';
    }

    // Determine transport / security badges
    let transportBadge = '';
    if (lowerType.includes('ws')) {
      transportBadge = '<span class="node-badge-tag">WS</span>';
    } else if (lowerType.includes('httpupgrade')) {
      transportBadge = '<span class="node-badge-tag">HTTPUpgrade</span>';
    } else if (lowerType.includes('grpc')) {
      transportBadge = '<span class="node-badge-tag">gRPC</span>';
    } else if (lowerType.includes('xhttp')) {
      transportBadge = '<span class="node-badge-tag">XHTTP</span>';
    }

    let secBadge = '';
    if (lowerType.includes('reality')) {
      secBadge = '<span class="node-badge-tag badge-reality">Reality</span>';
    } else if (lowerType.includes('tls') || lowerType.includes('shadowtls')) {
      secBadge = '<span class="node-badge-tag badge-tls">TLS</span>';
    }

    const encodedUri = encodeURIComponent(rawUri);
    const encodedTitle = encodeURIComponent(name);

    html += `
      <div class="node-item-card">
        <div class="node-card-header">
          <div class="node-card-title-group">
            <span class="proto-badge ${protoClass}">${protoLabel}</span>
            <h4 class="node-remark-title" title="${escapeHtml(name)}">${escapeHtml(name)}</h4>
          </div>
          <div class="node-badges-group">
            ${transportBadge}
            ${secBadge}
          </div>
        </div>

        <div class="node-card-meta">
          <div class="node-location-tag">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="loc-icon">
              <path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"></path>
              <circle cx="12" cy="10" r="3"></circle>
            </svg>
            <span>${escapeHtml(locationStr || 'Global Server')}</span>
          </div>
          ${node.note ? `<div class="node-location-tag" style="opacity:.85;font-size:.78rem">${escapeHtml(node.note)}</div>` : ''}
        </div>

        <div class="node-uri-box">
          <input type="text" class="node-uri-input" readonly value="${escapeHtml(rawUri)}" onclick="this.select();">
        </div>

        <div class="node-actions-row">
          <button type="button" class="btn-node-copy" data-action="copy-text" data-text="${encodedUri}">
            <svg class="btn-action-svg" viewBox="0 0 24 24" fill="currentColor">
              <path d="M16 1H4c-1.1 0-2 .9-2 2v14h2V3h12V1zm3 4H8c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h11c1.1 0 2-.9 2-2V7c0-1.1-.9-2-2-2zm0 16H8V7h11v14z"/>
            </svg>
            <span>Copy Link</span>
          </button>
          <button type="button" class="btn-node-qr" data-action="qr-text" data-text="${encodedUri}" data-title="${encodedTitle}" title="Show QR Code">
            <svg class="btn-action-svg" viewBox="0 0 24 24" fill="currentColor">
              <path d="M3 3h8v8H3V3zm2 2v4h4V5H5zm8-2h8v8h-8V3zm2 2v4h4V5h-4zM3 13h8v8H3v-8zm2 2v4h4v-4H5zm13-2h3v2h-3v-2zm-5 0h3v2h-3v-2zm2 2h2v2h-2v-2zm-2 2h3v2h-3v-2zm5 0h2v4h-4v-2h2v-2zm-3 2h2v2h-2v-2z"/>
            </svg>
            <span>QR</span>
          </button>
          ${node.wgConf ? `
            <a href="/knight/wg.conf" download="wg0.conf" class="btn-node-dl" title="Download WireGuard Profile">
              <span>.conf</span>
            </a>
          ` : ''}
        </div>
      </div>
    `;
  });

  container.innerHTML = html;
}

// --- Load Gate Data from Server ---
async function loadGateData() {
  try {
    const pathSegments = window.location.pathname.split('/').filter(Boolean);
    const pathPrefix = pathSegments[0] || 'knight';

    // Fetch server status
    const res = await fetch('/health');
    const data = await res.json();
    gateData = data;

    // Determine host and port
    const pubPort = data.publicPort || window.location.port || '2705';
    const serverHost = data.domain || data.host || window.location.hostname;
    const locationStr = data.location || 'Global Server';

    // Format Uptime
    let uptimeStr = '--';
    if (data.uptime !== undefined) {
      const mins = Math.floor(data.uptime / 60);
      const secs = Math.floor(data.uptime % 60);
      uptimeStr = `${mins}m ${secs}s`;
    }

    // Update Home Section Stats
    const homeLocation = document.getElementById('homeLocation');
    if (homeLocation) homeLocation.innerText = locationStr;

    const homePort = document.getElementById('homePort');
    if (homePort) homePort.innerText = pubPort;

    const homeUptime = document.getElementById('homeUptime');
    if (homeUptime) homeUptime.innerText = uptimeStr;

    // Update Sub Section Metrics
    const statLocation = document.getElementById('statLocation');
    if (statLocation) statLocation.innerText = locationStr;

    const statPort = document.getElementById('statPort');
    if (statPort) statPort.innerText = pubPort;

    const statHost = document.getElementById('statHost');
    if (statHost) statHost.innerText = serverHost;

    const statUptime = document.getElementById('statUptime');
    if (statUptime) statUptime.innerText = uptimeStr;

    // Update Node Section Header
    const nodesLocation = document.getElementById('nodesLocation');
    if (nodesLocation) nodesLocation.innerText = locationStr;

    // Update Engines
    const engines = [];
    if (data.engines?.singbox) engines.push('sing-box');
    if (data.engines?.xray) engines.push('xray');
    if (data.engines?.argo) engines.push('argo');
    const statEngines = document.getElementById('statEngines');
    if (statEngines) statEngines.innerText = engines.join(' + ') || 'sing-box active';

    // Subscription URLs protocol determination:
    // Default to HTTP for raw IP/ports so Windows clients (v2rayN) connect without SSL handshake errors.
    // If the panel was loaded over HTTPS or has forceHttps/publicBaseUrl, default to HTTPS.
    let activeProto = (data.forceHttps || window.location.protocol === 'https:') ? 'https:' : 'http:';

    const updateSubscriptionUrls = (proto) => {
      let origin;
      if (data.publicBaseUrl && typeof data.publicBaseUrl === 'string' && data.publicBaseUrl.trim()) {
        origin = data.publicBaseUrl.trim().replace(/\/+$/, '');
      } else if (data.subBase && typeof data.subBase === 'string' && data.subBase.trim()) {
        origin = data.subBase.trim().replace(/\/+$/, '');
      } else {
        const hostPort = window.location.port ? `${window.location.hostname}:${window.location.port}` : window.location.hostname;
        if (proto === 'https:') {
          if (data.domain) {
            origin = data.domain.startsWith('http') ? data.domain : `https://${data.domain}`;
          } else if (window.location.protocol === 'https:') {
            origin = window.location.origin;
          } else {
            origin = `https://${hostPort}`;
          }
        } else {
          origin = `http://${hostPort}`;
        }
      }

      const bkTok = (data && data.subToken) ? encodeURIComponent(data.subToken) : ''; const bkQ = (u) => bkTok ? u + (u.indexOf('?') >= 0 ? '&' : '?') + 'token=' + bkTok : u; const compatSubUrl = bkQ(`${origin}/${pathPrefix}/base64`);
      const fullSubUrl = bkQ(`${origin}/${pathPrefix}/base64?compat=full`);
      const clashUrl = bkQ(`${origin}/${pathPrefix}/clash`);
      const sbUrl = bkQ(`${origin}/${pathPrefix}/sb/raw`);
      const wgConfUrl = bkQ(`${origin}/${pathPrefix}/wg.conf`);

      const elCompat = document.getElementById('urlSubCompat');
      if (elCompat) elCompat.value = compatSubUrl;

      const elFull = document.getElementById('urlSubFull');
      if (elFull) elFull.value = fullSubUrl;

      const elClash = document.getElementById('urlClash');
      if (elClash) elClash.value = clashUrl;

      const elSb = document.getElementById('urlSb');
      if (elSb) elSb.value = sbUrl;

      const elWg = document.getElementById('urlWgConf');
      if (elWg) elWg.value = wgConfUrl;

      const btnDlWg = document.getElementById('btnDownloadWg');
      if (btnDlWg) btnDlWg.href = `${origin}/${pathPrefix}/wg.conf`;

      const compatBadge = document.getElementById('compatBadge');
      if (compatBadge) {
        compatBadge.innerText = (proto === 'https:') ? '(HTTPS Subscription)' : '(v2rayN / Windows Ready)';
      }
    };

    updateSubscriptionUrls(activeProto);

    // Setup interactive protocol toggle buttons
    const btnProtoHttp = document.getElementById('btnProtoHttp');
    const btnProtoHttps = document.getElementById('btnProtoHttps');
    if (btnProtoHttp && btnProtoHttps) {
      btnProtoHttp.classList.toggle('active', activeProto === 'http:');
      btnProtoHttps.classList.toggle('active', activeProto === 'https:');

      btnProtoHttp.onclick = () => {
        activeProto = 'http:';
        btnProtoHttp.classList.add('active');
        btnProtoHttps.classList.remove('active');
        updateSubscriptionUrls('http:');
        showToast('Switched to HTTP (v2rayN Windows compatible)');
      };

      btnProtoHttps.onclick = () => {
        activeProto = 'https:';
        btnProtoHttps.classList.add('active');
        btnProtoHttp.classList.remove('active');
        updateSubscriptionUrls('https:');
        showToast('Switched to HTTPS (Requires SSL Proxy)');
      };
    }

    // Render node list
    renderNodes(data.nodes, locationStr);

  } catch (err) {
    console.error('Failed to load gate status:', err);
    const container = document.getElementById('nodesContainer');
    if (container) {
      container.innerHTML = `
        <div class="no-nodes-msg">
          <p>Failed to connect to gate server. Please refresh or check connection.</p>
        </div>
      `;
    }
  }
}

// --- Home page latest YouTube video thumbnail & click ---
async function initLatestVideo() {
  try {
    const res = await fetch('/api/latest-video');
    const data = await res.json();
    if (data && data.ok && data.videoId) {
      const heroCard = document.querySelector('.single-hero-card');
      const heroImg = document.querySelector('.hero-card-img');
      if (heroCard && heroImg) {
        const preImg = new Image();
        preImg.onload = () => {
          heroImg.src = data.thumbnail;
        };
        preImg.src = data.thumbnail;

        heroCard.style.cursor = 'pointer';
        heroCard.title = data.title || 'Watch latest video on YouTube';
        heroCard.onclick = () => {
          window.open(data.url, '_blank', 'noopener,noreferrer');
        };

        const badgeText = heroCard.querySelector('.hero-card-badge span:last-child');
        if (badgeText) {
          badgeText.innerText = 'Latest Video • Watch Now';
        }
      }
    }
  } catch (_) {}
}

document.addEventListener('DOMContentLoaded', () => {
  handleRouting();
  loadGateData();
  initLatestVideo();
});

// --- Traffic usage view (BK_TRAFFIC_APPLIED) ---
(function () {
  const $ = (id) => document.getElementById(id);
  if (!$('viewUsage')) return;
  const prefix = '/' + (window.location.pathname.split('/').filter(Boolean)[0] || 'knight');
  const API = prefix + '/api/traffic';
  const NAMES = { 'VLESS-WS': 'VLESS WS', 'VMess-WS': 'VMess WS', 'Trojan-WS': 'Trojan WS', 'VLESS-XHTTP': 'VLESS XHTTP', 'VLESS-HTTPUpgrade': 'VLESS HTTPUpgrade', 'VMess-HTTPUpgrade': 'VMess HTTPUpgrade', 'Trojan-HTTPUpgrade': 'Trojan HTTPUpgrade', 'VLESS-gRPC': 'VLESS gRPC', 'Shadowsocks-WS': 'Shadowsocks WS', 'Other': 'Other' };
  const COLORS = { 'VLESS-WS': '#60a5fa', 'VMess-WS': '#a78bfa', 'Trojan-WS': '#f9a8d4', 'VLESS-XHTTP': '#5eead4', 'VLESS-HTTPUpgrade': '#fcd34d', 'VMess-HTTPUpgrade': '#c4b5fd', 'Trojan-HTTPUpgrade': '#fda4af', 'VLESS-gRPC': '#86efac', 'Shadowsocks-WS': '#fdba74', 'Other': '#94a3b8' };
  const fmt = (b) => {
    b = Number(b) || 0; const neg = b < 0; b = Math.abs(b);
    const u = ['B', 'KiB', 'MiB', 'GiB', 'TiB']; let i = 0;
    while (b >= 1024 && i < u.length - 1) { b /= 1024; i++; }
    return (neg ? '-' : '') + (i === 0 ? b.toFixed(0) : b.toFixed(b >= 100 ? 0 : b >= 10 ? 1 : 2)) + ' ' + u[i];
  };
  const set = (id, v) => { const el = $(id); if (el && el.textContent !== v) el.textContent = v; };
  const tot = (e) => e ? (e.up || 0) + (e.down || 0) : 0;
  let timer = null; let last = null;

  function navDots(level) {
    document.querySelectorAll('[data-page="usage"]').forEach((a) => {
      let d = a.querySelector('.bku-nav-dot');
      if (level === 'warn' || level === 'over') {
        if (!d) { d = document.createElement('span'); d.className = 'bku-nav-dot'; const s = a.querySelector('span'); (s || a).appendChild(d); }
        d.classList.toggle('over', level === 'over');
      } else if (d) d.remove();
    });
  }

  function render(d) {
    if (!d || !d.ok) return;
    last = d;
    set('bkuLiveUp', fmt(d.live.upBps) + '/s'); set('bkuLiveDown', fmt(d.live.downBps) + '/s');
    set('bkuDayTotal', fmt(d.day.total)); set('bkuDayUp', fmt(d.day.up)); set('bkuDayDown', fmt(d.day.down));
    set('bkuMonthTotal', fmt(d.month.used)); set('bkuMonthUp', fmt(d.month.up)); set('bkuMonthDown', fmt(d.month.down));
    set('bkuMonthKey', '(' + d.month.key + ')');
    set('bkuAllTotal', fmt(d.allTime.total)); set('bkuAllUp', fmt(d.allTime.up)); set('bkuAllDown', fmt(d.allTime.down));
    const rows = d.keys.filter((k) => k === 'VLESS-WS' || k === 'VMess-WS' || k === 'Trojan-WS' || k === 'VLESS-XHTTP' || tot(d.allTime.per[k]) > 0 || (d.active[k] || 0) > 0);
    let html = '';
    rows.forEach((k) => {
      const m = d.month.per[k] || {}; const a = d.active[k] || 0;
      html += '<tr><td><span class="bku-dot" style="background:' + (COLORS[k] || '#94a3b8') + ';box-shadow:0 0 10px ' + (COLORS[k] || '#94a3b8') + '"></span>' + escapeHtml(NAMES[k] || k) + '</td>' +
        '<td><span class="bku-pill' + (a ? ' on' : '') + '">' + a + '</span></td>' +
        '<td>' + fmt(tot(d.day.per[k])) + '</td><td>' + fmt(m.up) + '</td><td>' + fmt(m.down) + '</td><td>' + fmt(tot(m)) + '</td><td>' + fmt(tot(d.allTime.per[k])) + '</td></tr>';
    });
    const rb = $('bkuRows'); if (rb && rb.innerHTML !== html) rb.innerHTML = html;
    let foot = '<tr><td>Total</td><td></td><td>' + fmt(d.day.total) + '</td><td>' + fmt(d.month.up) + '</td><td>' + fmt(d.month.down) + '</td><td>' + fmt(d.month.total) + '</td><td>' + fmt(d.allTime.total) + '</td></tr>';
    if (d.month.baseBytes) foot += '<tr><td colspan="5">Manual monthly baseline (adjustment)</td><td>' + fmt(d.month.baseBytes) + '</td><td></td></tr>';
    const fb = $('bkuFoot'); if (fb && fb.innerHTML !== foot) fb.innerHTML = foot;

    const box = $('bkuLimit');
    if (d.limit) {
      box.hidden = false;
      const pct = Math.max(0, d.limit.pct);
      box.classList.toggle('is-warn', d.limit.level === 'warn');
      box.classList.toggle('is-over', d.limit.level === 'over');
      set('bkuLimitText', fmt(d.limit.used) + ' of ' + fmt(d.limit.bytes) + ' used this month');
      set('bkuLimitPct', pct.toFixed(1) + '%');
      $('bkuBar').style.width = Math.min(100, pct).toFixed(2) + '%';
      set('bkuLimitMsg', d.limit.level === 'over' ? 'Limit reached (estimate). Check your VPS provider usage meter.'
        : d.limit.level === 'warn' ? 'Over 80% used — ' + fmt(d.limit.remaining) + ' left this month.'
        : fmt(d.limit.remaining) + ' left this month.');
      navDots(d.limit.level);
    } else { box.hidden = true; navDots('ok'); }
    const resets = new Date(d.month.resetsAt);
    set('bkuMeta', 'Counting since ' + new Date(d.since).toLocaleString() + ' · month resets ' + resets.toUTCString().replace(':00 GMT', ' UTC').replace(' GMT', ' UTC') + (d.persisted ? ' · saved to ' + d.file : ' · not saved (data folder not writable)'));
  }

  async function load() {
    try {
      const r = await fetch(API, { cache: 'no-store', credentials: 'same-origin' });
      if (r.ok) render(await r.json());
    } catch (_) {}
  }
  async function post(path, body) {
    const r = await fetch(API + path, { method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json', 'X-BK-Req': '1' }, body: JSON.stringify(body || {}) });
    if (!r.ok) throw new Error('HTTP ' + r.status);
    render(await r.json());
  }
  const isActive = () => $('viewUsage').classList.contains('active') && document.visibilityState === 'visible';
  function schedule() { clearTimeout(timer); timer = setTimeout(async () => { await load(); schedule(); }, isActive() ? 2000 : 60000); }
  window.addEventListener('hashchange', () => { if (/usage|traffic/.test(window.location.hash)) load(); schedule(); });
  document.addEventListener('visibilitychange', () => { if (isActive()) load(); schedule(); });

  const resetBtn = $('bkuResetBtn');
  resetBtn.addEventListener('click', async () => {
    if (!window.confirm('Reset all traffic counters (today, month and all time)?')) return;
    resetBtn.disabled = true;
    try { await post('/reset'); if (typeof showToast === 'function') showToast('Traffic counter reset'); } catch (_) { if (typeof showToast === 'function') showToast('Reset failed'); }
    resetBtn.disabled = false;
  });
  $('bkuSyncBtn').addEventListener('click', async () => {
    const v = parseFloat($('bkuSyncGb').value);
    if (!isFinite(v) || v < 0) { if (typeof showToast === 'function') showToast('Enter a valid used traffic amount in GiB'); return; }
    try { await post('/baseline', { gb: v }); $('bkuSyncGb').value = ''; if (typeof showToast === 'function') showToast('Monthly baseline updated'); } catch (_) { if (typeof showToast === 'function') showToast('Sync failed'); }
  });
  load(); schedule();
})();
