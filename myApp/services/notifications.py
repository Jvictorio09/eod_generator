"""Notification dispatch — in-app now; Slack/email later."""

from django.utils import timezone

from myApp.models import TaskNotification


def notify_unblocker(blocker, *, event="created"):
    """
    Notify the person who can unblock a task.

    # TODO: dispatch (Slack/email)
    """
    _ = event, blocker
    return False


def send_scheduled_eod(user, report):
    """
    Deliver an auto-generated EOD report to the user's configured channel.

    # TODO: dispatch (Slack/email) — respect user profile delivery prefs
    """
    _ = user, report
    return False


def notify_task_assigned(task, *, assigner_name):
    """Record an in-app notification when the boss assigns a task."""
    message = f"{assigner_name} assigned you a task: {task.title}"
    notification = TaskNotification.objects.create(
        recipient=task.user,
        task=task,
        kind=TaskNotification.Kind.TASK_ASSIGNED,
        message=message[:500],
    )
    # TODO: dispatch (Slack/email/push)
    return notification


def serialize_notification(notification):
    return {
        "id": notification.id,
        "kind": notification.kind,
        "message": notification.message,
        "task_id": notification.task_id,
        "read": notification.read_at is not None,
        "created_at": notification.created_at.isoformat(),
    }


def unread_notifications(user, *, limit=20):
    qs = (
        TaskNotification.objects.filter(recipient=user, read_at__isnull=True)
        .select_related("task")
        .order_by("-created_at")[:limit]
    )
    return [serialize_notification(n) for n in qs]


def mark_notifications_read(user, notification_ids=None):
    qs = TaskNotification.objects.filter(recipient=user, read_at__isnull=True)
    if notification_ids:
        qs = qs.filter(pk__in=notification_ids)
    now = timezone.now()
    return qs.update(read_at=now)
