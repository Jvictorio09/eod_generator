"""One-shot workspace payload — fewer round trips on employee load."""

from django.contrib.auth import get_user_model
from django.utils import timezone

from myApp.models import Task
from myApp.services.notifications import unread_notifications
from myApp.services.project_service import list_active_projects, list_user_project_progress, project_eod_insights
from myApp.services.report_service import (
    consistency_stats,
    serialize_history_entries,
    submitted_history_entries,
    wins_archive,
)
from myApp.services.task_service import (
    rollover_tomorrow_tasks,
    serialize_task,
    stale_in_progress_tasks,
)

User = get_user_model()


def _serialize_users():
    users = User.objects.filter(is_active=True).select_related("profile").order_by("username")
    return [
        {
            "id": u.id,
            "username": u.username,
            "display_name": (
                u.profile.display_name
                if getattr(u, "profile", None)
                else u.get_full_name() or u.username
            ),
        }
        for u in users
    ]


def build_workspace_bootstrap(user, day=None):
    day = day or timezone.localdate()
    rolled = 0
    if day == timezone.localdate():
        rolled = rollover_tomorrow_tasks(user, day)

    tasks_qs = (
        Task.objects.filter(user=user, date=day)
        .select_related("assigned_by", "assigned_by__profile", "project_ref")
        .prefetch_related("blockers")
    )
    notifications = unread_notifications(user)
    history = submitted_history_entries(user, limit=15)

    return {
        "date": day.isoformat(),
        "rolled_count": rolled,
        "tasks": [serialize_task(t, include_stale=True) for t in tasks_qs],
        "stale_elsewhere": [
            serialize_task(t, include_stale=True)
            for t in stale_in_progress_tasks(user, day)
        ],
        "users": _serialize_users(),
        "projects": list_active_projects(),
        "notifications": notifications,
        "unread_count": len(notifications),
        "consistency": consistency_stats(user),
        "wins": wins_archive(user, limit=15),
        "project_insights": project_eod_insights(user, days=30),
        "project_self_progress": list_user_project_progress(user),
        "reports": serialize_history_entries(history),
    }
