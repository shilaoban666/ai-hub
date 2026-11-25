import asyncio
from types import SimpleNamespace

import httpx

from conversation_title import (
    fallback_session_title,
    generate_session_title,
    normalize_session_title,
)


def _model(protocol="anthropic-messages"):
    return SimpleNamespace(
        api_protocol=protocol,
        api_key="test-key",
        api_proxy_url="https://models.example.com",
        name="test-model",
    )


def test_greeting_uses_stable_intent_title_without_model_request():
    async def scenario():
        async def handler(_request):
            raise AssertionError("known greetings should not call the model")

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await generate_session_title(_model(), "  Hi! ", client=client)

    assert asyncio.run(scenario()) == "简单问候"
    assert fallback_session_title("你好？") == "简单问候"
    assert fallback_session_title("Thanks!") == "表达感谢"


def test_anthropic_title_generation_summarizes_instead_of_copying_prompt():
    captured = []

    async def scenario():
        async def handler(request):
            captured.append(request)
            return httpx.Response(
                200,
                json={"content": [{"type": "text", "text": "标题：排查算点未扣除。"}]},
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await generate_session_title(
                _model(),
                "咨询了问题，但是算点不消耗，为啥",
                client=client,
            )

    assert asyncio.run(scenario()) == "排查算点未扣除"
    assert captured[0].url == httpx.URL("https://models.example.com/v1/messages")
    assert captured[0].headers["x-api-key"] == "test-key"


def test_openai_title_generation_and_failure_fallback():
    responses = [
        httpx.Response(200, json={"choices": [{"message": {"content": "技能安装故障排查"}}]}),
        httpx.Response(503),
    ]

    async def scenario():
        async def handler(_request):
            return responses.pop(0)

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            generated = await generate_session_title(
                _model("openai-completions"), "企业市场的技能为什么不能安装", client=client
            )
            fallback = await generate_session_title(
                _model("openai-completions"), "第二个标题请求失败", client=client
            )
            return generated, fallback

    assert asyncio.run(scenario()) == ("技能安装故障排查", "第二个标题请求失败")


def test_title_normalization_is_bounded():
    fallback = "备用标题"
    assert normalize_session_title("《简洁标题》", fallback) == "简洁标题"
    assert len(normalize_session_title("很长" * 30, fallback)) <= 30


if __name__ == "__main__":
    test_greeting_uses_stable_intent_title_without_model_request()
    test_anthropic_title_generation_summarizes_instead_of_copying_prompt()
    test_openai_title_generation_and_failure_fallback()
    test_title_normalization_is_bounded()
    print("conversation title tests passed")
