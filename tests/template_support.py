"""Trusted fixture registration and tool-supplied schema samples, never app-name routing."""
import hashlib
from pathlib import Path
import sys
from studio.producer.catalog import Catalog


def evidence(flags,fields,version) -> dict:
    return dict(schema_version='motion-cli-evidence-v1',tool_version=version,operation='sfx',format='stereo-44100-pcm16',
        arguments=[dict(flag=flag,value=value) for flag,value in zip(flags,['direction','seconds','seed','output','receipt'])],
        receipt=dict(zip(['output','direction','seconds','seed','version'],fields)),
        effects=dict(destination='local-workspace',network='none',cost='zero',model='none',credentials='none',
                     use='noncommercial_local_technical_evaluation'),
        process=dict(execution='synchronous-no-detach',exit='zero-success-nonzero-failure',stop='process-group-term-kill',idempotency='no-replay',timeout_seconds=3),
        seconds_min=0.1,seconds_max=2.0,seconds_default=0.1,seed_default=7)


DOCUMENTS = [
    evidence(['--words','--duration','--random','--wave','--report'],['wave','words','duration','random','build'],'1.0'),
    evidence(['--description','--length','--seed-value','--destination','--manifest'],['file','description','length','seed_value','version'],'2.4')]


class TemplateCatalog(Catalog):
    test_only = True

    def __init__(self,root):
        super().__init__()
        self.targets = []
        interpreter = str(Path(sys.executable).resolve())
        runtime_digest = hashlib.sha256(Path(interpreter).read_bytes()).hexdigest()
        for leaf in ('lumen-tone','ripple-forge'):
            directory = Path(root)/leaf
            directory.mkdir(parents=True)
            executable = directory/'tool'
            source = (Path(__file__).parent/'fixtures'/(leaf+'.py')).read_text().split('\n',1)[1]
            executable.write_text('#!'+interpreter+'\n'+source)
            executable.chmod(0o700)
            self.cli_targets[str(executable)] = dict(fixture=True,digest=hashlib.sha256(executable.read_bytes()).hexdigest(),
                                                  dependencies={interpreter:runtime_digest})
            self.targets.append(str(executable))


def count(target):
    file = Path(target).parent/'effects.jsonl'
    return len(file.read_text().splitlines()) if file.exists() else 0
