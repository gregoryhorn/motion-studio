"""Stdio real-store/RPC fixture. Tool/checker execution ports are controlled fixtures."""
import json
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch
from studio.director.cards.learning import Cards
from studio.director.cards.schema import Prepare, Mapping
from studio.persistence.primitives import identity
from tests.workspace_e2e.fixture import WorkspaceFixture, ROOT
from tests.media_import_fixtures import png
from tests.test_director import checker


def main():
    effects=0
    def execute(*_args):
        nonlocal effects
        effects+=1
        return png(),dict(mime='image/png',width=1,height=1)
    with tempfile.TemporaryDirectory(prefix='director-browser-') as temporary, patch('studio.director.review.crystal_ball.run',side_effect=checker), patch.object(Cards,'execute',side_effect=execute), patch('studio.director.cards.learning.fingerprint',return_value=dict(path='controlled',sha256='0'*64)):
        fixture=WorkspaceFixture(Path(temporary))
        try:
            take=fixture.seed()
            fixture.rpc('director.card.prepare',Prepare(command=identity(),name='Controlled tool',
                documentation='https://example.org/official',mapping=Mapping(executable='magick',
                    operation='One harmless tiny blue square',arguments=['-size','32x32','xc:blue','{output}'],
                    format='png',version='fixture',cost='zero',seconds=0,shape='32x32 blue square')).model_dump())
            for line in sys.stdin:
                request=json.loads(line)
                try:
                    if request.get('op')=='take':
                        result=take
                    elif request.get('op')=='counts':
                        result=dict(effects=effects)
                    elif request.get('op')=='restart':
                        fixture.reopen();result=dict(restarted=True)
                    else:
                        result=fixture.rpc(request['method'],request.get('payload',{}),root=request.get('payload',{}).get('session_id',ROOT))
                except Exception:
                    result=dict(error='FIXTURE_FAILED')
                print(json.dumps(dict(id=request['id'],result=result)),flush=True)
        finally:
            fixture.close()


if __name__=='__main__':main()
