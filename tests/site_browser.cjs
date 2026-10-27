/* Run: node tests/site_browser.cjs <public-release-root> <playwright-module> [browser-executable]
 * Tests only the public static website and fictional release fixtures. No screenshots,
 * private windows, real clipboard reads/writes, financial files, or actual GitHub requests.
 */
'use strict';
const assert=require('assert');
const fs=require('fs');
const http=require('http');
const path=require('path');
const crypto=require('crypto');
const root=path.resolve(process.argv[2]);
const {chromium}=require(process.argv[3]);
const website=path.join(root,'website');
const prefix='/private-accounting-personal-finance/';
const files={'index.html':'text/html; charset=utf-8','styles.css':'text/css; charset=utf-8','app.js':'text/javascript; charset=utf-8','icon.svg':'image/svg+xml','.nojekyll':'text/plain'};
const repo='https://github.com/fictional-finance/fictional-release';
const fakeDownload=Buffer.from('FICTIONAL ARCHIVE FIXTURE ONLY');
const fixture={version:'1.1.0',tag:'v1.1.0',status:'pre-release',repository_url:repo,release_url:repo+'/releases/tag/v1.1.0',zip_url:repo+'/releases/download/v1.1.0/fictional-windows.zip',checksum_url:repo+'/releases/download/v1.1.0/fictional-windows.zip.sha256',installer_url:repo+'/releases/download/v1.1.0/install.ps1',verification_url:repo+'/blob/v1.1.0/TEST-REPORT.md',guide_url:repo+'/blob/v1.1.0/docs/USER-GUIDE.md',issues_url:repo+'/issues',install_command:"Write-Output 'FICTIONAL INSTALL TEST ONLY'",zip_sha256:crypto.createHash('sha256').update(fakeDownload).digest('hex'),installer_sha256:crypto.createHash('sha256').update('FICTIONAL SCRIPT ONLY').digest('hex')};
let config={...fixture,repository_url:null,zip_url:null,install_command:null};
const checks=[],errors=[],external=[],missing=[];
let browser,context,server,origin,mockedDownloads=0;
async function serve(){
  server=http.createServer((req,res)=>{
    const pathname=new URL(req.url,'http://127.0.0.1').pathname;
    if(!pathname.startsWith(prefix)){res.writeHead(404).end();return;}
    const rel=pathname.slice(prefix.length)||'index.html';
    if(rel==='release.json'){
      if(config===null){res.writeHead(503,{'Content-Type':'application/json'}).end('{}');return;}
      res.writeHead(200,{'Content-Type':'application/json','Cache-Control':'no-store'}).end(JSON.stringify(config));return;
    }
    if(!Object.hasOwn(files,rel)){missing.push(rel);res.writeHead(404).end();return;}
    res.writeHead(200,{'Content-Type':files[rel]}).end(fs.readFileSync(path.join(website,rel)));
  });
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  origin='http://127.0.0.1:'+server.address().port;
}
async function visit(page,next){config=next;await page.goto(origin+prefix);await page.waitForFunction(()=>document.getElementById('release-status').textContent!=='Checking release links…');}
async function main(){
  await serve();
  browser=await chromium.launch({executablePath:process.argv[4],headless:true,args:['--disable-extensions','--disable-background-networking','--disable-sync']});
  context=await browser.newContext({viewport:{width:1440,height:1000},acceptDownloads:true});
  await context.addInitScript(()=>{
    Object.defineProperty(navigator,'clipboard',{configurable:true,value:{writeText:async text=>{window.__fictionalClipboard=text;}}});
  });
  await context.route('**/*',route=>{
    const url=route.request().url();
    if(url.startsWith(origin+'/'))return route.continue();
    if(url===fixture.zip_url){mockedDownloads++;return route.fulfill({status:200,contentType:'application/octet-stream',headers:{'Content-Disposition':'attachment; filename="fictional-windows.zip"'},body:fakeDownload});}
    external.push(url);return route.abort();
  });
  const page=await context.newPage();page.on('pageerror',e=>errors.push(e.message));
  await visit(page,config);
  assert.ok(await page.getByRole('button',{name:'Copy command',exact:true}).isDisabled());
  for(const link of await page.locator('[data-link="zip_url"]').all())assert.equal(await link.getAttribute('href'),null);
  assert.match(await page.locator('#release-status').textContent(),/being prepared/);
  checks.push('unpublished or incomplete release safely disables downloads and command');

  await visit(page,fixture);
  assert.equal(await page.title(),'Private Accounting · Personal finance, on your computer');
  assert.equal(await page.locator('#release-status').textContent(),'');
  assert.equal(await page.locator('#install-command').inputValue(),fixture.install_command);
  for(const link of await page.locator('[data-link]').all())assert.equal(await link.getAttribute('href'),fixture[await link.getAttribute('data-link')]);
  assert.equal(missing.length,0);
  checks.push('project-subpath assets and complete pinned release links render correctly');

  await page.getByRole('button',{name:'Copy command',exact:true}).click();
  await page.getByText('Copied. Review the command, then paste it into Windows PowerShell.').waitFor();
  assert.equal(await page.evaluate(()=>window.__fictionalClipboard),fixture.install_command);
  assert.equal(await page.evaluate(()=>window.__installRuns),undefined);
  checks.push('copy control copies exact fictional command without executing it');

  await page.evaluate(()=>{navigator.clipboard.writeText=async()=>{throw Error('Fictional clipboard refusal');};});
  await page.getByRole('button',{name:'Copied',exact:true}).click();
  await page.getByText(/Automatic copy is unavailable/).waitFor();
  assert.deepEqual(await page.locator('#install-command').evaluate(e=>({selected:e.selectionStart===0&&e.selectionEnd===e.value.length,focused:document.activeElement===e})),{selected:true,focused:true});
  checks.push('clipboard refusal offers accessible selected-text fallback');

  const downloadEvent=page.waitForEvent('download');
  await page.getByRole('link',{name:'Download for Windows',exact:true}).first().click();
  const download=await downloadEvent;
  assert.equal(download.suggestedFilename(),'fictional-windows.zip');
  assert.deepEqual(fs.readFileSync(await download.path()),fakeDownload);
  assert.equal(mockedDownloads,1);
  checks.push('download button resolves expected release asset through fictional mocked download');

  const summary=page.getByText('Does the app need internet?',{exact:true});await summary.focus();await page.keyboard.press('Space');
  assert.equal(await summary.evaluate(e=>e.parentElement.open),true);
  await page.keyboard.press('Enter');assert.equal(await summary.evaluate(e=>e.parentElement.open),false);
  await page.getByRole('link',{name:'Privacy',exact:true}).click();assert.equal(new URL(page.url()).hash,'#privacy');
  await page.getByRole('link',{name:'Get started',exact:true}).click();assert.equal(new URL(page.url()).hash,'#get-started');
  checks.push('keyboard FAQ and section navigation work');

  for(const width of [320,375,768,1440]){
    await page.setViewportSize({width,height:900});
    const sizes=await page.evaluate(()=>({document:document.documentElement.scrollWidth,viewport:innerWidth}));
    assert.ok(sizes.document<=sizes.viewport+1,'Horizontal overflow at '+width+': '+JSON.stringify(sizes));
    assert.ok(await page.getByRole('button',{name:'Copy command',exact:true}).isVisible());
  }
  await page.emulateMedia({reducedMotion:'reduce'});
  assert.equal(await page.evaluate(()=>getComputedStyle(document.documentElement).scrollBehavior),'auto');
  checks.push('four viewport widths avoid horizontal overflow; reduced motion respected');

  assert.equal(await page.locator('form,input,iframe').count(),0);
  assert.equal(await page.locator('textarea').count(),1);
  assert.equal(await page.locator('textarea').getAttribute('readonly'),'');
  assert.ok(await page.getByText(/GitHub hosts this page and logs visitors/).count());
  assert.ok(await page.getByText(/Models and Ollama are not bundled/).count());
  checks.push('no data-entry/upload forms; local processing and hosting limitations disclosed');

  await visit(page,{...fixture,zip_url:'javascript:alert(1)'});
  assert.equal(await page.locator('[data-link="zip_url"]').first().getAttribute('href'),null);
  assert.ok(await page.getByRole('button',{name:'Copy command',exact:true}).isDisabled());
  await visit(page,{...fixture,installer_url:'https://github.com/unrelated/other/releases/download/v1.1.0/install.ps1'});
  assert.equal(await page.locator('[data-link="installer_url"]').getAttribute('href'),null);
  assert.equal(await page.locator('[data-link="zip_url"]').first().getAttribute('href'),null);
  await visit(page,{...fixture,tag:'v9.9.9'});
  assert.match(await page.locator('#release-status').textContent(),/temporarily unavailable/);
  assert.ok(await page.getByRole('button',{name:'Copy command',exact:true}).isDisabled());
  await visit(page,{...fixture,zip_sha256:'not-a-checksum'});
  assert.equal(await page.locator('[data-link="zip_url"]').first().getAttribute('href'),null);
  checks.push('unsafe or mismatched URLs, tags, and invalid checksums cannot enable installation');

  await visit(page,null);
  assert.match(await page.locator('#release-status').textContent(),/temporarily unavailable/);
  assert.ok(await page.getByRole('button',{name:'Copy command',exact:true}).isDisabled());
  checks.push('release metadata failure leaves downloads safely disabled');

  assert.deepEqual(errors,[]);assert.deepEqual(external,[]);
  checks.push('zero script errors, unpermitted external requests, screenshots, or real clipboard access');
  console.log(JSON.stringify({passed:true,checks,mocked_downloads:mockedDownloads,unpermitted_external_requests:external.length,script_errors:errors.length,screenshots:0,private_data_used:false},null,2));
}
(async()=>{try{await main();}catch(error){console.error(JSON.stringify({passed:false,error:String(error.stack||error),checks,script_errors:errors,unpermitted_external_requests:external},null,2));process.exitCode=1;}finally{if(browser)await browser.close();if(server)await new Promise(resolve=>server.close(resolve));}})();
