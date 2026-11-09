"""Read-only host diagnostics on the existing capability tool.

A readiness report is not execution authority or a reservation. Admission must
be measured again under the owned-job kernel fence at the time of execution.
"""
from __future__ import annotations

from .contracts import ADAPTER, TEXT, BOOL, arr, obj, ident, integer, validate, ContractError


def branches():
    location = obj({'host': TEXT})
    topology = obj({'client': location,
                    'backend': obj({'host': TEXT, 'address': TEXT}),
                    'files': obj({'host': TEXT, 'accessible': BOOL}),
                    'compute': location,
                    'preview': obj({'host': TEXT, 'accessible': BOOL}),
                    'authentication': BOOL, 'reconnect': BOOL})
    return [obj({'action': {'const': 'host_readiness'},
                 'adapter_id': ADAPTER, 'paths': {**arr(TEXT), 'maxItems': 16}},
                ['adapter_id', 'paths']),
            obj({'action': {'const': 'task_overview'}, 'project_id': ident('prj'),
                 'limit': {**integer(1), 'maximum': 100}, 'after_job_id': ident('job')},
                ['limit', 'after_job_id']),
            obj({'action': {'const': 'setup_report'},
                 'selected_packs': {**arr(TEXT), 'maxItems': 64, 'uniqueItems': True}},
                ['selected_packs']),
            obj({'action': {'const': 'topology_check'}, 'topology': topology}),
            obj({'action': {'const': 'tool_readiness'}})]


def dispatch(runtime, args):
    if args['action'] == 'topology_check':
        from .host_safety import validate_topology
        return validate_topology(args['topology'])
    if args['action'] == 'tool_readiness':
        from .tool_integration import tool_readiness
        # No lazy registry construction, refresh or invocation on a passive read.
        # Only the trusted bridge's read-only hook snapshot is eligible; public
        # request/project JSON cannot supply inventory.
        inventory = None
        if runtime.host_bridge is not None:
            try:
                inventory = runtime.host_bridge.observed_inventory()
            except ContractError:
                pass  # No trusted current snapshot: explicitly not observed.
        return tool_readiness(runtime._registry, inventory)
    if args['action'] == 'task_overview':
        return task_overview(runtime, args)
    if args['action'] == 'setup_report':
        from pathlib import Path
        from .setup import inspect_setup, release
        try:
            return inspect_setup(Path(__file__).resolve().parents[1],
                                 selected_packs=args.get('selected_packs'))
        except release.ValidationError as exc:
            raise ContractError('SETUP_INVALID', 'Setup manifest, payload or selected pack is invalid; inspect the standalone setup report.') from exc
    from .host_safety import snapshot, admission

    requirements = None
    adapter = None
    route = None
    if 'adapter_id' in args:
        adapter = runtime.registry.inspect(args['adapter_id'])
        requirements = host_requirements(adapter['declaration']['resource_needs'])
        from .gpu_route import for_registry
        route = for_registry(runtime.registry, args['adapter_id'])
    paths = args.get('paths', [])
    observed = snapshot(paths=paths)
    route_args = {'gpu_route': route} if route is not None else {}
    policy = admission(paths=paths, requirements=requirements, **route_args)
    return {'schema': 'motion/v1/host-readiness',
            'snapshot': observed, 'admission': policy,
            'adapter': adapter,
            'qualification': 'measured host metadata, not exercised route support',
            'reservation': False, 'execution_authorized': False,
            'remote_client_verified': False}


def host_requirements(needs):
    """Translate the closed adapter vocabulary to enforced-child cap vocabulary.

    Unknown declared peaks keep bounded lightweight defaults; these caps are not
    a promise the workload fits. GPU routes refuse without a qualified boundary.
    """
    result = {}
    if needs.get('ram_bytes') is not None:
        result['memory_bytes'] = needs['ram_bytes']
    if needs.get('cpu_threads') is not None:
        result['cpu_cores'] = needs['cpu_threads']
    if needs.get('gpu_vram_bytes') is not None:
        result['gpu'] = True
    return result


def task_overview(runtime, args):
    """Bounded status projections; listing does not renew or repair a lease."""
    pid = args['project_id']
    fs = runtime.projects._filesystem()
    runtime.projects._pointer(fs, pid)  # Require a committed project, even if empty.
    names = sorted(name[:-5] for name in fs.names(runtime.projects._base(pid) + '/jobs')
                   if name.endswith('.json'))
    for jid in names:
        validate(jid, ident('job'))
    after = args.get('after_job_id')
    if after is not None and after not in names:
        raise ContractError('INVALID_ARGUMENT', 'Job overview cursor is not present in this project.')
    remaining = [jid for jid in names if after is None or jid > after]
    selected = remaining[:args.get('limit', 25)]
    jobs = runtime.jobs()
    items = []
    counts = {'failed': 0, 'blocked': 0, 'stale': 0, 'unreadable': 0}
    for jid in selected:
        try:
            status = jobs.status(pid, jid)
        except (ContractError, OSError, KeyError, ValueError, TypeError) as exc:
            # Corrupt work must be visible, without leaking unsanitized file data.
            items.append({'job_id': jid, 'readable': False,
                          'error': {'code': getattr(exc, 'code', 'RECORD_UNAVAILABLE'),
                                    'message': 'Job status could not be read; inspect this exact job.'}})
            counts['unreadable'] += 1
            continue
        items.append({'job_id': jid, 'readable': True, 'status': status})
        counts['failed'] += int(status['state'] == 'failed')
        counts['blocked'] += int(bool(status.get('blocking_reason')))
        counts['stale'] += int(bool(status.get('stale')) or
                               bool(status.get('monitoring', {}).get('stale_reasons')))
    more = len(remaining) > len(selected)
    return {'schema': 'motion/v1/task-overview', 'project_id': pid,
            'items': items, 'counts_on_page': counts,
            'next_after_job_id': selected[-1] if more and selected else None,
            'has_more': more, 'ordering': 'job_id ascending, not chronological',
            'execution_authorized': False}
