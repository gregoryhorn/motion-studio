"""Exact-final audio facts. Only explicit owned measurement may run a process.

Consumers are pure, never decode on read or treat source/encode intent as proof.
"""
import hashlib
import json
from decimal import Decimal, InvalidOperation
import subprocess

from .contracts import ContractError


def measure_final_audio(payload, audio_facts, *, run_process, input_path=None):
    """Measure decoded presentation audio from the final container, before gain.

    loudnorm's input_i/input_tp are measurements, not its normalized output.
    Explicit presentation trim excludes AAC decoder frame padding, not content.
    The full input report and exact command are retained in the probe receipt.
    """
    count = audio_facts['presentation_samples']
    command = ['ffmpeg','-v','info','-xerror','-i',input_path or 'pipe:0','-map','0:a:0','-vn',
        '-af', f'atrim=end_sample={count},loudnorm=print_format=json', '-f','null','-']
    output = run_process(command, input=None if input_path else payload, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, timeout=7200 if input_path else 300, check=True)
    try:
        text = output.stderr.decode('utf-8')
        report, _ = json.JSONDecoder().raw_decode(text[text.rindex('{'):])
        integrated, peak = str(report['input_i']), str(report['input_tp'])
        finite = Decimal(integrated).is_finite() and Decimal(peak).is_finite()
    except (ValueError, KeyError, UnicodeError, InvalidOperation) as exc:
        raise ContractError('OUTPUT_INVALID', 'Final audio loudness measurement report is invalid.') from exc
    return dict(schema='motion/v1/final-audio-measurement',
        source_sha256='sha256:'+hashlib.sha256(payload).hexdigest(),
        method='ffmpeg.loudnorm.input', scope='decoded_presentation_audio',
        presentation_samples=count, sample_rate_hz=audio_facts['sample_rate_hz'],
        status='finite' if finite else 'nonfinite', integrated_lufs=integrated,
        true_peak_dbtp=peak, report=report, command=command,
        stderr_sha256='sha256:'+hashlib.sha256(output.stderr).hexdigest())


def audio_targets_met(probe, constraints, audio):
    """Check BOTH current profile and variant targets, with explicit tolerance.

    Variant loudness uses the profile's explicit LU tolerance (the variant
    schema has no tolerance field). True peak is a ceiling, with zero slack.
    Unknown/nonfinite measurement never satisfies a configured numeric target.
    """
    lufs = [v for v in (constraints['loudness_lufs'], audio['loudness_lufs']) if v is not None]
    peaks = [v for v in (constraints['true_peak_dbtp'], audio['true_peak_dbtp']) if v is not None]
    if not lufs and not peaks:
        return True
    value = probe.get('audio_measurement', {})
    if (value.get('schema') != 'motion/v1/final-audio-measurement'
            or value.get('source_sha256') != probe.get('sha256')
            or value.get('method') != 'ffmpeg.loudnorm.input'
            or value.get('scope') != 'decoded_presentation_audio'
            or value.get('presentation_samples') != probe.get('presentation_samples')
            or value.get('sample_rate_hz') != probe.get('sample_rate_hz')
            or value.get('status') != 'finite'):
        return False
    try:
        actual, peak = Decimal(value['integrated_lufs']), Decimal(value['true_peak_dbtp'])
        if not actual.is_finite() or not peak.is_finite():
            return False
        tolerance = constraints['loudness_tolerance_lu']
        if lufs:
            if tolerance is None:
                return False
            tolerance = Decimal(tolerance)
            if not tolerance.is_finite() or tolerance < 0:
                return False
            if any(not Decimal(target).is_finite() or abs(actual-Decimal(target)) > tolerance for target in lufs):
                return False
        return all(Decimal(target).is_finite() and peak <= Decimal(target) for target in peaks)
    except (InvalidOperation, KeyError, TypeError):
        return False
