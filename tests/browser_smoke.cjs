/* Run: node tests/browser_smoke.cjs <fresh-extracted-app-folder> <playwright-module-path> [browser-executable]
 * Only new fictional storage is used. No screenshots or private windows are read.
 * Requires separately installed developer Node + Playwright; not needed by app users.
 */
const fs = require('fs'); const path = require('path'); const cp = require('child_process'); const assert = require('assert');
const {randomUUID} = require('crypto');
const appRoot=path.resolve(process.argv[2]); const {chromium}=require(process.argv[3]);
const scratch=path.join(appRoot,'tests','.a-'+randomUUID().slice(0,8)); fs.mkdirSync(scratch);
const data=path.join(scratch,'fake');
let child,browser,session;const errors=[],external=[],checks=[];
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
function start(){child=cp.spawn(path.join(appRoot,'runtime','python.exe'),[path.join(appRoot,'app','launch.py'),'--no-browser','--data-dir',data],{windowsHide:true,stdio:['ignore','pipe','pipe']}); child.stderr.on('data',()=>{});}
async function ready(){for(let i=0;i<200;i++){try{session=JSON.parse(fs.readFileSync(path.join(data,'session.json'),'utf8'));const r=await fetch(`http://127.0.0.1:${session.port}/api/ping`,{headers:{Authorization:'Bearer '+session.token}});if(r.ok)return;}catch{} if(child.exitCode!==null)throw Error('Fictional app process ended before readiness');await sleep(50);}throw Error('Fictional launch timed out');}
async function api(route,body){const r=await fetch(`http://127.0.0.1:${session.port}`+route,{method:body?'POST':'GET',headers:{Authorization:'Bearer '+session.token,'Content-Type':'application/json'},body:body?JSON.stringify(body):undefined});const j=await r.json();if(!r.ok)throw Error(j.error||'API failure');return j;}
async function waitFor(pred){for(let i=0;i<100;i++){if(await pred())return;await sleep(50);}throw Error('State condition timed out');}
(async()=>{
  start();await ready();checks.push('bundled runtime isolated launch');
  browser=await chromium.launch({executablePath:process.argv[4],headless:true,args:['--disable-extensions','--disable-background-networking','--disable-sync']});
  const context=await browser.newContext({viewport:{width:1440,height:1000},acceptDownloads:true});
  await context.route('**/*',route=>{const u=new URL(route.request().url());if(u.hostname==='127.0.0.1')route.continue();else {external.push(u.origin);route.abort();}});
  const page=await context.newPage();page.on('pageerror',e=>errors.push(e.message));page.on('dialog',d=>d.accept());
  await page.goto(`http://127.0.0.1:${session.port}/#${session.token}`);
  await page.getByRole('dialog').waitFor();
  await page.getByLabel('What would you like to understand?').fill('Fictional monthly practice');
  await page.getByLabel('Overview starts').fill('2026-01-01');await page.getByLabel('Overview ends').fill('2026-01-31');
  await page.getByRole('dialog').getByRole('checkbox').check();await page.getByRole('button',{name:'Review my setup',exact:true}).click();
  async function approveLast(){const card=page.locator('.review-card').last(); await card.waitFor();for(const c of await card.getByRole('checkbox').all())await c.check();await card.getByRole('button',{name:/Approve/}).click();await waitFor(async()=>!(await api('/api/state')).proposals.length);await page.locator('.review-card').waitFor({state:'hidden'});}
  await approveLast();assert.equal((await api('/api/state')).state.setup.goals,'Fictional monthly practice');checks.push('first-run setup preview approval');
  await page.getByRole('button',{name:'Settings & help',exact:false}).click();await page.getByRole('button',{name:'Prepare sample data',exact:true}).click();
  await waitFor(async()=>(await api('/api/state')).proposals.length===1);let s=await api('/api/state');assert.equal(s.state.transactions.length,0);assert.equal(s.proposals.length,1);await approveLast();checks.push('demo requires explicit approval');
  await page.getByRole('button',{name:'Add information',exact:true}).first().click();
  await page.getByLabel('Date',{exact:true}).fill('2026-01-07');await page.getByLabel('Amount (USD, signed)').fill('-3.25');await page.getByLabel('Description',{exact:true}).fill('Fictional tea <img src=x onerror=alert(1)>');await page.getByLabel('Account',{exact:true}).fill('Demo checking');await page.getByLabel('Type',{exact:true}).selectOption('expense');await page.getByLabel('Category',{exact:true}).fill('Food');
  await page.getByRole('button',{name:'Review this entry',exact:true}).click();assert.equal(await page.locator('.review-card img').count(),0);await approveLast();checks.push('manual proposal and inert text');
  await page.getByRole('button',{name:'Transactions',exact:true}).click();await page.getByRole('button',{name:/Edit Fictional tea/}).click();await page.getByRole('dialog').getByLabel('Amount (USD, signed)').fill('-4.25');await page.getByRole('button',{name:'Review my changes',exact:true}).click();await approveLast();assert.equal((await api('/api/state')).state.transactions.find(t=>t.description.startsWith('Fictional tea')).amount,'-4.25');checks.push('saved transaction edit preserves identity');
  await page.getByRole('button',{name:'Plans & debts',exact:true}).click();await page.getByRole('button',{name:'Add plan',exact:true}).click();await page.getByRole('dialog').getByLabel('Category',{exact:true}).fill('Food');await page.getByLabel('Planned amount (USD)').fill('200');await page.getByLabel('Starts',{exact:true}).fill('2026-01-01');await page.getByLabel('Ends',{exact:true}).fill('2026-01-31');await page.getByRole('button',{name:'Review this plan'}).click();await approveLast();checks.push('dated budget review');
  await page.getByRole('button',{name:'Plans & debts',exact:true}).click();await page.getByRole('button',{name:'Add debt',exact:true}).click();await page.getByLabel('Debt name').fill('Fictional loan');await page.getByLabel('Reported balance (USD)').fill('120');await page.getByLabel('Balance as of').fill('2026-01-20');await page.getByRole('dialog').getByLabel('Source',{exact:true}).fill('Fictional statement');await page.getByRole('button',{name:'Review this debt'}).click();await approveLast();checks.push('reported debt review');
  await page.getByRole('button',{name:'Add information',exact:true}).first().click();await page.getByRole('tab',{name:'Upload a file'}).click();
  const csv='date,description,amount,account,classification,category\n2026-01-15,Fictional file income,123.45,Demo checking,income,Other\n';
  await page.getByLabel('Choose a local file to preview').setInputFiles({name:'fictional-browser.csv',mimeType:'text/csv',buffer:Buffer.from(csv)});
  await page.getByRole('heading',{name:'fictional-browser.csv'}).waitFor();assert.equal((await api('/api/state')).documents.length,0);
  await page.getByRole('button',{name:'Keep local copy',exact:true}).click();await waitFor(async()=>(await api('/api/state')).documents.length===1);checks.push('file preview and explicit persistent original');
  await page.getByRole('button',{name:'Propose these entries',exact:true}).first().click();await approveLast();checks.push('canonical file rows approval');
  await page.getByRole('button',{name:'Files & exports',exact:true}).first().click();
  for(const title of ['Excel workbook','Transactions CSV','Readable report','Data JSON','Complete backup']){
    const wait=page.waitForEvent('download');await page.getByRole('button',{name:new RegExp('^'+title)}).click();const download=await wait;await download.saveAs(path.join(scratch,download.suggestedFilename()));assert.ok(fs.statSync(path.join(scratch,download.suggestedFilename())).size>0);
  }checks.push('all five UI export downloads');
  for(const title of ['Dashboard','Transactions','Plans & debts','Add information','Review','Files & exports']){await page.getByRole('button',{name:title,exact:true}).first().click();assert.equal(await page.locator('#main h1').count(),1);}
  await page.setViewportSize({width:390,height:844});await page.getByRole('button',{name:'Open navigation'}).click();await page.getByRole('button',{name:'Dashboard',exact:true}).click();assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>window.innerWidth+2),false);checks.push('navigation and mobile layout without screenshots');
  const before=(await api('/api/state')).state;await api('/api/shutdown',{confirm:true});await new Promise(r=>child.on('exit',r));
  start();await ready();const after=(await api('/api/state')).state;assert.deepEqual(after,before);checks.push('shutdown and reopen retain saved records');
  assert.equal(errors.length,0,JSON.stringify(errors));assert.equal(external.length,0,JSON.stringify(external));checks.push('no browser script errors or external requests');
  await api('/api/shutdown',{confirm:true});await new Promise(r=>child.on('exit',r));await browser.close();
  console.log(JSON.stringify({passed:true,checks,screenshots:0,private_data_used:false}));
})().catch(async e=>{console.error(JSON.stringify({passed:false,error:e.message,checks,script_errors:errors,external_requests:external}));try{if(session)await api('/api/shutdown',{confirm:true});}catch{}if(child&&child.exitCode===null)child.kill();if(browser)await browser.close();process.exitCode=1;});
