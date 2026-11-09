"""Conditional production windows from exact local job evidence, never a timer service.

Explicit scope references existing compiled nodes/jobs; no second mutable task
tracker is created. Optional immutable reports retain scope and calibration.
"""
from __future__ import annotations

from datetime import datetime, timezone
from fractions import Fraction
import json
from math import ceil

from .contracts import (ContractError, BOOL, DIGEST, KEY, TEXT, arr, digest,
                        enum, ident, integer, nullable, obj, ref)

EVIDENCE = obj({'job_id': ident('job'), 'target_key': KEY})
TASK = obj({'task_key': KEY, 'phase': enum('edit', 'render', 'qc', 'delivery'),
    'dependencies': arr(KEY, unique=True), 'plan_target': KEY,
    'job_id': nullable(ident('job')), 'external_wait': BOOL, 'unknown_work': BOOL,
    'measurements': arr(EVIDENCE, unique=True)})


def branches():
    from .plans import DEFS
    return [obj({'action': {'const': 'eta'}, 'project_id': ident('prj'),
        'plan': DEFS['PlanRef'], 'tasks': arr(TASK, 1), 'scope_complete': BOOL,
        'stale_after_seconds': integer(1, 2592000), 'record': BOOL}),
        obj({'action': {'const': 'eta_calibrate'}, 'project_id': ident('prj'),
             'estimate': ref('ArtifactRef')})]


def instant(text):
    return datetime.fromisoformat(text.replace('Z', '+00:00'))


def milliseconds(start, end):
    span = instant(end) - instant(start)
    result = (span.days * 86400 + span.seconds) * 1000 + span.microseconds // 1000
    if result < 0:
        raise ContractError('TIMING_INVALID', 'Observed job timestamps run backwards.')
    return result


def work(node):
    p = node['parameters']
    if type(p.get('duration_samples')) is int and type(p.get('sample_rate')) is int:
        return 'audio_seconds', Fraction(p['duration_samples'], p['sample_rate'])
    if type(p.get('duration_frames')) is int:
        return 'frames', Fraction(p['duration_frames'])
    span = p.get('range')
    if isinstance(span, dict) and type(span.get('end_frame')) is int and type(span.get('start_frame')) is int:
        return 'frames', Fraction(span['end_frame'] - span['start_frame'])
    return 'invocations', Fraction(1)


def compatibility(node):
    # Work quantity can scale; every other setting and input semantic stays pinned.
    p = json.loads(json.dumps(node['parameters']))
    p.pop('duration_samples', None)
    p.pop('duration_frames', None)
    if 'range' in p:
        p['range'] = 'bounded_frame_range'
    return digest(dict(binding=node['binding'], operation=node['operation'],
        parameters=p, input_ports=sorted(node['inputs'])))


def find_node(plan, target):
    selected = [n for n in plan['nodes'] if n['target_key'] == target]
    if len(selected) != 1:
        raise ContractError('NOT_FOUND', 'ETA target is not a unique compiled node.')
    return selected[0]


def observation(runtime, pid, job_id, target):
    bundle = runtime.jobs().read(pid, job_id)
    node = find_node(bundle['plan_record'], target)
    state = next(s for s in bundle['job']['node_states'] if s['node_id'] == node['node_id'])
    attempt = bundle['attempts'].get(state.get('attempt_id'))
    return bundle, node, state, attempt


def estimate(runtime, args):
    pid = args['project_id']
    plan = runtime.compiler.load(pid, args['plan'])
    tasks = {row['task_key']: row for row in args['tasks']}
    if len(tasks) != len(args['tasks']):
        raise ContractError('INVALID_ARGUMENT', 'ETA task keys must be unique.')
    for task in tasks.values():
        if set(task['dependencies']) - set(tasks):
            raise ContractError('INVALID_ARGUMENT', 'ETA references unknown dependencies.')
    pending, ordered, completed = set(tasks), [], set()
    while pending:
        ready = sorted(k for k in pending if set(tasks[k]['dependencies']) <= completed)
        if not ready:
            raise ContractError('INVALID_ARGUMENT', 'ETA dependencies contain a cycle.')
        ordered.extend(ready)
        completed.update(ready)
        pending -= set(ready)
    now = datetime.now(timezone.utc)
    from .project import _now
    fs = runtime.projects._filesystem()
    pointer = runtime.projects._pointer(fs, pid)
    plan_stale = plan['project_revision'] != pointer['revision']
    uncovered = sorted({n['target_key'] for n in plan['nodes']} - {t['plan_target'] for t in tasks.values()})
    if len({t['plan_target'] for t in tasks.values()}) != len(tasks):
        raise ContractError('INVALID_ARGUMENT', 'An ETA scope cannot count the same compiled target twice.')
    rows = []
    for key in ordered:
        task = tasks[key]
        node = find_node(plan, task['plan_target'])
        unit, amount = work(node)
        if amount <= 0:
            raise ContractError('TIMING_INVALID', 'ETA work quantity must be positive.')
        rates, sources, rejected = [], [], []
        for evidence in task['measurements']:
            bundle, measured, state, attempt = observation(runtime, pid, evidence['job_id'], evidence['target_key'])
            reason = None
            if state['state'] != 'succeeded' or not attempt or not attempt['started_at'] or not attempt['ended_at']:
                reason = 'no_completed_successful_attempt'
            elif compatibility(measured) != compatibility(node) or work(measured)[0] != unit:
                reason = 'incompatible_binding_or_settings'
            elif (now - instant(attempt['ended_at'])).total_seconds() > args['stale_after_seconds']:
                reason = 'stale_evidence'
            elif instant(attempt['ended_at']) > now:
                reason = 'future_evidence_timestamp'
            elif not state['outputs']:
                reason = 'no_collected_output'
            if reason:
                rejected.append(dict(evidence=evidence, reason=reason))
                continue
            for pin in state['outputs']:
                runtime.artifacts.resolve(pid, pin)
            observed_ms = milliseconds(attempt['started_at'], attempt['ended_at'])
            quantity = work(measured)[1]
            if observed_ms <= 0 or quantity <= 0:
                rejected.append(dict(evidence=evidence, reason='nonpositive_measurement'))
                continue
            rates.append(Fraction(observed_ms) / quantity)
            sources.append(dict(job_id=evidence['job_id'], attempt_id=attempt['attempt_id'],
                target_key=evidence['target_key'], ended_at=attempt['ended_at'], elapsed_ms=observed_ms,
                units=dict(num=quantity.numerator, den=quantity.denominator),
                binding_sha256=digest(measured['binding']), outputs=state['outputs']))
        status, elapsed_ms, actual_ms = 'not_started', 0, None
        if task['job_id'] is not None:
            bundle, current, state, attempt = observation(runtime, pid, task['job_id'], task['plan_target'])
            if current['fingerprint'] != node['fingerprint']:
                raise ContractError('HASH_MISMATCH', 'ETA job does not execute the selected plan node.')
            status = state['state']
            if bundle['job']['cancel']['requested'] or bundle['job']['state'] in ('failed', 'cancelled', 'interrupted') or status in ('failed', 'cancelled', 'interrupted'):
                status = 'stopped'
            elif status == 'running' and attempt and instant(attempt['owner']['lease_expires_at']) < now:
                status = 'observation_stale'
            if attempt and attempt['started_at']:
                ended = attempt['ended_at'] or now.isoformat()
                elapsed_ms = milliseconds(attempt['started_at'], ended)
                if attempt['ended_at']:
                    actual_ms = elapsed_ms
        reason = None
        window = None
        if status == 'succeeded':
            window = dict(low_ms=0, high_ms=0)
        elif status == 'stopped':
            reason = 'execution_stopped'
        elif status == 'observation_stale':
            reason = 'running_lease_expired_reconcile_required'
        elif task['external_wait'] or status == 'awaiting_external':
            reason = 'external_wait'
        elif task['unknown_work']:
            reason = 'unknown_work'
        elif plan_stale:
            reason = 'plan_scope_stale'
        elif not rates:
            reason = 'no_compatible_fresh_measurement'
        else:
            low, high = ceil(min(rates) * amount), ceil(max(rates) * amount)
            if status == 'running' and elapsed_ms > high:
                reason = 'running_attempt_exceeds_measured_window'
            else:
                window = dict(low_ms=max(0, low - elapsed_ms), high_ms=max(0, high - elapsed_ms))
        rows.append(dict(task_key=key, phase=task['phase'], dependencies=task['dependencies'],
            job_id=task['job_id'], plan_target=task['plan_target'], status=status,
            units=dict(kind=unit, num=amount.numerator, den=amount.denominator),
            window=window, unknown_reason=reason, elapsed_ms=elapsed_ms, actual_ms=actual_ms,
            measurements=sources, rejected_measurements=rejected))
    phases = {}
    for phase in ('edit', 'render', 'qc', 'delivery'):
        selected = [r for r in rows if r['phase'] == phase]
        known = [r['window'] for r in selected if r['window'] is not None]
        phases[phase] = dict(known_serial_subtotal=dict(low_ms=sum(w['low_ms'] for w in known),
            high_ms=sum(w['high_ms'] for w in known)), unknown_tasks=[r['task_key'] for r in selected if r['window'] is None])
    complete = args['scope_complete'] and not uncovered and not plan_stale and all(r['window'] is not None for r in rows)
    report = dict(schema='motion/v1/production-eta', project_id=pid,
        observed_at=_now(), project_revision=pointer['revision'], plan=args['plan'],
        scope=args['tasks'], scope_complete=args['scope_complete'], plan_stale=plan_stale,
        uncovered_plan_targets=uncovered,
        tasks=rows, phases=phases, complete=complete, finish_time=None,
        condition='Observed-rate windows are conditional on comparable host load, inputs and engine state; they are not confidence intervals or a promised finish time.',
        serialized_remaining_window=None)
    if complete:
        # Current job scheduler executes each job serially; independent job/phase
        # overlap is not assumed. Report a serial bound, not a fabricated schedule.
        report['serialized_remaining_window'] = dict(low_ms=sum(r['window']['low_ms'] for r in rows),
            high_ms=sum(r['window']['high_ms'] for r in rows))
    if args['record']:
        report['artifact'] = runtime.artifacts.publish_json(pid, report, kind='report')
    return report


def calibrate(runtime, args):
    pid = args['project_id']
    record = runtime.artifacts.resolve(pid, args['estimate'])
    if record['media_type'] != 'application/json' or record['size_bytes'] > 16777216:
        raise ContractError('INVALID_ARGUMENT', 'ETA calibration needs a bounded JSON estimate report.')
    fs = runtime.projects._filesystem()
    with runtime.artifacts.open_record(fs, record) as stream:
        report = json.load(stream)
    if report.get('schema') != 'motion/v1/production-eta' or report.get('project_id') != pid:
        raise ContractError('INVALID_ARGUMENT', 'Not an owning production ETA report.')
    rows = []
    for task in report['tasks']:
        actual = None
        state_name = 'unbound'
        if task['job_id']:
            _, node, state, attempt = observation(runtime, pid, task['job_id'], task['plan_target'])
            state_name = state['state']
            if attempt and attempt['started_at'] and attempt['ended_at']:
                actual = milliseconds(attempt['started_at'], attempt['ended_at'])
        window = task['window']
        projected = None if window is None else {k: v + task['elapsed_ms'] for k, v in window.items()}
        rows.append(dict(task_key=task['task_key'], status=state_name, estimated_total=projected,
            actual_ms=actual, within_observed_window=None if actual is None or projected is None else
                projected['low_ms'] <= actual <= projected['high_ms']))
    value = dict(schema='motion/v1/eta-calibration', project_id=pid, estimate=args['estimate'], tasks=rows)
    return dict(calibration=value, artifact=runtime.artifacts.publish_json(pid, value, kind='report', inputs=[args['estimate']]))


def dispatch(runtime, args):
    return estimate(runtime, args) if args['action'] == 'eta' else calibrate(runtime, args)
