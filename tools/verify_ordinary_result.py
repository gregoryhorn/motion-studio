"""Read-only real ordinary result verification/reopen; never prepares/starts/retries."""
import json
from pathlib import Path
import subprocess
import wave
from studio.assets.producer_files import allocation, read_leaf
from studio.assets.retention import Assets
from studio.persistence.store import Store
from studio.runs.helper_environment import helper_environment
from studio.runs.process_observation import retirement
from studio.runs.service import LocalRuns
from studio.producer import local_sfx as sfx


def main():
    home = Path('var')
    receipt = json.loads((home/'state/qs1-normal-browser-receipt.json').read_text())
    store = Store(home)
    runs = LocalRuns(store)
    try:
        before = [row['id'] for row in runs.records.rows()]
        row = runs.records.get(receipt['result_run'])
        assert row['status'] == 'Ready for review'
        assert row['plan']['parameters']['use'] == 'noncommercial_local_technical_evaluation'
        assert row['process']['exited'] and row['process']['exit_code'] == 0 and row['process']['group_retired']
        retired, _ = retirement(row['process']['incarnation'])
        assert retired
        assert row['candidate'] == receipt['result_candidate']
        assert row['plan']['parameters']['seconds'] == 3 and row['plan']['parameters']['seed'] == 42
        assert row['plan']['parameters']['steps'] == 100 and row['plan']['parameters']['negative'] == sfx.NEGATIVE
        directory, descriptor, _ = allocation(store,row)
        import os
        try:
            data = read_leaf(descriptor,'candidate.wav',16*1024*1024)
            native = read_leaf(descriptor,'candidate.wav.json',16384)
        finally:
            os.close(descriptor)
        frames = sfx.native_output(data,native,row['plan'],directory/'candidate.wav')
        native_facts = json.loads(native)
        # Reopen through the same asset store; no collection/generation mutation.
        assets = Assets(store)
        retained, take = assets.retrieve(row['candidate'])
        assert retained == data == (home/'state/qs1-normal-downloaded.wav').read_bytes()
        assert take['review'] == 'Not reviewed'
        final = home/'media'/(row['candidate']+'.wav')
        with wave.open(str(final),'rb') as audio:
            facts = dict(frames=audio.getnframes(),rate=audio.getframerate(),channels=audio.getnchannels(),width=audio.getsampwidth())
        assert facts == dict(frames=132300,rate=44100,channels=2,width=2) and frames == 132300
        decoder = subprocess.run(['/usr/bin/ffmpeg','-v','error','-i',str(final),'-f','null','-'],
            env=helper_environment(),stdin=subprocess.DEVNULL,capture_output=True,timeout=30)
        assert decoder.returncode == 0
        assert (home/'media'/(receipt['historical_candidate']+'.wav')).read_bytes() == (home/'state/lq1-downloaded.wav').read_bytes()
        assert before == [item['id'] for item in runs.records.rows()]
        with store.transaction() as db:
            audit = db.execute("SELECT * FROM ordinary_control_checks WHERE label='CF-QS1-r2-one-real'").fetchone()
            normal = db.execute('SELECT * FROM normal_admissions WHERE run=?',(row['id'],)).fetchone()
        assert audit['source'] == receipt['source_manifest'] and normal['state'] == 'entered'
        private = dict(receipt,verification='passed',facts=facts,bytes=len(data),technical_check='passed',
            observed_exit=0,group_retired=True,full_independent_decode=True,same_original_bytes=True,
            historical_bytes_unchanged=True,no_reopen_dispatch=True,
            reported_elapsed_seconds=native_facts['elapsed_seconds'],reported_gpu_peak_mib=native_facts['gpu_peak_allocated_mib'])
        (home/'state/qs1-normal-verified.json').write_text(json.dumps(private,indent=2)+'\n')
        print(json.dumps({key: private[key] for key in ('verification','run','candidate','result_run','result_candidate',
            'source_manifest','facts','bytes','observed_exit','group_retired','full_independent_decode','same_original_bytes',
            'historical_bytes_unchanged','no_reopen_dispatch','reported_elapsed_seconds','reported_gpu_peak_mib','listening')},indent=2))
    finally:
        runs.close()


if __name__ == '__main__':
    main()
