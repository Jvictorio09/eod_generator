from datetime import datetime, timedelta
import re
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.db.models import Q
from django.utils import timezone

from myApp.models import EODReport, EODReportArchive, Task, UserProfile
from myApp.services.ai import format_plain_eod_report, generate_eod_report, generate_week_review
from myApp.services.notifications import send_scheduled_eod
from myApp.services.task_service import get_or_create_profile, tasks_for_report

User = get_user_model()

CONSISTENCY_WINDOW_DAYS = 30


def format_project_progress_section(progress):
    """Plain-text section 5 for EOD body."""
    from myApp.services.project_service import normalize_project_progress

    rows = normalize_project_progress(progress or [])
    if not rows:
        return ""
    lines = ["5. PROJECT PROGRESS"]
    for item in rows:
        lines.append(f"- {item['name']}: {item['percent']}%")
    return "\n".join(lines)


def merge_project_progress_into_content(content, progress):
    """Replace or append project progress in EOD text so it matches saved JSON."""
    section = format_project_progress_section(progress)
    text = (content or "").strip()
    if not section:
        return text
    if text:
        text = re.sub(
            r"\n?5\.\s*PROJECT\s*PROGRESS\s*\n(?:[ \t]*[-•*].*(?:\n|$))*",
            "",
            text,
            flags=re.IGNORECASE,
        ).rstrip()
        return f"{text}\n\n{section}"
    return section


def report_content_for_display(report):
    """EOD body with project % synced from the saved snapshot."""
    if not report:
        return ""
    content = report.content or ""
    progress = getattr(report, "project_progress", None) or []
    if progress:
        return merge_project_progress_into_content(content, progress)
    return content


def archive_content_for_display(archive):
    if not archive:
        return ""
    return merge_project_progress_into_content(
        archive.content or "",
        getattr(archive, "project_progress", None) or [],
    )


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
    existing = EODReport.objects.filter(user=user, date=day).first()
    if existing and existing.status == EODReport.Status.SUBMITTED:
        existing.draft_content = content
        existing.format = report_format
        existing.tone = tone
        existing.length = length
        existing.auto_generated = auto_generated
        existing.save(update_fields=["draft_content", "format", "tone", "length", "auto_generated"])
        return existing

    report, _ = EODReport.objects.update_or_create(
        user=user,
        date=day,
        defaults={
            "content": content,
            "draft_content": "",
            "format": report_format,
            "tone": tone,
            "length": length,
            "status": EODReport.Status.DRAFT,
            "submitted_at": None,
            "auto_generated": auto_generated,
        },
    )
    return report


def _archive_submitted_report(report):
    if report.status != EODReport.Status.SUBMITTED or not report.submitted_at:
        return
    EODReportArchive.objects.create(
        user=report.user,
        log_date=report.date,
        format=report.format,
        tone=report.tone,
        length=report.length,
        content=report.content,
        project_progress=report.project_progress or [],
        submitted_at=report.submitted_at,
    )


def submitted_history_entries(user, *, limit=50):
    """All posted EODs for history UI — current submissions plus archived re-posts."""
    entries = []
    for report in (
        EODReport.objects.filter(user=user, status=EODReport.Status.SUBMITTED)
        .select_related("user", "user__profile")
        .order_by("-submitted_at", "-date")
    ):
        entries.append({
            "kind": "report",
            "id": report.id,
            "date": report.date,
            "submitted_at": report.submitted_at,
            "report": report,
        })
    for archive in (
        EODReportArchive.objects.filter(user=user)
        .select_related("user", "user__profile")
        .order_by("-submitted_at")
    ):
        entries.append({
            "kind": "archive",
            "id": archive.id,
            "date": archive.log_date,
            "submitted_at": archive.submitted_at,
            "archive": archive,
        })
    entries.sort(
        key=lambda row: row["submitted_at"] or row["date"],
        reverse=True,
    )
    return entries[:limit]


def report_preview(content, max_len=140):
    """Short readable preview — skips EOD headers and section titles."""
    if not content:
        return ""
    skip_prefixes = (
        "EOD REPORT",
        "1. TASKS",
        "2. IN PROGRESS",
        "3. BLOCKER",
        "4. TOMORROW",
        "5. NOTES",
        "5. PROJECT",
    )
    for raw in content.splitlines():
        line = raw.strip().lstrip("-•* ").strip()
        if not line or line.startswith("---"):
            continue
        upper = line.upper()
        if any(upper.startswith(p) for p in skip_prefixes):
            continue
        return line[:max_len]
    collapsed = " ".join(content.split())
    return collapsed[:max_len]


def serialize_report_summary(report):
    profile = getattr(report.user, "profile", None)
    return {
        "id": report.id,
        "date": report.date.isoformat(),
        "format": report.format,
        "tone": report.tone,
        "length": report.length,
        "status": report.status,
        "author_username": report.user.username,
        "author_name": profile.display_name if profile and profile.display_name else report.user.username,
        "submitted_at": report.submitted_at.isoformat() if report.submitted_at else None,
        "excerpt": (report.content or "")[:200],
        "preview": report_preview(report.content),
        "created_at": report.created_at.isoformat(),
        "is_archive": False,
    }


def serialize_archive_summary(archive):
    profile = getattr(archive.user, "profile", None)
    return {
        "id": f"a{archive.id}",
        "date": archive.log_date.isoformat(),
        "format": archive.format,
        "tone": archive.tone,
        "length": archive.length,
        "status": EODReport.Status.SUBMITTED,
        "author_username": archive.user.username,
        "author_name": profile.display_name if profile and profile.display_name else archive.user.username,
        "submitted_at": archive.submitted_at.isoformat(),
        "excerpt": (archive.content or "")[:200],
        "preview": report_preview(archive.content),
        "created_at": archive.archived_at.isoformat(),
        "is_archive": True,
    }


def serialize_history_entries(entries):
    rows = []
    for row in entries:
        if row["kind"] == "archive":
            rows.append(serialize_archive_summary(row["archive"]))
        else:
            rows.append(serialize_report_summary(row["report"]))
    return rows


def report_display_content(report):
    """Text shown in the generate modal — prefer fresh draft over posted body."""
    draft = (report.draft_content or "").strip()
    if draft:
        return draft
    return (report.content or "").strip()


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


def submit_eod(user, day=None, *, content=None, report_format=None, tone=None, length=None, model=None, project_progress=None):
    """Mark today's generated EOD as SUBMITTED. Fast path — no AI call on post."""
    from myApp.services.notifications import notify_eod_posted
    from myApp.services.project_service import normalize_project_progress, persist_eod_project_progress

    day = day or timezone.localdate()
    profile = get_or_create_profile(user)
    normalized_progress = (
        normalize_project_progress(project_progress)
        if project_progress is not None
        else None
    )

    if not Task.objects.filter(user=user, date=day).exists():
        raise ValueError("No tasks for this day")

    report_format = report_format or profile.default_format
    tone = tone or profile.default_tone
    length = length or profile.default_length

    report = EODReport.objects.filter(user=user, date=day).first()
    incoming = (content or "").strip()

    if incoming:
        if report:
            if report.status == EODReport.Status.SUBMITTED:
                report.draft_content = incoming
            else:
                report.content = incoming
            report.format = report_format
            report.tone = tone
            report.length = length
            report.save()
        else:
            report = EODReport.objects.create(
                user=user,
                date=day,
                content=incoming,
                format=report_format,
                tone=tone,
                length=length,
                status=EODReport.Status.DRAFT,
            )

    if not report:
        raise ValueError("Generate your EOD first, then post.")

    to_publish = (report.draft_content or report.content or "").strip()
    if not to_publish:
        raise ValueError("Generate your EOD first, then post.")

    if normalized_progress is not None:
        to_publish = merge_project_progress_into_content(to_publish, normalized_progress)

    if report.status == EODReport.Status.SUBMITTED:
        if report.draft_content.strip():
            _archive_submitted_report(report)
            report.content = to_publish
            report.draft_content = ""
            report.format = report_format
            report.tone = tone
            report.length = length
            report.submitted_at = timezone.now()
            report.save()
            if normalized_progress is not None:
                persist_eod_project_progress(user, report, normalized_progress)
        return report

    report.content = to_publish
    report.draft_content = ""
    report.format = report_format
    report.tone = tone
    report.length = length
    report.status = EODReport.Status.SUBMITTED
    report.submitted_at = timezone.now()
    report.save()
    if normalized_progress is not None:
        persist_eod_project_progress(user, report, normalized_progress)
    notify_eod_posted(report)
    return report


def create_and_store_report(user, day, *, report_format=None, tone=None, length=None, model=None, auto_generated=False, project_progress=None):
    profile = get_or_create_profile(user)
    report_format = report_format or profile.default_format
    tone = tone or profile.default_tone
    length = length or profile.default_length
    model = model or profile.ai_model

    name = profile.display_name or user.get_full_name() or user.username
    date_str = day.strftime("%B %d, %Y")
    resolved = tasks_for_report(user, day)
    from myApp.services.project_service import normalize_project_progress, prefill_project_progress, projects_from_tasks

    if project_progress is None:
        progress = prefill_project_progress(user, day, projects_from_tasks(user, day))
    else:
        progress = normalize_project_progress(project_progress)

    if report_format == "PLAIN":
        content = format_plain_eod_report(
            name=name,
            date_str=date_str,
            tasks_payload=resolved,
            project_progress=progress,
        )
    else:
        content = generate_eod_report(
            name=name,
            date_str=date_str,
            tasks_payload=resolved,
            style=profile.style_guide,
            model=model,
            report_format=report_format,
            tone=tone,
            length=length,
            project_progress=progress,
        )
    if progress:
        content = merge_project_progress_into_content(content, progress)

    existing = EODReport.objects.filter(user=user, date=day).first()
    if existing and existing.status == EODReport.Status.SUBMITTED:
        existing.draft_content = content
        existing.format = report_format
        existing.tone = tone
        existing.length = length
        existing.auto_generated = auto_generated
        existing.project_progress = progress
        existing.save(update_fields=["draft_content", "format", "tone", "length", "auto_generated", "project_progress"])
        return existing

    report = save_report(
        user=user,
        day=day,
        content=content,
        report_format=report_format,
        tone=tone,
        length=length,
        auto_generated=auto_generated,
    )
    if progress:
        report.project_progress = progress
        report.save(update_fields=["project_progress"])
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
