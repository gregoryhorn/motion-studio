// Offline package convention reused from browser-production-reuse.mjs. No host proof.
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {spawn, execFileSync} from 'node:child_process';
import {createInterface} from 'node:readline';
import {createRequire} from 'node:module';
const require = createRequire(import.meta.url);

export async function createHarness() {
  const {chromium} = require(process.env.PLAYWRIGHT_PACKAGE);
  for (const name of ['NATIVE_BUNDLE', 'ESBUILD', 'CHROME_EXECUTABLE']) {
    if (!process.env[name]) throw Error('MISSING_' + name);
  }
  const temp = fs.mkdtempSync(path.join(process.env.TMPDIR || os.tmpdir(), 'workspace-browser-'));
  let bridge, browser, closed;
  const waiting = new Map();
  let sequence = 0;
  const cleanup = async () => {
    try { await browser?.close(); }
    finally {
      if (bridge) {
        bridge.stdin.end();
        const timer = setTimeout(() => bridge.kill('SIGKILL'), 5000);
        await closed;
        clearTimeout(timer);
      }
      fs.rmSync(temp, {recursive:true, force:true});
    }
  };
  try {
    execFileSync(process.env.PYTHON || 'python', ['-m', 'zipfile', '-e', process.env.NATIVE_BUNDLE, temp]);
    const entries = [path.join(temp, 'motion-studio/desktop/plugin.js'),
      path.join(temp, 'motion-studio/plugin.js'), path.join(temp, 'plugin.js')];
    const entry = entries.find(item => fs.existsSync(item));
    if (!entry) throw Error('PACKAGE_DESKTOP_ENTRY_MISSING');
    execFileSync(process.env.ESBUILD, ['tests/native-browser-fixture.js', '--bundle', '--format=iife',
      '--platform=browser', '--log-level=error', '--alias:motion-studio-package=' + entry,
      '--alias:@hermes/plugin-sdk=' + path.resolve('tests/workspace_e2e/sdk.js'),
      '--outfile=' + path.join(temp, 'fixture.js')]);
    bridge = spawn(process.env.PYTHON || 'python', ['-m', 'tests.workspace_e2e.fixture'],
      {stdio:['pipe', 'pipe', 'pipe']});
    // Never publish raw bridge errors or payloads. The bounded failure code is sufficient.
    bridge.stderr.resume();
    closed = new Promise(resolve => bridge.once('exit', code => {
      for (const entry of waiting.values()) {
        clearTimeout(entry.timer); entry.reject(Error('WORKSPACE_BRIDGE_EXITED'));
      }
      waiting.clear(); resolve(code);
    }));
    createInterface({input:bridge.stdout}).on('line', line => {
      const message = JSON.parse(line), entry = waiting.get(message.id);
      if (!entry) return;
      waiting.delete(message.id); clearTimeout(entry.timer);
      message.error ? entry.reject(Error('WORKSPACE_FIXTURE_FAILED')) : entry.resolve(message.result);
    });
    const rpc = message => new Promise((resolve, reject) => {
      const id = ++sequence;
      const timer = setTimeout(() => {waiting.delete(id); reject(Error('WORKSPACE_RPC_TIMEOUT'));}, 15000);
      waiting.set(id, {resolve, reject, timer});
      bridge.stdin.write(JSON.stringify({id, ...message}) + '\n');
    });
    browser = await chromium.launch({executablePath:process.env.CHROME_EXECUTABLE, headless:true,
      args:['--no-sandbox']});
    const context = await browser.newContext({offline:true, serviceWorkers:'block', acceptDownloads:true});
    await context.exposeBinding('nativeRPC', (_source, message) => rpc(message));
    const html = '<html><body><div id="root"></div><script>' +
      fs.readFileSync(path.join(temp, 'fixture.js'), 'utf8').replaceAll('</script', '<\\/script') + '</script></body></html>';
    await context.route('**/*', route => route.request().url() === 'https://motion.invalid/' ?
      route.fulfill({contentType:'text/html', body:html}) : route.abort());
    const page = await context.newPage();
    page.setDefaultTimeout(10000);
    return {page, rpc, close:cleanup, mode:'offline-packaged-fixture', ...workspaceHooks({page, context, rpc, temp}),
      target:{root:'session-a', profile:'fixture'}, otherRoot:'other-root', otherProfile:'different-profile',
      navigate:() => page.goto('https://motion.invalid/'),
      selectScope:scope => page.evaluate(value => {
        window.workspaceHost.state.focusedSessionId.set(value.root);
        window.workspaceHost.state.profile.set(value.profile);
        window.workspaceHost.state.focusedSessionOwner.set({connectionId:'fixture-primary', profile:value.profile});
      }, scope),
      identity:() => page.evaluate(() => ({root:window.workspaceHost.state.focusedSessionId.get(),
        profile:window.workspaceHost.state.profile.get()}))};
  } catch (error) {
    await cleanup();
    throw error;
  }
}

// Hooks drive only the visible workspace controls; RPC is used to observe saved state, never to perform the action.
function workspaceHooks({page, context, rpc, temp}) {
  const root = 'session-a';
  const named = (target, name) => target.getByRole('button', {name, exact:true});
  const opened = async production => (await rpc({op:'rpc', method:'production.open', payload:{session_id:root, production}})).current;
  const until = async (probe, label) => {
    for (let attempt = 0; attempt < 100; attempt++) {
      const value = await probe(); if (value) return value;
      await new Promise(resolve => setTimeout(resolve, 150));
    }
    throw Error(label);
  };
  // Review is the section holding Import a take; it enables once a same-kind saved request is listed.
  const chooser = async target => {
    await named(target, 'Review').click();
    const control = target.locator('.production-import').getByRole('button', {name:'Import a take', exact:true});
    await until(() => control.isEnabled(), 'IMPORT_CONTROL_UNAVAILABLE');
    const [dialog] = await Promise.all([target.waitForEvent('filechooser'), control.click()]);
    return dialog;
  };
  const importInto = async (target, production, asset, file) => {
    const before = (await opened(production)).assets.find(item => item.id === asset).takes.map(take => take.id);
    await (await chooser(target)).setFiles(file);
    return until(async () => (await opened(production)).assets.find(item => item.id === asset).takes
      .find(take => !before.includes(take.id)), 'IMPORT_NOT_OBSERVED');
  };
  const reopen = async target => {
    await target.locator('details.ms-more > summary').click();
    await named(target, 'Reopen project').click();
    await target.getByRole('region', {name:'Review'}).waitFor();
  };
  // Controlled synthetic media from the installed encoder: a test-pattern PNG and a one-second H.264 clip.
  const encoded = (name, args) => {
    const output = path.join(temp, name);
    execFileSync(process.env.FFMPEG || 'ffmpeg', ['-loglevel', 'error', '-y', '-f', 'lavfi', '-i',
      'testsrc=size=64x64:rate=10:duration=1', ...args, output]);
    return fs.readFileSync(output);
  };
  const png = () => encoded('controlled.png', ['-frames:v', '1']);
  const mp4 = () => encoded('controlled.mp4', ['-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-an']);
  const assetOfKind = async (production, kind) => (await opened(production)).assets.find(item => item.kind === kind);
  const importKind = async (target, kind, file) => {
    await rpc({op:'seed-request', kind});
    const production = (await rpc({op:'rpc', method:'production.list', payload:{session_id:root}})).productions[0].id;
    const asset = await assetOfKind(production, kind);
    await named(target, 'Review').click();
    await target.locator('.production-asset').nth(asset.position).click();
    await importInto(target, production, asset.id, file);
    await named(target, 'Open viewer').click();
  };
  return {
    cancelInput:async ({file}) => { void file; await (await chooser(page)).setFiles([]); },
    importTake:async ({file, production, asset}) => {
      const take = await importInto(page, production, asset, file);
      return {take:take.id, request:take.request};
    },
    exportSelected:async ({production, asset, reviewAlternative}) => {
      const takes = (await opened(production)).assets.find(item => item.id === asset).takes;
      await named(page, 'Review').click();
      await page.locator('.production-take').nth(takes.findIndex(take => take.id === reviewAlternative)).click();
      await named(page, 'Outputs').click();
      await named(page, 'Save selected file').click();
      const link = page.getByRole('link', {name:/^Download /});
      await link.waitFor();
      const [download] = await Promise.all([page.waitForEvent('download'), link.click()]);
      return fs.readFileSync(await download.path());
    },
    pendingInputScopeChange:async ({file, selectScope}) => {
      const dialog = await chooser(page);
      await selectScope({root:'other-root', profile:'fixture'});
      await selectScope({root, profile:'fixture'});
      // The obsolete chooser may no longer have an input to deliver to; either way nothing may be saved.
      await dialog.setFiles(file).catch(() => {});
      await new Promise(resolve => setTimeout(resolve, 500));
      await reopen(page);
    },
    reviewImageVideo:async () => {
      await page.setViewportSize({width:1280, height:900});
      await importKind(page, 'Image', {name:'controlled.png', mimeType:'image/png', buffer:png()});
      // A second window of the same workspace keeps the image on screen while the video is reviewed.
      const second = await context.newPage(); second.setDefaultTimeout(10000);
      await second.goto('https://motion.invalid/');
      await named(second, 'Production').click();
      await second.getByRole('region', {name:'Review'}).waitFor();
      await importKind(second, 'Video', {name:'controlled.mp4', mimeType:'video/mp4', buffer:mp4()});
      return {image:page.locator('.media-review img'), video:second.locator('.media-review video')};
    },
  };
}
