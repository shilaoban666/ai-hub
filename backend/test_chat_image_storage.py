import asyncio
import base64
import io
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
import requests
from fastapi import HTTPException, UploadFile
from starlette.datastructures import Headers

import agent_routes
import chat_image_storage as storage
from agent_memory import AgentMemory
from auth import CurrentUser
from database import settings
from message_content import pack_user_content
from models import Agent, AgentSession
from runtimes.attachments import build_runtime_attachments
from test_agent_routes import _create_db

PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=')
URL = 'https://images.example.oss-cn-shanghai.aliyuncs.com/tmp/chat-images/7/20261111/' + 'a' * 32 + '.png'


@pytest.fixture(autouse=True)
def oss_config(monkeypatch):
    monkeypatch.setattr(settings, 'oss_bucket', 'images.example')
    monkeypatch.setattr(settings, 'oss_endpoint', 'vpc100-oss-cn-shanghai.aliyuncs.com')
    monkeypatch.setattr(settings, 'oss_public_endpoint', 'oss-cn-shanghai.aliyuncs.com')
    monkeypatch.setattr(settings, 'oss_chat_image_prefix', 'tmp/chat-images')
    monkeypatch.setattr(settings, 'oss_access_key_id', 'test-id')
    monkeypatch.setattr(settings, 'oss_access_key_secret', 'test-secret')


def response(status=200, chunks=(PNG,)):
    result = Mock(status_code=status)
    result.__enter__ = Mock(return_value=result)
    result.__exit__ = Mock(return_value=False)
    result.iter_content.return_value = iter(chunks)
    return result


def test_upload_uses_public_read_acl_and_returns_unsigned_public_endpoint():
    with patch.object(storage.requests, 'put', return_value=response()) as put:
        url = storage.upload_chat_image(PNG, 'image/png', 7)
    key = storage.image_object_key(url, 7)
    assert put.call_args.args[0] == 'https://images.example.vpc100-oss-cn-shanghai.aliyuncs.com/' + key
    assert put.call_args.kwargs['data'] == PNG
    assert put.call_args.kwargs['headers']['x-oss-object-acl'] == 'public-read'
    assert put.call_args.kwargs['headers']['Authorization'].startswith('OSS test-id:')
    assert put.call_args.kwargs['allow_redirects'] is False
    assert '?' not in url


def test_feedback_upload_uses_permanent_owner_prefix(monkeypatch):
    monkeypatch.setattr(settings, 'oss_feedback_image_prefix', 'feedback/images')
    with patch.object(storage.requests, 'put', return_value=response()) as put:
        url = storage.upload_feedback_image(PNG, 'image/png', 7)
    assert '/feedback/images/7/' in url
    assert '/tmp/' not in url
    assert put.call_args.kwargs['headers']['x-oss-object-acl'] == 'public-read'
    assert '?' not in url


@pytest.mark.parametrize('data,media', [(b'', 'image/png'), (b'x' * (storage.MAX_IMAGE_BYTES + 1), 'image/png'),
                                      (b'<svg/>', 'image/svg+xml'), (b'<script/>', 'image/png')])
def test_invalid_or_oversized_images_never_reach_oss(data, media):
    with patch.object(storage.requests, 'put') as put, pytest.raises(ValueError):
        storage.upload_chat_image(data, media, 7)
    put.assert_not_called()


@pytest.mark.parametrize('url', [URL.replace('https://', 'http://'), URL.replace('images.example.', 'evil.'),
                               URL.replace('/7/', '/8/'), URL + '?x=1', URL + '#fragment',
                               URL.replace('/20261111/', '/../'), URL.replace('/tmp/', '/other/')])
def test_remote_urls_cannot_read_other_workspaces_or_arbitrary_hosts(url):
    with patch.object(storage.requests, 'get') as get, pytest.raises(ValueError):
        storage.read_chat_image(url, 7)
    get.assert_not_called()


def test_runtime_reads_oss_image_bytes_without_workspace_file_access():
    provider = Mock()
    with patch.object(storage.requests, 'get', return_value=response()) as get:
        attachments = build_runtime_attachments(provider, SimpleNamespace(id=7), [URL, 'notes.txt', URL], 'claude_code')
    assert attachments[0].image_data == PNG
    assert attachments[0].path == URL
    assert attachments[0].media_type == 'image/png'
    assert len(attachments) == 2
    assert attachments[1].image_data is None
    provider.read_file_limited.assert_not_called()
    assert get.call_args.kwargs['stream'] is True


def test_download_bounds_stream_and_rejects_redirects():
    with patch.object(storage.requests, 'get', return_value=response(chunks=[b'x' * storage.MAX_IMAGE_BYTES, b'x'])):
        with pytest.raises(ValueError, match='5 MB'):
            storage.read_chat_image(URL, 7)
    with patch.object(storage.requests, 'get', return_value=response(302)):
        with pytest.raises(storage.ImageStorageError, match='302'):
            storage.read_chat_image(URL, 7)


def test_storage_errors_do_not_expose_credentials_or_request_details():
    with patch.object(storage.requests, 'put', side_effect=requests.RequestException('test-secret')):
        with pytest.raises(storage.ImageStorageError) as error:
            storage.upload_chat_image(PNG, 'image/png', 7)
    assert 'test-secret' not in str(error.value)
    with patch.object(storage.requests, 'put', return_value=response(403)):
        with pytest.raises(storage.ImageStorageError, match='403'):
            storage.upload_chat_image(PNG, 'image/png', 7)


def test_image_route_checks_agent_access_and_returns_only_public_url():
    db = Mock()
    user = CurrentUser(9)
    file = UploadFile(file=io.BytesIO(PNG), filename='screenshot.png', headers=Headers({'content-type': 'image/png'}))
    agent = object()
    with (patch.object(agent_routes, 'get_usable_agent', return_value=agent) as access,
          patch.object(agent_routes, 'bind_agent_workspace', return_value=(SimpleNamespace(id=7), None)),
          patch.object(agent_routes, 'upload_chat_image', return_value=URL) as upload,
          patch.object(agent_routes, 'get_workspace_provider') as provider):
        result = asyncio.run(agent_routes.upload_conversation_image(1, file, db, user))
    access.assert_called_once_with(db, 1, 9)
    upload.assert_called_once_with(PNG, 'image/png', 7)
    provider.assert_not_called()
    assert result == {'name': 'screenshot.png', 'url': URL}
    with patch.object(agent_routes, 'get_usable_agent', side_effect=HTTPException(404)), patch.object(agent_routes, 'upload_chat_image') as upload:
        with pytest.raises(HTTPException):
            asyncio.run(agent_routes.upload_conversation_image(1, file, db, user))
        upload.assert_not_called()


def test_follow_up_history_keeps_public_links_without_changing_saved_text():
    db = _create_db()
    try:
        db.add(Agent(id=1, user_id=7, name='Agent', is_deleted=False))
        db.add(AgentSession(id=1, agent_id=1, user_id=7, is_deleted=False))
        db.commit()
        memory = AgentMemory(db, 1)
        memory.save_user_message(pack_user_content('Describe this', [URL]))
        history = memory.load_history()
        assert history == [{'role': 'user', 'content': 'Describe this\n\n图片公网链接：\n' + URL}]
        assert memory.get_first_message() == 'Describe this'
    finally:
        db.close()


def test_current_turn_supplies_public_link_and_image_to_model():
    import agent_service
    from runtimes.base import RuntimeAttachment
    from test_agent_service import _DB, _Memory, _Runtime, _Sandbox, _agent, _execution_dependencies, _model, _session

    received = {}

    class CaptureRuntime(_Runtime):
        async def run(self, config, ctx, user_input, history, on_event, run_context=None):
            received['prompt'] = user_input
            received['attachments'] = run_context.attached_files
            await super().run(config, ctx, user_input, history, on_event, run_context)

    image = RuntimeAttachment(path=URL, filename='image.png', media_type='image/png', image_data=PNG)
    with (_execution_dependencies(), patch.object(agent_service, 'AgentMemory', _Memory),
          patch.object(agent_service, 'get_workspace_provider', return_value=_Sandbox()),
          patch.object(agent_service, 'build_mcp_json', return_value=({}, [])),
          patch.object(agent_service, 'build_runtime_attachments', return_value=(image,)),
          patch.object(agent_service, 'get_runtime', return_value=CaptureRuntime())):
        result = asyncio.run(agent_service.execute_agent_turn(
            agent=_agent(), user_input='Describe this', session_id=11, user_id=7,
            db=_DB(_session(), _model()), attached_files=[URL], interactive_permissions=False,
        ))
    assert result.status == 'succeeded'
    assert f'图片公网链接: {URL}' in received['prompt']
    assert received['attachments'] == (image,)
