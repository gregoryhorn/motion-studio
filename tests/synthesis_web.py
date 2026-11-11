"""Test-only web shim around the registered RPC boundary, never normal launch."""
from pathlib import Path
from fastapi import Request
from fastapi.responses import Response
from studio.connectors.synthesis.host import StructuredCaller, Scope
from studio.connectors.synthesis.jobs import Jobs
from studio.connectors.synthesis.service import Synthesis
from studio.native.backend.registration import register
from tests.synthesis_support import Context, Ports, Facade, route
from tests.template_support import count


def install_fixture(app):
    fallback = app.router.routes.pop()
    assert fallback.path == '/{path:path}'
    jobs, facade = Jobs(app.state.store), Facade()
    scope = Scope('fixture-profile', 'fixture-session', 1)
    service = Synthesis(jobs, route, StructuredCaller(facade), lambda s:s == scope)
    ctx = Context();ports = Ports(service, scope);register(ctx, ports=ports)

    @app.get('/fixture/synthesis')
    def page():
        return Response('<!doctype html><html lang="en"><head><link rel="stylesheet" href="/style.css"><title>Offline synthesis fixture</title></head><body><main><h1>Offline CS1 fake host</h1><div id="fixture-root"></div><button id="fixture-switch">Change fixture session</button><script type="module" src="/fixture/synthesis.js"></script></main></body></html>', media_type='text/html')

    @app.get('/fixture/synthesis.js')
    def script():
        return Response((Path(__file__).parent/'synthesis-fixture.js').read_text(), media_type='text/javascript')

    @app.post('/api/cs1/selection')
    async def select(request: Request):
        return jobs.select(scope, await request.json())

    @app.post('/api/cs1/rpc')
    async def rpc(request: Request):
        body = await request.json()
        if set(body) != {'route', 'method', 'params'}: return dict(error='INVALID_FIXTURE_RPC')
        if body['route'] != dict(connectionId='fixture-local', mode='local', profile='fixture-profile', targetProfile='fixture-profile'):
            return dict(error='GATEWAY_DENIED')
        method = body['method']
        if method not in ctx.methods: return dict(error='METHOD_DENIED')
        params = body['params']
        if params.get('session_id') != scope.session: return dict(error='GATEWAY_DENIED')
        return ctx.methods[method](params, session_id=scope.session)

    @app.get('/api/cs1/receipt')
    def receipt():
        return dict(kind='fake-host-only', facade_calls=len(facade.calls), effects=[count(t) for t in app.state.runs.catalog.targets])
    app.router.routes.append(fallback)
