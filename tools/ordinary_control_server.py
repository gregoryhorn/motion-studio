"""One authorized ordinary-control check server; normal app runtime, no test grant.

Owned loopback/temp credential only. The durable audit reservation refuses a repeated
real check. It does not grant producer authority: only normal authenticated Create does.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import time
import uvicorn
from studio.domain import Fault
from studio.producer import local_sfx as sfx
from studio.producer.evaluation import enable_evaluation
from studio.producer.live_sfx import resources, USE
from studio.runs.persistence import ACTIVE
from studio.server import create_app


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--state',type=Path,required=True)
    parser.add_argument('--secret-file',type=Path,required=True)
    parser.add_argument('--port',type=int,required=True)
    args = parser.parse_args()
    try:
        info = args.secret_file.lstat()
        import os, stat
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise Fault('UNSAFE_SECRET_FILE',409)
        secret = args.secret_file.read_bytes()
        app = create_app(args.state,secret,f'http://127.0.0.1:{args.port}')
        runs = app.state.runs
        if any(row['status'] in ACTIVE for row in runs.records.rows()):
            raise Fault('EFFECT_UNCERTAIN',409)
        files = {**sfx.FILE_PINS,**sfx.model_pins()}
        sfx.check_pins(files)
        free, conflict = resources()
        disk = shutil.disk_usage(args.state).free
        sfx.eligible_resources(free,True,disk,conflict)
        manifest = hashlib.sha256(Path('docs/evidence/code-manifest.json').read_bytes()).hexdigest()
        with runs.store.transaction() as db:
            db.execute('CREATE TABLE IF NOT EXISTS ordinary_control_checks(label TEXT PRIMARY KEY, created REAL, source TEXT)')
            if db.execute("SELECT 1 FROM ordinary_control_checks WHERE label='CF-QS1-r2-one-real'").fetchone():
                raise Fault('ORDINARY_CHECK_ALREADY_RESERVED',409)
            db.execute('INSERT INTO ordinary_control_checks VALUES(?,?,?)',('CF-QS1-r2-one-real',time.time(),manifest))
        original = runs.bindings.seed(runs.binding)
        record = enable_evaluation(runs.bindings,original['id'],original['revision'])
        print(json.dumps(dict(readiness='passed',pins_checked=len(files),free_mib=free,conflict=conflict,
            use=USE,binding=record['id'],binding_revision=record['revision'],source_manifest=manifest,
            observation='Fresh passive observation, repeated by normal runtime immediately before launch')),flush=True)
        uvicorn.run(app,host='127.0.0.1',port=args.port,access_log=False,log_level='critical',proxy_headers=False)
    except Fault as error:
        print(json.dumps(dict(readiness='blocked',reason=error.code)),flush=True)
        raise SystemExit(1) from None


if __name__ == '__main__':
    main()
