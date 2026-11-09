"""Focused saved-storyboard / nested HTML / retained SvgDraw integration."""
import copy
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from uuid import uuid4

import test_preproduction as fixtures
from test_assets import provenance
from test_jobs import FixtureAuthority
from studio.adapters import filmmaking as film
from studio.contracts import ContractError, canonical
from studio.project import ProjectStore
from studio.preproduction import ProductionTools
from studio.runtime import NativeRuntime


class StoryboardFilmTests(unittest.TestCase):
    tmp: tempfile.TemporaryDirectory
    projects: ProjectStore
    runtime: NativeRuntime
    tools: ProductionTools
    pid: str
    setUp = fixtures.PreproductionTests.setUp
    call = fixtures.PreproductionTests.call
    update = fixtures.PreproductionTests.update
    library = fixtures.PreproductionTests.library
    board = fixtures.PreproductionTests.board
    import_still = fixtures.PreproductionTests.import_still

    def test_saved_panel_nested_source_svg_and_stale_rejection(self):
        if not film.discover()['available']:
            self.skipTest('Local frame runtime unavailable')
        root=Path(self.tmp.name); visual=self.import_still()
        library=self.library()
        library['requirements']=[dict(requirement_id='hero',role='Panel visual',kind='image',required=True,
            status='ready',asset=visual,assessment='Panel palette and composition reference.',acquisition='Local authored fixture')]
        self.assertTrue(self.update('motion_asset_library',library)['ok'])
        board=self.board()
        panel=dict(panel_id='draw',title='Draw from the saved board',duration_frames=60,visual=visual,
            asset_requirements=['hero'],narration='A line becomes a garden.',on_screen_text='Room to grow.',
            motion='Trace the outline, then reveal the fill.',transition='Cut to the next panel.',notes='Locked native landscape composition.')
        board['panels']=[panel]
        self.assertTrue(self.update('motion_storyboard',board)['ok'])
        def revision():return self.projects.dispatch(dict(action='open',project_id=self.pid))['project_revision']
        def update(changes):
            result=self.projects.dispatch(dict(action='update',project_id=self.pid,expected_revision=revision(),request_id=str(uuid4()),changes=changes))
            return result
        def pins():return {(p['kind'],p['id']):p for p in self.projects.dispatch(dict(action='open',project_id=self.pid))['data']['documents']}
        profile=dict(profile_id='landscape',version='1',label='Storyboard frame fixture',sources=[],valid_until=None,
            constraints=dict(allowed_containers=['mp4'],allowed_video_codecs=['h264'],allowed_audio_codecs=[],width_px=1920,height_px=1080,
                rate=dict(num=30,den=1),max_duration_frames=60,max_bytes=None,alpha='forbidden',caption_modes=['none'],
                loudness_lufs=None,loudness_tolerance_lu=None,true_peak_dbtp=None))
        self.assertTrue(update([dict(op='put_delivery_profile',value=profile)])['ok'])
        variant=dict(variant_id='landscape',label='Native landscape',width_px=1920,height_px=1080,rate=dict(num=30,den=1),duration_frames=60,
            container='mp4',video_codec='h264',pixel_format='yuv420p',color=dict(primaries='bt709',transfer='bt709',matrix='bt709',range='limited'),
            alpha='none',audio=dict(mode='none',sample_rate=None,channels=None,codec=None,loudness_lufs=None,true_peak_dbtp=None),captions='none',
            profile=pins()['delivery_profile','landscape'],overrides=dict(reason='Native SVG panel frame fixture'))
        self.assertTrue(update([dict(op='set_variants',value=[variant])])['ok'])
        source=root/'source'; (source/'nested').mkdir(parents=True)
        (source/'art.svg').write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 240"><path d="M40 205 L200 40 L360 205 Z" fill="#cc5832"/><path d="M200 40 L200 205" stroke="#f0ebdc" stroke-width="8"/></svg>')
        (source/'spec.js').write_text('''import {SvgDraw} from './svg-draw.js';
const {panel}=await fetch('storyboard-panel.json').then(r=>r.json());
document.querySelector('#panel-title').textContent=panel.on_screen_text;
export default {title:panel.title,fps:30,bpm:120,beats:panel.duration_frames/15,hud:false,
palette:{bg:'#203a2c',paper:'#f0ebdc',accent:'#cc5832'},sfx:{mode:'none'},
scenes:[[SvgDraw,0,4,{src:'../art.svg',width:1200,height:720,y:600,
drawBeats:2,fillBeats:1,stroke:'paper',strokeWidth:4,
motion:{camera:0,shake:0,flashes:0,effects:0}}]]};''')
        (source/'nested/index.html').write_text('''<!doctype html><html><head><base href="../"><meta charset="utf-8">
<script>window.__ready=new Promise((resolve,reject)=>{window.__resolveReady=resolve;addEventListener('error',e=>reject(e.error||Error(e.message)))});window.__ready.catch(()=>{});</script>
<style>@font-face{font-family:Archivo;src:url(fonts/Archivo.ttf)}@font-face{font-family:JBM;src:url(fonts/JetBrainsMono.ttf)}@font-face{font-family:Inst;src:url(fonts/InstrumentSans.ttf)}
html,body{margin:0;background:#203a2c;overflow:hidden}#root,.stage{position:relative;width:1920px;height:1080px}.scenes,.overlay,.ground,.cam,.scene{position:absolute;inset:0}.flash,.vig,.inv{display:none}canvas.fx{position:absolute;inset:0}
#panel-title{position:absolute;top:95px;left:0;width:1920px;text-align:center;color:#f0ebdc;font:700 76px Inst;z-index:10}</style></head>
<body><div id="root"></div><div id="panel-title"></div><script type="module" src="main.js"></script></body></html>''')
        packaged: dict=film.package_kinetic_source(source,['spec.js','art.svg','nested/index.html'])
        packaged=film.package_storyboard_source(self.runtime,self.pid,'draw',source,'nested/index.html',[m['relative_path'] for m in packaged['members']])
        manifest=source/'source.json'; manifest.write_bytes(canonical(packaged))
        self.assertEqual(film.source_entry(manifest),source/'nested/index.html')
        self.assertEqual(json.loads((source/'storyboard-panel.json').read_bytes())['panel'],panel)
        imported=self.runtime.asset(dict(action='import',project_id=self.pid,expected_revision=revision(),request_id=str(uuid4()),
            source=dict(kind='local',path=str(manifest)),label='Editable saved-panel SVG scene',kind='scene_source',provenance=provenance()))
        self.assertTrue(imported['ok'],imported); source_pin=imported['data']['asset']['artifact']
        scene=film.storyboard_scene(self.runtime,self.pid,'draw','landscape',dict(width_px=1920,height_px=1080),source_pin)
        self.assertEqual(scene['source_runtime']['entry_member'],'nested/index.html')
        for text in (panel['motion'],panel['on_screen_text'],panel['narration'],panel['transition']):self.assertIn(text,scene['motion_intent'])
        made=update([dict(op='put_scene',value=dict(scene,new_scene_key='panel')),
            dict(op='set_bindings',value=dict(selected_adapter_ids=[film.ADAPTER_ID],preferences={},pins={}))])
        self.assertTrue(made['ok'],made); scene_pin=next(p for p in made['data']['changed'] if p['kind']=='scene')
        cold=NativeRuntime(ProjectStore(self.projects.root))
        saved=cold.document(self.pid,scene_pin)['document']['value']
        self.assertEqual(saved['storyboard_binding']['panel_id'],'draw')
        requests=[dict(target_key='frame_'+str(frame),operation='scene.frame@1',adapter_id=film.ADAPTER_ID,
            inputs=dict(source=dict(kind='artifact',artifact=source_pin),assets=[dict(kind='artifact',artifact=visual)]),
            parameters=dict(scene=scene_pin,frame=frame,alpha='none')) for frame in (0,15,50)]
        compiled=self.runtime.plan(dict(action='compile',project_id=self.pid,expected_revision=made['project_revision'],request_id=str(uuid4()),
            targets=[r['target_key'] for r in requests],requests=requests))
        self.assertTrue(compiled['ok'],compiled)
        jobs=self.runtime.jobs(authority=FixtureAuthority())
        submitted=jobs.dispatch(dict(action='submit',project_id=self.pid,expected_revision=made['project_revision'],request_id=str(uuid4()),plan=compiled['data']['plan']['plan']))
        self.assertTrue(submitted['ok'],submitted); jid=submitted['data']['job']['job_id'];jobs.run_queued(self.pid,jid)
        bundle=jobs.read(self.pid,jid)
        if bundle['job']['state']!='succeeded':
            self.fail(str(dict(job=bundle['job'],attempts=bundle.get('attempts'))))
        outputs=cold.run(dict(action='status',project_id=self.pid,job_id=jid,section='outputs'))
        self.assertTrue(outputs['ok'],outputs); rows=outputs['data']['items']
        frames=[r for r in rows if r['kind']=='frame'];self.assertEqual(len(frames),3)
        self.assertEqual(len({r['sha256'] for r in frames}),3)
        if destination:=os.environ.get('MOTION_STORYBOARD_EVIDENCE'):
            retained=Path(destination);retained.mkdir(parents=True,exist_ok=True)
            shutil.copytree(source,retained/'editable-source',dirs_exist_ok=True)
            for i,record in enumerate(frames):shutil.copyfile(cold.artifact_path(self.pid,{k:record[k] for k in ('artifact_id','sha256')}),retained/f'frame-{i}.png')
            (retained/'receipt.json').write_bytes(canonical(dict(project_id=self.pid,job_id=jid,scene=saved,frames=frames,nested_entry=True,cold_readback=True,panel=panel)))
        library['assessed']=False
        self.assertTrue(self.update('motion_asset_library',library)['ok'])
        self.assertTrue(self.call('motion_storyboard')['data']['stale'])
        with self.assertRaises(ContractError):film.storyboard_scene(self.runtime,self.pid,'draw','landscape',scene['canvas'],source_pin)
        for changes in ([dict(op='put_scene',value=saved)],
                        [dict(op='put_scene',value=saved),dict(op='set_stage',value='concept')],
                        [dict(op='set_storyboard',value=copy.deepcopy(board))]):
            result=update(changes);self.assertFalse(result['ok'],result);self.assertEqual(result['error']['code'],'ASSETS_UNRESOLVED')
        self.assertFalse(self.update('motion_storyboard',board)['ok'])
        self.assertFalse(self.runtime.plan(dict(action='compile',project_id=self.pid,expected_revision=revision(),request_id=str(uuid4()),targets=['frame_0'],requests=requests[:1]))['ok'])
