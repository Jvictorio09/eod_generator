from datetime import timedelta

from django.contrib.auth import get_user_model
from django.utils import timezone

from myApp.models import Blocker, Task, UserProfile

User = get_user_model()

STALE_DAYS = 3
BLOCKER_ATTENTION_DAYS = 2


def get_or_create_profile(user):
    profile, _ = UserProfile.objects.get_or_create(user=user)
    return profile


def rollover_tomorrow_tasks(user, today=None):
    """Idempotent: copy yesterday's TOMORROW tasks into today as IN_PROGRESS."""
    today = today or timezone.localdate()
    yesterday = today - timedelta(days=1)
    rolled = 0

    for old in Task.objects.filter(
        user=user, date=yesterday, status=Task.Status.TOMORROW
    ):
        _, created = Task.objects.get_or_create(
            user=user,
            date=today,
            rolled_from=old,
            defaults={
                "title": old.title,
                "project": old.project,
                "status": Task.Status.IN_PROGRESS,
            },
        )
        if created:
            rolled += 1
    return rolled


def stale_in_progress_tasks(user, today=None):
    """Tasks still IN_PROGRESS with no update in STALE_DAYS days."""
    cutoff = timezone.now() - timedelta(days=STALE_DAYS)
    today = today or timezone.localdate()
    return Task.objects.filter(
        user=user,
        status=Task.Status.IN_PROGRESS,
        updated_at__lt=cutoff,
    ).exclude(date=today)


def active_blocker(task):
    return task.blockers.order_by("-created_at").first()


def blocker_age_label(blocker):
    if not blocker:
        return None
    days = (timezone.now() - blocker.created_at).days
    if days == 0:
        return "Blocked today"
    if days == 1:
        return "Blocked 1 day"
    return f"Blocked {days} days"


def serialize_blocker(blocker):
    if not blocker:
        return None
    unblocker = None
    if blocker.unblocker_id:
        profile = getattr(blocker.unblocker, "profile", None)
        unblocker = {
            "id": blocker.unblocker_id,
            "username": blocker.unblocker.username,
            "display_name": profile.display_name if profile else blocker.unblocker.get_full_name() or blocker.unblocker.username,
        }
    return {
        "id": blocker.id,
        "kind": blocker.kind,
        "kind_label": blocker.get_kind_display(),
        "unblocker": unblocker,
        "dependency_text": blocker.dependency_text,
        "note": blocker.note,
        "age_label": blocker_age_label(blocker),
        "created_at": blocker.created_at.isoformat(),
    }


def serialize_task(task, *, include_stale=False):
    blocker = active_blocker(task)
    assigned_by = None
    from_boss = False
    if task.assigned_by_id:
        profile = getattr(task.assigned_by, "profile", None)
        assigned_by = {
            "id": task.assigned_by_id,
            "username": task.assigned_by.username,
            "display_name": profile.display_name if profile else task.assigned_by.username,
            "role": profile.role if profile else None,
        }
        from_boss = bool(profile and profile.role == UserProfile.Role.BOSS)
    data = {
        "id": task.id,
        "title": task.title,
        "project": task.project,
        "status": task.status,
        "date": task.date.isoformat(),
        "blocker": serialize_blocker(blocker),
        "assigned_by": assigned_by,
        "from_boss": from_boss,
        "created_at": task.created_at.isoformat(),
        "updated_at": task.updated_at.isoformat(),
        "rolled_from": task.rolled_from_id,
    }
    if include_stale:
        cutoff = timezone.now() - timedelta(days=STALE_DAYS)
        data["is_stale"] = (
            task.status == Task.Status.IN_PROGRESS and task.updated_at < cutoff
        )
    return data


def tasks_for_report(user, date=None):
    date = date or timezone.localdate()
    qs = Task.objects.filter(user=user, date=date).prefetch_related("blockers")
    completed, progress, blockers, tomorrow = [], [], [], []

    for task in qs:
        blocker = active_blocker(task)
        entry = {
            "text": task.title,
            "project": task.project or None,
            "blocker": None,
        }
        if blocker:
            parts = []
            if blocker.note:
                parts.append(blocker.note)
            if blocker.unblocker_id:
                profile = getattr(blocker.unblocker, "profile", None)
                name = profile.display_name if profile else blocker.unblocker.username
                parts.append(f"Waiting on: {name}")
            elif blocker.dependency_text:
                parts.append(f"Waiting on: {blocker.dependency_text}")
            entry["blocker"] = " — ".join(parts) if parts else blocker.get_kind_display()

        if task.status == Task.Status.DONE:
            completed.append(entry)
        elif task.status == Task.Status.BLOCKED:
            blockers.append(entry)
        elif task.status == Task.Status.TOMORROW:
            tomorrow.append(entry)
        else:
            progress.append(entry)

    return {
        "completed": completed,
        "progress": progress,
        "blockers": blockers,
        "tomorrow": tomorrow,
    }


def attach_blocker(task, *, kind, unblocker_id=None, dependency_text="", note=""):
    blocker = Blocker.objects.create(
        task=task,
        kind=kind,
        unblocker_id=unblocker_id or None,
        dependency_text=(dependency_text or "").strip(),
        note=(note or "").strip(),
    )
    if task.status != Task.Status.DONE:
        task.status = Task.Status.BLOCKED
        task.save(update_fields=["status", "updated_at"])
    return blocker


def clear_blockers(task):
    task.blockers.all().delete()
    if task.status == Task.Status.BLOCKED:
        task.status = Task.Status.IN_PROGRESS
        task.save(update_fields=["status", "updated_at"])


def dashboard_data(today=None):
    today = today or timezone.localdate()
    threshold = timezone.now() - timedelta(days=BLOCKER_ATTENTION_DAYS)

    all_users = User.objects.filter(is_active=True).select_related("profile")
    submitted_ids = set(
        Task.objects.filter(date=today)
        .values_list("user_id", flat=True)
        .distinct()
    )

    lanes = {
        "shipped": [],
        "in_flight": [],
        "blocked": [],
        "needs_attention": [],
    }
    blocker_heatmap = {}
    wins = []
    pending_count = 0

    for user in all_users:
        profile = getattr(user, "profile", None)
        display = profile.display_name if profile else user.get_full_name() or user.username
        dept = profile.department_name if profile else ""

        if user.id not in submitted_ids:
            pending_count += 1
            lanes["needs_attention"].append({
                "type": "no_submission",
                "user": display,
                "department": dept,
                "message": "No log yet today",
            })

        tasks = Task.objects.filter(user=user, date=today).prefetch_related("blockers")
        for task in tasks:
            entry = {
                "id": task.id,
                "title": task.title,
                "project": task.project,
                "user": display,
                "department": dept,
                "status": task.status,
            }
            blocker = active_blocker(task)

            if task.status == Task.Status.DONE:
                lanes["shipped"].append(entry)
                wins.append({**entry, "user": display})
            elif task.status == Task.Status.IN_PROGRESS:
                lanes["in_flight"].append(entry)
            elif task.status == Task.Status.BLOCKED:
                entry["blocker"] = serialize_blocker(blocker)
                lanes["blocked"].append(entry)
                if blocker and blocker.created_at <= threshold:
                    lanes["needs_attention"].append({
                        "type": "stale_blocker",
                        "user": display,
                        "task": task.title,
                        "age_label": blocker_age_label(blocker),
                        "blocker": serialize_blocker(blocker),
                    })
                if blocker:
                    key = (
                        f"user:{blocker.unblocker_id}"
                        if blocker.unblocker_id
                        else f"dep:{blocker.dependency_text.lower()}"
                    )
                    if key not in blocker_heatmap:
                        blocker_heatmap[key] = {
                            "unblocker": serialize_blocker(blocker),
                            "dependency_text": blocker.dependency_text,
                            "count": 0,
                            "people": set(),
                            "tasks": [],
                        }
                    blocker_heatmap[key]["count"] += 1
                    blocker_heatmap[key]["people"].add(display)
                    blocker_heatmap[key]["tasks"].append(task.title)

    heatmap = []
    for item in blocker_heatmap.values():
        item["people"] = sorted(item["people"])
        if item["count"] >= 1:
            heatmap.append(item)
    heatmap.sort(key=lambda x: (-x["count"], x.get("dependency_text") or ""))

    return {
        "date": today.isoformat(),
        "lanes": lanes,
        "blocker_heatmap": heatmap[:10],
        "wins": wins[:12],
        "pending_count": pending_count,
        "team_size": all_users.count(),
    }
