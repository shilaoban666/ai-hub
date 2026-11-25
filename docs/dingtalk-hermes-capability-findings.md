# 钉钉与 Hermes 渠道能力核查记录

## 1. 核查信息

- 核查日期：2026-07-17
- Hermes 仓库：`NousResearch/hermes-agent`
- AI Hub 设计固定参考提交：`7b5ba2054721dde998ed47fd4a0f031955278e99`
- 核查时 Hermes HEAD：`0f102fa4dc04b7dfdab048169aaaa640d09d7523`
- 结论：上述两个提交中的 `plugins/platforms/dingtalk/adapter.py` blob 均为
  `8017589e350bc363589a60198d75f9f312a3e763`，本记录描述的钉钉行为在核查时仍是
  Hermes 当前实现。

本记录只保存调研结果，不代表已批准或已实现对应能力。

## 2. “对方正在输入”

### 2.1 结论

钉钉机器人当前没有与微信 iLink `sendtyping` 对等的公开原生 typing 接口。
Hermes 同样不支持钉钉原生“对方正在输入”。

Hermes 的 `DingTalkAdapter.send_typing()` 是空实现：

```python
async def send_typing(self, chat_id: str, metadata=None) -> None:
    """DingTalk does not support typing indicators."""
    pass
```

### 2.2 Hermes 的替代体验

Hermes 使用以下机制反馈处理状态：

1. 收到消息后，通过钉钉机器人表情 OpenAPI 给原消息添加 `Thinking` 表情。
2. 完成后撤回 `Thinking`，再添加 `Done` 表情。
3. 可选使用 AI Card 流式更新回复内容。

表情反馈和 AI Card 流式更新都不是原生 typing，产品文案不能描述为“对方正在输入”。

### 2.3 AI Hub 当前行为

- 微信 channel spec 设置了 `supports_typing=True`，Worker 会在 AgentRun 生命周期内调用
  `getconfig`、`sendtyping(status=1)` 和 `sendtyping(status=2)`。
- 钉钉 channel spec 没有开启 `supports_typing`。
- `DingTalkStreamClient.get_typing_ticket()` 返回空字符串，`send_typing()` 为空操作。
- 因此钉钉绑定后不显示“对方正在输入”是当前明确的能力边界，不是绑定状态异常。

## 3. 语音消息

### 3.1 Hermes 支持的处理链路

Hermes 支持一条钉钉入站语音处理路径：

1. 从富文本消息项中识别 `type=voice` 和 `downloadCode`。
2. 将原生 voice 项标记为 `MessageType.VOICE`；普通音频附件保持
   `MessageType.AUDIO`，不会自动转写。
3. 使用钉钉 Robot OpenAPI 的 `RobotMessageFileDownloadRequest`，通过 access token、
   `robotCode` 和 `downloadCode` 获取临时下载 URL。
4. 下载并缓存语音文件。
5. 送入 Hermes 通用 STT，通过已配置的本地 Whisper、Groq、OpenAI、Mistral、xAI、
   ElevenLabs 或插件 provider 转写。
6. 将转写文字加入用户消息后交给 Agent；配置允许时可先向用户回显转写结果。

### 3.2 Hermes 实现边界

- 已核查的适配器没有优先读取钉钉回调中的 `audio.recognition`，主要采用
  “下载语音文件 + 自有 STT”。
- Hermes 测试明确覆盖的是 richText 中 `type=voice`、带 `downloadCode` 的消息形态。
- 不能据此推断所有钉钉 audio/voice payload 形态都已覆盖；需要用真实钉钉回调样本验证
  SDK 是否会把其他形态统一映射为 richText voice 项。

### 3.3 AI Hub 当前行为

- `DingTalkStreamClient._parse_callback_payload()` 目前只接受 `msgtype=text`，其他类型均
  标记为 `unsupported`。
- AI Hub 的通用 Channel Worker 只消费平台已经提供的语音转写文本，没有媒体下载和
  ASR/STT 流程。
- 微信可用是因为 iLink 的 `voice_item.text` 已包含转写，不代表 AI Hub 当前能够处理
  原始音频。
- 钉钉 channel spec 没有开启 `supports_voice_transcript`，所以 unsupported 提示会明确为
  “当前仅支持文字消息”。

## 4. 后续实现候选（未实施）

按风险和改动量排序：

1. 优先解析钉钉 `audio.recognition`；存在非空转写时，复用现有 `message_type=voice` 文本
   链路。
2. 没有 `recognition` 时，再考虑实现 `downloadCode -> 临时 URL -> 安全下载 -> ASR`。
3. 媒体下载前必须补齐 access token 管理、SSRF 防护、重定向限制、响应体大小限制、
   MIME sniffing、临时文件 TTL 和清理机制。
4. 处理状态可以参考 Hermes 实现 `Thinking/Done` 表情反馈。
5. 如需流式视觉反馈，可单独评估 AI Card；不得将其命名为原生 typing。

## 5. 上游依据

- Hermes 钉钉适配器：
  <https://github.com/NousResearch/hermes-agent/blob/7b5ba2054721dde998ed47fd4a0f031955278e99/plugins/platforms/dingtalk/adapter.py>
- Hermes 钉钉测试：
  <https://github.com/NousResearch/hermes-agent/blob/7b5ba2054721dde998ed47fd4a0f031955278e99/tests/gateway/test_dingtalk.py>
- Hermes Gateway STT：
  <https://github.com/NousResearch/hermes-agent/blob/7b5ba2054721dde998ed47fd4a0f031955278e99/gateway/run.py>
- Hermes 钉钉用户文档：
  <https://github.com/NousResearch/hermes-agent/blob/7b5ba2054721dde998ed47fd4a0f031955278e99/website/docs/user-guide/messaging/dingtalk.md>

