process.umask(0o077);
const { chromium } = require('playwright-core');
const fs = require('node:fs/promises');
const path = require('node:path');
const { execFileSync } = require('node:child_process');
const tls = require('node:tls');
const net = require('node:net');
const { X509Certificate } = require('node:crypto');
const assert = require('node:assert/strict');

const EXPECTED_TAGS = [
  'VLESS-REALITY-XHTTP-H2',
  'VLESS-TLS-XHTTP-H2',
  'VLESS-REALITY-VISION',
  'WIREGUARD',
  'AMNEZIAWG-3.1',
  'HYSTERIA2',
];

function isRfc1918(address) {
  if (typeof address !== 'string' || !net.isIPv4(address)) return false;
  const parts = address.split('.').map(Number);
  if (parts.length !== 4 || parts.some(n => !Number.isInteger(n) || n < 0 || n > 255)) {
    return false;
  }
  const [a, b] = parts;
  return a === 10 || (a === 172 && b >= 16 && b <= 31) || (a === 192 && b === 168);
}

async function loadCa() {
  if (process.env.PREVIEW08_CA) {
    return {
      source: 'PREVIEW08_CA',
      buffer: await fs.readFile(process.env.PREVIEW08_CA),
    };
  }
  for (const candidate of ['/tmp/preview08-ca/root.pem', '/tmp/preview06a-ca/root.pem']) {
    try {
      const buffer = await fs.readFile(candidate);
      return { source: candidate, buffer };
    } catch (err) {
      if (err.code !== 'ENOENT') throw err;
    }
  }
  throw new Error('Lab CA not found at /tmp/preview08-ca/root.pem or /tmp/preview06a-ca/root.pem');
}

function getPanelCredentials() {
  try {
    const logs = execFileSync(
      'journalctl',
      ['-u', '3xui-pro-fork.service', '-o', 'cat', '--no-pager', '--grep=Username:|Password:'],
      { encoding: 'utf8', maxBuffer: 4 * 1024 * 1024 }
    );
    const matches = Array.from(logs.matchAll(/Username:\s*(\S+)\s+Password:\s*(\S+)/g));
    if (matches.length > 0) {
      const latest = matches[matches.length - 1];
      return { username: latest[1], password: latest[2], source: 'journalctl' };
    }
  } catch {
    // Fall back to explicit environment credentials when journalctl is unavailable or unmatched.
  }
  const envUser = process.env.PREVIEW08_PANEL_USER;
  const envPass = process.env.PREVIEW08_PANEL_PASS;
  if (envUser && envPass) {
    return { username: envUser, password: envPass, source: 'env' };
  }
  throw new Error('Panel credentials unavailable from journalctl or PREVIEW08_PANEL_USER/PREVIEW08_PANEL_PASS');
}

function makeRedactor(secrets) {
  return value => {
    let text = String(value ?? '');
    for (const secret of secrets) {
      if (typeof secret === 'string' && secret.length > 0) {
        text = text.split(secret).join('[REDACTED]');
      }
    }
    text = text.replace(/(Authorization:\s*Bearer\s+)\S+/gi, '$1[REDACTED]');
    return text;
  };
}

function assertSanitized(serialized, strictSecrets) {
  for (const secret of strictSecrets) {
    if (typeof secret === 'string' && secret.length > 0 && serialized.includes(secret)) {
      throw new Error('Sanitization guard failed: secret material detected in report');
    }
  }
}

async function waitForCondition(page, fn, arg, timeoutMs = 20000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const remaining = Math.max(500, deadline - Date.now());
      await page.waitForFunction(fn, arg, { timeout: remaining, polling: 200 });
      return true;
    } catch (err) {
      const msg = err && err.message ? err.message : String(err);
      if (/Execution context was destroyed|Cannot find context|navigation/i.test(msg)) {
        await page.waitForLoadState('domcontentloaded', { timeout: 5000 }).catch(() => {});
        continue;
      }
      return false;
    }
  }
  return false;
}

(async () => {
  const outputPath = process.env.PREVIEW08_UI_OUTPUT || '/tmp/preview08-ui-results.json';
  const redactSecrets = [];
  const strictSecrets = [];
  const redact = makeRedactor(redactSecrets);

  const report = {
    status: 'FAIL',
    scope: 'disposable Debian13 preview-08 UI',
    rfc1918_lab_bind: false,
    tls_pinning: 'NOT_RUN',
    step_a_xonix: { status: 'NOT_RUN' },
    step_b_panel_inbounds: { status: 'NOT_RUN' },
    step_c_clients: { status: 'NOT_RUN' },
  };

  let browser;
  try {
    const web = JSON.parse(await fs.readFile('/var/lib/3xui-pro-fork/preview-web.json', 'utf8'));
    assert.ok(isRfc1918(web.public_address), 'LAB ONLY: preview-web.json public_address must be RFC1918');
    report.rfc1918_lab_bind = true;

    const state = JSON.parse(await fs.readFile('/var/lib/3xui-pro-fork/preview-panel.json', 'utf8'));
    assert.ok(state && typeof state.domain === 'string' && state.domain.length > 0, 'Missing panel domain');
    assert.ok(state.layout && typeof state.layout.panel_path === 'string' && state.layout.panel_path.length > 0, 'Missing panel_path');
    if (web.domain) {
      assert.equal(state.domain, web.domain, 'preview-web.json and preview-panel.json domains differ');
    }

    const barePanelPath = state.layout.panel_path.replace(/\/+$/, '');
    redactSecrets.push(state.layout.panel_path);
    strictSecrets.push(state.layout.panel_path);
    if (barePanelPath.length > 1) {
      redactSecrets.push(barePanelPath);
      strictSecrets.push(barePanelPath);
    }
    if (state.api_token) {
      redactSecrets.push(state.api_token);
      strictSecrets.push(state.api_token);
    }

    const domain = state.domain;
    const origin = 'https://' + domain;
    const target = origin + state.layout.panel_path;
    report.domain = domain;

    const pem = await fs.readFile('/var/lib/3xui-preview-acme/config/live/3xui-preview/fullchain.pem');
    const expected = new X509Certificate(pem).raw.toString('base64');
    const caInfo = await loadCa();
    const ca = caInfo.buffer;

    async function verifyTls() {
      await new Promise((resolve, reject) => {
        const s = tls.connect(
          { host: domain, port: 443, servername: domain, ca, rejectUnauthorized: true },
          () => {
            try {
              assert.equal(s.getPeerCertificate().raw.toString('base64'), expected, 'TLS leaf certificate mismatch');
              s.end();
              resolve();
            } catch (err) {
              s.destroy();
              reject(err);
            }
          }
        );
        s.on('error', reject);
        s.setTimeout(5000, () => s.destroy(new Error('TLS timeout')));
      });
    }

    await verifyTls();
    report.tls_pinning = 'PASS';

    browser = await chromium.launch({
      executablePath: process.env.CHROME_PATH || '/usr/bin/chromium',
      headless: true,
      args: ['--no-proxy-server', '--disable-dev-shm-usage'],
    });

    const page = await browser.newPage({ viewport: { width: 1440, height: 1080 } });
    const cdp = await page.context().newCDPSession(page);
    await cdp.send('Network.enable');
    await cdp.send('Security.enable');
    await cdp.send('Security.setOverrideCertificateErrors', { override: true });

    cdp.on('Security.certificateError', async e => {
      let action = 'cancel';
      try {
        const reqUrl = new URL(e.requestURL);
        if ((reqUrl.origin === origin || reqUrl.origin === 'wss://' + domain) &&
            /^(?:net::)?ERR_CERT_AUTHORITY_INVALID$/.test(e.errorType)) {
          await verifyTls();
          action = 'continue';
        }
      } catch {
        // Keep cancellation on invalid URL or failed TLS verification.
      }
      await cdp.send('Security.handleCertificateError', { eventId: e.eventId, action });
    });

    const buckets = {
      stepA: { consoleErrors: [], pageErrors: [] },
      stepB: { consoleErrors: [], pageErrors: [] },
      stepC: { consoleErrors: [], pageErrors: [] },
    };
    let currentStep = 'stepA';

    page.on('pageerror', err => {
      buckets[currentStep].pageErrors.push(redact(err && err.message ? err.message : String(err)));
    });
    page.on('console', msg => {
      if (msg.type() === 'error') {
        buckets[currentStep].consoleErrors.push(redact(msg.text()));
      }
    });

    // Step A: XONIX decoy site at https://<domain>/
    currentStep = 'stepA';
    const xonixResponse = await page.goto(origin + '/', { waitUntil: 'networkidle', timeout: 30000 });
    assert.ok(xonixResponse, 'No response from XONIX decoy site');
    assert.equal(xonixResponse.status(), 200, 'Expected HTTP 200 from XONIX decoy site');
    assert.equal((await cdp.send('Network.getCertificate', { origin })).tableNames[0], expected, 'Chromium XONIX cert mismatch');
    const title = await page.title();
    assert.match(title, /XONIX/i, 'Unexpected XONIX page title');

    const canvas = page.locator('canvas').first();
    await canvas.waitFor({ state: 'visible', timeout: 10000 });
    const box = await canvas.boundingBox();
    assert.ok(box && box.width > 0 && box.height > 0, 'XONIX canvas bounding box must be non-zero');

    report.step_a_xonix = {
      status: buckets.stepA.consoleErrors.length === 0 && buckets.stepA.pageErrors.length === 0 ? 'PASS' : 'FAIL',
      http_status: xonixResponse.status(),
      title_matched: /XONIX/i.test(title),
      canvas_present: true,
      canvas_box: { width: Math.round(box.width), height: Math.round(box.height) },
      console_error_count: buckets.stepA.consoleErrors.length,
      pageerror_count: buckets.stepA.pageErrors.length,
    };
    assert.equal(buckets.stepA.pageErrors.length, 0, 'XONIX pageerror(s): ' + buckets.stepA.pageErrors.join('; '));
    assert.equal(buckets.stepA.consoleErrors.length, 0, 'XONIX console error(s): ' + buckets.stepA.consoleErrors.join('; '));

    // Step B: 3x-ui Panel login, auth cookies, Inbounds table & 6 enabled protocols
    currentStep = 'stepB';
    const creds = getPanelCredentials();
    redactSecrets.push(creds.password);
    strictSecrets.push(creds.password);
    if (creds.username.length >= 6) {
      redactSecrets.push(creds.username);
      strictSecrets.push(creds.username);
    }

    const panelResponse = await page.goto(target, { waitUntil: 'networkidle', timeout: 30000 });
    assert.ok(panelResponse && panelResponse.status() < 400, 'Failed to load panel login page');
    assert.equal((await cdp.send('Network.getCertificate', { origin })).tableNames[0], expected, 'Chromium Panel cert mismatch');

    const userInput = page.locator('input[type="text"]').first();
    const passInput = page.locator('input[type="password"]').first();
    await userInput.waitFor({ state: 'visible', timeout: 15000 });
    await passInput.waitFor({ state: 'visible', timeout: 15000 });
    await userInput.fill(creds.username);
    await passInput.fill(creds.password);
    await page.locator('button[type="submit"]').click();

    const inboundsMenu = page.getByRole('menuitem', { name: /Inbounds/i });
    await inboundsMenu.waitFor({ state: 'visible', timeout: 20000 });

    const cookies = await page.context().cookies([target, page.url()]);
    const authCookies = cookies.filter(c => c.httpOnly || /(?:3x-ui|x-ui|session|auth|token)/i.test(c.name));
    assert.ok(cookies.length > 0 && authCookies.length > 0, 'No auth cookies found after panel login');
    for (const cookie of authCookies) {
      assert.equal(cookie.httpOnly, true, `Cookie ${cookie.name} must have httpOnly=true`);
      assert.equal(cookie.secure, true, `Cookie ${cookie.name} must have secure=true`);
      assert.match(String(cookie.sameSite || ''), /^lax$/i, `Cookie ${cookie.name} must have sameSite=Lax`);
    }

    await inboundsMenu.click();
    await page.waitForLoadState('networkidle', { timeout: 15000 }).catch(() => {});
    await waitForCondition(
      page,
      tags => {
        if (document.querySelector('.ant-spin-spinning')) return false;
        const rows = Array.from(document.querySelectorAll('table tbody tr')).filter(tr => {
          if (tr.classList.contains('ant-table-measure-row') ||
              tr.classList.contains('ant-table-placeholder') ||
              tr.classList.contains('ant-table-expanded-row')) {
            return false;
          }
          const rect = tr.getBoundingClientRect();
          return rect.width > 0 && rect.height > 0;
        });
        if (rows.length === 0) return false;
        return tags.every(tag => rows.some(tr => (tr.innerText || '').includes(tag)));
      },
      EXPECTED_TAGS,
      15000
    );

    const inboundInspection = await page.evaluate(tags => {
      const rows = Array.from(document.querySelectorAll('table tbody tr')).filter(tr => {
        if (tr.classList.contains('ant-table-measure-row') ||
            tr.classList.contains('ant-table-placeholder') ||
            tr.classList.contains('ant-table-expanded-row')) {
          return false;
        }
        const rect = tr.getBoundingClientRect();
        return rect.width > 0 && rect.height > 0;
      });
      const byTag = {};
      for (const tag of tags) {
        const matched = rows.filter(tr => (tr.innerText || '').includes(tag));
        if (matched.length === 0) {
          byTag[tag] = { visible: false, enabled: false, toggle_type: 'missing', row_matches: 0 };
          continue;
        }
        const tr = matched[0];
        const switches = Array.from(tr.querySelectorAll('.ant-switch, [role="switch"]'));
        const statusCheckboxes = Array.from(tr.querySelectorAll('input[type="checkbox"]:not(.ant-checkbox-input)'));
        const fallbackCheckboxes = Array.from(tr.querySelectorAll('input[type="checkbox"]'));
        let enabled = false;
        let toggleType = 'missing';
        if (switches.length > 0) {
          toggleType = 'ant-switch';
          enabled = switches.every(sw => sw.classList.contains('ant-switch-checked') || sw.getAttribute('aria-checked') === 'true');
        } else if (statusCheckboxes.length > 0) {
          toggleType = 'checkbox';
          enabled = statusCheckboxes.every(cb => cb.checked);
        } else if (fallbackCheckboxes.length > 0) {
          toggleType = 'checkbox';
          enabled = fallbackCheckboxes.every(cb => cb.checked);
        }
        byTag[tag] = {
          visible: true,
          enabled,
          toggle_type: toggleType,
          row_matches: matched.length,
        };
      }
      return { total_visible_rows: rows.length, by_tag: byTag };
    }, EXPECTED_TAGS);

    const allSixVisible = EXPECTED_TAGS.every(tag => inboundInspection.by_tag[tag].visible);
    const allSixEnabled = EXPECTED_TAGS.every(tag => inboundInspection.by_tag[tag].enabled);

    report.step_b_panel_inbounds = {
      status: allSixVisible && allSixEnabled && buckets.stepB.pageErrors.length === 0 ? 'PASS' : 'FAIL',
      credentials_source: creds.source,
      auth_cookies: {
        count: authCookies.length,
        httpOnly: authCookies.every(c => c.httpOnly === true),
        secure: authCookies.every(c => c.secure === true),
        sameSite_lax: authCookies.every(c => /^lax$/i.test(String(c.sameSite || ''))),
      },
      total_visible_rows: inboundInspection.total_visible_rows,
      all_six_visible: allSixVisible,
      all_six_enabled: allSixEnabled,
      inbounds: inboundInspection.by_tag,
      console_error_count: buckets.stepB.consoleErrors.length,
      pageerror_count: buckets.stepB.pageErrors.length,
    };

    assert.equal(buckets.stepB.pageErrors.length, 0, 'Panel Inbounds pageerror(s): ' + buckets.stepB.pageErrors.join('; '));
    assert.ok(allSixVisible, 'Missing expected inbound tags in panel UI: ' +
      EXPECTED_TAGS.filter(tag => !inboundInspection.by_tag[tag].visible).join(', '));
    assert.ok(allSixEnabled, 'Disabled or unverified inbound row toggle(s) in panel UI: ' +
      EXPECTED_TAGS.filter(tag => !inboundInspection.by_tag[tag].enabled).join(', '));

    // Step C: Clients view
    currentStep = 'stepC';
    const clientsMenu = page.getByRole('menuitem', { name: /^Clients$/i });
    await clientsMenu.waitFor({ state: 'visible', timeout: 10000 });
    await clientsMenu.click();
    await page.mouse.move(1250, 700);
    await page.waitForLoadState('networkidle', { timeout: 15000 }).catch(() => {});

    await waitForCondition(
      page,
      () => {
        if (document.querySelector('.ant-spin-spinning')) return false;
        const rows = Array.from(document.querySelectorAll('table tbody tr')).filter(tr => {
          if (tr.classList.contains('ant-table-measure-row') ||
              tr.classList.contains('ant-table-placeholder') ||
              tr.classList.contains('ant-table-expanded-row')) {
            return false;
          }
          const rect = tr.getBoundingClientRect();
          return rect.width > 0 && rect.height > 0 && (tr.innerText || '').trim().length > 0;
        });
        return rows.length > 0;
      },
      null,
      20000
    );

    const clientsInspection = await page.evaluate(() => {
      const tables = Array.from(document.querySelectorAll('table'));
      let targetTable = null;
      let dataRows = [];
      for (const table of tables) {
        const rows = Array.from(table.querySelectorAll('tbody tr')).filter(tr => {
          if (tr.classList.contains('ant-table-measure-row') ||
              tr.classList.contains('ant-table-placeholder') ||
              tr.classList.contains('ant-table-expanded-row')) {
            return false;
          }
          const rect = tr.getBoundingClientRect();
          return rect.width > 0 && rect.height > 0;
        });
        if (rows.length > 0) {
          targetTable = table;
          dataRows = rows;
          break;
        }
      }
      if (!targetTable) {
        return { table_loaded: false, email_column_found: false, rendered_row_count: 0, non_empty_email_count: 0 };
      }
      const headers = Array.from(targetTable.querySelectorAll('thead th'));
      const emailColIdx = headers.findIndex(th => /\bemail\b/i.test((th.innerText || '').trim()));
      let nonEmptyEmailCount = 0;
      for (const tr of dataRows) {
        const cells = Array.from(tr.querySelectorAll('td'));
        if (emailColIdx >= 0 && cells[emailColIdx]) {
          if ((cells[emailColIdx].innerText || '').trim().length > 0) {
            nonEmptyEmailCount++;
          }
        } else if (cells.some(td => (td.innerText || '').trim().length > 0)) {
          nonEmptyEmailCount++;
        }
      }
      return {
        table_loaded: dataRows.length > 0,
        email_column_found: emailColIdx >= 0,
        rendered_row_count: dataRows.length,
        non_empty_email_count: nonEmptyEmailCount,
      };
    });

    const clientsPass =
      clientsInspection.table_loaded &&
      clientsInspection.rendered_row_count > 0 &&
      clientsInspection.non_empty_email_count === clientsInspection.rendered_row_count &&
      buckets.stepC.consoleErrors.length === 0 &&
      buckets.stepC.pageErrors.length === 0;

    report.step_c_clients = {
      status: clientsPass ? 'PASS' : 'FAIL',
      ...clientsInspection,
      console_error_count: buckets.stepC.consoleErrors.length,
      pageerror_count: buckets.stepC.pageErrors.length,
    };

    assert.equal(buckets.stepC.pageErrors.length, 0, 'Clients pageerror(s): ' + buckets.stepC.pageErrors.join('; '));
    assert.equal(buckets.stepC.consoleErrors.length, 0, 'Clients console error(s): ' + buckets.stepC.consoleErrors.join('; '));
    assert.ok(clientsInspection.table_loaded && clientsInspection.rendered_row_count > 0, 'Clients table rendered zero rows');
    assert.equal(clientsInspection.non_empty_email_count, clientsInspection.rendered_row_count, 'One or more client rows lack rendered email');

    report.status = 'PASS';
  } catch (err) {
    report.status = 'FAIL';
    report.error = redact(err && err.message ? err.message : String(err));
    process.exitCode = 1;
  } finally {
    if (browser) {
      await browser.close().catch(() => {});
    }
    const serialized = JSON.stringify(report, null, 2) + '\n';
    assertSanitized(serialized, strictSecrets);
    await fs.mkdir(path.dirname(outputPath), { recursive: true, mode: 0o700 });
    await fs.writeFile(outputPath, serialized, { mode: 0o600 });
    process.stdout.write(serialized);
  }
})();
