"""Explicit synthetic ordinary UI harness. No such fixture switches in normal launcher."""
import argparse
import os
from pathlib import Path
import uvicorn
from studio.assets.producer_files import allocation
from studio.producer.evaluation import enable_evaluation
from studio.server import create_app
from tests.producer_support import fixture_binding


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--home',type=Path,required=True)
    parser.add_argument('--port',type=int,required=True)
    parser.add_argument('--legacy',action='store_true')
    args = parser.parse_args()
    binding = fixture_binding(args.home/'offline-tool','cache-layout-mismatch' if args.legacy else 'good')
    app = create_app(args.home/'var',(args.home/'test-secret').read_bytes(),f'http://127.0.0.1:{args.port}',_test_binding=binding)
    runs = app.state.runs
    runs.worker.grace = 0.1
    old = runs.bindings.seed(binding)
    enable_evaluation(runs.bindings,old['id'],old['revision'])
    if args.legacy:
        original = runs.prepare_app
        def prepare(model):
            receipt = original(model)
            row = runs.records.get(receipt['id'])
            # Only the first synthetic plan receives an old shared allocation.
            if len(runs.records.rows()) == 1 and row['process'] is None:
                _, descriptor, pin = allocation(runs.store,row)
                os.close(descriptor)
                runs.records.update(row['id'],process=dict(allocation=pin))
            return receipt
        runs.prepare_app = prepare
    uvicorn.run(app,host='127.0.0.1',port=args.port,access_log=False,log_level='critical',proxy_headers=False)


if __name__ == '__main__':
    main()
