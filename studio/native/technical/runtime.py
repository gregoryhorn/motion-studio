"""Lazy isolated public context association; no private host imports or live defaults."""
from dataclasses import dataclass, field, replace
import threading
from ...domain import Fault
from ...connectors.synthesis.host import Route, Scope, StructuredCaller
from ...connectors.synthesis.service import Synthesis, quietly
from ...native.technical.storage import TechnicalStore
from ...native.technical.records import TechnicalJobs

AUDIENCE = 'Gateway-authorized session controllers, including operators and multiple clients of the same session; not exclusive human or LOCAL-only proof.'


@dataclass
class TechnicalPolicy:
    # Internal reviewed association only; never settings/env/renderer authority.
    audience_accepted: bool = False
    revision: str = 'unconfigured'
    expected_instance: str = ''
    create_store: bool = False
    route: Route = field(default_factory=Route)


class TechnicalRuntime:
    def __init__(self, ctx, policy=None):
        self.ctx = ctx
        self.policy = policy or TechnicalPolicy()
        self.enabled = True
        self.mutex = threading.RLock()
        self.store = self.jobs = self.service = None
        self.retirement = None

    def route(self):
        route = self.policy.route
        return replace(route, revision=route.revision+':'+self.policy.revision if route.revision else '')

    def authorized(self, scope):
        return bool(self.enabled and self.policy.audience_accepted and self.store and self.store.held
                    and scope.profile == self.store.instance and scope.epoch == 0)

    def acquire(self, session):
        if not self.enabled or not self.policy.audience_accepted:
            raise Fault('TECHNICAL_ACCESS_UNAVAILABLE', 409)
        if self.store is None:
            store = TechnicalStore(self.ctx.state.data_dir, expected_instance=self.policy.expected_instance,
                                   create=self.policy.create_store)
            try:
                jobs = TechnicalJobs(store)
                jobs.recover()  # Exclusive lease only; never resubmit.
                self.store, self.jobs = store, jobs
                self.service = Synthesis(jobs, self.route, self.call, self.authorized)
            except BaseException:
                store.close()
                raise
        # epoch=0 is a stable record partition, NOT a host lifecycle epoch.
        return Scope(self.store.instance, session, 0)

    def call(self, packet):
        # Resolve the public remote facade only AFTER verified route/claim.
        return StructuredCaller(self.ctx.llm)(packet)

    def status(self, scope, *, job=None, command=None):
        service, store, jobs = self.service, self.store, self.jobs
        if service is None or store is None or jobs is None: raise Fault('TECHNICAL_ACCESS_UNAVAILABLE', 409)
        if job: return service.read(scope, job)
        if command: return service.find(scope, command)
        try:
            self.route().require()
            inference = 'admitted'
        except Fault: inference = 'unavailable'
        return dict(audience=AUDIENCE, inference=inference, private_media='unavailable',
            service_generation=store.generation, **jobs.overview(scope))

    def unload(self):
        with self.mutex:
            if not self.enabled: return
            self.enabled = False
            service, jobs, store = self.service, self.jobs, self.store
            if service is None or jobs is None or store is None: return
            # Stop admission immediately; retain lock until owned workers settle.
            workers = tuple(service.workers)
            def retire():
                for worker in workers: worker.join()
                jobs.recover()
                store.close()
            if any(worker.is_alive() for worker in workers):
                self.retirement = threading.Thread(target=lambda:quietly(retire), daemon=True, name='technical-retirement')
                self.retirement.start()
            else: quietly(retire)
