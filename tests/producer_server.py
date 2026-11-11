"""TEST ONLY loopback harness with explicit fake-child injection, never normal launcher."""
import argparse
from pathlib import Path
import uvicorn
from studio.server import create_app
from tests.producer_support import fixture_binding


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--home', type=Path, required=True)
    parser.add_argument('--port', type=int, required=True)
    parser.add_argument('--flexibility', action='store_true')
    args = parser.parse_args()
    binding = fixture_binding(args.home / 'offline-tool')
    secret = (args.home / 'test-secret').read_bytes()
    if args.flexibility:
        from tests.adapter_fixtures import OfflineCatalog
        from tests.flexibility_setup import populate
        app = create_app(args.home / 'var', secret, f'http://127.0.0.1:{args.port}', _test_catalog=OfflineCatalog())
        populate(app.state.runs, args.home)
    else:
        app = create_app(args.home / 'var', secret, f'http://127.0.0.1:{args.port}', _test_binding=binding)
    uvicorn.run(app, host='127.0.0.1', port=args.port, access_log=False, log_level='critical', proxy_headers=False)


if __name__ == '__main__':
    main()
