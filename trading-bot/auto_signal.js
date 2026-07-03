#!/usr/bin/env node
/**
 * XTB US100 — Signal Automator (Node.js)
 *
 * - Surveille xtb_bot_playwright.log en temps réel
 * - Détecte les signaux LONG / SHORT
 * - Connecte à Chrome via CDP (port 9222)
 * - Pré-remplit le formulaire d'ordre xStation5 (prix, SL, TP, volume)
 * - Notification Windows système
 *
 * Lancer : node auto_signal.js
 * Arrêter : Ctrl+C
 */

'use strict';

const fs   = require('fs');
const http = require('http');
const path = require('path');
const { exec } = require('child_process');

let WebSocket;
try {
  WebSocket = require('ws');
} catch {
  console.error('[ERREUR] Dépendance manquante — lancer: npm install');
  process.exit(1);
}

// ── Configuration ─────────────────────────────────────────────────────────────
const LOG_PATH  = path.join(__dirname, 'xtb_bot_playwright.log');
const CDP_URL   = 'http://127.0.0.1:9222';
const VOLUME    = 0.1;   // lots par défaut
const POLL_MS   = 1500;  // lecture log toutes les 1.5s

// ── État ──────────────────────────────────────────────────────────────────────
let lastSignal  = 'SKIP';
let lastGrade   = null;
let lastLogSize = 0;
let cdpWs       = null;
let cdpReady    = false;

// ── Parser log ────────────────────────────────────────────────────────────────
function parseLogTail(text) {
  const lines = text.split('\n');
  const result = { signal: 'SKIP', grade: null, entry: null, sl: null, tp1: null, tp2: null, atr: null };

  for (let i = lines.length - 1; i >= 0; i--) {
    const l = lines[i];

    if (!result.signal || result.signal === 'SKIP') {
      if (/SIGNAL PRO/.test(l)) {
        if (/\bLONG\b/.test(l))  result.signal = 'LONG';
        else if (/\bSHORT\b/.test(l)) result.signal = 'SHORT';
        else result.signal = 'SKIP';
      }
    }
    if (!result.grade) {
      const m = l.match(/GRADE\s+(A\+|A|B|SKIP)/);
      if (m) result.grade = m[1];
    }
    if (!result.entry) {
      const m = l.match(/[Ee]ntry[:\s]+([\d.]+)/);
      if (m) result.entry = parseFloat(m[1]);
    }
    if (!result.sl) {
      const m = l.match(/\bSL[:\s]+([\d.]+)/);
      if (m) result.sl = parseFloat(m[1]);
    }
    if (!result.tp1) {
      const m = l.match(/\bTP1?[:\s]+([\d.]+)/);
      if (m) result.tp1 = parseFloat(m[1]);
    }
    if (!result.tp2) {
      const m = l.match(/\bTP2[:\s]+([\d.]+)/);
      if (m) result.tp2 = parseFloat(m[1]);
    }
    if (!result.atr) {
      const m = l.match(/ATR\s*:\s*([\d.]+)/);
      if (m) result.atr = parseFloat(m[1]);
    }

    // S'arrêter au début du bloc de scan courant
    if (/── SCAN/.test(l) && result.signal !== 'SKIP') break;
  }
  return result;
}

// ── Notification Windows (tray balloon) ───────────────────────────────────────
function notify(title, body) {
  const ps = `
    Add-Type -AssemblyName System.Windows.Forms
    Add-Type -AssemblyName System.Drawing
    $n = New-Object System.Windows.Forms.NotifyIcon
    $n.Icon = [System.Drawing.SystemIcons]::Information
    $n.Visible = $true
    $n.BalloonTipTitle = '${title.replace(/'/g, "''")}'
    $n.BalloonTipText  = '${body.replace(/'/g, "''")}'
    $n.BalloonTipIcon  = 'Info'
    $n.ShowBalloonTip(8000)
    Start-Sleep -Seconds 9
    $n.Dispose()
  `.trim();

  exec(`powershell -NoProfile -WindowStyle Hidden -Command "${ps}"`,
    (err) => { if (err) console.warn('[NOTIF] Erreur PowerShell:', err.message); });
}

// ── CDP ────────────────────────────────────────────────────────────────────────
function getCDPTargets() {
  return new Promise((resolve, reject) => {
    http.get(`${CDP_URL}/json`, (res) => {
      let data = '';
      res.on('data', d => data += d);
      res.on('end', () => {
        try { resolve(JSON.parse(data)); }
        catch (e) { reject(e); }
      });
    }).on('error', reject);
  });
}

async function connectCDP() {
  try {
    const targets = await getCDPTargets();
    const tab = targets.find(t => t.type === 'page' && t.url.includes('xstation5.xtb.com'));
    if (!tab) { console.log('[CDP] Onglet xStation5 introuvable'); return; }

    if (cdpWs) try { cdpWs.terminate(); } catch {}
    cdpWs = new WebSocket(tab.webSocketDebuggerUrl);

    cdpWs.on('open', () => {
      cdpReady = true;
      console.log('[CDP] Connecté — xStation5 prêt');
    });
    cdpWs.on('error', (e) => {
      cdpReady = false;
      console.log('[CDP] Erreur WS:', e.message);
    });
    cdpWs.on('close', () => {
      cdpReady = false;
      console.log('[CDP] Déconnecté — tentative reconnexion dans 10s');
      setTimeout(connectCDP, 10000);
    });
  } catch (e) {
    console.log('[CDP] Connexion échouée:', e.message);
    setTimeout(connectCDP, 10000);
  }
}

function cdpEval(expression) {
  return new Promise((resolve) => {
    if (!cdpReady || !cdpWs || cdpWs.readyState !== WebSocket.OPEN) {
      resolve(null); return;
    }
    const id = Date.now() + Math.floor(Math.random() * 1000);
    const timer = setTimeout(() => {
      cdpWs.off('message', handler);
      resolve(null);
    }, 6000);

    function handler(raw) {
      try {
        const msg = JSON.parse(raw);
        if (msg.id === id) {
          clearTimeout(timer);
          cdpWs.off('message', handler);
          resolve(msg.result);
        }
      } catch {}
    }
    cdpWs.on('message', handler);
    cdpWs.send(JSON.stringify({ id, method: 'Runtime.evaluate',
      params: { expression, returnByValue: true } }));
  });
}

// ── Pré-remplissage formulaire xStation5 ─────────────────────────────────────
async function prefillOrder(side, entry, sl, tp1, vol) {
  // Helper Angular setter
  const setValJS = (selector, value) => `
    (function(){
      var el = document.querySelector('${selector}');
      if (!el) return false;
      var ctrl = window.$ && $(el).data('$ngModelController');
      if (ctrl) {
        ctrl.$setViewValue('${value}');
        ctrl.$commitViewValue();
        ctrl.$render();
        return true;
      }
      var desc = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value');
      if (desc) {
        desc.set.call(el,'${value}');
        el.dispatchEvent(new Event('input',{bubbles:true}));
        el.dispatchEvent(new Event('change',{bubbles:true}));
      }
      return true;
    })()
  `;

  // Cliquer sur l'onglet Buy ou Sell dans le panneau d'ordre
  const clickSide = `
    (function(){
      var btns = Array.from(document.querySelectorAll('button, [class*="buy"], [class*="sell"], [class*="tab"]'));
      var target = btns.find(b => b.textContent.trim().toUpperCase() === '${side}');
      if (target) { target.click(); return 'clicked: ' + target.textContent.trim(); }
      return 'not found';
    })()
  `;

  const r1 = await cdpEval(clickSide);
  console.log('[CDP] Side button:', JSON.stringify(r1));

  // Volume
  if (vol)   await cdpEval(setValJS('[ng-model*="volume"],[name*="volume"]', vol));
  // SL
  if (sl)    await cdpEval(setValJS('[ng-model*="sl"],[ng-model*="stopLoss"],[name*="sl"]', sl));
  // TP
  if (tp1)   await cdpEval(setValJS('[ng-model*="tp"],[ng-model*="takeProfit"],[name*="tp"]', tp1));

  console.log(`[CDP] Formulaire pré-rempli — ${side} | Vol:${vol} | SL:${sl} | TP:${tp1}`);
}

// ── Boucle principale ─────────────────────────────────────────────────────────
async function main() {
  console.log('╔══════════════════════════════════════════════════╗');
  console.log('║   XTB US100 — Signal Automator (Node.js)        ║');
  console.log('║   Log  : xtb_bot_playwright.log                 ║');
  console.log('║   CDP  : localhost:9222                         ║');
  console.log('╚══════════════════════════════════════════════════╝\n');

  await connectCDP();

  setInterval(async () => {
    // Reconnexion CDP si nécessaire
    if (!cdpReady) return;

    // Lire le log
    let stat;
    try { stat = fs.statSync(LOG_PATH); } catch { return; }
    if (stat.size === lastLogSize) return;
    lastLogSize = stat.size;

    const readSize = Math.min(4096, stat.size);
    const buf = Buffer.alloc(readSize);
    const fd  = fs.openSync(LOG_PATH, 'r');
    fs.readSync(fd, buf, 0, readSize, stat.size - readSize);
    fs.closeSync(fd);

    const { signal, grade, entry, sl, tp1, tp2, atr } = parseLogTail(buf.toString('utf8'));

    // Retour au SKIP
    if (signal === 'SKIP') {
      if (lastSignal !== 'SKIP') {
        console.log(`[${ts()}] Signal → SKIP`);
        lastSignal = 'SKIP';
      }
      return;
    }

    // Nouveau signal actionnable
    if (signal !== lastSignal || grade !== lastGrade) {
      lastSignal = signal;
      lastGrade  = grade;

      const banner = [
        '═'.repeat(54),
        ` ▶  SIGNAL ${signal}  — GRADE ${grade}`,
        ` Entry : ${entry ?? 'prix marché'}`,
        ` SL    : ${sl ?? '—'}`,
        ` TP1   : ${tp1 ?? '—'}   TP2 : ${tp2 ?? '—'}`,
        ` ATR   : ${atr ?? '—'} pts   Vol : ${VOLUME} lot`,
        '═'.repeat(54),
        ' ➤  CLIQUEZ BUY/SELL DANS XSTATION5',
        '═'.repeat(54),
      ].join('\n');

      console.log('\n' + banner + '\n');

      // Notification Windows
      const notifBody =
        `${signal} Grade ${grade}\n` +
        `Entry: ${entry ?? 'marché'}  SL: ${sl}  TP1: ${tp1}\n` +
        `➤ Cliquez ${side} dans xStation5`;
      notify(`⚡ SIGNAL US100 ${signal}`, notifBody.replace('${side}', signal));

      // Pré-remplir formulaire
      if (cdpReady) {
        await prefillOrder(signal, entry, sl, tp1, VOLUME);
      }
    }

  }, POLL_MS);

  console.log(`[${ts()}] Surveillance active (Ctrl+C pour arrêter)\n`);
  process.on('SIGINT', () => {
    console.log('\n[AUTO] Arrêt propre.');
    if (cdpWs) cdpWs.terminate();
    process.exit(0);
  });
}

function ts() {
  return new Date().toISOString().replace('T', ' ').substr(0, 19) + ' GMT';
}

main().catch(console.error);
