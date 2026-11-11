"""Explicit two-target synthetic browser harness; not available in studio launcher."""
import argparse
import json
from pathlib import Path
import uvicorn
from studio.server import create_app
from tests.template_support import TemplateCatalog,DOCUMENTS


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--home',type=Path,required=True)
    parser.add_argument('--port',type=int,required=True)
    parser.add_argument('--synthesis-fixture',action='store_true')
    args=parser.parse_args()
    catalog=TemplateCatalog(args.home/'tools')
    for index,doc in enumerate(DOCUMENTS):
        (args.home/f'document-{index}.json').write_text(json.dumps(doc))
    app=create_app(args.home/'var',(args.home/'test-secret').read_bytes(),f'http://127.0.0.1:{args.port}',_test_catalog=catalog)
    app.state.runs.worker.grace=0.1
    if args.synthesis_fixture:
        from tests.synthesis_web import install_fixture
        install_fixture(app)
    uvicorn.run(app,host='127.0.0.1',port=args.port,access_log=False,log_level='critical',proxy_headers=False)


if __name__=='__main__': main()
