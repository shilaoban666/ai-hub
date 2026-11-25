from datetime import date, datetime
from decimal import Decimal
from typing import Optional
import re

from pydantic import BaseModel, Field, field_validator
from schemas import ThinkingLevel, ReasoningVisibility, RuntimeType
from credit_labels import DEFAULT_CREDIT_DISPLAY_NAME
from runtime_environment import validate_runtime_environment


class WorkbenchSettingsDraft(BaseModel):
    model_config = {"protected_namespaces": ()}

    assistant_name: str = Field(default="AI 助手", min_length=1, max_length=200)
    assistant_icon: str = Field(default="H", min_length=1, max_length=255)
    assistant_mascot: str = Field(default="@cow", min_length=1, max_length=255)
    assistant_description: Optional[str] = Field(default=None, max_length=20_000)
    system_prompt: Optional[str] = Field(default=None, max_length=200_000)
    default_model_id: Optional[int] = Field(default=None, gt=0)

    @field_validator("assistant_name")
    @classmethod
    def normalize_assistant_name(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("助手名称不能为空")
        return value

    @field_validator("assistant_icon", "assistant_mascot")
    @classmethod
    def validate_appearance(cls, value, info):
        value = value.strip()
        if value in ("@cow", "@sprout") or re.fullmatch(r"/uploads/images/[A-Za-z0-9_-]+\.(?:png|jpe?g|gif|webp|ico|svg)", value, re.I):
            return value
        if info.field_name == "assistant_icon" and value and len(value) <= 8:
            return value
        raise ValueError("请选择内置形象或上传图片；聊天头像也可使用不超过 8 个字符的文字")


class AgentSettingsDraft(BaseModel):
    model_config = {"protected_namespaces": ()}

    runtime_type: RuntimeType = "claude_code"
    thinking_level: ThinkingLevel = "inherit"
    reasoning_visibility: ReasoningVisibility = "off"
    max_turns: int = Field(default=50, ge=1, le=200)
    timeout_seconds: int = Field(default=600, ge=1, le=3600)
    credit_display_name: str = Field(default=DEFAULT_CREDIT_DISPLAY_NAME, min_length=1, max_length=50)
    credit_display_name_en: str = Field(default="Credits", min_length=1, max_length=50)
    initial_claim_amount: Decimal = Field(default=Decimal("0.00"), ge=0, decimal_places=2)
    daily_claim_amount: Decimal = Field(default=Decimal("0.00"), ge=0, decimal_places=2)
    per_run_limit: Decimal = Field(default=Decimal("0.00"), ge=0, decimal_places=2)
    low_balance_threshold: Decimal = Field(default=Decimal("0.00"), ge=0, decimal_places=2)
    claim_timezone: str = Field(default="Asia/Shanghai", min_length=1, max_length=50)
    max_concurrent_runs: int = Field(default=1, ge=1, le=20)

    @field_validator("thinking_level")
    @classmethod
    def validate_thinking_level(cls, value, info):
        if info.data.get("runtime_type", "claude_code") == "claude_code" and value not in {
            "inherit", "low", "medium", "high", "xhigh", "max",
        }:
            raise ValueError(f"Claude Agent 不支持推理强度 {value}")
        return value


class SettingsVersion(BaseModel):
    id: int
    version: int
    status: str
    created_by: int
    published_by: Optional[int] = None
    published_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class AgentSettingsResponse(AgentSettingsDraft, SettingsVersion):
    pass


class WorkbenchSettingsResponse(WorkbenchSettingsDraft, SettingsVersion):
    pass


class AgentSettingsState(BaseModel):
    draft: Optional[AgentSettingsResponse] = None
    published: Optional[AgentSettingsResponse] = None


class WorkbenchSettingsState(BaseModel):
    draft: Optional[WorkbenchSettingsResponse] = None
    published: Optional[WorkbenchSettingsResponse] = None


# Legacy schemas remain available for reading old settings; combined writes are retired.
class AssistantSettingsDraft(WorkbenchSettingsDraft, AgentSettingsDraft):
    pass


class AssistantSettingsResponse(AssistantSettingsDraft, SettingsVersion):
    pass


class AssistantSettingsState(BaseModel):
    draft: Optional[AssistantSettingsResponse] = None
    published: Optional[AssistantSettingsResponse] = None


class GlobalSettingsUpdate(BaseModel):
    brand_icon: str = Field(default="H", min_length=1, max_length=8)
    brand_name: str = Field(default="AI Hub", min_length=1, max_length=100)
    brand_subtitle: str = Field(default="合趣网络", min_length=1, max_length=100)

    @field_validator("brand_icon", "brand_name", "brand_subtitle")
    @classmethod
    def normalize_brand_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("品牌信息不能为空")
        return normalized


class GlobalSettingsResponse(GlobalSettingsUpdate):
    updated_by: Optional[int] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class GlobalRuntimeEnvironment(BaseModel):
    variables: dict[str, str] = Field(default_factory=dict, max_length=100)

    _validate_variables = field_validator("variables")(validate_runtime_environment)


class PlatformModelUpsert(BaseModel):
    model_config = {"protected_namespaces": ()}

    name: str = Field(min_length=1, max_length=100)
    provider: str = Field(default="Anthropic", min_length=1, max_length=50)
    api_key: Optional[str] = Field(default=None, max_length=500)
    api_proxy_url: Optional[str] = Field(default=None, max_length=500)
    api_protocol: str = Field(default="anthropic-messages", pattern="^(anthropic-messages|openai-completions)$")
    reasoning_support: str = Field(default="auto", pattern="^(auto|enabled|disabled)$")
    remarks: Optional[str] = Field(default=None, max_length=200)
    is_enabled: bool = True
    input_rate: int = Field(default=0, ge=0)
    output_rate: int = Field(default=0, ge=0)
    cache_read_rate: int = Field(default=0, ge=0)
    cache_creation_rate: int = Field(default=0, ge=0)
    rate_scale: int = Field(default=1_000_000, ge=1)


class CreditBalanceResponse(BaseModel):
    available_balance: Decimal
    reserved_balance: Decimal
    display_name: str


class CreditAccountResponse(BaseModel):
    available_balance: Decimal
    reserved_balance: Decimal
    status: str
    version: int
    display_name: str
    display_name_en: str
    daily_claim_amount: Decimal
    today: date
    claimed_today: bool
    low_balance_threshold: Decimal


class CreditLedgerItem(BaseModel):
    id: int
    entry_type: str
    amount: Decimal
    available_after: Decimal
    reserved_after: Decimal
    run_id: Optional[str] = None
    reason: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class CreditLedgerList(BaseModel):
    total: int
    items: list[CreditLedgerItem]


class CreditAdjustmentRequest(BaseModel):
    amount: Decimal = Field(max_digits=20, decimal_places=2)
    reason: str = Field(min_length=1, max_length=1000)

    @field_validator("amount")
    @classmethod
    def validate_amount(cls, value):
        if value == 0:
            raise ValueError("积分调整金额不能为 0")
        return value

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("积分调整原因不能为空")
        return value


class ChatAssistantResponse(BaseModel):
    description: Optional[str] = None
    id: int
    name: str
    icon: str
    skills: list[dict] = Field(default_factory=list)
    default_model_id: int
    runtime_type: str
    thinking_level: ThinkingLevel = "inherit"
    reasoning_visibility: ReasoningVisibility = "off"
    models: list[dict] = Field(default_factory=list)


class BootstrapResponse(BaseModel):
    assistant_id: int
    assistant_name: str
    assistant_icon: str
    settings_version: int
    default_model_id: int
    runtime_type: str
    workspace_status: str
    workspace: dict
    credit: CreditAccountResponse
    assistant: Optional[ChatAssistantResponse] = None
