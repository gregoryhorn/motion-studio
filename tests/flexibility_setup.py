"""Trusted isolated catalog scenarios for the browser; no browser-controlled setup."""
from tests.adapter_fixtures import OfflineCatalog, FixtureA, FixtureB, worker_location, setup


def populate(runs, root):
    for name, adapter, reason in (('portable-a', FixtureA(), 'OFFLINE_ONLY'),
                                  ('portable-b', FixtureB(), 'OFFLINE_ONLY'),
                                  ('resource', FixtureB(), 'RESOURCE_BUSY'),
                                  ('restricted', FixtureB(), 'USE_RESTRICTED'),
                                  ('missing', FixtureB(), 'APP_MISSING'),
                                  ('stale', FixtureB(), 'RUNTIME_DRIFT')):
        location = worker_location(root / name, adapter)
        record = setup(runs, adapter, location)
        if reason == 'APP_MISSING':
            location.unlink()
            runs.bindings.check_setup(record['id'], record['revision'])
        elif reason == 'RUNTIME_DRIFT':
            location.write_text(location.read_text() + '\n# controlled offline drift\n')
            runs.bindings.check_setup(record['id'], record['revision'])
        elif reason != 'OFFLINE_ONLY':
            runs.bindings.revise(record['id'], record['revision'], reason=reason,
                availability='Restricted for this use' if reason == 'USE_RESTRICTED' else 'Unavailable',
                action='Choose a suitable local method' if reason == 'USE_RESTRICTED' else 'Review current resource issue')
