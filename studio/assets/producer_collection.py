"""Bounded original WAV/receipt validation and same-candidate immutable retention."""
import hashlib
import os
from ..assets.producer_files import allocation, read_leaf
from ..assets.retention import sync_directory, read_private
from ..assets.audio_profiles import validate_audio
from ..domain import Fault, MAX_BYTES
from ..persistence.store import canonical, identity



class ProducerCollection:
    def __init__(self, runs, catalog):
        self.runs, self.store = runs, runs.store
        self.catalog = catalog
        self.after_finalize = lambda: None

    def verify_original(self, run):
        """Read/validate only; collection recovery never infers eligibility from absence."""
        row = self.runs.get(run)
        process = row['process'] or {}
        if not process.get('exited') or not process.get('group_retired') or process.get('exit_code') != 0:
            raise Fault('EFFECT_UNCERTAIN', 409)
        directory, descriptor, _ = allocation(self.store, row)
        try:
            data = read_leaf(descriptor, 'candidate.wav', MAX_BYTES)
            raw = read_leaf(descriptor, 'candidate.wav.json', 16384)
            frames = self.catalog.for_plan(row['plan']).validate_native_output(data, raw, row['plan'], directory / 'candidate.wav')
            facts = validate_audio(data, row['plan'].get('outputs', 'stereo-44100-pcm16'), frames)
            adapter = self.catalog.for_plan(row['plan'])
            if hasattr(adapter, 'collection_evidence'):
                facts['lineage'] = adapter.collection_evidence(raw, row['plan'], directory / 'candidate.wav')
            manifest = dict(digest=hashlib.sha256(data).hexdigest(), size=len(data), facts=facts,
                            receipt_digest=hashlib.sha256(raw).hexdigest(), check_version=1)
            if row['collection'] is not None and row['collection'] != manifest:
                raise Fault('OUTPUT_CHANGED', 409)
            return manifest
        finally:
            os.close(descriptor)

    def collect(self, run):
        row = self.runs.get(run)
        if row['status'] == 'Ready for review':
            return self.runs.public(run)
        if row['status'] not in ('Collecting', 'Collection blocked') or not (row['process'] or {}).get('exited'):
            raise Fault('EFFECT_UNCERTAIN', 409)
        descriptor = None
        try:
            directory, descriptor, _ = allocation(self.store, row)
            output = directory / 'candidate.wav'
            data = read_leaf(descriptor, 'candidate.wav', MAX_BYTES)
            raw = read_leaf(descriptor, 'candidate.wav.json', 16384)
            adapter = self.catalog.for_plan(row['plan'])
            frames = adapter.validate_native_output(data, raw, row['plan'], output)
            profile = row['plan'].get('outputs', 'stereo-44100-pcm16')
            facts = validate_audio(data, profile, frames)
            if hasattr(adapter, 'collection_evidence'):
                facts['lineage'] = adapter.collection_evidence(raw, row['plan'], output)
            manifest = dict(digest=hashlib.sha256(data).hexdigest(), size=len(data), facts=facts,
                            receipt_digest=hashlib.sha256(raw).hexdigest(), check_version=1)
            if row['collection'] is not None and row['collection'] != manifest:
                raise Fault('OUTPUT_CHANGED')
            self.runs.update(run, collection=manifest, status='Collecting', error=None)
            final = self.store.home / 'media' / (row['candidate'] + '.wav')
            if final.exists() or final.is_symlink():
                if read_private(final) != data:
                    raise Fault('RETAINED_FILE_CORRUPT')
            else:
                part = self.store.home / 'media' / (identity() + '.part')
                fd = os.open(part, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
                with os.fdopen(fd, 'wb') as target:
                    target.write(data)
                    target.flush()
                    os.fsync(target.fileno())
                os.chmod(part, 0o400)
                os.link(part, final, follow_symlinks=False)
                part.unlink()
                sync_directory(final.parent)
            if hasattr(adapter, 'retain_evidence'):
                adapter.retain_evidence(self.store, row, output, raw)
            self.after_finalize()
            with self.store.transaction() as db:
                db.execute('INSERT OR IGNORE INTO takes VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                           (row['candidate'], row['candidate'], None, row['plan']['request'],
                            row['plan']['revision'], manifest['digest'], len(data),
                            'Test-only ' + adapter.describe()['name'] if row['fixture'] else adapter.describe()['name'],
                            canonical(facts), 'Not reviewed', 'test_fixture' if row['fixture'] else 'producer_output'))
                db.execute("UPDATE local_runs SET status='Ready for review',error=NULL WHERE id=?", (run,))
            return self.runs.public(run)
        except (Fault, OSError) as error:
            code = error.code if isinstance(error, Fault) else 'OUTPUT_PAIR_INCOMPLETE'
            self.runs.update(run, status='Collection blocked', error=code)
            raise Fault(code, 409) from None
        finally:
            if descriptor is not None:
                os.close(descriptor)
