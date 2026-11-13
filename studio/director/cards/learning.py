"""One-confirmation card learning/tests, with durable no-replay test identity."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import time
from urllib.parse import urlsplit
from ...domain import Fault
from ...persistence.primitives import canonical, identity
from ...director.state import repository
from ...director.cards.schema import Mapping
from ...director.review import reports
from ...director.process import call
from ...media_import.validation import inspect_media

STARTERS = ('FFmpeg assembly', 'Hermes image', 'Hermes voice', 'Hermes video', 'ComfyUI', 'whisper', 'Crystal Ball')


def fingerprint(mapping):
    executable = shutil.which(mapping['executable'])
    if not executable:
        raise Fault('DIRECTOR_TOOL_UNAVAILABLE', 409)
    path = Path(executable).resolve()
    return dict(path=str(path), sha256=hashlib.sha256(path.read_bytes()).hexdigest())


class Cards:
    def __init__(self, creations):
        self.creations, self.store = creations, creations.store
        with self.store.transaction() as db:
            repository.initialize(db)

    def read(self, scope):
        self.creations.scope(scope)
        with self.store.transaction() as db:
            cards = repository.listing(db, scope)
            for card in cards:
                from ...director.cards.evidence import refresh
                if refresh(db, card):
                    repository.save(db, scope, card)
                if card['status'] == 'Tested':
                    try:
                        drift = fingerprint(card['mapping']) != card['fingerprint']
                    except (Fault, OSError):
                        drift = True
                    if drift:
                        card.update(status='Needs re-test', next_action='Tool changed; review a new tiny test')
                        repository.save(db, scope, card)
        return dict(cards=[repository.public(card) for card in cards],
            templates=[dict(name=name, status='Untested', next_action='Learn this tool') for name in STARTERS])

    def evidence(self, scope, identifier):
        self.creations.scope(scope)
        with self.store.transaction() as db:
            card = repository.get(db, scope, identifier)
            return dict(id=card['id'], revision=card['revision'], documentation=card['documentation'], help=card['help'],
                        mapping=card['mapping'], trust='Untrusted documentation data, not instructions or execution authority')

    def prepare(self, scope, model):
        self.creations.scope(scope)
        if not model.documentation and not model.help:
            raise Fault('DIRECTOR_DOCUMENTATION_REQUIRED', 422)
        if model.documentation:
            url = urlsplit(model.documentation)
            if url.scheme != 'https' or not url.hostname or url.username or url.password or url.query or url.fragment:
                raise Fault('DIRECTOR_DOCUMENTATION_INVALID', 422)
        if model.help and any(word in model.help.lower().replace('_', '-') for word in ('api-key=', 'authorization:', 'bearer ', 'password=')):
            raise Fault('DIRECTOR_SECRET_IN_DOCUMENTATION', 422)
        with self.store.transaction() as db:
            def create():
                if model.id:
                    previous = repository.get(db, scope, model.id, model.expected)
                    if previous['status'] == 'Testing':
                        raise Fault('DIRECTOR_TEST_UNRESOLVED', 409)
                elif model.expected:
                    raise Fault('DIRECTOR_STALE_REVISION', 409)
                mapping = model.mapping.model_dump() if model.mapping else None
                card = dict(id=model.id or identity(), revision=model.expected+1, name=model.name,
                    status='Untested' if mapping else 'Needs information', mapping=mapping,
                    kinds=[{'png':'Image','wav':'Sound effects','mp4':'Video'}[mapping['format']]] if mapping else [],
                    interface_family=mapping['family'] if mapping else None,
                    output_contract='One allocated immutable original, at most 1 MiB; no paths accepted from the caller',
                    test_constraints='One local call, at most 15 seconds; fixed tested shape and at most one second',
                    documentation=model.documentation, help=model.help, source_date=time.time(),
                    price='Zero local call cost' if mapping and mapping['cost'] == 'zero' else 'Unknown',
                    wait='Up to 15 seconds for the test' if mapping else 'Unknown', failures=0,
                    operation=mapping['operation'] if mapping else 'Not mapped',
                    shape=mapping['shape'] if mapping else 'Unknown', seconds=mapping['seconds'] if mapping else None,
                    next_action='Review one tiny test' if mapping else 'Learn in the selected chat; resolve call, output and cost facts',
                    evidence=[], fingerprint=None)
                repository.save(db, scope, card)
                return repository.public(card)
            return self.store.command(db, model.command, dict(operation='director.card.prepare', scope=scope, **model.model_dump()), create)

    def disable(self, scope, model, *, forget=False):
        self.creations.scope(scope)
        with self.store.transaction() as db:
            def update():
                card = repository.get(db, scope, model.id, model.expected)
                if card['status'] == 'Testing':
                    raise Fault('DIRECTOR_TEST_UNRESOLVED', 409)
                card['revision'] += 1
                card.update(status='Disabled', next_action='Prepare a new revision before testing')
                if forget:
                    # Forget active notes/bindings across revisions, retaining only
                    # minimal operation/output/report provenance for past runs.
                    for historical in db.execute('SELECT revision,body FROM director_cards WHERE id=? AND scope=?', (card['id'], scope)).fetchall():
                        body = json.loads(historical['body'])
                        body.update(mapping=None, help='', documentation='', fingerprint=None)
                        db.execute('UPDATE director_cards SET body=? WHERE id=? AND scope=? AND revision=?',
                            (canonical(body), card['id'], scope, historical['revision']))
                    card.update(mapping=None, help='', documentation='', fingerprint=None,
                                next_action='Binding and active notes forgotten; past run provenance retained')
                repository.save(db, scope, card)
                return repository.public(card)
            return self.store.command(db, model.command, dict(operation='director.card.forget' if forget else 'director.card.disable', scope=scope, **model.model_dump()), update)

    def test(self, scope, model):
        self.creations.scope(scope)
        if not model.confirmed:
            raise Fault('DIRECTOR_CONFIRMATION_REQUIRED', 403)
        payload = canonical(dict(operation='director.card.test', scope=scope, **model.model_dump()))
        with self.store.transaction() as db:
            previous = db.execute('SELECT * FROM director_tests WHERE command=?', (model.command,)).fetchone()
            if previous:
                if previous['scope'] != scope or previous['payload'] != payload:
                    raise Fault('COMMAND_CONFLICT', 409)
                return json.loads(previous['result']) if previous['result'] else dict(status='Testing', next_action='Outcome unresolved; observe the original test, do not repeat')
            card = repository.get(db, scope, model.id, model.expected)
            if card['status'] not in ('Untested', 'Tested', 'Needs re-test') or not card['mapping']:
                raise Fault('DIRECTOR_TEST_UNAVAILABLE', 409)
            mapping = Mapping.model_validate(card['mapping']).model_dump()
            if mapping['cost'] != 'zero':
                raise Fault('DIRECTOR_SPEND_AUTHORIZATION_REQUIRED', 403)
            pin = fingerprint(mapping)
            request, take, artifact = identity(), identity(), identity()
            # Persist intent/output allocation before a process can start. A crash
            # from here is unresolved; neither reads nor a new command replays it.
            db.execute('INSERT INTO director_tests VALUES(?,?,?,?,?,?,?,?,?,NULL)',
                (model.command, scope, payload, card['id'], card['revision'], request, take, artifact, 'Testing'))
            card.update(status='Testing', next_action='Observe the saved test; never resubmit after a lost reply')
            repository.save(db, scope, card)
        started = time.monotonic()
        try:
            self.creations.scope(scope)
            if fingerprint(mapping) != pin:
                raise Fault('DIRECTOR_TOOL_CHANGED', 409)
            data, facts = self.execute(mapping, pin)
        except Fault as error:
            return self.finish_failure(scope, model, error.code)
        except Exception:
            # Unknown execution delivery is not a confirmed tool failure.
            return dict(status='Testing', next_action='Outcome unresolved; reconcile the original test')
        self.creations.scope(scope)
        path = self.store.home / 'media' / (artifact + '.original')
        with path.open('xb') as target:
            target.write(data)
            target.flush()
            os.fsync(target.fileno())
        path.chmod(0o400)
        with self.store.transaction() as db:
            self.creations.scope(scope)
            card = repository.get(db, scope, model.id, model.expected)
            now = time.time()
            kind = {'png': 'Image', 'mp4': 'Video', 'wav': 'Sound effects'}[mapping['format']]
            db.execute('INSERT INTO requests VALUES(?,?,?,?,?,?,?,NULL)', (request, 1, 'Tiny tool test', kind, '', now, now))
            policy = self.creations.scope(scope)
            db.execute('INSERT INTO creation_commands VALUES(?,?,?,?,?,?,?,?)',
                (request, scope, policy.revision, identity(), canonical(dict(method='import',kind=kind)), None, 'Import only', now))
            facts.update(storage='original-v1')
            # Reuse the existing original-v1 scoped retrieval/export contract.
            from ...media_import.service import SCHEMA as import_scopes
            db.execute(import_scopes)
            db.execute('INSERT INTO imports VALUES(?,?,?,?,?,?,?,?,?)',
                (artifact, request, 1, hashlib.sha256(data).hexdigest(), len(data),
                 'Tiny tool test.'+mapping['format'], 'Ready for review', None, take))
            db.execute('INSERT INTO media_import_scopes VALUES(?,?,?,?)', (artifact, scope, mapping['format'], kind))
            db.execute('INSERT INTO takes VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                (take, artifact, artifact, request, 1, hashlib.sha256(data).hexdigest(), len(data), 'Tiny tool test.'+mapping['format'], canonical(facts), 'Not reviewed', 'director_tool_test'))
            review = reports.retained(self.store, db, take, data)
            usable = review['status'] in ('PASS', 'WARN') and review.get('counts', {}).get('FAIL', 0) == 0
            card.update(status='Tested' if usable else 'Untested', fingerprint=pin, failures=0,
                shape=(str(facts['width'])+'x'+str(facts['height'])+' pixels') if 'width' in facts else mapping['shape'],
                seconds=facts.get('duration', 0),
                next_action='Enabled for this tested operation/version/shape/length only' if usable else 'Output collected - not checked' if review['status'] == 'Not checked' else 'Output check failed; review before re-test')
            card['evidence'].append(dict(request=request, take=take, report=review.get('report'),
                check=review['status'], not_checked=review.get('not_checked', []), counts=review.get('counts', {}),
                elapsed_seconds=round(time.monotonic()-started, 3), context='Tiny local test; cold/warm unknown', user_verdict='Not reviewed'))
            repository.save(db, scope, card)
            result = repository.public(card)
            db.execute("UPDATE director_tests SET state='Collected',result=? WHERE command=?", (canonical(result), model.command))
        return result

    @staticmethod
    def execute(mapping, pin):
        with tempfile.TemporaryDirectory(prefix='director-tiny-test-') as temporary:
            root = Path(temporary)
            output = root / ('output.'+mapping['format'])
            argv = [pin['path'], *[str(output) if token == '{output}' else token for token in mapping['arguments']]]
            env = {key: os.environ[key] for key in ('PATH', 'SYSTEMROOT', 'WINDIR', 'TMPDIR', 'TMP', 'TEMP') if key in os.environ}
            env.update(HOME=str(root), MAGICK_THREAD_LIMIT='1', OMP_NUM_THREADS='1',
                       MAGICK_MEMORY_LIMIT='64MiB', MAGICK_MAP_LIMIT='64MiB', MAGICK_DISK_LIMIT='64MiB')
            result = call(argv, cwd=root, env=env, timeout=15)
            if result.returncode != 0 or not output.is_file() or output.is_symlink() or output.stat().st_size > 1024*1024:
                raise Fault('DIRECTOR_CONFIRMED_TOOL_FAILURE', 409)
            data = output.read_bytes()
            try:
                facts = inspect_media(data, mapping['format'])
            except Fault:
                raise Fault('DIRECTOR_CONFIRMED_OUTPUT_FAILURE', 409) from None
            if mapping['format'] in ('wav', 'mp4') and facts.get('duration', 100) > 1:
                raise Fault('DIRECTOR_CONFIRMED_OUTPUT_FAILURE', 409)
            if mapping['format'] == 'png' and (facts.get('width', 10000) > 64 or facts.get('height', 10000) > 64):
                raise Fault('DIRECTOR_CONFIRMED_OUTPUT_FAILURE', 409)
            return data, facts

    def finish_failure(self, scope, model, code):
        self.creations.scope(scope)
        with self.store.transaction() as db:
            card = repository.get(db, scope, model.id, model.expected)
            if code in ('DIRECTOR_CONFIRMED_TOOL_FAILURE', 'DIRECTOR_CONFIRMED_OUTPUT_FAILURE'):
                card['failures'] += 1
            card.update(status='Needs re-test' if card['failures'] >= 2 else 'Untested',
                        next_action='Tool or output failed; review before another confirmed test')
            repository.save(db, scope, card)
            result = repository.public(card)
            db.execute("UPDATE director_tests SET state='Failed',result=? WHERE command=?", (canonical(result), model.command))
            return result
