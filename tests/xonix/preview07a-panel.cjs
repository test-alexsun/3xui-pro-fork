process.umask(0o077);
const {chromium}=require('playwright-core');
const fs=require('node:fs/promises');const {execFileSync}=require('node:child_process');const tls=require('node:tls');const {X509Certificate}=require('node:crypto');const assert=require('node:assert/strict');
(async()=>{
 const web=JSON.parse(await fs.readFile('/var/lib/3xui-pro-fork/preview-web.json','utf8'));assert.equal(web.public_address,'10.77.5.1','LAB ONLY');
 const state=JSON.parse(await fs.readFile('/var/lib/3xui-pro-fork/preview-panel.json','utf8'));const origin='https://'+state.domain;const target=origin+state.layout.panel_path;
 const pem=await fs.readFile('/var/lib/3xui-preview-acme/config/live/3xui-preview/fullchain.pem');const expected=new X509Certificate(pem).raw.toString('base64');const ca=await fs.readFile('/tmp/preview06a-ca/root.pem');
 async function verify(){await new Promise((resolve,reject)=>{const s=tls.connect({host:state.domain,port:443,servername:state.domain,ca,rejectUnauthorized:true},()=>{try{assert.equal(s.getPeerCertificate().raw.toString('base64'),expected);s.end();resolve()}catch(e){s.destroy();reject(e)}});s.on('error',reject);s.setTimeout(5000,()=>s.destroy(new Error('TLS timeout')))});}
 await verify();const browser=await chromium.launch({executablePath:'/usr/bin/chromium',headless:true,args:['--no-proxy-server','--disable-dev-shm-usage']});
 try{
  const page=await browser.newPage({viewport:{width:1440,height:1080}});const cdp=await page.context().newCDPSession(page);await cdp.send('Network.enable');await cdp.send('Security.enable');await cdp.send('Security.setOverrideCertificateErrors',{override:true});
  cdp.on('Security.certificateError',async e=>{let action='cancel';if(new URL(e.requestURL).origin===origin&&/^(?:net::)?ERR_CERT_AUTHORITY_INVALID$/.test(e.errorType)){try{await verify();action='continue'}catch{}}await cdp.send('Security.handleCertificateError',{eventId:e.eventId,action})});
  await page.goto(target,{waitUntil:'networkidle'});assert.equal((await cdp.send('Network.getCertificate',{origin})).tableNames[0],expected);
  const logs=execFileSync('journalctl',['-u','3xui-pro-fork.service','-o','cat','--no-pager','--grep=Username:|Password:'],{encoding:'utf8',maxBuffer:4*1024*1024});const credentials=logs.match(/Username: (\S+)\s+Password: (\S+)/);assert.ok(credentials);
  await page.locator('input[type="text"]').first().fill(credentials[1]);await page.locator('input[type="password"]').first().fill(credentials[2]);
  await page.locator('button[type="submit"]').click();await page.waitForTimeout(1300);
  await page.getByRole('menuitem',{name:/Inbounds/i}).click();await page.waitForTimeout(800);
  const text=await page.locator('body').innerText();for(const tag of ['VLESS-REALITY-XHTTP-H2','VLESS-TLS-XHTTP-H2','VLESS-REALITY-VISION'])assert.ok(text.includes(tag));console.log('INBOUNDS_VISIBLE',JSON.stringify(['VLESS-REALITY-XHTTP-H2','VLESS-TLS-XHTTP-H2','VLESS-REALITY-VISION'].map(tag=>({tag,present:text.includes(tag)}))));
  await page.screenshot({path:'/tmp/preview07a-inbounds.png',fullPage:true,mask:[page.getByText(credentials[1],{exact:true})]});
  await page.getByRole('menuitem',{name:/^Clients$/i}).click();await page.mouse.move(1250,700);await page.waitForTimeout(600);
  await page.getByRole('button',{name:'Add Clients',exact:true}).click();
  const dialog=page.getByRole('dialog');await dialog.getByPlaceholder('Email',{exact:true}).fill('preview07a-ui');
  await dialog.getByLabel('Attached inbounds',{exact:true}).click();
  for(const tag of ['VLESS-REALITY-XHTTP-H2','VLESS-TLS-XHTTP-H2','VLESS-REALITY-VISION']){
   await page.locator('.ant-select-item-option-content').filter({hasText:tag}).click();
  }
  await page.keyboard.press('Escape');
  await dialog.getByRole('tab',{name:'Credentials',exact:true}).click();
  await dialog.getByLabel('Flow',{exact:true}).click();
  await page.locator('.ant-select-item-option-content').filter({hasText:/^xtls-rprx-vision$/}).click();
  await dialog.getByRole('button',{name:'Create',exact:true}).click();
  await dialog.waitFor({state:'hidden'});await page.waitForTimeout(700);
  assert.ok((await page.locator('body').innerText()).includes('preview07a-ui'));
  console.log('UI_CLIENT_CREATED_AND_ATTACHED');
 }finally{await browser.close()}
})().catch(e=>{console.error(e.message);process.exitCode=1});
