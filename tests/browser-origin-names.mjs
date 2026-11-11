// Actual Chromium accessibility names; all three origin projections are synthetic DOM data.
export async function originNames(context, origin, fixtureAudio, check) {
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  try {
    await page.goto(origin);
    await page.locator('#workspace').waitFor({state: 'visible'});
    await page.evaluate(async audioBytes => {
      const {renderTakes} = await import('/takes.js');
      const container = document.createElement('section');
      container.id = 'origin-names';
      document.body.append(container);
      const takes = ['user_import', 'test_fixture', 'producer_output'].map(origin => ({
        id: `origin-${origin}`, name: 'Synthetic accessibility projection', origin,
        request: 'synthetic-origin-request', revision: 1,
        facts: {duration: 0.1, rate: 44100, channels: 2}, size: 17684,
        technical: 'Test projection only', review: 'Not reviewed', rights: 'Usage rights not verified'
      }));
      renderTakes(container, {takes, requests: []}, async () => {});
      await Promise.all([...container.querySelectorAll('audio')].map(audio => new Promise((resolve, reject) => {
        audio.onloadedmetadata = resolve;
        audio.onerror = reject;
        audio.preload = 'metadata';
        audio.src = URL.createObjectURL(new Blob([Uint8Array.from(atob(audioBytes), value => value.charCodeAt(0))], {type: 'audio/wav'}));
      })));
    }, fixtureAudio);
    const cdp = await context.newCDPSession(page);
    const document = await cdp.send('DOM.getDocument');
    const {nodeIds} = await cdp.send('DOM.querySelectorAll', {nodeId: document.root.nodeId, selector: '#origin-names audio'});
    const backendIds = new Set();
    for (const nodeId of nodeIds) {
      backendIds.add((await cdp.send('DOM.describeNode', {nodeId})).node.backendNodeId);
    }
    const ax = await cdp.send('Accessibility.getFullAXTree');
    const names = ax.nodes.filter(node => backendIds.has(node.backendDOMNodeId))
      .map(node => node.name?.value ?? null).sort();
    await cdp.detach();
    const expected = ['user_import', 'test_fixture', 'producer_output']
      .map(origin => `Candidate origin-${origin}, 0.100 seconds`).sort();
    console.log(JSON.stringify({syntheticOriginProjection: true, accessibleAudioNames: names}));
    check('B2-R02 actual AX audio names neutral for user_import, test_fixture and producer_output',
      JSON.stringify(names) === JSON.stringify(expected));
    check('B2-R02 origin name projection has no runtime errors', errors.length === 0);
  } finally {
    await page.close();
  }
}
