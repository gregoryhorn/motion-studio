"""Additional independently exercised race/interpreter/mismatch boundaries."""
import concurrent.futures
import json
from pathlib import Path
import threading
import time
from studio.domain import Fault
from studio.persistence.store import identity
from studio.connectors.synthesis.host import StructuredCaller
from studio.connectors.synthesis.service import Synthesis
from studio.connectors.synthesis.validation import validate
from tests.test_connector_synthesis import SynthesisFixture
from tests.synthesis_support import selection, envelope, HOME


class AdditionalBoundaries(SynthesisFixture):
    def test_packet_refusal_is_before_job_or_invocation_admission(self):
        docs = selection()
        for index in range(4):
            docs['sources'][0]['excerpts'].append(dict(id='extra-'+str(index), section='Reference',
                text='Public technical specification. ' * 100))
        selected = self.jobs.select(self.scope, docs)
        command = identity()
        with self.assertRaisesRegex(Fault, 'SYNTHESIS_PACKET_TOO_LARGE'):
            self.prepare(command=command, evidence=selected['id'])
        with self.store.transaction() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM cs_jobs').fetchone()[0], 0)
        self.assertEqual(self.service.find(self.scope, command)['state'], 'Command not observed')
        self.assertEqual(self.held, [])
        self.assertFalse(self.facade.calls)

    def test_real_public_manual_excerpt_does_not_qualify_sox(self):
        docs = json.loads((HOME/'sox-mismatch.json').read_text())
        self.jobs.select(self.scope, docs)
        item = envelope();version = docs['sources'][0]['version']
        item['tool_version'] = item['mapping']['tool_version'] = version
        quote = docs['sources'][0]['excerpts'][0]['text']
        for refs in item['evidence_map'].values():
            for ref in refs: ref.update(excerpt='part-0', quote=quote)
        result = validate(self.response(item), docs)
        self.assertEqual(result['state'], 'Needs information')
        self.assertNotIn('proposal', result)
        self.assertLessEqual(len(result['questions']), 3)

    def test_contradictory_flag_receipt_and_colon_claims(self):
        for text in ('Argument 1 uses --invented for direction.', 'Receipt output field: wrong.',
                     'Model use: requires-model.'):
            docs = selection()
            docs['sources'][0]['excerpts'].append(dict(id='contradiction',section='Reference',text=text))
            self.assertEqual(validate(self.response(envelope()), docs)['state'], 'Needs information')

    def test_atomic_duplicate_prepare_race(self):
        command = identity()
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
            futures = [pool.submit(self.prepare, command=command) for _ in range(6)]
            rows = [future.result() for future in futures]
        self.assertEqual(len({row['id'] for row in rows}), 1)
        self.assertEqual(len(self.held), 1)
        self.run_job();self.assertEqual(len(self.facade.calls), 1)

    def test_observation_deadline_unknown_then_late_result_discard(self):
        arrived, release = threading.Event(), threading.Event()
        def hold(): arrived.set();release.wait(5)
        self.facade.hook = hold
        service = Synthesis(self.jobs, lambda:self.policy, StructuredCaller(self.facade),
                            lambda s:s == self.scope, observation_seconds=0.02)
        row = service.prepare(self.scope, identity(), self.selected['id'], 1, self.selected['template'])
        try:
            self.assertTrue(arrived.wait(3))
            deadline = time.monotonic()+3
            while service.read(self.scope, row['id'])['state'] == 'In flight' and time.monotonic()<deadline:
                time.sleep(0.01)
            self.assertEqual(service.read(self.scope, row['id'])['state'], 'Outcome unknown')
            with self.assertRaisesRegex(Fault, 'SLOT_BLOCKED'): self.prepare()
        finally:
            release.set()
            for thread in service.workers: thread.join(5)
        self.assertEqual(self.result(row)['state'], 'Stale proposal')
        self.assertIsNone(self.result(row)['result'])
        self.assertEqual(len(self.facade.calls), 1)

    def test_restart_during_validation_keeps_unknown_and_no_replay(self):
        row = self.prepare()
        with self.store.transaction() as db:
            saved = self.jobs.owned(db, self.scope, row['id'])
            saved.update(state='Validating', invocation_possible=True)
            self.jobs.write(db, saved)
        self.jobs.recover();self.run_job()
        self.assertEqual(self.result(row)['state'], 'Outcome unknown')
        self.assertFalse(self.facade.calls)

    def test_validated_mapping_reuses_existing_disabled_candidate_checks(self):
        from studio.server import create_app
        from studio.connectors.schema import Intake, RevisionAction
        from tests.template_support import TemplateCatalog, count, DOCUMENTS
        catalog = TemplateCatalog(Path(self.temp.name)/'fixture-tools')
        app = create_app(Path(self.temp.name)/'separate-fixture-var', b'nonprivate-offline-fixture-owner-value', _test_catalog=catalog)
        self.addCleanup(app.state.runs.close)
        for index in (0, 1):
            self.selected = self.jobs.select(self.scope, selection(index))
            row = self.prepare();self.run_job()
            proposal = self.result(row)['result']['proposal']
            draft = app.state.runs.connectors.save(Intake(name='Offline prose fixture', target=catalog.targets[index],
                source='selected-documentation', evidence=json.dumps(proposal['mapping'])))
            self.assertEqual(draft['state'], 'Disabled')
            checked = app.state.runs.connectors.check(RevisionAction(id=draft['id'], revision=draft['revision'], digest=draft['digest']))
            self.assertEqual(checked['candidate']['documented'], DOCUMENTS[index])
            self.assertEqual(checked['state'], 'Setup checked')
            self.assertFalse(app.state.runs.bindings.get(checked['binding'], checked['binding_revision'])['enabled'])
        self.assertEqual([count(t) for t in catalog.targets], [0, 0])

    def test_no_inference_when_evidence_changes_before_worker_claim(self):
        row = self.prepare();self.jobs.select(self.scope, selection(1));self.run_job()
        self.assertEqual(self.result(row)['state'], 'Stale proposal')
        self.assertFalse(self.facade.calls)

    def test_provider_and_secondary_store_errors_do_not_leak_thread_trace(self):
        import contextlib
        import io
        self.facade.hook = lambda: (_ for _ in ()).throw(RuntimeError('PRIVATE_PROVIDER_SENTINEL'))
        service = Synthesis(self.jobs, lambda:self.policy, StructuredCaller(self.facade), lambda s:s == self.scope)
        service.failed = lambda scope, identifier: (_ for _ in ()).throw(RuntimeError('SECONDARY_STORE_FAILURE'))
        output = io.StringIO()
        with contextlib.redirect_stderr(output):
            row = service.prepare(self.scope, identity(), self.selected['id'], 1, self.selected['template'])
            for worker in service.workers: worker.join(5)
        self.assertEqual(output.getvalue(), '')
        self.assertTrue(self.result(row)['invocation_possible'])
        self.assertTrue(self.result(row)['active'])
        self.assertNotIn(b'PRIVATE_PROVIDER_SENTINEL', self.store.database.read_bytes())

    def test_isolated_style_facade_wire_preserves_bound_profile(self):
        from contextvars import ContextVar
        from types import SimpleNamespace
        profile = ContextVar('isolated-fixture-profile', default='wrong-launch')
        seen = []
        facade = self.facade
        class RemoteFacade:
            def complete_structured(self, **packet):
                # Simulated fixed plugin-key facade forwarding, not an actual
                # isolated host/auth qualification or browser profile override.
                wire = json.loads(json.dumps(dict(plugin_key='fixed-plugin-key', facade='llm', method='complete_structured', kwargs=packet)))
                seen.append(profile.get())
                response = facade.complete_structured(**wire['kwargs'])
                return SimpleNamespace(**json.loads(json.dumps(dict(text=response.text, parsed=response.parsed))))
        service = Synthesis(self.jobs, lambda:self.policy, StructuredCaller(RemoteFacade()), lambda s:s == self.scope)
        token = profile.set('owning-profile')
        try:
            row = service.prepare(self.scope, identity(), self.selected['id'], 1, self.selected['template'])
            for worker in service.workers: worker.join(5)
        finally: profile.reset(token)
        self.assertEqual(seen, ['owning-profile'])
        self.assertEqual(self.result(row)['state'], 'Proposal ready')
