"""In-app notifications + optional email for oversight."""

import logging
import os

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import send_mail
from django.utils import timezone

from myApp.models import TaskNotification, UserProfile
from myApp.services.task_service import get_or_create_profile

User = get_user_model()
logger = logging.getLogger(__name__)


def _app_base_url():
    domain = (os.getenv("RAILWAY_PUBLIC_DOMAIN") or os.getenv("APP_BASE_URL", "")).strip()
    if not domain:
        return "http://127.0.0.1:8000"
    if domain.startswith("http://") or domain.startswith("https://"):
        return domain.rstrip("/")
    return f"https://{domain.rstrip('/')}"


def _email_enabled():
    return getattr(settings, "NOTIFY_EMAIL_ENABLED", False)


def _poster_display(user):
    profile = getattr(user, "profile", None)
    if profile and profile.display_name:
        return profile.display_name
    return user.get_full_name() or user.username


def _notification_link(notification):
    if notification.kind == TaskNotification.Kind.EOD_POSTED and notification.eod_report_id:
        report = notification.eod_report
        profile = getattr(report.user, "profile", None)
        board_id = profile.department_id if profile else None
        params = f"date={report.date.isoformat()}&user={report.user_id}"
        if board_id:
            params += f"&board={board_id}"
        return f"{_app_base_url()}/dashboard/?{params}"
    return f"{_app_base_url()}/dashboard/"


def _send_notification_email(user, *, subject, message):
    if not _email_enabled():
        return False
    profile = get_or_create_profile(user)
    if not profile.notify_email:
        return False
    to_email = (user.email or "").strip()
    if not to_email:
        return False
    try:
        send_mail(
            subject=subject,
            message=message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[to_email],
            fail_silently=False,
        )
        return True
    except Exception:
        logger.exception("Failed to send notification email to %s", user.username)
        return False


def oversight_recipients_for_eod(poster):
    """Bosses + the employee's department manager (not the poster)."""
    profile = get_or_create_profile(poster)
    recipients = []
    seen = {poster.id}

    for boss in UserProfile.objects.filter(
        role=UserProfile.Role.BOSS,
        user__is_active=True,
    ).select_related("user"):
        if boss.user_id not in seen:
            recipients.append(boss.user)
            seen.add(boss.user_id)

    if profile.role == UserProfile.Role.EMPLOYEE and profile.department_id:
        manager = (
            UserProfile.objects.filter(
                role=UserProfile.Role.MANAGER,
                department_id=profile.department_id,
                user__is_active=True,
            )
            .select_related("user")
            .first()
        )
        if manager and manager.user_id not in seen:
            recipients.append(manager.user)
            seen.add(manager.user_id)

    return recipients


def notify_eod_posted(report):
    """Alert boss/manager in-app and optionally by email when someone posts an EOD."""
    poster = report.user
    poster_name = _poster_display(poster)
    dept = getattr(poster, "profile", None)
    dept_name = dept.department.name if dept and dept.department_id else "their team"
    date_label = report.date.strftime("%B %d, %Y")
    message = f"{poster_name} posted their EOD for {date_label} ({dept_name})"
    link = f"{_app_base_url()}/dashboard/?date={report.date.isoformat()}&user={poster.id}"
    if dept and dept.department_id:
        link += f"&board={dept.department_id}"

    created = []
    for recipient in oversight_recipients_for_eod(poster):
        notification = TaskNotification.objects.create(
            recipient=recipient,
            eod_report=report,
            kind=TaskNotification.Kind.EOD_POSTED,
            message=message[:500],
        )
        created.append(notification)

        subject = f"[CloseOut] {poster_name} posted their EOD — {date_label}"
        body = (
            f"{poster_name} submitted their end-of-day report for {date_label}.\n\n"
            f"Team: {dept_name}\n\n"
            f"View in CloseOut:\n{link}\n"
        )
        _send_notification_email(recipient, subject=subject, message=body)

    return created


def notify_unblocker(blocker, *, event="created"):
    """Notify the person who can unblock a task."""
    _ = event, blocker
    return False


def send_scheduled_eod(user, report):
    """Deliver an auto-generated EOD report to the user's configured channel."""
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
    return notification


def serialize_notification(notification):
    return {
        "id": notification.id,
        "kind": notification.kind,
        "message": notification.message,
        "task_id": notification.task_id,
        "eod_report_id": notification.eod_report_id,
        "link": _notification_link(notification),
        "read": notification.read_at is not None,
        "created_at": notification.created_at.isoformat(),
    }


def unread_notifications(user, *, limit=20):
    qs = (
        TaskNotification.objects.filter(recipient=user, read_at__isnull=True)
        .select_related("task", "eod_report", "eod_report__user")
        .order_by("-created_at")[:limit]
    )
    return [serialize_notification(n) for n in qs]


def mark_notifications_read(user, notification_ids=None):
    qs = TaskNotification.objects.filter(recipient=user, read_at__isnull=True)
    if notification_ids:
        qs = qs.filter(pk__in=notification_ids)
    now = timezone.now()
    return qs.update(read_at=now)
