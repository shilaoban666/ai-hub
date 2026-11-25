"""Local feedback notification stub (external IAM/DingTalk notifications removed)."""


class FeedbackNotificationError(RuntimeError):
    """Raised when feedback notification dispatch fails."""


def sync_assignment_notification(*, authorization=None, feedback_id=None,
                                 previous_assignee_user_id=None, assignee_user_id=None,
                                 feedback_user=None, session_title=None, comment=None,
                                 detail_url=None, processing_status="pending"):
    return False


def sync_resolution_notification(*, authorization=None, feedback_id=None, feedback_user_id=None,
                                 session_title=None, processing_remark=None, detail_url=None,
                                 resolution_key=None):
    return False
