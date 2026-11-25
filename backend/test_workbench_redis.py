"""Real Redis checks; point the explicit test variables at an isolated instance."""

import asyncio
import json
import os
from contextlib import asynccontextmanager
from unittest.mock import patch
from uuid import uuid4

import pytest
from redis.asyncio import Redis
from redis.exceptions import TimeoutError as RedisTimeoutError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import agent_service
import agent_stream
import agent_stream_redis
from agent_stream import StreamSnapshot, replay_events
from agent_stream_redis import RedisRunStore, TTL_SECONDS
from database import Base
from models import Agent, AgentMessage, AgentRun


pytestmark = pytest.mark.skipif(
    os.environ.get("AIHUB_TEST_REDIS") != "1",
    reason="Set AIHUB_TEST_REDIS=1 and AIHUB_TEST_REDIS_PORT for a dedicated Redis instance",
)


def _client(*, socket_timeout=2):
    return Redis(
        host=os.environ.get("AIHUB_TEST_REDIS_HOST", "127.0.0.1"),
        port=int(os.environ["AIHUB_TEST_REDIS_PORT"]),
        decode_responses=True,
        socket_connect_timeout=2,
        socket_timeout=socket_timeout,
    )


@asynccontextmanager
async def _store():
    client = _client()
    prefix = "aihub-integration:" + uuid4().hex + ":"
    store = RedisRunStore(client, prefix)
    try:
        await client.ping()
        yield store
    finally:
        keys = [key async for key in client.scan_iter(match=prefix + "*")]
        if keys:
            await client.delete(*keys)
        await client.aclose()


def _consume(snapshot, event):
    return snapshot.consume("data: " + json.dumps(event) + "\n\n")


def _events(chunks):
    result = []
    for chunk in chunks:
        for line in chunk.splitlines():
            if line.startswith("data: "):
                payload = json.loads(line[6:])
                result.extend(payload.get("events", [payload]))
    return result


def test_real_lua_compaction_retry_eviction_and_ttl():
    async def scenario():
        async with _store() as store:
            with patch.object(agent_stream_redis, "get_store", return_value=store):
                await agent_stream_redis.check_stream_store()
            assert not [key async for key in store.client.scan_iter(match=store.prefix + "*")]
            snapshot = StreamSnapshot()
            _consume(snapshot, {"type": "text", "content": "a"})
            assert await store.publish("lua", 1, [], snapshot.payload()) == 1
            _consume(snapshot, {"type": "text", "content": "b"})
            assert await store.publish("lua", 2, snapshot.batch) == 1
            assert await store.publish("lua", 2, snapshot.batch) == 1
            assert len(await store.read("lua", 1)) == 1
            _consume(snapshot, {"type": "text", "content": "c"})
            assert await store.publish("lua", 3, [], snapshot.payload()) == 1
            rows = await store.read("lua", 1)
            assert json.loads(rows[0][1])["events"][0]["content"] == "abc"
            assert await store.client.xlen(store.keys("lua")[1]) == 1
            for key in store.keys("lua"):
                assert 0 < await store.client.ttl(key) <= TTL_SECONDS
                await store.client.delete(key)
                _consume(snapshot, {"type": "text", "content": "d"})
                assert await store.publish("lua", snapshot.revision, snapshot.batch) == 0
                assert await store.publish("lua", snapshot.revision, [], snapshot.payload()) == 1
                assert json.loads((await store.read("lua", 0))[0][1])["events"][0]["content"] == snapshot.content[0]["content"]
            for key in store.keys("lua"):
                await store.client.expire(key, 1)
            await asyncio.sleep(1.1)
            assert await store.read("lua", 0) == []
    asyncio.run(scenario())


def test_real_blocking_read_and_reconnect_resume_from_cursor():
    async def scenario():
        async with _store() as publisher:
            snapshot = StreamSnapshot()
            _consume(snapshot, {"type": "text", "content": "a"})
            await publisher.publish("reconnect", 1, [], snapshot.payload())
            observer = RedisRunStore(_client(), publisher.prefix)
            waiter = asyncio.create_task(observer.wait("reconnect", 1, block=1000))
            try:
                await asyncio.sleep(0.05)
                assert not waiter.done()
                _consume(snapshot, {"type": "text", "content": "b"})
                await publisher.publish("reconnect", 2, snapshot.batch)
                await asyncio.wait_for(waiter, 1.5)
            finally:
                if not waiter.done():
                    waiter.cancel()
                    await asyncio.gather(waiter, return_exceptions=True)
                await observer.client.aclose()
            observer = RedisRunStore(_client(), publisher.prefix)
            try:
                rows = await observer.read("reconnect", 1)
                assert [revision for revision, _ in rows] == [2]
                assert json.loads(rows[0][1])["events"] == [{"type": "text", "content": "b"}]
                _consume(snapshot, {"type": "text", "content": "c"})
                await publisher.publish("reconnect", 3, [], snapshot.payload())
                rows = await observer.read("reconnect", 1)
                assert json.loads(rows[0][1])["events"][0]["content"] == "abc"
            finally:
                await observer.client.aclose()
    asyncio.run(scenario())


def test_real_expired_cache_replays_permanent_reply(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'replay.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    try:
        with factory() as db:
            db.add(Agent(id=1, user_id=7, name="test"))
            db.add(AgentMessage(id=102, session_id=11, role="assistant", content="saved reply"))
            db.add(AgentRun(id="expired", agent_id=1, session_id=11, user_id=7,
                            status="succeeded", assistant_message_id=102))
            db.commit()

        async def scenario():
            async with _store() as store:
                await store.publish("expired", 1, [], {
                    "type": "run_snapshot", "revision": 1,
                    "events": [{"type": "text", "content": "cached reply"}],
                })
                for key in store.keys("expired"):
                    await store.client.expire(key, 1)
                await asyncio.sleep(1.1)
                assert await store.read("expired", 0) == []
                with patch.object(agent_stream, "get_store", return_value=store):
                    async def collect():
                        return [chunk async for chunk in replay_events(factory, "expired", after=10)]
                    events = _events(await asyncio.wait_for(collect(), 3))
                assert "".join(event.get("content", "") for event in events if event["type"] == "text") == "saved reply"
                assert events[-1] == {"type": "stream_end", "status": "succeeded"}
        asyncio.run(scenario())
    finally:
        engine.dispose()


def test_real_write_timeout_owner_rebuilds_snapshot_without_reexecution():
    async def scenario():
        async with _store() as admin_store:
            publisher = RedisRunStore(_client(socket_timeout=0.1), admin_store.prefix)
            timeout_revisions = []
            original_publish = publisher.publish
            async def publish(*args, **kwargs):
                try:
                    return await original_publish(*args, **kwargs)
                except RedisTimeoutError:
                    timeout_revisions.append(args[1])
                    raise
            executed = []
            async def feed(**kwargs):
                executed.append("owner")
                yield 'data: {"type":"run_queued","run_id":"timeout","session_id":1}\n\n'
                await admin_store.client.execute_command("CLIENT", "PAUSE", 400, "WRITE")
                yield 'data: {"type":"text","content":"before recovery"}\n\n'
                await asyncio.sleep(0.5)
                yield 'data: {"type":"text","content":" after recovery"}\n\n'
            try:
                with (patch.object(publisher, "publish", side_effect=publish),
                      patch.object(agent_service, "get_store", return_value=publisher),
                      patch.object(agent_stream, "get_store", return_value=admin_store),
                      patch.object(agent_service, "_run_agent_chat_feed", feed),
                      patch.object(agent_service, "read_events", return_value=([], {"status": "succeeded"}, []))):
                    stream = agent_service.run_agent_chat(agent_id=1)
                    await anext(stream)
                    await stream.aclose()
                    await asyncio.wait_for(asyncio.gather(*list(agent_service._WEB_STREAM_TASKS)), 5)
                assert timeout_revisions == [2]
                assert executed == ["owner"]
                rows = await admin_store.read("timeout", 0)
                events = json.loads(rows[0][1])["events"]
                assert next(event["content"] for event in events if event["type"] == "text") == "before recovery after recovery"
                assert events[-1] == {"type": "stream_end", "status": "succeeded"}
            finally:
                await publisher.client.aclose()
    asyncio.run(scenario())
