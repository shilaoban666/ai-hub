from pydantic import ValidationError

from enterprise_schemas import GlobalSettingsResponse, GlobalSettingsUpdate
from models import PlatformGlobalSettings


def test_global_settings_defaults_match_existing_brand():
    settings = GlobalSettingsResponse()

    assert settings.brand_icon == "H"
    assert settings.brand_name == "AI Hub"
    assert settings.brand_subtitle == "合趣网络"


def test_global_settings_model_defaults_are_backwards_compatible():
    assert PlatformGlobalSettings.brand_icon.property.columns[0].default.arg == "H"
    assert PlatformGlobalSettings.brand_name.property.columns[0].default.arg == "AI Hub"
    assert PlatformGlobalSettings.brand_subtitle.property.columns[0].default.arg == "合趣网络"


def test_global_settings_accept_custom_brand():
    settings = GlobalSettingsUpdate(
        brand_icon="趣",
        brand_name="趣点工作台",
        brand_subtitle="企业智能助手",
    )

    assert settings.brand_icon == "趣"
    assert settings.brand_name == "趣点工作台"
    assert settings.brand_subtitle == "企业智能助手"


def test_global_settings_trim_values_and_reject_blank_text():
    settings = GlobalSettingsUpdate(
        brand_icon=" 趣 ",
        brand_name=" 趣点工作台 ",
        brand_subtitle=" 企业智能助手 ",
    )
    assert settings.brand_icon == "趣"
    assert settings.brand_name == "趣点工作台"
    assert settings.brand_subtitle == "企业智能助手"

    try:
        GlobalSettingsUpdate(brand_icon="  ")
    except ValidationError:
        pass
    else:
        raise AssertionError("blank brand icon must be rejected")


if __name__ == "__main__":
    test_global_settings_defaults_match_existing_brand()
    test_global_settings_model_defaults_are_backwards_compatible()
    test_global_settings_accept_custom_brand()
    test_global_settings_trim_values_and_reject_blank_text()
    print("global settings tests passed")
