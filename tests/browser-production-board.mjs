import os from 'node:os';
// Source-only browser harness: temporary bundle, synthetic controller, zero live RPC.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {createRequire} from 'node:module';
const require=createRequire(import.meta.url);
const modules=process.env.BOARD_NODE_MODULES||path.join(process.env.HERMES_SOURCE||path.join(os.homedir(),'.hermes/hermes-agent-official'),'apps/desktop/node_modules');
const esbuild=require(path.join(modules,'esbuild'));
const playwright=process.env.PLAYWRIGHT_PACKAGE||path.dirname(require.resolve('playwright/package.json'));
const {chromium}=require(playwright),{expect}=require(path.join(playwright,'test.js'));
const scratch=process.env.TMPDIR||'/tmp';
const output=fs.mkdtempSync(path.join(scratch,'production-board-browser-'));
const sources=['studio/native/frontend/production-plan.js','studio/native/frontend/production-style.js',
  'studio/native/frontend/production-page.js','tests/production-board-fixture.js','tests/production-board-widgets.js',
  'tests/browser-production-board.mjs','tests/production-board.mjs'];
await esbuild.build({entryPoints:['tests/production-board-fixture.js'],bundle:true,format:'iife',platform:'browser',
  alias:{'react':path.join(modules,'react'),'react-dom':path.join(modules,'react-dom'),
    '@hermes/plugin-sdk':path.resolve('tests/production-board-widgets.js')},
  outfile:path.join(output,'fixture.js'),logLevel:'error'});
const acorn=require('acorn');
const appBundle=path.join(output,'plan-app-only.js');
await esbuild.build({entryPoints:['studio/native/frontend/production-plan.js'],bundle:true,format:'esm',platform:'browser',
  external:['react','@hermes/plugin-sdk'],outfile:appBundle,logLevel:'error'});
const spans=[];
function inspect(node,file){
  if(!node||typeof node!=='object')return;
  if(['FunctionDeclaration','FunctionExpression','ArrowFunctionExpression'].includes(node.type))
    spans.push({file,start:node.loc.start.line,end:node.loc.end.line,span:node.loc.end.line-node.loc.start.line+1});
  for(const value of Object.values(node))if(Array.isArray(value))value.forEach(child=>inspect(child,file));
    else if(value&&typeof value==='object'&&value.type)inspect(value,file);
}
for(const file of [...sources,appBundle])inspect(acorn.parse(fs.readFileSync(file,'utf8'),
  {ecmaVersion:'latest',sourceType:'module',locations:true}),file);
assert.ok(spans.every(fn=>fn.span<=300),'Complete source and app-only bundle functions stay <=300 lines');
const browser=await chromium.launch({executablePath:process.env.CHROME_EXECUTABLE||
  undefined,headless:true,args:['--no-sandbox']});
const checks=[],errors=[],consoleErrors=[],network=[];
const context=await browser.newContext({offline:true,serviceWorkers:'block',reducedMotion:'reduce',viewport:{width:1400,height:1000}});
await context.route('**/*',route=>{network.push('UNEXPECTED_NETWORK');return route.abort();});
const page=await context.newPage();page.on('pageerror',()=>errors.push('PAGE_ERROR'));
page.on('console',message=>{if(message.type()==='error')consoleErrors.push('CONSOLE_ERROR');});
const button=name=>page.getByRole('button',{name,exact:true});
const board=()=>page.getByRole('list',{name:'Planned assets'});
const cards=()=>board().locator(':scope > li');
const card=index=>cards().nth(index);
async function check(name,run){await run();checks.push(name);}
const calls=()=>page.evaluate(()=>window.boardCalls);
const noOverflow=async()=>assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
let failed=false;
try{
  const script=fs.readFileSync(path.join(output,'fixture.js'),'utf8').replaceAll('</script','<\\/script');
  await page.setContent('<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"></head><body style="margin:0;background:#111614"><div id="root"></div><script>'+script+'</script></body></html>');
  await button('Plan').click();await expect(board()).toBeVisible();
  await check('actual ProductionPage renders five-kind board, separate QA/selection/stale cues',async()=>{
    // An isolated intentionally wrong expectation proves failure propagation.
    await expect(cards()).toHaveCount(process.argv.includes('--negative-control')?6:5);
    for(const kind of ['Sound effects','Music','Voice','Image','Video'])await expect(board().getByRole('button',{name:new RegExp(kind)})).toBeVisible();
    await expect(card(0).getByRole('button')).toContainText('Selected take 2');
    await expect(card(0).getByRole('button')).toContainText('QA: Not reviewed');
    await expect(card(0).getByRole('button')).toContainText('Stale selection - earlier inputs');
    await expect(card(1).getByRole('button')).toContainText('No selected take');
    await expect(card(1).getByRole('button')).not.toContainText('current');
  });
  await check('native summary opens by keyboard and names exact dependency/reference/take',async()=>{
    const summary=card(0).locator('summary');await summary.focus();await page.keyboard.press('Enter');
    await expect(card(0)).toContainText('Depends on: 2. Music - Controlled music');
    await expect(card(0)).toContainText('Controlled reference / revision 1');
    await expect(card(0)).toContainText('Selected take ID: synthetic-take-2');
    const linked=card(0).getByRole('list',{name:'Linked takes for 1. Sound effects'});
    await expect(linked.getByRole('listitem')).toHaveCount(2);
    await expect(linked.getByRole('listitem').nth(0)).toContainText('Take 1 / Approved / alternative');
    await expect(linked.getByRole('listitem').nth(1)).toContainText('Take 2 / Not reviewed / selected');
    await page.keyboard.press('Enter');await expect(summary).toBeFocused();
  });
  await check('long intent preview stays concise with full text in keyboard-accessible details',async()=>{
    const preview=card(4).locator('.production-asset-intent'),full='Controlled '+('long-unbroken-label'.repeat(14));
    assert.ok((await preview.innerText()).length<=120);assert.match(await preview.innerText(),/\.\.\.$/);
    const summary=card(4).locator('summary');await summary.focus();await page.keyboard.press('Enter');
    await expect(card(4).getByText('Intent: '+full,{exact:true})).toBeVisible();
    await page.keyboard.press('Enter');
  });
  await check('keyboard asset navigation preserves focus and does not select an output',async()=>{
    const second=card(1).getByRole('button');await second.focus();await page.keyboard.press('Enter');
    await expect(second).toBeFocused();await expect(second).toHaveAttribute('aria-pressed','true');
    assert.deepEqual((await calls()).map(c=>c.operation),['chooseAsset']);
    await expect(card(0).getByRole('button')).toContainText('Selected take 2');
    await card(0).getByRole('button').click();
  });
  await check('intent editing and saved-state rerender preserve focused input and text',async()=>{
    const input=page.getByLabel('Asset intent',{exact:true});await input.fill('Controlled changed impact');
    await page.evaluate(()=>window.boardFixture.refresh());await expect(input).toBeFocused();
    await expect(input).toHaveValue('Controlled changed impact');
  });
  await check('non-drag reorder remains draft-only until existing revisioned save',async()=>{
    const before=(await calls()).length;await button('Move later').focus();await page.keyboard.press('Enter');
    await expect(button('Move later')).toBeFocused();
    await expect(page.getByLabel('Plan position',{exact:true})).toHaveValue('1');assert.equal((await calls()).length,before);
    await expect(card(0).getByRole('button')).toContainText('1. Sound effects');
    await button('Save asset').click();
    await expect(card(1).getByRole('button')).toContainText('2. Sound effects');
    const update=(await calls()).find(c=>c.operation==='updateAsset');
    assert.equal(update.args[0].position,1);assert.equal(update.args[0].intent,'Controlled changed impact');
    assert.equal(update.args[0].expected,3);assert.equal(update.args[1].asset,'synthetic-asset-0');
    await expect(button('Save asset')).toBeFocused();
  });
  await check('dependency and reference editing uses existing checkboxes and save payload',async()=>{
    await page.getByText('Dependencies and references',{exact:true}).click();
    const dependencies=page.getByRole('group',{name:'Depends on'});
    await dependencies.getByRole('checkbox',{name:/Voice/}).check();
    await page.getByRole('group',{name:'Uses references'}).getByRole('checkbox').uncheck();
    await button('Save asset').click();
    const update=(await calls()).filter(c=>c.operation==='updateAsset').at(-1).args[0];
    assert.deepEqual(update.depends_on,['synthetic-asset-1','synthetic-asset-2']);assert.deepEqual(update.references,[]);
  });
  await check('add uses existing scoped callback with all five kinds available',async()=>{
    await expect(page.getByLabel('New asset media kind').locator('option')).toHaveCount(5);
    await page.getByLabel('New asset media kind').selectOption('Image');
    await page.getByLabel('New asset intent').fill('Controlled inserted image');await button('Add asset').click();
    await expect(cards()).toHaveCount(6);
    const add=(await calls()).find(c=>c.operation==='addAsset');assert.equal(add.args[0],'Image');
    assert.equal(add.args[1],'Controlled inserted image');assert.equal(add.args[2].production,'synthetic-production');
  });
  await check('busy state disables add, edit, move, save and board context buttons',async()=>{
    await page.evaluate(()=>window.boardFixture.busy(true));
    for(const locator of [board().getByRole('button').first(),page.getByLabel('New asset media kind'),
      page.getByLabel('Asset intent',{exact:true}),button('Move earlier'),button('Save asset'),button('Add asset')])
      await expect(locator).toBeDisabled();
    await page.evaluate(()=>window.boardFixture.busy(false));
  });
  await page.screenshot({path:path.join(output,'wide.png'),fullPage:true});
  await check('200 percent text and 320 CSS pixel layout retain warnings/actions without overflow',async()=>{
    await page.addStyleTag({content:'html{font-size:200%}'});await page.setViewportSize({width:640,height:1000});
    await noOverflow();await expect(button('Save asset')).toBeVisible();
    await expect(card(1).getByRole('button')).toContainText('Stale selection');
    await page.screenshot({path:path.join(output,'text-200.png'),fullPage:true});
    await page.addStyleTag({content:'html{font-size:100%}'});await page.setViewportSize({width:320,height:900});
    await noOverflow();await button('Move earlier').scrollIntoViewIfNeeded();await expect(button('Move earlier')).toBeVisible();
    for(const name of ['Review','Brief','Plan','References','Outputs']){
      const bounds=await page.getByRole('navigation',{name:'Production sections'}).getByRole('button',{name,exact:true}).boundingBox();
      assert.ok(bounds&&bounds.x>=0&&bounds.x+bounds.width<=320,'All section switches fit narrow viewport');
    }
    await page.screenshot({path:path.join(output,'narrow.png'),fullPage:true});
    // Open progressive content at the narrowest width, including linked take IDs.
    const summary=card(1).locator('summary');await summary.focus();await page.keyboard.press('Enter');
    await expect(card(1).getByRole('list',{name:'Linked takes for 2. Sound effects'})).toBeVisible();
    await noOverflow();await page.keyboard.press('Enter');
  });
  await check('no audio/video autoplay or network effects',async()=>{
    assert.equal(await page.locator('audio[autoplay],video[autoplay]').count(),0);
    assert.deepEqual(network,[]);assert.ok((await calls()).every(c=>['chooseAsset','addAsset','updateAsset'].includes(c.operation)));
  });
  await check('empty reference/dependency states point to supported actions',async()=>{
    await page.evaluate(()=>window.boardFixture.single());
    await expect(cards()).toHaveCount(1);
    await expect(page.getByText('No other assets. Add an asset before defining a dependency.')).toBeVisible();
    await expect(page.getByText('No references yet. Add one in References.')).toBeVisible();
    await expect(button('Move earlier')).toBeDisabled();await expect(button('Move later')).toBeDisabled();
  });
  await check('empty Production plan retains add controls without fake takes',async()=>{
    await page.evaluate(()=>window.boardFixture.empty());await expect(page.getByText('No assets in this plan.')).toBeVisible();
    await expect(button('Add asset')).toBeVisible();await expect(page.getByLabel('Selected asset plan')).toHaveCount(0);
  });
  assert.deepEqual(errors,[]);assert.deepEqual(consoleErrors,[]);
}catch(error){failed=true;throw error;}
finally{
  fs.writeFileSync(path.join(output,'results.json'),JSON.stringify({status:failed?'FAILED':'PASSED',checks,errors,consoleErrors,
    network,dependencies:{node:process.version,react:require(path.join(modules,'react/package.json')).version,
      esbuild:esbuild.version,playwright:require(path.join(playwright,'package.json')).version},
    sourceFunctionMax:Math.max(...spans.filter(fn=>sources.includes(fn.file)).map(fn=>fn.span)),
    temporaryBundleFunctionMax:Math.max(...spans.filter(fn=>!sources.includes(fn.file)).map(fn=>fn.span))},null,2)+'\n');
  await browser.close();console.log(JSON.stringify({output,passed:checks.length,status:failed?'FAILED':'PASSED',pageErrors:errors.length}));
}
