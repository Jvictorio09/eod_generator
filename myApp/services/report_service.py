from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.db.models import Q
from django.utils import timezone

from myApp.models import EODReport, Task, UserProfile
from myApp.services.ai import generate_eod_report, generate_week_review
from myApp.services.notifications import send_scheduled_eod
from myApp.services.task_service import get_or_create_profile, tasks_for_report

User = get_user_model()

CONSISTENCY_WINDOW_DAYS = 30


def serialize_profile_prefs(profile):
    return {
        "display_name": profile.display_name,
        "department": profile.department_name,
        "department_id": profile.department_id,
        "role": profile.role,
        "ai_model": profile.ai_model,
        "style_guide": profile.style_guide,
        "timezone": profile.timezone,
        "default_format": profile.default_format,
        "default_tone": profile.default_tone,
        "default_length": profile.default_length,
        "auto_send_enabled": profile.auto_send_enabled,
        "auto_send_time": profile.auto_send_time.isoformat() if profile.auto_send_time else None,
        "quiet_hours_start": profile.quiet_hours_start.isoformat() if profile.quiet_hours_start else None,
        "quiet_hours_end": profile.quiet_hours_end.isoformat() if profile.quiet_hours_end else None,
    }


def upsert_draft_report(*, user, day, content, report_format, tone, length, auto_generated=False):
    report, _ = EODReport.objects.update_or_create(
        user=user,
        date=day,
        defaults={
            "content": content,
            "format": report_format,
            "tone": tone,
            "length": length,
            "status": EODReport.Status.DRAFT,
            "submitted_at": None,
            "auto_generated": auto_generated,
        },
    )
    return report


def save_report(*, user, day, content, report_format, tone, length, auto_generated=False):
    return upsert_draft_report(
        user=user,
        day=day,
        content=content,
        report_format=report_format,
        tone=tone,
        length=length,
        auto_generated=auto_generated,
    )


def submit_eod(user, day=None, *, report_format=None, tone=None, length=None, model=None):
    """Generate or reuse today's report and mark SUBMITTED. Idempotent per user+date."""
    day = day or timezone.localdate()
    profile = get_or_create_profile(user)

    if not Task.objects.filter(user=user, date=day).exists():
        raise ValueError("No tasks for this day")

    report = EODReport.objects.filter(user=user, date=day).first()
    if report and report.content.strip():
        report.status = EODReport.Status.SUBMITTED
        report.submitted_at = timezone.now()
        report.save(update_fields=["status", "submitted_at"])
        return report

    report = create_and_store_report(
        user,
        day,
        report_format=report_format or profile.default_format,
        tone=tone or profile.default_tone,
        length=length or profile.default_length,
        model=model or profile.ai_model,
    )
    report.status = EODReport.Status.SUBMITTED
    report.submitted_at = timezone.now()
    report.save(update_fields=["status", "submitted_at"])
    return report


def create_and_store_report(user, day, *, report_format=None, tone=None, length=None, model=None, auto_generated=False):
    profile = get_or_create_profile(user)
    report_format = report_format or profile.default_format
    tone = tone or profile.default_tone
    length = length or profile.default_length
    model = model or profile.ai_model

    name = profile.display_name or user.get_full_name() or user.username
    date_str = day.strftime("%B %d, %Y")
    resolved = tasks_for_report(user, day)

    content = generate_eod_report(
        name=name,
        date_str=date_str,
        tasks_payload=resolved,
        style=profile.style_guide,
        model=model,
        report_format=report_format,
        tone=tone,
        length=length,
    )
    report = save_report(
        user=user,
        day=day,
        content=content,
        report_format=report_format,
        tone=tone,
        length=length,
        auto_generated=auto_generated,
    )
    return report


def consistency_stats(user, today=None):
    today = today or timezone.localdate()
    start = today - timedelta(days=CONSISTENCY_WINDOW_DAYS - 1)

    task_days = set(
        Task.objects.filter(user=user, date__gte=start, date__lte=today)
        .values_list("date", flat=True)
        .distinct()
    )
    report_days = set(
        EODReport.objects.filter(user=user, date__gte=start, date__lte=today)
        .values_list("date", flat=True)
        .distinct()
    )
    active_days = task_days | report_days
    count = len(active_days)
    pct = round(count / CONSISTENCY_WINDOW_DAYS * 100)

    return {
        "window_days": CONSISTENCY_WINDOW_DAYS,
        "active_days": count,
        "percent": pct,
        "message": _consistency_message(pct),
        "private": True,
    }


def _consistency_message(pct):
    if pct >= 80:
        return "Strong rhythm — you're showing up consistently."
    if pct >= 50:
        return "Steady progress — a few more days and you'll build a solid habit."
    if pct >= 25:
        return "Getting started — every log counts."
    return "Fresh start — no pressure, just log when you can."


def wins_archive(user, limit=40):
    wins = (
        Task.objects.filter(user=user, status=Task.Status.DONE)
        .order_by("-date", "-updated_at")[:limit]
    )
    return [
        {
            "id": w.id,
            "title": w.title,
            "project": w.project,
            "date": w.date.isoformat(),
        }
        for w in wins
    ]


def week_review_payload(user, today=None):
    today = today or timezone.localdate()
    start = today - timedelta(days=6)
    tasks = Task.objects.filter(user=user, date__gte=start, date__lte=today).order_by("date")
    reports = EODReport.objects.filter(user=user, date__gte=start, date__lte=today).order_by("-created_at")

    by_day = {}
    for t in tasks:
        key = t.date.isoformat()
        by_day.setdefault(key, {"tasks": [], "reports": []})
        by_day[key]["tasks"].append({
            "title": t.title,
            "status": t.status,
            "project": t.project,
        })

    for r in reports:
        key = r.date.isoformat()
        by_day.setdefault(key, {"tasks": [], "reports": []})
        by_day[key]["reports"].append({
            "format": r.format,
            "excerpt": r.content[:300],
        })

    return {
        "start": start.isoformat(),
        "end": today.isoformat(),
        "days": by_day,
    }


def search_content(user, query, *, team=False, limit=25, viewer=None):
    q = (query or "").strip()
    if len(q) < 2:
        return {"results": []}

    viewer_profile_obj = None
    if viewer:
        viewer_profile_obj = get_or_create_profile(viewer)

    if team:
        report_qs = EODReport.objects.filter(
            content__icontains=q,
            status=EODReport.Status.SUBMITTED,
        ).select_related("user", "user__profile")
        task_qs = Task.objects.filter(title__icontains=q).select_related("user", "user__profile")

        if viewer_profile_obj and viewer_profile_obj.role == UserProfile.Role.MANAGER:
            if viewer_profile_obj.department_id:
                report_qs = report_qs.filter(user__profile__department_id=viewer_profile_obj.department_id)
                task_qs = task_qs.filter(user__profile__department_id=viewer_profile_obj.department_id)
            else:
                return {"results": []}
    else:
        task_qs = Task.objects.filter(user=user, title__icontains=q)
        report_qs = EODReport.objects.filter(user=user, content__icontains=q)

    results = []
    for t in task_qs.order_by("-date")[:limit]:
        profile = getattr(t.user, "profile", None)
        results.append({
            "type": "task",
            "id": t.id,
            "title": t.title,
            "date": t.date.isoformat(),
            "status": t.status,
            "user": profile.display_name if profile else t.user.username,
        })
    for r in report_qs.order_by("-date")[:limit]:
        profile = getattr(r.user, "profile", None)
        results.append({
            "type": "report",
            "id": r.id,
            "title": f"EOD report ({r.get_format_display()})",
            "date": r.date.isoformat(),
            "excerpt": r.content[:200],
            "user": profile.display_name if profile else r.user.username,
        })

    results.sort(key=lambda x: x["date"], reverse=True)
    return {"results": results[:limit]}


def _local_now(profile):
    try:
        tz = ZoneInfo(profile.timezone or "UTC")
    except Exception:
        tz = ZoneInfo("UTC")
    return timezone.now().astimezone(tz)


def _in_quiet_hours(local_time, profile):
    if not profile.quiet_hours_start or not profile.quiet_hours_end:
        return False
    t = local_time.time()
    start = profile.quiet_hours_start
    end = profile.quiet_hours_end
    if start <= end:
        return start <= t <= end
    return t >= start or t <= end


def users_due_for_auto_send():
    due = []
    for profile in UserProfile.objects.filter(auto_send_enabled=True, auto_send_time__isnull=False).select_related("user"):
        if not profile.user.is_active:
            continue
        local = _local_now(profile)
        local_date = local.date()
        if profile.last_auto_send_date == local_date:
            continue
        if _in_quiet_hours(local, profile):
            continue
        target = datetime.combine(local_date, profile.auto_send_time, tzinfo=local.tzinfo)
        delta_minutes = abs((local - target).total_seconds()) / 60
        if delta_minutes <= 15:
            has_tasks = Task.objects.filter(user=profile.user, date=local_date).exists()
            if has_tasks:
                due.append((profile, local_date))
    return due


def run_auto_send_for_profile(profile, local_date):
    try:
        report = create_and_store_report(
            profile.user,
            local_date,
            auto_generated=True,
        )
        send_scheduled_eod(profile.user, report)
        profile.last_auto_send_date = local_date
        profile.save(update_fields=["last_auto_send_date"])
        return True
    except Exception:
        return False
