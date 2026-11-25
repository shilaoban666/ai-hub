"""Bounded run snapshots for refresh recovery, shared across API workers."""

import asyncio
import json
import logging
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import exists, func, or_, tuple_
from models import AgentMessage, AgentPermissionRequest, AgentRun, AgentRunEvent
from agent_stream_redis import get_store
from credit_billing import recorded_charged_points

SNAPSHOT_INTERVAL_SECONDS = 5.0
SNAPSHOT_RETENTION_MINUTES = 10
RUNNING_STATUSES = ('queued', 'running')
RETAINED_STATUSES = (*RUNNING_STATUSES, 'unknown')
logger = logging.getLogger(__name__)


class StreamSnapshot:
    """Coalesce deltas in memory; Redis stores the latest checkpoint."""

    def __init__(self):
        self.revision = 0
        self.content = []
        self.metadata = {}
        self.permissions = {}
        self.usage = {}
        self.last_saved_at = None
        self.saved_revision = 0
        self.batch = []

    def consume(self, chunk):
        self.batch = []
        urgent = False
        for line in chunk.splitlines():
            if not line.startswith('data: '):
                continue
            event = json.loads(line[6:])
            kind = event.get('type')
            if kind not in {'text', 'thinking', 'tool_use', 'tool_result', 'usage', 'permission_request',
                            'run_queued', 'run_start', 'info', 'context_notice', 'done', 'error',
                            'cancelled', 'turn_metrics', 'stream_end', 'artifacts', 'credit_usage'}:
                continue
            self.revision += 1
            # content entries are mutated below, but deltas must stay immutable.
            self.batch.append(dict(event))
            if kind in {'text', 'thinking'}:
                if self.content and self.content[-1]['type'] == kind:
                    self.content[-1]['content'] = self.content[-1].get('content', '') + event.get('content', '')
                else:
                    self.content.append(event)
            elif kind in {'tool_use', 'tool_result', 'artifacts'}:
                self.content.append(event)
            elif kind == 'usage':
                for key, value in (event.get('usage') or {}).items():
                    if isinstance(value, (int, float)) and not isinstance(value, bool):
                        self.usage[key] = self.usage.get(key, 0) + value
            elif kind == 'permission_request':
                self.permissions[event['req_id']] = event
                urgent = True
            else:
                self.metadata[kind] = event
                urgent = urgent or kind in {'run_queued', 'run_start', 'error', 'cancelled', 'turn_metrics', 'stream_end'}
        return urgent

    def should_save(self, urgent=False, now=None):
        now = time.monotonic() if now is None else now
        return self.saved_revision != self.revision and (
            urgent or self.last_saved_at is None or now - self.last_saved_at >= SNAPSHOT_INTERVAL_SECONDS
        )

    def saved(self, now=None):
        self.saved_revision = self.revision
        self.last_saved_at = time.monotonic() if now is None else now

    def payload(self):
        events = [self.metadata[k] for k in ('run_queued', 'run_start') if k in self.metadata]
        events += self.content
        if self.usage:
            events.append({'type': 'usage', 'usage': self.usage})
        events += [self.metadata[k] for k in ('info', 'context_notice', 'credit_usage') if k in self.metadata]
        events += list(self.permissions.values())
        events += [self.metadata[k] for k in ('error', 'cancelled', 'done', 'turn_metrics', 'stream_end') if k in self.metadata]
        return {'type': 'run_snapshot', 'revision': self.revision, 'events': events}


def _completed_snapshot(db, run, after):
    """A reconnect after temporary data expiry reads the permanent message."""
    started_at = run.started_at or run.created_at
    events = [{'type': 'run_start', 'run_id': run.id, 'session_id': run.session_id,
               'started_at': started_at.isoformat() if started_at is not None else None}]
    message = db.get(AgentMessage, run.assistant_message_id) if run.assistant_message_id else None
    if message is not None:
        try:
            content = json.loads(message.content)
        except (ValueError, TypeError):
            content = [{'type': 'text', 'content': message.content or ''}]
        blocks = content.get('blocks', []) if isinstance(content, dict) else content
        if isinstance(blocks, list):
            events.extend(block for block in blocks if isinstance(block, dict) and block.get('type') != 'usage')
    try:
        usage = json.loads(run.usage_detail) if run.usage_detail else None
    except ValueError:
        usage = None
    events.append({'type': 'turn_metrics', 'usage': usage, 'duration_ms': run.duration_ms,
                   'assistant_message_id': run.assistant_message_id,
                   'charged_points': recorded_charged_points(run)})
    terminal = 'done' if run.status == 'succeeded' else 'cancelled' if run.status == 'cancelled' else 'error'
    events.extend([{'type': terminal, 'content': run.error_message or '', 'error_code': run.error_code},
                   {'type': 'stream_end', 'status': run.status}])
    if terminal == 'error':
        saved_error = next((event for event in reversed(events[:-2])
                            if event.get('type') == 'error' and event.get('error_code') == run.error_code), None)
        if saved_error is not None:
            events[-2]['metadata'] = saved_error.get('metadata')
    return {'type': 'run_snapshot', 'revision': after + 1, 'events': events}


def read_events(factory, run_id, after, *, include_legacy=True):
    with factory() as db:
        run = db.query(AgentRun).filter_by(id=run_id).first()
        if run is None:
            return [], None, []
        state = {'status': run.status, 'error': run.error_message, 'error_code': run.error_code}
        if run.status not in RUNNING_STATUSES:
            payload = _completed_snapshot(db, run, after)
            return [(payload['revision'], json.dumps(payload, ensure_ascii=False))], state, []
        snapshot = db.get(AgentRunEvent, (run_id, 0)) if include_legacy else None
        rows = []
        if snapshot is not None:
            payload = json.loads(snapshot.payload)
            if payload['revision'] > after:
                rows = [(payload['revision'], snapshot.payload)]
        elif include_legacy:
            # Rolling upgrades can still have an old owner writing event rows.
            legacy = db.query(AgentRunEvent).filter(
                AgentRunEvent.run_id == run_id, AgentRunEvent.sequence > after,
            ).order_by(AgentRunEvent.sequence).limit(200).all()
            rows = [(row.sequence, row.payload) for row in legacy]
        pending = [row[0] for row in db.query(AgentPermissionRequest.req_id).filter(
            AgentPermissionRequest.run_id == run_id,
            AgentPermissionRequest.status == 'pending',
            AgentPermissionRequest.expires_at > datetime.now(timezone.utc),
        ).order_by(AgentPermissionRequest.req_id).all()]
        return rows, state, pending


def cleanup_expired_snapshots(factory, now=None, batch_size=1000):
    """Bounded deletion covers both old event rows and current snapshots."""
    cutoff = (now or datetime.now(timezone.utc)) - timedelta(minutes=SNAPSHOT_RETENTION_MINUTES)
    with factory() as db:
        expired_run = exists().where(
            AgentRun.id == AgentRunEvent.run_id,
            AgentRun.status.notin_(RETAINED_STATUSES),
            func.coalesce(AgentRun.finished_at, AgentRun.updated_at, AgentRun.created_at) < cutoff,
        )
        orphan = ~exists().where(AgentRun.id == AgentRunEvent.run_id)
        # Select keys, then recheck eligibility during deletion. A newly active
        # run must never lose its snapshot because cleanup raced a state change.
        keys = db.query(AgentRunEvent.run_id, AgentRunEvent.sequence).filter(
            or_(expired_run, orphan & (AgentRunEvent.created_at < cutoff)),
        ).limit(batch_size).all()
        if not keys:
            return 0
        count = db.query(AgentRunEvent).filter(
            tuple_(AgentRunEvent.run_id, AgentRunEvent.sequence).in_(keys),
            or_(expired_run, orphan & (AgentRunEvent.created_at < cutoff)),
        ).delete(synchronize_session=False)
        db.commit()
        return count


async def cleanup_snapshot_loop(factory):
    while True:
        try:
            # Small commits also drain pre-upgrade backlogs without a huge DELETE.
            for _ in range(10):
                if await asyncio.to_thread(cleanup_expired_snapshots, factory) < 1000:
                    break
                await asyncio.sleep(0.1)
        except Exception:
            logger.exception('Unable to clean expired run snapshots; will retry')
        await asyncio.sleep(60)


async def replay_events(factory, run_id, after=0):
    """Blocking Redis subscription; occasional SQL reconciliation, never token polling."""
    yield ': ' + (' ' * 4096) + '\n\n'
    next_reconcile = 0
    pending = []
    last_pending = None
    checked_permissions = set()
    redis_seen = False
    legacy = []
    while True:
        # SQL is only a fallback for legacy owners, expired cache, owner crashes,
        # and permissions decided in another tab. At most once per 15 seconds.
        if time.monotonic() >= next_reconcile:
            legacy, state, pending = await asyncio.to_thread(
                read_events, factory, run_id, after, include_legacy=not redis_seen,
            )
            next_reconcile = time.monotonic() + 15
            if state is None:
                return
            if state['status'] not in RUNNING_STATUSES:
                # Terminal state is committed after permanent messages/metrics.
                # Prefer the Redis checkpoint, falling back to permanent history.
                try:
                    rows = await get_store().read(run_id, after)
                except Exception:
                    rows = []
                has_end = any(e.get('type') == 'stream_end' for _, raw in rows
                              for e in json.loads(raw).get('events', [json.loads(raw)]))
                if not has_end:
                    rows = legacy
            else:
                rows = None
        else:
            rows = None
        if rows is None:
            try:
                rows = await get_store().read(run_id, after)
                redis_seen = redis_seen or bool(rows)
            except Exception:
                rows, legacy = legacy, []
                if not rows:
                    yield ': cache reconnecting\n\n'
                    await asyncio.sleep(2)
                    continue
            if not rows and legacy:
                rows, legacy = legacy, []
        for sequence, payload in rows:
            event = json.loads(payload)
            after = sequence
            if event.get('type') in {'run_snapshot', 'run_delta'}:
                # New permission events can arrive after the last reconciliation;
                # check them once on delivery, not on each token or snapshot.
                requests = [item for item in event['events'] if item.get('type') == 'permission_request']
                if any(item.get('req_id') not in checked_permissions for item in requests):
                    pending = await asyncio.to_thread(pending_permissions, factory, run_id)
                    checked_permissions.update(item.get('req_id') for item in requests)
                event['events'] = [item for item in event['events']
                                   if item.get('type') != 'permission_request' or item.get('req_id') in pending]
                payload = json.dumps(event, ensure_ascii=False)
                ended = any(item.get('type') == 'stream_end' for item in event['events'])
            else:
                ended = event.get('type') == 'stream_end'
                if event.get('type') == 'permission_request' and event.get('req_id') not in pending:
                    payload = '{"type":"heartbeat"}'
            yield f'id: {sequence}\ndata: {payload}\n\n'
            if ended:
                return
        if pending != last_pending:
            yield f'data: {json.dumps({"type": "permission_sync", "pending_ids": pending})}\n\n'
            last_pending = pending
        if rows:
            continue
        yield ': heartbeat\n\n'
        try:
            await get_store().wait(run_id, after, block=max(100, int((next_reconcile - time.monotonic()) * 1000)))
        except Exception:
            await asyncio.sleep(2)


def pending_permissions(factory, run_id):
    with factory() as db:
        return [row[0] for row in db.query(AgentPermissionRequest.req_id).filter(
            AgentPermissionRequest.run_id == run_id,
            AgentPermissionRequest.status == 'pending',
            AgentPermissionRequest.expires_at > datetime.now(timezone.utc),
        ).order_by(AgentPermissionRequest.req_id).all()]
