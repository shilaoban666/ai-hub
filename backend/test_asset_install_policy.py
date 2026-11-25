from types import SimpleNamespace
from unittest.mock import patch

from asset_routes import _auto_publish_public_release, _catalog_release_access
from auth import CurrentUser


def _release(**overrides):
    values = {
        "id": 11,
        "status": "published",
        "scan_status": "passed",
        "scan_report_json": "{}",
        "file_path": "release.zip",
        "file_url": "/releases/release.zip",
        "reviewed_at": None,
        "native_approved": False,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_public_published_release_is_installable_without_manual_approval():
    skill = SimpleNamespace(user_id=8, is_public=True)
    user = CurrentUser(user_id=7)

    with patch("asset_routes.os.path.isfile", return_value=True):
        installable, reason = _catalog_release_access(
            _release(), skill, user, system_release_id=None
        )

    assert installable is True
    assert reason is None


def test_marketplace_release_requires_publication_but_ignores_scan_status():
    skill = SimpleNamespace(user_id=8, is_public=True)
    user = CurrentUser(user_id=7)

    with patch("asset_routes.os.path.isfile", return_value=True):
        unpublished = _catalog_release_access(
            _release(status="pending_review"), skill, user, system_release_id=None
        )
        unsafe = _catalog_release_access(
            _release(scan_status="failed"), skill, user, system_release_id=None
        )

    assert unpublished == (False, "版本不可安装")
    assert unsafe == (True, None)


def test_public_release_is_upgraded_from_retired_review_state():
    skill = SimpleNamespace(user_id=8, is_public=True)
    release = _release(status="pending_review")

    assert _auto_publish_public_release(release, skill) is True
    assert release.status == "published"


def test_private_release_is_not_auto_published():
    skill = SimpleNamespace(user_id=8, is_public=False)
    release = _release(status="pending_review")

    assert _auto_publish_public_release(release, skill) is False
    assert release.status == "pending_review"


def test_asset_reviewer_can_install_private_enterprise_release():
    skill = SimpleNamespace(user_id=8, is_public=False)
    reviewer = CurrentUser(user_id=7, permissions=["aihub:assets:review"])

    with patch("asset_routes.os.path.isfile", return_value=True):
        installable, reason = _catalog_release_access(
            _release(), skill, reviewer, system_release_id=None
        )

    assert installable is True
    assert reason is None


def test_regular_user_cannot_install_private_enterprise_release():
    skill = SimpleNamespace(user_id=8, is_public=False)
    user = CurrentUser(user_id=7)

    with patch("asset_routes.os.path.isfile", return_value=True):
        installable, reason = _catalog_release_access(
            _release(), skill, user, system_release_id=None
        )

    assert installable is False
    assert reason == "版本未向当前用户发布"


def test_scan_failure_restoration_does_not_restore_revoked_or_reviewed_releases():
    from datetime import datetime
    from skill_release_policy import restore_scan_rejected_release

    for release in (
        _release(status="revoked", scan_status="failed"),
        _release(status="rejected", scan_status="failed", reviewed_at=datetime.now()),
    ):
        original_status = release.status
        assert restore_scan_rejected_release(release) is False
        assert release.status == original_status


if __name__ == "__main__":
    test_public_published_release_is_installable_without_manual_approval()
    test_marketplace_release_requires_publication_but_ignores_scan_status()
    test_public_release_is_upgraded_from_retired_review_state()
    test_private_release_is_not_auto_published()
    test_asset_reviewer_can_install_private_enterprise_release()
    test_regular_user_cannot_install_private_enterprise_release()
    test_scan_failure_restoration_does_not_restore_revoked_or_reviewed_releases()
    print("7 asset install policy tests passed")
