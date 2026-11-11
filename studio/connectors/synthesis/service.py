"""One-shot inert proposal service. No inference on status/reopen or automatic repair."""
from contextvars import copy_context
import threading
from ...domain import Fault
from ...connectors.synthesis.host import StructuredCaller
from ...connectors.synthesis.validation import validate


def quietly(function, *args):
    # Even a secondary persistence failure must not make Python's thread error
    # printer expose the raw provider exception that led here. Durable claimed
    # work stays blocked; exclusive restart reconciliation marks it unknown.
    try:
        return function(*args)
    except Exception:
        return None


class Synthesis:
    def __init__(self, jobs, route, caller, authorized, *, launch=None, observation_seconds: float=120):
        self.jobs, self.route, self.caller, self.authorized = jobs, route, caller, authorized
        self.launch = launch or self._launch
        self.workers = []
        self.observation_seconds = min(120, observation_seconds)

    def _launch(self, task):
        context = copy_context()
        thread = threading.Thread(target=lambda: quietly(context.run, task), daemon=True, name='connector-proposal')
        self.workers.append(thread)
        thread.start()

    def gate(self, scope):
        if not self.authorized(scope): raise Fault('SYNTHESIS_SCOPE_DENIED', 403)
        self.route().require()

    def prepare(self, scope, command, evidence, revision, template):
        self.gate(scope)
        with self.jobs.store.transaction() as db:
            selected = self.jobs.evidence(db, scope, evidence)
        # Build/size-check before durable invocation-possible or facade access.
        packet = StructuredCaller.packet(selected['body'])
        row, created = self.jobs.prepare(scope, command, evidence, revision, template, self.route().revision)
        if created: self.launch(lambda: self.work(scope, row['id'], packet))
        return self.jobs.public(row)

    def read(self, scope, identifier, *, result=False):
        # Reads remain possible if route unavailable, but require current ownership.
        if not self.authorized(scope): raise Fault('SYNTHESIS_SCOPE_DENIED', 403)
        with self.jobs.store.transaction() as db:
            row = self.jobs.owned(db, scope, identifier)
        return self.jobs.public(row, result)

    def abandon(self, scope, identifier):
        if not self.authorized(scope): raise Fault('SYNTHESIS_SCOPE_DENIED', 403)
        with self.jobs.store.transaction() as db:
            row = self.jobs.owned(db, scope, identifier)
            if row['active']:
                row.update(discarded=True, result=None)
                row['state'] = 'Abandoned' if row['invocation_possible'] else 'Cancelled before dispatch'
                if not row['invocation_possible']: row['active'] = False
                self.jobs.write(db, row)
        return self.jobs.public(row)

    def find(self, scope, command):
        if not self.authorized(scope): raise Fault('SYNTHESIS_SCOPE_DENIED', 403)
        with self.jobs.store.transaction() as db:
            found = db.execute('SELECT id FROM cs_jobs WHERE profile=? AND session=? AND command=?',
                               (scope.profile, scope.session, command)).fetchone()
            if not found: return dict(state='Command not observed', active=True, id=None)
            return self.jobs.public(self.jobs.owned(db, scope, found[0]))

    def work(self, scope, identifier, packet):
        try:
            self.gate(scope)
            with self.jobs.store.transaction() as db:
                row = self.jobs.owned(db, scope, identifier)
                if row['state'] != 'Prepared' or row['discarded']: return
                if not self.jobs.fresh(db, scope, row, self.route().revision):
                    row.update(state='Stale proposal', active=False)
                    self.jobs.write(db, row)
                    return
                selected = self.jobs.evidence(db, scope, row['evidence'])
                # Atomically wins against pre-dispatch abandon; crash from here
                # onwards is ambiguous even if the call has not yet begun.
                row.update(state='In flight', invocation_possible=True)
                self.jobs.write(db, row)
            context = copy_context()
            deadline = threading.Timer(self.observation_seconds, lambda:quietly(context.run, self.failed, scope, identifier))
            deadline.daemon = True
            deadline.start()
            try:
                response = self.caller(packet)
            finally:
                deadline.cancel()
        except Exception:
            self.failed(scope, identifier)
            return
        try:
            with self.jobs.store.transaction() as db:
                row = self.jobs.owned(db, scope, identifier)
                if not row['discarded'] and row['state'] == 'In flight':
                    row['state'] = 'Validating'
                    self.jobs.write(db, row)
            result = validate(response, selected['body'])
        except Exception:
            result = dict(state='Invalid proposal', error='INVALID_PROPOSAL',
                          questions=['Select clearer supported documentation before a deliberate new preparation.'])
        # Raw response/provider error never reaches persistence or event/log APIs.
        del response
        with self.jobs.store.transaction() as db:
            row = self.jobs.owned(db, scope, identifier)
            if row['discarded']:
                row.update(state='Abandoned', active=False, result=None)
            elif row['state'] not in ('In flight', 'Validating'):
                # A restart/unknown marker cannot be treated as newly admitted work.
                row.update(state='Stale proposal', active=False, result=None)
            else:
                try:
                    self.gate(scope)
                    fresh = self.jobs.fresh(db, scope, row, self.route().revision)
                except Exception:
                    fresh = False
                row.update(state=result['state'] if fresh else 'Stale proposal', active=False,
                           result=result if fresh else None)
            self.jobs.write(db, row)

    def failed(self, scope, identifier):
        with self.jobs.store.transaction() as db:
            row = self.jobs.owned(db, scope, identifier)
            if not row['active']: return
            if row['invocation_possible']:
                row.update(state='Abandoned' if row['discarded'] else 'Outcome unknown', error='SETTLEMENT_UNOBSERVED')
            else:
                row.update(state='Cancelled before dispatch', active=False, error='ADMISSION_UNAVAILABLE')
            self.jobs.write(db, row)
