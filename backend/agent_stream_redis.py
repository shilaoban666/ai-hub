"""Redis-only transient output. Snapshot and retained deltas advance atomically."""

import asyncio
import json
from uuid import uuid4

from redis.asyncio import Redis

from database import settings

TTL_SECONDS = 600
MAX_BATCHES = 256
MAX_DELTA_BYTES = 256 * 1024

# Snapshot replacement and delta trimming must be one operation. A reader can
# always recover from the snapshot if its cursor predates the retained tail.
PUBLISH = """
if ARGV[2] == '' and (redis.call('EXISTS', KEYS[1]) == 0 or redis.call('EXISTS', KEYS[2]) == 0) then return 0 end
if ARGV[2] ~= '' then
  redis.call('HSET', KEYS[1], 'revision', ARGV[1], 'payload', ARGV[2])
  redis.call('DEL', KEYS[2])
end
if ARGV[3] ~= '' or ARGV[2] ~= '' then
  local last = redis.call('XREVRANGE', KEYS[2], '+', '-', 'COUNT', 1)
  if #last == 0 or tonumber(string.match(last[1][1], '^(%d+)')) < tonumber(ARGV[1]) then
    redis.call('XADD', KEYS[2], ARGV[1] .. '-0', 'payload', ARGV[3])
  end
end
redis.call('EXPIRE', KEYS[1], ARGV[4])
redis.call('EXPIRE', KEYS[2], ARGV[4])
return 1
"""

READ = """
if redis.call('EXISTS', KEYS[1]) == 0 then return {'', {}} end
local rev = tonumber(redis.call('HGET', KEYS[1], 'revision') or '0')
local cursor = tonumber(ARGV[1])
local snapshot = ''
if rev > cursor then
  snapshot = redis.call('HGET', KEYS[1], 'payload') or ''
  cursor = rev
end
return {snapshot, redis.call('XRANGE', KEYS[2], (cursor + 1) .. '-0', '+', 'COUNT', 200)}
"""


class StreamUnavailable(Exception):
    pass


class RedisRunStore:
    def __init__(self, client, prefix):
        self.client = client
        self.prefix = prefix

    def keys(self, run_id):
        # Same hash slot if an operator later uses a cluster-aware client.
        base = self.prefix + '{' + run_id + '}'
        return base + ':snapshot', base + ':events'

    async def publish(self, run_id, revision, events, snapshot=None):
        encode = lambda value: json.dumps(value, ensure_ascii=False, separators=(',', ':'))
        payload = encode({'type': 'run_delta', 'events': events}) if events and snapshot is None else ''
        return await self.client.eval(PUBLISH, 2, *self.keys(run_id), revision,
                                     encode(snapshot) if snapshot else '', payload, TTL_SECONDS)

    async def read(self, run_id, after):
        snapshot, tail = await self.client.eval(READ, 2, *self.keys(run_id), after)
        rows = []
        if snapshot:
            rows.append((json.loads(snapshot)['revision'], snapshot))
        for entry_id, fields in tail:
            payload = dict(zip(fields[::2], fields[1::2])).get('payload')
            if payload:
                rows.append((int(entry_id.split('-')[0]), payload))
        return rows

    async def wait(self, run_id, after, block=15000):
        # No SQL and no hot polling while the model is quiet. Re-read atomically
        # after waking: compaction may have happened during this blocking read.
        snapshot_key, stream_key = self.keys(run_id)
        if not await self.client.exists(snapshot_key):
            # Evicted snapshots make the retained tail insufficient for replay.
            # Avoid a hot loop over that tail until the owner recreates it.
            await asyncio.sleep(2)
            return
        await self.client.xread({stream_key: f'{after}-0'}, count=1, block=block)


_store = None


def get_store():
    global _store
    if _store is None:
        if not settings.redis_host.strip():
            raise StreamUnavailable('请配置后端 REDIS_HOST 后再发起对话')
        try:
            client = Redis(host=settings.redis_host.strip(), port=settings.redis_port,
                           password=settings.redis_password or None, decode_responses=True,
                           socket_connect_timeout=2, socket_timeout=20,
                           max_connections=1024, health_check_interval=30)
            _store = RedisRunStore(client, settings.aihub_redis_prefix)
        except Exception:
            # Never expose a URL, password, or connection exception to the user.
            raise StreamUnavailable('对话 Redis 配置无效，请联系管理员') from None
    return _store


async def check_stream_store():
    try:
        store = get_store()
        probe = 'health-' + uuid4().hex
        # Check the actual read/write commands and ACL, not just PING access.
        await store.publish(probe, 1, [], {'type': 'run_snapshot', 'revision': 1, 'events': []})
        try:
            if not await store.read(probe, 0):
                raise StreamUnavailable('对话缓存暂不可用，请稍后重试')
            await store.client.xread({store.keys(probe)[1]: '0-0'}, count=1)
        finally:
            await store.client.delete(*store.keys(probe))
    except StreamUnavailable:
        raise
    except Exception:
        raise StreamUnavailable('对话缓存暂不可用，请稍后重试') from None


async def close_stream_store():
    global _store
    if _store is not None:
        await _store.client.aclose()
        _store = None
