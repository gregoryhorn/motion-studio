"""Opt-in one-call local FFmpeg/Crystal Ball/retention/export qualification."""
import argparse
import base64
import importlib.metadata
import io
import json
from pathlib import Path
import tempfile
import zipfile
from studio.director.cards.schema import Prepare, Mapping
from studio.director.cards.learning import Cards
from studio.persistence.primitives import identity
from studio.native.production.models import Brief, Create, LinkTake
from studio.media_import import MediaImports
from studio.media_import.contracts import RetrieveTake
from studio.production_export import ProductionExport
from tests.production_support import production_setup


def qualify(root):
    ctx,creation,production,_=production_setup(root)
    try:
        cards=Cards(creation.acquire())
        card=cards.prepare('canonical-root',Prepare(command=identity(),name='FFmpeg tiny blue movie',
            documentation='https://ffmpeg.org/ffmpeg-filters.html',
            mapping=Mapping(executable='ffmpeg',operation='Create one 160x90 blue 0.6s MP4',
                arguments=['-v','error','-f','lavfi','-i','color=c=blue:s=160x90:d=0.6',
                    '-c:v','libx264','-pix_fmt','yuv420p','{output}'],format='mp4',
                version='installed executable fingerprint',cost='zero',shape='160x90 blue movie',seconds=0.6)))
        payload=dict(id=card['id'],expected=card['revision'],command=identity(),confirmed=True)
        test=ctx.methods['director.card.test'](payload,session_id='canonical-root')
        replay=ctx.methods['director.card.test'](payload,session_id='canonical-root')
        with creation.store.transaction() as db:
            test_count=db.execute('SELECT count(*) FROM director_tests').fetchone()[0]
            reports_before=db.execute('SELECT count(*) FROM director_reports').fetchone()[0]
        reopened=Cards(creation.acquire()).read('canonical-root')['cards'][0]
        evidence=test.get('evidence',[])
        if not evidence:
            return dict(status=test.get('status'),actual_test_calls=test_count,qualified=False)
        take=evidence[0]
        service=production.acquire()
        imports=MediaImports(creation.store,service.creations.authorize_request,assets=service.assets)
        data,_=imports.retrieve('canonical-root',RetrieveTake(take=take['take']))
        current=service.create('canonical-root',Create(command=identity(),title='Controlled qualification',
            brief=Brief(text='Controlled local fixture'),kinds=['Video']))['current']
        asset=current['assets'][0]['id']
        for action in (service.link_take,service.select_take):
            current=action('canonical-root',LinkTake(command=identity(),production=current['id'],
                expected=current['revision'],asset=asset,request=take['request'],take=take['take']))['current']
        export=ProductionExport(service,media_imports=imports).prepare('canonical-root',current,[asset])
        try:
            archive=b''.join(base64.b64decode(export.chunk(offset)['bytes']) for offset in range(0,export.size,49152))
            with zipfile.ZipFile(io.BytesIO(archive)) as contents:
                manifest=json.loads(contents.read('manifest.json'))
                selected=manifest['outputs'][0]
                exact=contents.read(selected['filename'])==data
        finally:
            export.close()
        with creation.store.transaction() as db:
            reports_after=db.execute('SELECT count(*) FROM director_reports').fetchone()[0]
            assets=db.execute('SELECT count(*) FROM director_report_assets').fetchone()[0]
        return dict(real_tool='FFmpeg',version_source='Actual executable SHA256 pin; supplied label is not version proof',
            checker_version=importlib.metadata.version('crystal-ball-media'),actual_test_calls=test_count,
            output_bytes=len(data),status=test.get('status'),check=take['check'],
            replay_same_result=replay==test,reopened_status=reopened['status'],
            export_exact_original=exact,export_check=selected['crystal_ball'],retained_checker_asset_count=assets,
            reused_report_on_export=reports_before==reports_after==1,
            qualified=test_count==1 and replay==test and test.get('status')=='Tested' and exact and reports_after==1,
            evidence_boundary='Real local CLI/checker and scoped retrieval/export; development host fixture, not native install/user approval')
    finally:
        creation.unload()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--confirm-tiny-test',action='store_true',help='Authorize ONE local zero-cost FFmpeg call: 160x90 blue 0.6s MP4, max 15s, checked activation; no install or provider')
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if not args.confirm_tiny_test:parser.error('Explicit tiny-test confirmation is required')
    with tempfile.TemporaryDirectory(prefix='director-live-') as temporary:
        result=qualify(Path(temporary))
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))
    return 0 if result['qualified'] else 1


if __name__=='__main__':raise SystemExit(main())
