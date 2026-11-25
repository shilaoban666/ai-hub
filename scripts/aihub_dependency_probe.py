"""Bounded local-launch checks. Never print credentials or raw exceptions."""
import asyncio
from pathlib import Path
import sys


def check(label, operation):
    try:
        operation()
    except Exception:
        print(f'[FAIL] {label}; check the service .env, network/VPN and required credentials.', flush=True)
        raise SystemExit(1) from None


def database(settings):
    from sqlalchemy import create_engine, text
    options = {}
    if settings.database_url.startswith('mysql+pymysql:'):
        options['connect_args'] = {'connect_timeout': 5, 'read_timeout': 5, 'write_timeout': 5}
    engine = create_engine(settings.database_url, **options)
    try:
        with engine.connect() as connection:
            connection.execute(text('SELECT 1'))
    finally:
        engine.dispose()


def redis(settings):
    from redis import Redis
    if not settings.redis_host.strip():
        raise ValueError('Missing Redis host')
    with Redis(host=settings.redis_host, port=settings.redis_port,
               password=settings.redis_password or None,
               socket_connect_timeout=5, socket_timeout=5) as client:
        client.ping()


def signing_keys():
    from cryptography.hazmat.primitives import serialization
    from app.core.jwt_utils import _private_key_pem, _public_key_pem
    from cryptography.hazmat.primitives.asymmetric import rsa
    private = serialization.load_pem_private_key(_private_key_pem(), password=None)
    public = serialization.load_pem_public_key(_public_key_pem())
    if (not isinstance(private, rsa.RSAPrivateKey) or not isinstance(public, rsa.RSAPublicKey)
            or private.key_size < 2048 or private.public_key().public_numbers() != public.public_numbers()):
        raise ValueError('Invalid or mismatched RS256 keys')


async def chat_store():
    from agent_stream_redis import check_stream_store, close_stream_store
    try:
        await asyncio.wait_for(check_stream_store(), timeout=15)
    finally:
        await close_stream_store()


def main():
    # Services keep their own configuration loader and dependency environment.
    sys.path.insert(0, str(Path.cwd()))
    service = sys.argv[1]
    if service == 'backend':
        from database import settings
    else:
        from app.config import settings
    if service in ('backend', 'iam'):
        check(f'{service} MySQL connection failed', lambda: database(settings))
    if service == 'backend':
        check('AI Hub chat Redis read/write check failed', lambda: asyncio.run(chat_store()))
    else:
        check(f'{service} Redis connection failed', lambda: redis(settings))
    if service == 'iam':
        check('IAM RS256 signing key validation failed', signing_keys)
    print(f'[OK] {service} dependencies ready', flush=True)


if __name__ == '__main__':
    check('Service dependency configuration failed', main)
