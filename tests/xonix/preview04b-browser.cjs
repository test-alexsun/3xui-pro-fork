const { chromium } = require('playwright-core');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const { X509Certificate } = require('node:crypto');
const tls = require('node:tls');
const https = require('node:https');

function verifyLabCertificate(url, ca, expected) {
  return new Promise((resolve, reject) => {
    const socket = tls.connect({
      host: '127.0.0.1', port: Number(url.port || 443), servername: url.hostname,
      ca, rejectUnauthorized: true,
    }, () => {
      const leaf = socket.getPeerCertificate().raw.toString('base64');
      socket.end();
      if (leaf !== expected) reject(new Error('TLS peer certificate differs from lab certificate'));
      else resolve();
    });
    socket.setTimeout(5000, () => socket.destroy(new Error('TLS preflight timed out')));
    socket.once('error', reject);
  });
}

function checkMissingPanelRoute(url, ca, expected) {
  return new Promise((resolve, reject) => {
    const request = https.get({
      host: '127.0.0.1', port: Number(url.port || 443), servername: url.hostname,
      headers: { Host: url.host }, path: url.pathname, ca, rejectUnauthorized: true,
    }, response => {
      try {
        assert.ok(response.socket.getPeerCertificate().raw.toString('base64') === expected,
          'panel API TLS peer differs from lab certificate');
        assert.ok([401, 403, 404].includes(response.statusCode),
          'unexpected response to missing panel API route: ' + response.statusCode);
      } catch (error) {
        response.resume();
        reject(error);
        return;
      }
      let body = '';
      response.setEncoding('utf8');
      response.on('data', data => { body += data; });
      response.once('error', reject);
      response.once('end', () => {
        if (/<title>[^<]*XONIX/i.test(body)) reject(new Error('missing panel API route returned XONIX'));
        else resolve(response.statusCode);
      });
    });
    request.setTimeout(10000, () => request.destroy(new Error('panel API request timed out')));
    request.once('error', reject);
  });
}

async function main() {
  const [target, certificate] = process.argv.slice(2);
  if (!target || !certificate) throw new Error('usage: node preview04b-browser.cjs HTTPS_URL CERT_PEM');
  const origin = new URL(target);
  const panel = new URL('/panel/api/preview04b-missing', origin);
  panel.hostname = 'panel.' + origin.hostname;
  const ca = await fs.readFile(certificate);
  const expected = new X509Certificate(ca).raw.toString('base64');
  for (const url of [origin, panel]) await verifyLabCertificate(url, ca, expected);
  const browser = await chromium.launch({
    executablePath: process.env.CHROME_PATH || '/usr/bin/chromium',
    headless: true,
    timeout: 90000,
    args: ['--no-proxy-server',
      '--host-resolver-rules=MAP ' + origin.hostname + ' 127.0.0.1, ' +
      'MAP ' + panel.hostname + ' 127.0.0.1, EXCLUDE localhost'],
  });
  try {
    const page = await browser.newPage();
    const errors = [], external = [], failed = [], requests = [];
    const cdp = await page.context().newCDPSession(page);
    await cdp.send('Network.enable');
    await cdp.send('Security.enable');
    await cdp.send('Security.setOverrideCertificateErrors', {override: true});
    // Trust only the validated lab peer on these two loopback HTTPS origins.
    // All other certificate errors are rejected. Check Chrome's actual leaf
    // separately after each HTTPS navigation.
    cdp.on('Security.certificateError', async event => {
      const url = new URL(event.requestURL);
      let action = 'cancel';
      if ([origin.origin, panel.origin].includes(url.origin) &&
          /^(?:net::)?ERR_CERT_AUTHORITY_INVALID$/.test(event.errorType)) {
        try {
          await verifyLabCertificate(url, ca, expected);
          action = 'continue';
        } catch {
          // Retain cancellation if validation fails.
        }
      }
      await cdp.send('Security.handleCertificateError', {eventId: event.eventId, action});
    });
    cdp.on('Network.requestWillBeSent', ({request}) => requests.push(new URL(request.url).pathname));
    async function checkCertificate(url) {
      const {tableNames} = await cdp.send('Network.getCertificate', {origin: url.origin});
      assert.ok(tableNames[0] === expected, 'Chromium received a different TLS certificate');
    }
    page.on('pageerror', error => errors.push(error.message));
    page.on('console', message => {
      if (message.type() === 'error') errors.push(message.text());
    });
    page.on('request', request => {
      const url = new URL(request.url());
      if (url.origin !== origin.origin && url.protocol !== 'data:') external.push(request.url());
    });
    page.on('response', response => {
      if (response.status() >= 400) failed.push(response.status() + ' ' + response.url());
    });
    const response = await page.goto(origin.href, {waitUntil: 'load', timeout: 90000});
    assert.equal(response.status(), 200);
    await checkCertificate(origin);
    assert.match(await page.title(), /XONIX/i);
    await page.click('#modalButton');
    await page.keyboard.down('ArrowLeft');
    assert.equal(await page.evaluate(() => game.player.dx), -1);
    await page.keyboard.up('ArrowLeft');
    assert.equal(await page.evaluate(() => game.player.dx), 0);
    await page.waitForTimeout(700);
    assert.deepEqual(errors, []);
    assert.deepEqual(external, []);
    assert.deepEqual(failed, []);
    assert.ok(!requests.includes('/favicon.ico'));
    for (const path of ['/preview04b-missing', '/.preview04b-private']) {
      assert.equal((await page.goto(new URL(path, origin).href)).status(), 404);
    }
    const listing = await page.goto(new URL('/.well-known/acme-challenge/', origin).href);
    assert.ok([403, 404].includes(listing.status()));
    console.log('PREVIEW04B_XONIX_BROWSER_HTTPS_PASS');
    const status = await checkMissingPanelRoute(panel, ca, expected);
    console.log('PREVIEW04B_MISSING_PANEL_API_PASS status=' + status);
  } finally {
    await browser.close();
  }
}

main().catch(error => {
  console.error(error.message);
  process.exitCode = 1;
});
