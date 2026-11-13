"""Root-scoped commands over the existing request/run/asset authority."""
import base64
import hashlib
import json
import time
from ...domain import Fault, opaque, ReviewAction, TakeAction
from ...persistence.store import canonical, identity
from ...producer.contracts import PrepareApp
from ...assets.retention import Assets
from ...native.creation import music, hermes
from ...producer.music.contract import OPERATION
from ...media_import.contracts import describe_take
from ...director.state.projections import summary as director_summary, active as director_active


class Creations:
    def __init__(self, runtime, store, runs):
        self.runtime, self.store, self.runs = runtime, store, runs
        self.assets = Assets(store)
        with store.transaction() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS creation_roots(root TEXT PRIMARY KEY, policy TEXT)''')
            db.execute('CREATE TABLE IF NOT EXISTS music_roots(root TEXT PRIMARY KEY, policy TEXT)')
            db.execute('CREATE TABLE IF NOT EXISTS music_intents(request TEXT PRIMARY KEY, policy TEXT)')
            db.execute('''CREATE TABLE IF NOT EXISTS creation_commands(
                request TEXT PRIMARY KEY, root TEXT, policy TEXT, command TEXT UNIQUE,
                input TEXT, run TEXT, phase TEXT, created REAL)''')
            hermes.initialize(db)

    def admit(self, root):
        self.runtime.access()
        with self.store.transaction() as db:
            db.execute('INSERT OR REPLACE INTO creation_roots VALUES(?,?)', (root, self.runtime.policy.revision))
        return dict(admitted=True, effects=self.runtime.policy.local_generator,
                    audience=self.runtime.policy.audience)

    def admit_music(self, root):
        self.runtime.access(root)
        policy = self.runtime.policy.music
        policy.access()
        with self.store.transaction() as db:
            db.execute('INSERT OR REPLACE INTO music_roots VALUES(?,?)', (root, policy.revision))
        return dict(admitted=True, effects=policy.effects, media='Music')

    def scope(self, root, *, effect=False, kind='Sound effects'):
        if kind == 'Music': return music.scope(self, root, effect)
        scope = self.runtime.access(root)
        with self.store.transaction() as db:
            row = db.execute('SELECT policy FROM creation_roots WHERE root=?', (root,)).fetchone()
        if not row or row[0] != scope.revision:
            raise Fault('CREATION_WORKFLOW_REVIEW_REQUIRED', 403)
        policy = self.runtime.policy
        if effect and not (policy.local_generator and policy.agent_starts and policy.delegated_starts):
            raise Fault('CREATION_EFFECT_REVIEW_REQUIRED', 403)
        return scope

    def owned(self, db, root, request):
        row = db.execute('SELECT * FROM creation_commands WHERE request=? AND root=?', (opaque(request), root)).fetchone()
        if not row:
            raise Fault('CREATION_SCOPE_DENIED', 403)
        return dict(row)

    def authorize_request(self, db, root, request):
        """Shared retained-source authority, including the saved Music policy pin."""
        command = self.owned(db, root, request)
        snapshot = self.store.request(db, request)
        is_external = hermes.external(command)
        self.scope(root, kind='Sound effects' if is_external else snapshot['kind'])
        if snapshot['kind'] == 'Music' and not is_external:
            pinned = db.execute('SELECT policy FROM music_intents WHERE request=?', (request,)).fetchone()
            if not pinned or pinned[0] != self.runtime.policy.music.revision:
                raise Fault('MUSIC_POLICY_CHANGED', 403)
        return snapshot

    def prepare(self, root, model):
        from ...native.skills import verify_integrity
        verify_integrity()
        if getattr(model, 'method', None) == 'hermes_tool':
            return hermes.prepare(self, root, model)
        kind = getattr(model, 'kind', 'Sound effects')
        scope = self.scope(root, kind=kind)
        value = dict(direction=model.direction, seconds=model.seconds, seed=model.seed, parent=model.parent)
        if kind == 'Music':
            value.update(kind=kind, schema_version=2, instrumental=model.instrumental,
                         reference_requested=model.reference_requested)
        encoded = canonical(value)
        with self.store.transaction() as db:
            if model.parent:
                self.owned(db, root, model.parent)
            recent = db.execute('SELECT * FROM creation_commands WHERE root=? ORDER BY rowid DESC LIMIT 1', (root,)).fetchone()
            recent = self.resolve(db, dict(recent)) if recent else None
            if recent and recent['input'] == encoded:
                if recent['phase'] == 'Unqualified': return self.read(root, recent['request'], db=db)
                if recent['run']: return self.read(root, recent['request'], db=db)
                self.unfinished(db, recent)
                pending = recent
            else:
                if recent: self.new_intent(db, recent, model.parent)
                request, command, now = identity(), identity(), time.time()
                # Commit permanent intent BEFORE plan construction or invocation.
                db.execute('INSERT INTO requests VALUES(?,?,?,?,?,?,?,NULL)',
                           (request, 1, model.direction, kind, '', now, now))
                db.execute('INSERT INTO creation_commands VALUES(?,?,?,?,?,?,?,?)',
                           (request, root, scope.revision, command, encoded, None, 'Preparing', now))
                pending = self.owned(db, root, request)
                if kind == 'Music':
                    db.execute('INSERT INTO music_intents VALUES(?,?)', (request, self.runtime.policy.music.revision))
            if kind == 'Music' and music.unsupported(model):
                db.execute("UPDATE creation_commands SET phase='Unqualified' WHERE request=?", (pending['request'],))
                return self.read(root, pending['request'], db=db)
        return self.finish_prepare(root, pending, model)

    def collect_output(self, root, model):
        return hermes.collect(self, root, model)

    def new_intent(self, db, recent, parent):
        if hermes.external(recent) and parent == recent['request']:
            db.execute("UPDATE external_submissions SET state='abandoned' WHERE request=? AND state='awaiting_output'", (recent['request'],))
            return
        if parent == recent['request'] and recent['phase'] == 'Unqualified': return
        if parent != recent['request'] or not recent['run']:
            raise Fault('CREATION_UNRESOLVED', 409)
        status = db.execute('SELECT status FROM local_runs WHERE id=?', (recent['run'],)).fetchone()[0]
        recovery = self.runs.recovery.get(recent['request'])
        successor = self.runs.records.get(recovery['successor']) if recovery and recovery.get('successor') else None
        worker = self.runs.threads.get(recent['run'])
        if (status not in ('Ready for review', 'Failed', 'Cancelled') or
                (recovery and recovery['state'] in ('Reserved','Applying')) or
                (successor and successor['status'] not in ('Ready for review','Failed','Cancelled')) or
                (worker and worker.is_alive())):
            raise Fault('CREATION_UNRESOLVED', 409)

    def unfinished(self, db, row):
        # The exclusive store lease and serialized tool/RPC service hold here.
        # Run + prepare receipt commit atomically; launch requires a run and the
        # engine's durable claim. This is proof from that authority, not a timeout.
        snapshot = self.store.request(db, row['request'], 1)
        if snapshot['kind'] == 'Music':
            pinned = db.execute('SELECT policy FROM music_intents WHERE request=?', (row['request'],)).fetchone()
            if not pinned or pinned[0] != self.runtime.policy.music.revision:
                raise Fault('MUSIC_POLICY_CHANGED', 403)
        if (row['phase'] != 'Preparing' or row['run'] or row['policy'] != self.runtime.policy.revision or
                snapshot['text'] != json.loads(row['input'])['direction'] or
                db.execute('SELECT 1 FROM receipts WHERE command=?', (row['command'],)).fetchone() or
                db.execute("SELECT 1 FROM local_runs WHERE json_extract(plan,'$.request')=?", (row['request'],)).fetchone()):
            raise Fault('CREATION_PREPARATION_UNCERTAIN', 409)

    def finish_prepare(self, root, row, model):
        kind = getattr(model, 'kind', 'Sound effects')
        self.scope(root, kind=kind)
        with self.store.transaction() as db:
            self.unfinished(db, row)
        binding = self.runtime.binding(kind)
        operation = OPERATION if kind == 'Music' else 'sfx'
        request, command = row['request'], row['command']
        with self.store.transaction() as db:
            selected = db.execute('SELECT * FROM app_methods WHERE request=?', (request,)).fetchone()
            if selected and (selected['binding'],selected['revision'],selected['operation']) != (binding['id'],binding['revision'],operation):
                raise Fault('CREATION_PREPARATION_CHANGED', 409)
        self.runs.bindings.select(request, binding['id'], binding['revision'], operation)
        receipt = self.runs.prepare_app(PrepareApp(command=command, request=request, revision=1,
            binding=binding['id'], binding_revision=binding['revision'], operation=operation,
            options=(dict(seconds=model.seconds, seed=model.seed, instrumental=True) if kind == 'Music' else
                     dict(seconds=model.seconds, seed=model.seed, language='en'))))
        with self.store.transaction() as db:
            db.execute("UPDATE creation_commands SET run=?,phase='Prepared' WHERE request=?", (receipt['id'], request))
        return self.read(root, request)

    def resolve(self, db, row):
        if not row['run']:
            receipt = db.execute('SELECT result FROM receipts WHERE command=?', (row['command'],)).fetchone()
            if receipt:
                row['run'] = json.loads(receipt[0])['id']
        return row

    def read(self, root, request=None, *, db=None):
        self.scope(root)
        if db is None:
            with self.store.transaction() as connection:
                return self.read(root, request, db=connection)
        if request is None:
            recent = db.execute('SELECT request FROM creation_commands WHERE root=? ORDER BY rowid DESC LIMIT 1', (root,)).fetchone()
            if not recent: return dict(current=None, submission_state='not_started')
            request = recent[0]
        row = self.resolve(db, self.owned(db, root, request))
        snapshot = self.authorize_request(db, root, request)
        kind = snapshot['kind']
        result: dict = dict(request=request, revision=snapshot['revision'], command=row['command'], run=row['run'],
                      state='Preparation interrupted - observe saved intent', certainty='not attempted',
                      review='Not reviewed', effect_review=not self.runtime.policy.local_generator)
        result.update(kind=kind)
        if hermes.external(row):
            result.update(hermes.submission_status(db, request))
            seconds = json.loads(row['input']).get('seconds')
            if seconds is not None:
                result['defaults'] = dict(seconds=seconds)
            result.update(method='hermes_tool', state='Awaiting Hermes output',
                          certainty='External execution unobserved', effect_review=False,
                          preparation_retryable=False, next_action='Collect the same tool output with the saved submission and attempt IDs. Never regenerate to recover a lost reply.')
            result['takes'] = [dict(id=t['id'], size=t['size'], review=t['review'], origin=t['origin'],
                descriptor=describe_take(t, kind=kind), facts=json.loads(t['facts']), **director_summary(db, t),
                selected=snapshot['selected'] == t['id']) for t in db.execute('SELECT * FROM takes WHERE request=?', (request,)) if director_active(db, t)]
            if json.loads(row['input']).get('method') == 'import':
                result.update(method='import', state='Awaiting import',
                              next_action='Import an existing file; this request never generates.')
            elif kind == 'Music':
                result['next_action'] = 'MUSIC_LIVE_UNQUALIFIED: offer WAV import; no Music generation.'
            if result['submission_state'] == 'abandoned':
                result.update(state='Abandoned', next_action='External cancellation is unverified; do not regenerate as recovery.')
            if result['takes']:
                result.update(state='Ready for review', certainty='Retained output verified')
            return result
        if kind == 'Music': result['effect_review'] = not self.runtime.policy.music.effects
        if row['phase'] == 'Unqualified':
            from ...native.creation.registration import MusicPrepare
            reason = music.unsupported(MusicPrepare(**json.loads(row['input'])))
            result.update(state='Saved - route unqualified', failure=reason, preparation_retryable=False,
                          next_action='Request preserved without substitution; this Music route is not yet qualified.')
        elif not row['run']:
            try:
                self.unfinished(db, row)
                result.update(preparation_retryable=True,
                    next_action='Deliberately repeat the identical prepare to finish this saved no-effect intent.')
            except Fault:
                result.update(preparation_retryable=False, certainty='unresolved',
                    next_action='Preparation authority could not be reconciled. Do not remint or start.')
        if row['run']:
            run = self.runs.records.public(row['run'])
            plan = self.runs.records.get(row['run'])['plan']
            result['method'] = plan['method']
            result['defaults'] = {key:plan['parameters'][key] for key in ('seconds','seed','steps')}
            if kind == 'Music':
                result['defaults'].update(instrumental=True, model='acestep-v15-turbo', batch=1, extra_lm=False)
                result['disclosure'] = 'Instrumental cue / 30-second default; requested seed only, effective seed unverified. PCM16 derivative; original native retained. No resample/cut/extra normalization.'
            result.update(state=run['status'], certainty=run['certainty'], failure=run['error'],
                          candidate=run['candidate'], stop_requested=run['stop_requested'],
                          local_gpu_busy=run['local_gpu_busy'], local_gpu_release=run['local_gpu_release'])
            if row['phase'] == 'Started' and run['status'] == 'Prepared':
                result['state'] = 'Start interrupted - observe; no replay'
            if row['phase'] == 'Refused':
                result['prelaunch_retryable'] = self.prelaunch(db, row, self.scope(root, kind=kind))
                result['next_action'] = 'Resource refused before launch. Deliberately retry the same Start only if prelaunch_retryable.'
            recovery = self.runs.recovery.get(request)
            if recovery:
                result['recovery'] = {
                    key:recovery.get(key) for key in ('state','next_action','successor','last_result','reserved')}
            result['takes'] = [dict(id=t['id'], size=t['size'], review=t['review'], origin=t['origin'],
                descriptor=describe_take(t, kind=kind), facts=json.loads(t['facts']), **director_summary(db, t),
                                   selected=snapshot['selected'] == t['id'])
                               for t in db.execute('SELECT * FROM takes WHERE request=?', (request,)) if director_active(db, t)]
        return result

    def prelaunch(self, db, row, scope):
        run = self.runs.records.get(row['run'])
        admission = db.execute('SELECT * FROM normal_admissions WHERE run=?', (row['run'],)).fetchone()
        worker = self.runs.threads.get(row['run'])
        return bool(run['status'] == 'Prepared' and run['certainty'] == 'not attempted' and
            run['process'] is None and not run['stop'] and not (worker and worker.is_alive()) and
            (not admission or (admission['state'] == 'armed' and admission['plan'] == run['plan_digest'] and
                               admission['owner'] == scope.key())))

    def start(self, root, model):
        from ...native.skills import verify_integrity
        verify_integrity()
        with self.store.transaction() as db:
            row = self.resolve(db, self.owned(db, root, model.request))
            snapshot = self.store.request(db, model.request, model.revision)
            kind = snapshot['kind']
            if hermes.external(row): raise Fault('HERMES_TOOL_GENERATION_EXTERNAL', 409)
            scope = self.scope(root, effect=True, kind=kind)
            plan = None
            if kind == 'Music':
                self.read(root, model.request, db=db)
                plan = self.runs.records.get(model.run)['plan']
                if self.runtime.binding(kind) != plan['binding']:
                    raise Fault('MUSIC_BINDING_DENIED', 403)
            if row['phase'] == 'Unqualified': raise Fault('MUSIC_ROUTE_UNQUALIFIED', 409)
            if row['command'] != model.command or row['run'] != model.run or row['policy'] != scope.revision:
                raise Fault('CREATION_COMMAND_CONFLICT', 409)
            # Unknown delivery never rearms. Only an explicitly recorded resource
            # refusal plus the engine's unchanged pre-claim evidence is retryable.
            if row['phase'] == 'Started':
                return self.read(root, model.request, db=db)
            if row['phase'] == 'Refused' and not self.prelaunch(db, row, scope):
                raise Fault('CREATION_NO_EFFECT_UNPROVEN', 409)
            db.execute("UPDATE creation_commands SET phase='Started' WHERE request=?", (model.request,))
        try:
            def authority():
                current = self.scope(root, effect=True, kind=kind)
                if current != scope: raise Fault('CREATION_SCOPE_DENIED', 403)
                if kind == 'Music' and (plan is None or self.runtime.binding(kind) != plan['binding']):
                    raise Fault('MUSIC_BINDING_DENIED', 403)
                return current
            self.runs.start(model.run, authority)
        except Fault as error:
            if error.code == 'RESOURCE_BUSY':
                with self.store.transaction() as db:
                    if self.prelaunch(db, row, scope):
                        db.execute("UPDATE creation_commands SET phase='Refused' WHERE request=?", (model.request,))
            raise
        return self.read(root, model.request)

    def stop(self, root, model):
        self.scope(root)
        with self.store.transaction() as db:
            row = self.resolve(db, self.owned(db, root, model.request))
            self.store.request(db, model.request, model.revision)
            self.scope(root, kind=self.store.request(db, model.request)['kind'])
            if row['run'] != model.run or row['command'] != model.command:
                raise Fault('CREATION_COMMAND_CONFLICT', 409)
        self.runs.stop(model.run)
        return self.read(root, model.request)

    def listing(self, root):
        self.scope(root)
        with self.store.transaction() as db:
            rows = db.execute('SELECT request FROM creation_commands WHERE root=? ORDER BY rowid DESC LIMIT 100', (root,)).fetchall()
            return dict(creations=[dict(self.read(root, r[0], db=db), direction=self.store.request(db, r[0])['text']) for r in rows],
                        audience=self.runtime.policy.audience, method=self.runtime.binding()['capabilities']['name'])

    def take(self, root, request, take):
        self.scope(root)
        with self.store.transaction() as db:
            self.authorize_request(db, root, request)
            row = dict(self.store.take(db, take))
            if row['request'] != request: raise Fault('CREATION_SCOPE_DENIED', 403)
        return row

    def chunk(self, root, model):
        row = self.take(root, model.request, model.take)
        # Reuse immutable, full-file integrity verification; never return raw paths.
        data, _ = self.assets.retrieve(model.take)
        part = data[model.offset:model.offset + 49152]
        if model.offset >= len(data): raise Fault('CREATION_CHUNK_INVALID', 422)
        self.take(root, model.request, model.take)  # Recheck media-specific scope after the byte read.
        descriptor = describe_take(row, kind=self.read(root, model.request)['kind'])
        return dict(mime=descriptor['mime'], descriptor=descriptor, take=row['id'], offset=model.offset, total=len(data), bytes=base64.b64encode(part).decode(),
                    sha256=hashlib.sha256(data).hexdigest(), chunk_sha256=hashlib.sha256(part).hexdigest())


    def action(self, root, model, operation):
        self.take(root, model.request, model.take)
        if operation == 'review':
            result = self.store.review(ReviewAction(command=model.command, take=model.take, outcome=model.outcome))
        else:
            result = self.store.select(TakeAction(command=model.command, request=model.request,
                expected=model.revision, take=model.take))
        return result
