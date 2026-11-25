import asyncio
import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import agent_service
import agent_stream
from agent_stream_redis import RedisRunStore
from fakeredis.aioredis import FakeRedis
from agent_memory import AgentMemory
from agent_service import AgentRunResult, run_agent_chat
from agent_stream import StreamSnapshot, read_events, replay_events, cleanup_expired_snapshots
from database import Base
from models import Agent, AgentMessage, AgentRun, AgentRunEvent, AgentSession
from runtimes.base import RuntimeEvent


@pytest.fixture(autouse=True)
def redis_store(monkeypatch):
    store = RedisRunStore(FakeRedis(decode_responses=True), 'test:chat:')
    monkeypatch.setattr(agent_service, 'get_store', lambda: store)
    monkeypatch.setattr(agent_stream, 'get_store', lambda: store)
    return store


class Lease:
    def commit_workspace(self, operation):
        operation()
        return True

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        pass

    async def is_owned(self):
        return True


def parse(chunk):
    events = [json.loads(line[6:]) for line in chunk.splitlines() if line.startswith('data: ')]
    return [item for event in events for item in (event['events'] if event['type'] in {'run_snapshot', 'run_delta'} else [event])]


def test_tool_html_survives_saved_history_and_completed_run_replay(tmp_path):
    engine = create_engine(f'sqlite:///{tmp_path / "html-history.db"}')
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    html = '<section>' + ('评分详情' * 4_000) + '</section>'
    try:
        with factory() as db:
            db.add(Agent(id=1, user_id=7, name='agent'))
            db.add(AgentSession(id=1, agent_id=1, user_id=7))
            db.commit()
            message = AgentMemory(db, 1).save_assistant_message([
                {'type': 'tool_use', 'name': 'Score', 'tool_use_id': 'score'},
                {'type': 'tool_result', 'tool_use_id': 'score',
                 'content': json.dumps({'data': {'s_html': html}}, ensure_ascii=False)},
            ])
            assert message is not None
            db.add(AgentRun(id='html-run', agent_id=1, session_id=1, user_id=7,
                            status='succeeded', assistant_message_id=message.id))
            db.commit()
            saved = json.loads(db.get(AgentMessage, message.id).content)
            assert saved['blocks'][1]['resultHtml'] == html
        # No cache: a fresh observer must reconstruct the full preview from SQL.
        rows, state, _ = read_events(factory, 'html-run', 0)
        assert state['status'] == 'succeeded'
        events = json.loads(rows[0][1])['events']
        assert next(event for event in events if event['type'] == 'tool_result')['resultHtml'] == html
        assert events[-1]['type'] == 'stream_end'
    finally:
        engine.dispose()


def test_timeout_details_and_live_debits_survive_history_and_completed_replay(tmp_path):
    engine = create_engine(f'sqlite:///{tmp_path / "timeout-history.db"}')
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    metadata = {'error_origin': 'model_connection',
                'error_detail': 'API Error: 504 upstream_timeout; request_id=req-history'}
    try:
        with factory() as db:
            db.add(Agent(id=1, user_id=7, name='agent'))
            db.add(AgentSession(id=1, agent_id=1, user_id=7))
            db.commit()
            message = AgentMemory(db, 1).save_assistant_message([
                {'type': 'text', 'content': 'partial reply'},
                {'type': 'error', 'content': '模型请求超时', 'error_code': 'model_request_timeout',
                 'metadata': metadata},
            ])
            assert message is not None
            db.add(AgentRun(id='timeout-run', agent_id=1, session_id=1, user_id=7,
                           status='timed_out', assistant_message_id=message.id,
                           error_code='model_request_timeout', error_message='模型请求超时',
                           settlement_status='pending_reconciliation', charged_points=1.23,
                           pricing_snapshot='{"billing_mode":"realtime"}'))
            db.commit()
            saved = json.loads(db.get(AgentMessage, message.id).content)
            assert saved['blocks'][-1]['metadata'] == metadata
        rows, _, _ = read_events(factory, 'timeout-run', 0)
        events = json.loads(rows[0][1])['events']
        assert next(event for event in events if event['type'] == 'turn_metrics')['charged_points'] == 1.23
        assert events[-2]['type'] == 'error'
        assert events[-2]['metadata'] == metadata
    finally:
        engine.dispose()


@pytest.mark.parametrize('disconnect_at', ['queued', 'text'])
@pytest.mark.parametrize('cancel', [False, True])
@pytest.mark.parametrize('cache_outage', [False, True])
def test_refresh_keeps_owner_alive_and_replays_without_reexecution(tmp_path, disconnect_at, cancel, cache_outage, redis_store):
    engine = create_engine(f'sqlite:///{tmp_path / "refresh.db"}', connect_args={'check_same_thread': False})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        db.add(Agent(id=1, user_id=7, name='agent', runtime_type='claude_code', timeout_seconds=60))
        db.commit()

    async def scenario():
        acquire_gate = asyncio.Event()
        output_gate = asyncio.Event()
        executed = []
        if disconnect_at == 'text':
            acquire_gate.set()

        async def acquire(**kwargs):
            await acquire_gate.wait()
            return Lease()

        async def execute(**kwargs):
            executed.append(kwargs['run_id'])
            db = kwargs['db']
            run = db.get(AgentRun, kwargs['run_id'])
            run.status = 'running'
            db.commit()
            await kwargs['on_started'](run.id, kwargs['session_id'])
            await kwargs['on_event'](RuntimeEvent(type='text', content='刷新前'))
            await output_gate.wait()
            # Exceed the live queue capacity: no reader must not block execution
            # or cause the closing marker to discard a token.
            for _ in range(350):
                await kwargs['on_event'](RuntimeEvent(type='text', content='续'))
            message = AgentMessage(session_id=kwargs['session_id'], role='assistant', content='刷新前' + '续' * 350)
            db.add(message)
            db.commit()
            run.assistant_message_id = message.id
            db.commit()
            return AgentRunResult(run_id=run.id, session_id=kwargs['session_id'], blocks=[],
                                  final_text=message.content, usage=None, runtime_session_id=None,
                                  status='succeeded', assistant_message_id=message.id)

        with (patch.object(agent_service, 'SessionLocal', factory),
              patch.object(agent_service, 'bind_agent_workspace', return_value=(SimpleNamespace(id=5), SimpleNamespace())),
              patch.object(agent_service, 'acquire_agent_execution_lease', acquire),
              patch.object(agent_service, 'execute_agent_turn', execute)):
            stream = run_agent_chat(agent_id=1, user_input='hello', session_id=None, user_id=7)
            seen = []
            async for chunk in stream:
                seen += parse(chunk)
                if any(e['type'] == disconnect_at or (disconnect_at == 'queued' and e['type'] == 'run_queued') for e in seen):
                    break
            run_id = next(e['run_id'] for e in seen if e['type'] == 'run_queued')
            await stream.aclose()  # HTTP disconnect / browser refresh
            if cache_outage:
                async def unavailable(*args, **kwargs):
                    raise ConnectionError('test cache failure')
                redis_store.publish = unavailable
            assert run_id in agent_service._ACTIVE_WEB_RUNS
            with factory() as db:
                assert db.get(AgentRun, run_id).status in {'queued', 'running'}
                assert db.get(AgentRun, run_id).cancel_requested is False
            if cancel:
                assert agent_service.cancel_web_run(run_id)
            else:
                acquire_gate.set()
                output_gate.set()
            await asyncio.wait_for(asyncio.gather(*list(agent_service._WEB_STREAM_TASKS)), 10)
            # A new observer reads from Redis after the task registry is
            # gone, just like a different API worker on page reload.
            replayed = []
            async for chunk in replay_events(factory, run_id):
                if '"type": "run_snapshot"' in chunk:
                    replayed = parse(chunk)
                else:
                    replayed += parse(chunk)
            assert replayed[-1]['type'] == 'stream_end'
            with factory() as db:
                run = db.get(AgentRun, run_id)
                assert run.status == ('cancelled' if cancel else 'succeeded')
                assert db.query(AgentRun).count() == 1
                assert db.query(AgentMessage).count() == (0 if cancel else 1)
                if not cancel:
                    assert len(executed) == 1
                    assert ''.join(e.get('content', '') for e in replayed if e['type'] == 'text') == '刷新前' + '续' * 350
                assert db.query(AgentRunEvent).filter_by(run_id=run_id).count() == 0
            assert run_id not in agent_service._ACTIVE_WEB_RUNS

    asyncio.run(scenario())
    engine.dispose()

def test_events_are_owned_and_permission_replay_ignores_resolved_prompts(tmp_path, redis_store):
    from datetime import datetime, timedelta, timezone
    from fastapi import HTTPException
    from agent_routes import get_messages, list_sessions, resume_agent_run
    from auth import CurrentUser
    from models import AgentPermissionRequest, AgentSession

    engine = create_engine(f'sqlite:///{tmp_path / "ownership.db"}')
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory() as db:
        db.add(Agent(id=1, user_id=7, name='agent'))
        db.add(AgentSession(id=1, agent_id=1, user_id=7))
        db.add(AgentRun(id='r', agent_id=1, session_id=1, user_id=7, source='web', status='running'))
        db.add_all([AgentPermissionRequest(req_id=req, run_id='r', tool_key='tool', tool_name='tool', tool_input='{}',
                                          status=status, expires_at=datetime.now(timezone.utc) + timedelta(minutes=1))
                    for req, status in [('answered', 'decided'), ('waiting', 'pending')]])
        db.commit()
        sessions = list_sessions(1, skip=0, limit=20, db=db, current_user=CurrentUser(user_id=7))
        assert sessions.items[0].active_run_id == 'r'
        messages = get_messages(1, 1, before_id=None, limit=100, db=db, current_user=CurrentUser(user_id=7))
        assert messages['session'].active_run_id == 'r'
        assert messages['session'].active_run_status == 'running'
        # Even staff cannot replay another user's private conversation.
        with pytest.raises(HTTPException) as exc:
            resume_agent_run(1, 'r', after=0, db=db, current_user=CurrentUser(user_id=8, is_superuser=True))
        assert exc.value.status_code in {403, 404}
        response = resume_agent_run(1, 'r', after=0, db=db, current_user=CurrentUser(user_id=7))
        assert response.media_type == 'text/event-stream'
    snapshot = StreamSnapshot()
    snapshot.consume(''.join('data: ' + json.dumps(e) + '\n\n' for e in [
        {'type': 'text', 'content': 'already seen'},
        {'type': 'permission_request', 'req_id': 'answered'},
        {'type': 'permission_request', 'req_id': 'waiting'},
        {'type': 'stream_end'},
    ]))
    async def replay():
        await redis_store.publish('r', snapshot.revision, [], snapshot.payload())
        events = []
        async for chunk in replay_events(factory, 'r', after=1):
            events.extend(parse(chunk))
        assert [e['content'] for e in events if e['type'] == 'text'] == ['already seen']
        assert [e['req_id'] for e in events if e['type'] == 'permission_request'] == ['waiting']
    asyncio.run(replay())
    engine.dispose()


def test_disconnect_before_first_frame_does_not_cancel_submission(redis_store):
    from contextlib import suppress

    async def scenario():
        gate = asyncio.Event()
        submitted = asyncio.Event()
        saved = []

        async def feed(**kwargs):
            await gate.wait()
            submitted.set()
            yield 'data: {"type":"run_queued","run_id":"r","session_id":1}\n\n'
            yield 'data: {"type":"text","content":"complete"}\n\n'

        async def save(run_id, revision, events, snapshot=None):
            saved.append(json.dumps(snapshot or events))
            return 1

        with (patch.object(agent_service, '_run_agent_chat_feed', feed),
              patch.object(redis_store, 'publish', save),
              patch.object(agent_service, 'read_events', return_value=([], {'status': 'succeeded'}, []))):
            stream = run_agent_chat(agent_id=1)
            reader = asyncio.create_task(anext(stream))
            await asyncio.sleep(0)
            reader.cancel()
            with suppress(asyncio.CancelledError):
                await reader
            gate.set()
            await asyncio.wait_for(asyncio.gather(*list(agent_service._WEB_STREAM_TASKS)), 2)
            assert submitted.is_set()
            assert 'complete' in ''.join(saved)
            assert 'stream_end' in saved[-1]
    asyncio.run(scenario())

def test_ten_thousand_deltas_use_redis_and_recover_after_compaction(redis_store):
    async def scenario():
        snapshot = StreamSnapshot()
        checkpoints = 0
        for i in range(100):
            snapshot.consume('data: {"type":"text","content":"' + '字' * 100 + '"}\n\n')
            checkpoint = snapshot.should_save(now=i / 10)
            await redis_store.publish('volume', snapshot.revision, snapshot.batch,
                                      snapshot.payload() if checkpoint else None)
            if checkpoint:
                snapshot.saved(now=i / 10)
                checkpoints += 1
        assert checkpoints == 2  # 5 seconds between full snapshots
        rows = await redis_store.read('volume', 1)  # cursor behind the trimmed tail
        assert json.loads(rows[0][1])['type'] == 'run_snapshot'
        events = [item for _, raw in rows for item in json.loads(raw)['events']]
        assert ''.join(e.get('content', '') for e in events) == '字' * 10000
        assert await redis_store.read('volume', 100) == []
        assert await redis_store.client.xlen(redis_store.keys('volume')[1]) <= 51
        for key in redis_store.keys('volume'):
            assert 0 < await redis_store.client.ttl(key) <= 600
        await redis_store.client.aclose()
    asyncio.run(scenario())


def test_snapshot_preserves_tools_usage_and_flushes_permissions_immediately():
    snapshot = StreamSnapshot()
    snapshot.consume('data: {"type":"text","content":"a"}\n\n')
    snapshot.saved(now=1)
    snapshot.consume('data: {"type":"usage","usage":{"input_tokens":2}}\n\n')
    snapshot.consume('data: {"type":"text","content":"b"}\n\n')
    assert snapshot.should_save(now=1.1) is False
    urgent = snapshot.consume('data: {"type":"permission_request","req_id":"p"}\n\n')
    assert snapshot.should_save(urgent, now=1.1) is True
    snapshot.consume('data: {"type":"tool_use","tool_use_id":"t","name":"Read"}\n\n')
    snapshot.consume('data: {"type":"tool_result","tool_use_id":"t","content":"result"}\n\n')
    snapshot.consume('data: {"type":"text","content":"c"}\n\n')
    snapshot.consume('data: {"type":"usage","usage":{"input_tokens":3}}\n\n')
    snapshot.consume('data: {"type":"credit_usage","usage":{"input_tokens":5},"metadata":{"charged_points":1.25,"available_balance":8.75}}\n\n')
    events = snapshot.payload()['events']
    assert [e['type'] for e in events[:4]] == ['text', 'tool_use', 'tool_result', 'text']
    assert events[0]['content'] == 'ab'
    assert next(e['usage'] for e in events if e['type'] == 'usage')['input_tokens'] == 5
    credit = next(e for e in events if e['type'] == 'credit_usage')
    assert credit['metadata']['charged_points'] == 1.25


def test_cleanup_is_bounded_preserves_active_runs_and_falls_back_to_history(tmp_path):
    from datetime import datetime, timedelta, timezone
    from models import AgentSession
    now = datetime.now(timezone.utc)
    old = now - timedelta(minutes=30)
    engine = create_engine(f'sqlite:///{tmp_path / "cleanup.db"}')
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory() as db:
        db.add(Agent(id=1, user_id=7, name='agent'))
        db.add(AgentSession(id=1, agent_id=1, user_id=7))
        db.add(AgentMessage(id=9, session_id=1, role='assistant', content='[{"type":"text","content":"永久历史"}]'))
        for run_id, status, finished in [('old', 'succeeded', old), ('recent', 'cancelled', now),
                                         ('live', 'running', old), ('unknown', 'unknown', old)]:
            db.add(AgentRun(id=run_id, agent_id=1, session_id=1, user_id=7, source='web', status=status,
                            finished_at=finished, assistant_message_id=9 if run_id == 'old' else None))
            db.add(AgentRunEvent(run_id=run_id, sequence=0, payload='{}', created_at=old))
        # Legacy rows are eligible too, but active legacy runs remain readable.
        db.add_all([AgentRunEvent(run_id='old', sequence=i, payload='{}', created_at=old) for i in range(1, 4)])
        db.add(AgentRunEvent(run_id='orphan', sequence=0, payload='{}', created_at=old))
        db.commit()
    assert cleanup_expired_snapshots(factory, now=now, batch_size=2) == 2
    assert cleanup_expired_snapshots(factory, now=now, batch_size=2) == 2
    assert cleanup_expired_snapshots(factory, now=now, batch_size=2) == 1
    assert cleanup_expired_snapshots(factory, now=now, batch_size=2) == 0
    with factory() as db:
        assert {r.run_id for r in db.query(AgentRunEvent).all()} == {'live', 'recent', 'unknown'}
        assert db.query(AgentMessage).count() == 1
        assert db.query(AgentRun).count() == 4
    rows, state, _ = read_events(factory, 'old', 500)
    assert state['status'] == 'succeeded'
    payload = json.loads(rows[0][1])
    assert payload['revision'] > 500
    assert next(e['content'] for e in payload['events'] if e['type'] == 'text') == '永久历史'
    assert payload['events'][-1]['type'] == 'stream_end'
    engine.dispose()


def test_redis_blocking_read_compaction_and_eviction(redis_store):
    async def scenario():
        snapshot = StreamSnapshot()
        snapshot.consume('data: {"type":"text","content":"a"}\n\n')
        await redis_store.publish('r', 1, [], snapshot.payload())
        waiter = asyncio.create_task(redis_store.wait('r', 1))
        await asyncio.sleep(0.02)
        assert not waiter.done()
        snapshot.consume('data: {"type":"text","content":"b"}\n\n')
        await redis_store.publish('r', 2, snapshot.batch)
        await asyncio.wait_for(waiter, 1)
        # A compaction racing the reader still recovers all output.
        snapshot.consume('data: {"type":"text","content":"c"}\n\n')
        await redis_store.publish('r', 3, [], snapshot.payload())
        rows = await redis_store.read('r', 1)
        assert json.loads(rows[0][1])['events'][0]['content'] == 'abc'
        # Losing either key must not publish an incomplete replay tail.
        for key in redis_store.keys('r'):
            await redis_store.client.delete(key)
            snapshot.consume('data: {"type":"text","content":"d"}\n\n')
            assert await redis_store.publish('r', snapshot.revision, snapshot.batch) == 0
            await redis_store.publish('r', snapshot.revision, [], snapshot.payload())
            rows = await redis_store.read('r', 0)
            assert json.loads(rows[0][1])['events'][0]['content'] == snapshot.content[0]['content']
        # Retrying an uncertain write does not duplicate the same batch.
        snapshot.consume('data: {"type":"text","content":"e"}\n\n')
        await redis_store.publish('r', snapshot.revision, snapshot.batch)
        await redis_store.publish('r', snapshot.revision, snapshot.batch)
        assert len(await redis_store.read('r', snapshot.revision - 1)) == 1
        await redis_store.client.aclose()
    asyncio.run(scenario())


def test_stream_connection_check_is_redacted_and_validates_write_access(monkeypatch, redis_store):
    import agent_stream_redis as transport
    async def scenario():
        monkeypatch.setattr(transport, 'get_store', lambda: redis_store)
        await transport.check_stream_store()
        assert await redis_store.client.dbsize() == 0
        async def forbidden(*args, **kwargs):
            raise ConnectionError('redis://secret-password@private-host')
        monkeypatch.setattr(redis_store, 'publish', forbidden)
        with pytest.raises(transport.StreamUnavailable) as exc:
            await transport.check_stream_store()
        assert 'secret-password' not in str(exc.value)
        await redis_store.client.aclose()
    asyncio.run(scenario())


def test_continuous_tokens_do_not_query_mysql(redis_store, monkeypatch):
    async def scenario():
        queries = []
        def reconcile(*args, **kwargs):
            queries.append(1)
            return [], {'status': 'running'}, []
        monkeypatch.setattr(agent_stream, 'read_events', reconcile)
        snapshot = StreamSnapshot()
        snapshot.consume('data: {"type":"run_start","run_id":"r"}\n\n')
        await redis_store.publish('r', 1, [], snapshot.payload())
        observer = replay_events(None, 'r')
        await anext(observer)  # proxy padding
        await anext(observer)  # first snapshot
        await anext(observer)  # initial permission sync
        for i in range(20):
            snapshot.consume('data: {"type":"text","content":"x"}\n\n')
            await redis_store.publish('r', snapshot.revision, snapshot.batch)
            chunk = await anext(observer)
            assert 'run_delta' in chunk
        assert len(queries) == 1
        await observer.aclose()
        await redis_store.client.aclose()
    asyncio.run(scenario())


@pytest.mark.parametrize('outage', [False, True])
def test_owner_bounds_redis_tail_and_rebuilds_after_write_failure(redis_store, monkeypatch, outage):
    async def scenario():
        lengths = []
        checkpoints = []
        original = redis_store.publish
        async def publish(run_id, revision, events, snapshot=None):
            if outage and revision == 3:
                raise ConnectionError('temporary test outage')
            result = await original(run_id, revision, events, snapshot)
            lengths.append(await redis_store.client.xlen(redis_store.keys(run_id)[1]))
            if snapshot:
                checkpoints.append(revision)
            return result
        async def feed(**kwargs):
            yield 'data: {"type":"run_queued","run_id":"bounded","session_id":1}\n\n'
            for _ in range(1000):
                yield 'data: {"type":"text","content":"x"}\n\n'
        monkeypatch.setattr(redis_store, 'publish', publish)
        monkeypatch.setattr(agent_service, '_run_agent_chat_feed', feed)
        monkeypatch.setattr(agent_service, 'read_events', lambda *args: ([], {'status': 'succeeded'}, []))
        stream = run_agent_chat(agent_id=1)
        await anext(stream)
        await stream.aclose()
        await asyncio.wait_for(asyncio.gather(*list(agent_service._WEB_STREAM_TASKS)), 5)
        rows = await redis_store.read('bounded', 0)
        events = json.loads(rows[0][1])['events']
        assert next(e['content'] for e in events if e['type'] == 'text') == 'x' * 1000
        assert events[-1]['type'] == 'stream_end'
        assert max(lengths) <= 256
        if not outage:
            assert len(checkpoints) >= 4
        await redis_store.client.aclose()
    asyncio.run(scenario())
