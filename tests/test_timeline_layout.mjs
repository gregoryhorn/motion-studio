// Real Chromium layout checks of the actual timeline component, with synthetic
// composition data only. This is not backend, media, or installed-client evidence.
// MOTION_BROWSER_MODULE_ROOT points to an existing React/esbuild/Playwright install.
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile, writeFile, mkdtemp, rm, mkdir } from 'node:fs/promises';
import { createRequire } from 'node:module';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { pathToFileURL } from 'node:url';

const moduleRoot = process.env.MOTION_BROWSER_MODULE_ROOT;
test('timeline fits its allocated pane and Fit tracks real resizes', { skip: !moduleRoot }, async t => {
  const require = createRequire(join(resolve(moduleRoot), 'package.json'));
  const { build } = require('esbuild');
  const { chromium } = require('@playwright/test');
  const directory = await mkdtemp(join(tmpdir(), 'motion-timeline-layout-'));
  const source = await readFile(new URL('../desktop/plugin.js', import.meta.url), 'utf8');
  const sdk = `
import { useSyncExternalStore } from 'react';
export const atom = initial => { let value = initial; const listeners = new Set(); return {
  get: () => value, set: next => { value = next; for (const fn of listeners) fn(); },
  subscribe: fn => { listeners.add(fn); return () => listeners.delete(fn); }
}; };
export const host = {activeConnectionId:()=> 'local',state:{profile:{get:()=> 'fixture'}}}, queryClient = { cancelQueries: () => {} };
export const useValue = a => useSyncExternalStore(a.subscribe, a.get), useQuery = () => ({});
export const PANES_AREA = 'panes', ROUTES_AREA = 'routes', PALETTE_AREA = 'palette', KEYBINDS_AREA = 'keybinds';
`;
  const entry = `
import React, { useSyncExternalStore } from 'react';
import { createRoot } from 'react-dom/client';
import { TimelineContent, DockBody, studioState, CSS } from 'timeline-source';
const version = { version_id: 'layout-fixture', format: {duration_frames: 300, fps: {num:30,den:1}}, clips: [], tracks: [
 {track_id:'v1',name:'V1',kind:'video',order:0,locked:false,visible:true,muted:false},
 {track_id:'a1',name:'A1',kind:'audio',order:1,locked:false,visible:true,muted:false}
] };
function Fixture() {
 const s = useSyncExternalStore(studioState.subscribe, studioState.get);
 if(window.fixtureDock) {
  const loaded=window.fixtureDock==='loaded';
  const projectName='Native project with a very long descriptive name and an unbroken identifier '+ 'project'.repeat(15);
  const compositionName='Saved composition with a long name for the final reviewed project';
  return React.createElement(DockBody,{model:{
   s:{...s,owner:{connectionId:'local',profile:'fixture'},project:loaded?'project-fixture':null,composition:loaded?'composition-fixture':null,storageError:loaded?'Connection status: saved composition is retained on this device while the exact preview is available to open.':null},
   native:{data:{projects:loaded?[{id:'project-fixture',name:projectName}]:[]}},boot:{},pcontext:{},catalog:{},
   head:loaded?{data:{data:{preview:{media_id:'fixture-preview',sha256:'a'.repeat(64),version_id:version.version_id}}}}:{},
   scope:loaded?{}:null,version:loaded?version:null,saved:loaded?{version_id:version.version_id,composition_revision:7}:null,
   compositions:loaded?[{composition_id:'composition-fixture',name:compositionName}]:[]
  }});
 }
 return React.createElement('section', {className:'ms timeline-pane', 'aria-label':'Timeline layout fixture'},
  React.createElement('style', null, CSS), React.createElement(TimelineContent, {model:{s,version}}));
}
window.showFixtureDock = value => {window.fixtureDock=value;studioState.set({...studioState.get()});};
window.setFixtureZoom = zoom => studioState.set({...studioState.get(),zoom});
window.getFixtureState = studioState.get;
window.setFixtureTracks = count => {
 version.tracks = Array.from({length:count}, (_,i) => ({track_id:'track-'+i,name:['V1','A1','Captions','Overlay'][i] || 'Track '+i,kind:i===1?'audio':'video',order:i,locked:false,visible:true,muted:false}));
 studioState.set({...studioState.get()});
};
createRoot(document.getElementById('root')).render(React.createElement(Fixture));
`;
  let browser;
  try {
    await build({ stdin: { contents: entry, resolveDir: moduleRoot }, outfile: join(directory, 'fixture.js'),
      bundle: true, format: 'iife', platform: 'browser', logLevel: 'silent',
      define: { 'import.meta.url': JSON.stringify('file:///timeline-layout-fixture') },
      alias: { react: require.resolve('react'), 'react-dom/client': require.resolve('react-dom/client') },
      plugins: [{ name: 'actual-timeline', setup(builder) {
        builder.onResolve({ filter: /^timeline-source$/ }, () => ({ path: 'source', namespace: 'timeline' }));
        builder.onResolve({ filter: /^@hermes\/plugin-sdk$/ }, () => ({ path: 'sdk', namespace: 'timeline' }));
        builder.onLoad({ filter: /.*/, namespace: 'timeline' }, args => ({
          contents: args.path === 'source' ? source + '\nexport { CSS, DockBody };' : sdk, loader: 'js', resolveDir: moduleRoot
        }));
      } }] });
    await writeFile(join(directory, 'fixture.html'), `<!doctype html><meta charset="utf-8"><title>Actual timeline layout fixture, not a live project</title><style>
html,body,#root{height:100%;width:100%;margin:0;overflow:hidden}
:root{--background:#141619;--foreground:#e8e9eb;--muted-foreground:#a7acb4;--border:#3c4149;--primary:#e8c667}
</style><div id="root"></div><script src="fixture.js"></script>`);
    browser = await chromium.launch({ executablePath: process.env.MOTION_BROWSER_EXECUTABLE || '/usr/bin/google-chrome', headless: true });
    const page = await browser.newPage();
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.goto(pathToFileURL(join(directory, 'fixture.html')).href);
    await page.waitForFunction(() => typeof window.setFixtureZoom === 'function', null, {timeout:3000});
    assert.deepEqual(errors, []);
    for (const [width, height] of [[360,180], [640,220], [1366,260], [2560,300], [480,180]]) {
      await t.test(`${width}x${height} allocated pane`, async () => {
        await page.setViewportSize({ width, height });
        await page.waitForSelector('.edit-timeline .lane');
        await page.waitForTimeout(100);
        const geometry = await page.evaluate(() => {
          const editor = document.querySelector('[aria-label="Composition timeline"]');
          const port = document.querySelector('.edit-timeline');
          const lane = port.querySelector('.ruler .lane');
          const gutter = port.querySelector('.trackhead');
          const rect = el => { const r = el.getBoundingClientRect(); return {left:r.left,right:r.right,top:r.top,bottom:r.bottom,width:r.width,height:r.height}; };
          return {editor:rect(editor),port:rect(port),lane:rect(lane),gutter:rect(gutter),
            clientWidth:port.clientWidth,scrollWidth:port.scrollWidth,clientHeight:port.clientHeight,
            pageWidth:document.documentElement.scrollWidth,pageHeight:document.documentElement.scrollHeight,
            fields:[...editor.querySelectorAll('input[type=number]')].map(rect)};
        });
        assert.ok(geometry.port.bottom <= height + 1, `track area escapes pane: ${JSON.stringify(geometry)}`);
        assert.ok(geometry.clientHeight >= 40, `no usable track area: ${JSON.stringify(geometry)}`);
        assert.ok(geometry.scrollWidth <= geometry.clientWidth + 1, `Fit causes horizontal overflow: ${JSON.stringify(geometry)}`);
        assert.ok(Math.abs(geometry.lane.width + geometry.gutter.width - geometry.clientWidth) <= 1, 'Fit does not use the real scrollport');
        assert.ok(geometry.fields.every(field => field.width <= 120), 'numeric controls consume the pane');
        assert.equal(geometry.pageWidth, width);
        assert.equal(geometry.pageHeight, height);
        if (process.env.MOTION_LAYOUT_SCREENSHOTS) {
          await mkdir(process.env.MOTION_LAYOUT_SCREENSHOTS, {recursive:true});
          await page.screenshot({path:join(process.env.MOTION_LAYOUT_SCREENSHOTS, `timeline-${width}x${height}.png`)});
        }
      });
    }
    await t.test('zoom can scroll and Fit restores the current viewport', async () => {
      await page.evaluate(() => window.setFixtureZoom(4));
      await page.waitForTimeout(100);
      assert.ok(await page.$eval('.edit-timeline', e => e.scrollWidth > e.clientWidth * 2));
      await page.getByRole('button', {name:'Fit',exact:true}).click();
      await page.waitForTimeout(100);
      assert.ok(await page.$eval('.edit-timeline', e => e.scrollWidth <= e.clientWidth + 1));
    });
    await t.test('compact controls and secondary actions remain reachable without clipping', async () => {
      await page.setViewportSize({width:360,height:180});
      await page.getByRole('button', {name:'More…',exact:true}).click();
      const menu = page.getByRole('dialog', {name:'More timeline actions'});
      assert.equal(await menu.isVisible(), true);
      const bounds = await menu.boundingBox();
      assert.ok(bounds.x >= 0 && bounds.y >= 0 && bounds.x + bounds.width <= 360 && bounds.y + bounds.height <= 180);
      await menu.getByRole('spinbutton', {name:'Range in · frames',exact:true}).fill('12');
      assert.equal(await page.evaluate(() => window.getFixtureState().range.start_frame), 12);
      await page.keyboard.press('Escape');
      assert.equal(await menu.isVisible(), false);
    });
    await t.test('table round trip restores live fit measurement', async () => {
      await page.getByRole('button', {name:'More…',exact:true}).click();
      await page.getByRole('button', {name:'Table',exact:true}).click();
      await page.waitForSelector('.timeline-table');
      await page.getByRole('button', {name:'More…',exact:true}).click();
      await page.getByRole('button', {name:'Table',exact:true}).click();
      await page.waitForSelector('.edit-timeline');
      await page.waitForTimeout(100);
      assert.ok(await page.$eval('.edit-timeline', e => e.scrollWidth <= e.clientWidth + 1));
    });
    await t.test('normal track sets fit without scrolling the UI', async () => {
      for (const [width,height,count] of [[360,180,2],[640,220,4],[1366,260,4],[2560,300,4]]) {
        await page.setViewportSize({width,height});
        await page.evaluate(n => window.setFixtureTracks(n), count);
        await page.waitForTimeout(100);
        const geometry = await page.evaluate(() => {
          const port=document.querySelector('.edit-timeline');
          const bottom=port.getBoundingClientRect().bottom;
          return {height:port.clientHeight,contentHeight:port.scrollHeight,
            tracks:[...port.querySelectorAll('.track')].map(e=>({height:e.clientHeight,bottom:e.getBoundingClientRect().bottom})),bottom,
            controls:[...document.querySelectorAll('.timeline-tools>.bar,.timeline-fields')].map(e=>({width:e.clientWidth,contentWidth:e.scrollWidth}))};
        });
        assert.ok(geometry.contentHeight <= geometry.height+1, `${width}x${height}/${count} tracks still require UI scrolling: ${JSON.stringify(geometry)}`);
        assert.ok(geometry.tracks.every(r=>r.height>=26 && r.bottom<=geometry.bottom+1), 'tracks are clipped or unreadably compressed');
        assert.ok(geometry.controls.every(r=>r.contentWidth<=r.width+1), 'controls require sideways scrolling');
        if (process.env.MOTION_LAYOUT_SCREENSHOTS) {
          await page.screenshot({path:join(process.env.MOTION_LAYOUT_SCREENSHOTS, `timeline-${width}x${height}-${count}tracks.png`)});
        }
      }
    });
    await t.test('buttons explain actions and retain distinct pressed states', async () => {
      for(const name of ['Select','Snap','Fit','More…']) {
        const button=page.getByRole('button',{name,exact:true});
        assert.ok((await button.getAttribute('title'))?.length>10, name+' lacks an explanation');
        assert.notEqual(await button.evaluate(e=>getComputedStyle(e).boxShadow),'none');
      }
      assert.ok(await page.getByRole('button',{name:'Lock V1',exact:true}).getAttribute('title'));
      assert.equal(await page.getByRole('button',{name:'Monitor-only solo V1',exact:true}).isDisabled(),true);
    });
    await t.test('actual dock contains headers, tabs and content within its allocated viewport', async () => {
      await page.evaluate(()=>window.showFixtureDock(true));
      for(const [width,height] of [[360,480],[420,600],[640,480],[900,720]]) {
        await page.setViewportSize({width,height});
        await page.waitForTimeout(60);
        const g=await page.evaluate(()=>{
          const dock=document.querySelector('.studio-dock'), tabs=dock.querySelector('.tabs'), content=dock.querySelector('[role=tabpanel]');
          return {width:dock.clientWidth,sw:dock.scrollWidth,height:dock.clientHeight,sh:dock.scrollHeight,
            content:content.clientHeight,tabWidth:tabs.clientWidth,tabScroll:tabs.scrollWidth,
            buttons:[...tabs.children].map(e=>({top:e.getBoundingClientRect().top,bottom:e.getBoundingClientRect().bottom,left:e.getBoundingClientRect().left,right:e.getBoundingClientRect().right}))};
        });
        assert.ok(g.sw<=g.width+1 && g.sh<=g.height+1, 'dock overflows '+JSON.stringify(g));
        assert.ok(g.content>=70,'no useful content area '+JSON.stringify(g));
        assert.ok(g.tabScroll<=g.tabWidth+1,'workspace tabs scroll horizontally');
        assert.ok(g.buttons.every(b=>b.left>=0 && b.right<=width+1 && b.top>=0 && b.bottom<=height),'unreachable workspace tab');
        if(process.env.MOTION_LAYOUT_SCREENSHOTS) await page.screenshot({path:join(process.env.MOTION_LAYOUT_SCREENSHOTS,`dock-${width}x${height}.png`)});
      }
    });
    await t.test('loaded saved Preview with long names retains reachable shell and scrollable content', async () => {
      await page.evaluate(()=>window.showFixtureDock('loaded'));
      for(const [width,height] of [[360,480],[420,600],[640,480],[900,720]]) {
        await page.setViewportSize({width,height});
        await page.waitForTimeout(80);
        const g=await page.evaluate(()=>{
          const dock=document.querySelector('.studio-dock'), port=dock.querySelector('[role=tabpanel]');
          port.scrollTop=0;
          const rect=e=>{const r=e.getBoundingClientRect();return {left:r.left,right:r.right,top:r.top,bottom:r.bottom};};
          return {width:dock.clientWidth,sw:dock.scrollWidth,height:dock.clientHeight,sh:dock.scrollHeight,
            content:port.clientHeight,contentWidth:port.clientWidth,contentScrollWidth:port.scrollWidth,
            controls:[...dock.querySelectorAll('header button,header select,[role=tab]')].map(rect)};
        });
        assert.ok(g.sw<=g.width+1 && g.sh<=g.height+1,'loaded shell overflows '+JSON.stringify(g));
        assert.ok(g.content>=70,'loaded preview loses usable content area '+JSON.stringify(g));
        assert.ok(g.contentScrollWidth<=g.contentWidth+1,'preview requires horizontal scrolling '+JSON.stringify(g));
        assert.ok(g.controls.every(r=>r.left>=0 && r.right<=width+1 && r.top>=0 && r.bottom<=height),'header or tab escapes '+JSON.stringify(g));
        const playback=page.getByRole('button',{name:'Open playback',exact:true});
        await playback.scrollIntoViewIfNeeded();
        assert.equal(await playback.isVisible(),true);
        const visiblePlayback=await playback.evaluate(e=>{
          const b=e.getBoundingClientRect(), m=e.closest('.monitor').getBoundingClientRect(), p=e.closest('[role=tabpanel]').getBoundingClientRect();
          return b.top>=Math.max(m.top,p.top) && b.bottom<=Math.min(m.bottom,p.bottom)+1 && b.left>=p.left && b.right<=p.right+1;
        });
        assert.equal(visiblePlayback,true,'playback action is clipped inside the monitor');
        const guides=page.getByRole('button',{name:'Safe guides',exact:true});
        await guides.scrollIntoViewIfNeeded();
        const bounds=await guides.boundingBox();
        assert.ok(bounds.y>=0 && bounds.y+bounds.height<=height,'bottom preview controls unreachable');
        await guides.click();
        assert.equal(await guides.getAttribute('aria-pressed'),'true');
        await guides.click();
        // The panel scrolls, never the surrounding shell. Return to the top for inspection.
        await page.locator('[role=tabpanel]').evaluate(e=>{e.scrollTop=0;});
        if(process.env.MOTION_LAYOUT_SCREENSHOTS) await page.screenshot({path:join(process.env.MOTION_LAYOUT_SCREENSHOTS,`dock-loaded-${width}x${height}.png`)});
      }
    });
    assert.deepEqual(errors, []);
  } finally {
    await browser?.close();
    await rm(directory, {recursive:true,force:true});
  }
});
