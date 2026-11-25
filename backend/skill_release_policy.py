"""Publication compatibility for versions rejected by the retired skill scanner."""
from sqlalchemy import and_, or_

from models import SkillRelease


def published_release_filter():
    return or_(
        SkillRelease.status == "published",
        and_(
            SkillRelease.status == "rejected",
            SkillRelease.scan_status == "failed",
            SkillRelease.reviewed_at.is_(None),
            SkillRelease.revoked_at.is_(None),
        ),
    )


def restore_scan_rejected_release(release) -> bool:
    if (
        release.status == "rejected"
        and release.scan_status == "failed"
        and release.reviewed_at is None
        and getattr(release, "revoked_at", None) is None
    ):
        release.status = "published"
        return True
    return False
