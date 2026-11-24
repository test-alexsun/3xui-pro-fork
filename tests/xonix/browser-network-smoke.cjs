const {chromium} = require('playwright-core');
const assert = require('assert');
const target = process.argv[2];
if (!target) throw new Error('supply the installed Nginx URL');
(async () => {
  const browser = await chromium.launch({headless:true, executablePath:process.env.CHROME_PATH || 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe'});
  const context = await browser.newContext();
  const page = await context.newPage();
  const cdp = await context.newCDPSession(page);
  await cdp.send('Network.enable');
  const requests = new Map();
  const errors = [], consoleErrors = [], failedResponses = [], external = [];
  const origin = new URL(target).origin;
  page.on('pageerror', e => errors.push(e.message));
  page.on('console', m => { if (m.type() === 'error') consoleErrors.push(m.text()); });
  page.on('request', r => { if (!r.url().startsWith(origin + '/') && !r.url().startsWith('data:')) external.push(r.url()); });
  page.on('response', r => { if (r.status() >= 400) failedResponses.push([r.status(),new URL(r.url()).pathname]); });
  cdp.on('Network.requestWillBeSent', e => requests.set(e.requestId, {
    url:e.request.url, method:e.request.method, type:e.type, initiator:e.initiator.type
  }));
  cdp.on('Network.responseReceived', e => {
    if (e.response.status >= 400) failedResponses.push({...requests.get(e.requestId),status:e.response.status});
  });
  const response = await page.goto(target);
  assert.equal(response.status(),200);
  await page.click('#modalButton');
  await page.keyboard.down('ArrowLeft');
  assert.equal(await page.evaluate(() => game.player.dx),-1);
  await page.keyboard.up('ArrowLeft');
  assert.equal(await page.evaluate(() => game.player.dx),0);
  await page.keyboard.press('p'); assert.equal(await page.evaluate(() => game.state),'paused');
  await page.click('#pauseButton'); assert.equal(await page.evaluate(() => game.state),'playing');
  await page.evaluate(()=>{game.restart();game.balls=[];game.player.x=10;game.player.y=10});
  await page.keyboard.press('Space'); assert.equal(await page.evaluate(()=>game.bombStock),2);
  await page.evaluate(()=>{game.player.x=11;game.player.y=10}); await page.keyboard.press('m');
  assert.equal(await page.evaluate(()=>game.mineStock),4);
  assert.equal(await page.evaluate(()=>{game.balls=[];game.trail=[90];game.trailSet=new Set([90]);game.capture();const captured=game.filled>=75;game.update(3);return captured}),true);
  await page.click('#restartButton'); assert.equal(await page.evaluate(()=>game.lives),3);
  await page.waitForTimeout(1000);
  assert.deepStrictEqual(errors,[]); assert.deepStrictEqual(external,[]);
  assert.deepStrictEqual(consoleErrors,[]); assert.deepStrictEqual(failedResponses,[]);
  await browser.close(); console.log('INSTALLED_NGINX_BROWSER_SMOKE_PASS');
})().catch(error=>{console.error(error.stack);process.exit(1)});
