"""Local, content-free accounting of direct Studio calls only.

Never allocate a session/API total among mixed tools. Provider usage is retained
only when the host supplies an exact tool_call_id and direct attribution flag.
Unknown is not zero. No transcript scans, uploads, timers or background service.
"""
from __future__ import annotations

from collections import Counter
import time

from .contracts import ContractError, digest
from .project import _now

TOOLS = frozenset(('motion_project', 'motion_asset', 'motion_asset_library',
    'motion_storyboard', 'motion_plan', 'motion_run', 'motion_caption',
    'motion_review', 'motion_deliver', 'motion_capabilities'))
TOKEN_FIELDS = ('fresh_input', 'output', 'cache_read', 'cache_write')


def key(value):
    return digest(str(value))


class UsageLedger:
    def __init__(self, projects, session_id):
        self.projects, self.session_id = projects, session_id
        self.base = 'usage/' + key(session_id or '')

    def begin(self, event, *, claim=None):
        sid, cid = event.get('session_id'), event.get('tool_call_id')
        tool = event.get('tool_name')
        if not sid or sid != self.session_id or not cid or (tool not in TOOLS and claim is None):
            return
        args = event.get('args') or {}
        if not isinstance(args, dict):
            args = {}
        fs = self.projects._filesystem(write=True)
        path = self.base + '/calls/' + key(cid) + '.json'
        try:
            metadata = fs.read(self.base + '/requests/' + key(event.get('api_request_id')) + '.json')
        except FileNotFoundError:
            metadata = {}
        with fs.lock(self.base + '/ledger.lock'):
            try:
                fs.read(path)
                return
            except FileNotFoundError:
                pass
            fs.write(path, dict(schema='motion/v1/usage-call', tool_call_id=cid,
                session_id=sid, profile=str(self.projects._filesystem().root),
                model=event.get('model') or metadata.get('model'),
                provider=event.get('provider') or metadata.get('provider'),
                api_request_id=event.get('api_request_id'), task_id=event.get('task_id'),
                project_id=(claim or {}).get('project_id', args.get('project_id')),
                job_id=(claim or {}).get('job_id', args.get('job_id')),
                attempt_id=(claim or {}).get('attempt_id', args.get('attempt_id')),
                tool=tool, action=args.get('action'), started_at=_now(),
                clock_ns=time.monotonic_ns(), outcome='pending', elapsed_ms=None,
                error_code=None, tokens=None, accounting='unknown', local_inference=None))

    def finish(self, event, result):
        if event.get('session_id') != self.session_id or not event.get('tool_call_id'):
            return
        fs = self.projects._filesystem(write=True)
        path = self.base + '/calls/' + key(event['tool_call_id']) + '.json'
        with fs.lock(self.base + '/ledger.lock'):
            try:
                row = fs.read(path)
            except FileNotFoundError:
                return  # Unrelated native calls never become Studio statistics.
            if row['outcome'] != 'pending':
                return
            value = result if isinstance(result, dict) else {}
            data = value.get('data', {})
            state = (data.get('job', {}) if isinstance(data, dict) else {}).get('state')
            error = value.get('error')
            code = error.get('code') if isinstance(error, dict) else None
            status = value.get('status')
            if state in ('failed', 'cancelled', 'interrupted'):
                outcome = state
            elif value.get('ok') is False:
                outcome = 'blocked' if status == 'blocked' else 'failed'
            elif event.get('status') not in (None, 'ok', 'success'):
                outcome = 'failed'
            elif value.get('ok') is True:
                outcome = 'accepted' if state in ('queued', 'running', 'awaiting_external') else 'succeeded'
            else:
                outcome = 'unknown'
            row.update(outcome=outcome, error_code=code, ended_at=_now(),
                elapsed_ms=max(0, (time.monotonic_ns() - row['clock_ns']) // 1000000))
            fs.write(path, row, replace=True)

    def attributed_usage(self, event):
        # API/session totals lack exact plugin attribution and are NOT consumed.
        if (event.get('session_id') != self.session_id or event.get('attribution') != 'exact_tool_call'
                or not event.get('tool_call_id')):
            return
        fs = self.projects._filesystem(write=True)
        path = self.base + '/calls/' + key(event['tool_call_id']) + '.json'
        with fs.lock(self.base + '/ledger.lock'):
            try:
                row = fs.read(path)
            except FileNotFoundError:
                return
            if row['api_request_id'] != event.get('api_request_id'):
                return
            if row['model'] and row['model'] != event.get('model'):
                return
            usage = event.get('usage')
            if not isinstance(usage, dict):
                return
            convention = event.get('accounting_convention')
            if convention not in ('input_includes_cache', 'input_excludes_cache', 'normalized_disjoint'):
                return
            def count(name):
                n = usage.get(name)
                return n if type(n) is int and n >= 0 else None
            cache_read, cache_write = count('cache_read_tokens'), count('cache_write_tokens')
            fresh = count('input_tokens')
            if convention == 'input_includes_cache':
                fresh = (fresh - cache_read - cache_write if fresh is not None
                    and cache_read is not None and cache_write is not None else None)
                if fresh is not None and fresh < 0:
                    return
            tokens = dict(fresh_input=fresh, output=count('output_tokens'),
                cache_read=cache_read, cache_write=cache_write)
            # Repeated hook delivery updates this exact row, never adds tokens.
            row.update(model=event.get('model'), provider=event.get('provider'),
                accounting=convention, local_inference=event.get('local_inference') is True,
                tokens=tokens)
            fs.write(path, row, replace=True)

    def summary(self, project_id=None, task_id=None):
        if not self.session_id:
            raise ContractError('PERMISSION_DENIED', 'Usage requires the direct calling session.')
        fs = self.projects._filesystem()
        calls = []
        for name in fs.names(self.base + '/calls'):
            row = fs.read(self.base + '/calls/' + name)
            if row['session_id'] != self.session_id:
                continue
            if project_id and row['project_id'] != project_id:
                continue
            if task_id and row['task_id'] != task_id:
                continue
            row.pop('clock_ns', None)
            calls.append(row)
        calls.sort(key=lambda r: (r['started_at'], r['tool_call_id']))
        def total(rows):
            totals = {field: 0 for field in TOKEN_FIELDS}
            unknown = {field: 0 for field in TOKEN_FIELDS}
            for row in rows:
                for field in TOKEN_FIELDS:
                    n = (row['tokens'] or {}).get(field)
                    if n is None:
                        unknown[field] += 1
                    else:
                        totals[field] += n
            return dict(known_subtotal=totals, unknown_calls=unknown,
                complete=all(n == 0 for n in unknown.values()))
        hosted = [row for row in calls if row['local_inference'] is not True]
        local = [row for row in calls if row['local_inference'] is True]
        return dict(schema='motion/v1/usage-summary', session_id=self.session_id,
            project_id=project_id, task_id=task_id, calls=calls, invocation_count=len(calls),
            features=dict(Counter(r['tool'] + ':' + str(r['action']) for r in calls)),
            outcomes=dict(Counter(r['outcome'] for r in calls)),
            failures=dict(Counter(r['error_code'] for r in calls if r['error_code'])),
            hosted_tokens=total(hosted), local_inference=total(local),
            monetary_cost=None, publication='local_only',
            attribution='Exact direct call records only; unavailable token attribution stays unknown.')


def pre_call(**event):
    from .project import ProjectStore
    if event.get('tool_name') in TOOLS and event.get('session_id'):
        UsageLedger(ProjectStore(), event['session_id']).begin(event)


def post_call(**event):
    import json
    from .project import ProjectStore
    if not event.get('session_id'):
        return
    value = event.get('result')
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            value = None
    UsageLedger(ProjectStore(), event['session_id']).finish(event, value)


def post_api(**event):
    from .project import ProjectStore
    if event.get('session_id'):
        UsageLedger(ProjectStore(), event['session_id']).attributed_usage(event)


def pre_api(**event):
    from .project import ProjectStore
    if not event.get('session_id') or not event.get('api_request_id'):
        return
    ledger = UsageLedger(ProjectStore(), event['session_id'])
    fs = ledger.projects._filesystem(write=True)
    fs.write(ledger.base + '/requests/' + key(event['api_request_id']) + '.json',
        dict(session_id=event['session_id'], api_request_id=event['api_request_id'],
            model=event.get('model'), provider=event.get('provider')), replace=True)
