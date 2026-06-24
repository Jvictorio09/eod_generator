"""Role-scoped oversight dashboard data."""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db.models import Count, Q
from django.utils import timezone

from myApp.models import Department, EODReport, Task, UserProfile
from myApp.services.task_service import active_blocker, blocker_age_label, get_or_create_profile, serialize_blocker

User = get_user_model()
MANAGERS_GROUP = "Managers"


def user_has_oversight(user):
    profile = get_or_create_profile(user)
    if profile.has_oversight_access():
        return True
    if user.is_staff or user.groups.filter(name=MANAGERS_GROUP).exists():
        return True
    return False


def viewer_profile(user):
    return get_or_create_profile(user)


def is_boss(profile):
    return profile.role == UserProfile.Role.BOSS


def is_manager_role(profile):
    return profile.role == UserProfile.Role.MANAGER


def is_boss_user(user):
    return is_boss(viewer_profile(user))


def departments_with_active_members():
    """Boards that have at least one active non-boss member (pilot: hide empty boards)."""
    return list(
        Department.objects.filter(
            members__user__is_active=True,
        )
        .exclude(members__role=UserProfile.Role.BOSS)
        .distinct()
        .order_by("name")
        .values_list("pk", flat=True)
    )


def accessible_department_ids(profile, user):
    """Department PKs the viewer may access. Empty = none."""
    populated = departments_with_active_members()
    if is_boss(profile):
        return populated
    if is_manager_role(profile) and profile.department_id:
        if int(profile.department_id) in populated:
            return [profile.department_id]
        return [profile.department_id]
    if user.is_staff or user.groups.filter(name=MANAGERS_GROUP).exists():
        if profile.department_id:
            return [profile.department_id]
        return populated
    return []


def can_access_department(profile, user, department_id):
    if department_id is None:
        return False
    return int(department_id) in accessible_department_ids(profile, user)


def can_assign_task_to_user(assigner, target_user_id):
    """Boss may assign tasks to any active non-boss team member."""
    profile = viewer_profile(assigner)
    if not is_boss(profile):
        return False
    try:
        target = User.objects.select_related("profile").get(pk=target_user_id, is_active=True)
    except User.DoesNotExist:
        return False
    target_profile = getattr(target, "profile", None)
    if not target_profile or target_profile.role == UserProfile.Role.BOSS:
        return False
    return True


def can_view_user_eod(viewer, target_user_id):
    """Manager/Boss may view a user's submitted EOD; employees only themselves."""
    if viewer.id == target_user_id:
        return True
    profile = viewer_profile(viewer)
    if not user_has_oversight(viewer):
        return False
    try:
        target = User.objects.select_related("profile").get(pk=target_user_id, is_active=True)
    except User.DoesNotExist:
        return False
    target_profile = getattr(target, "profile", None)
    if not target_profile:
        return False
    if is_boss(profile):
        return True
    if is_manager_role(profile) and profile.department_id:
        return target_profile.department_id == profile.department_id
    if viewer.is_staff or viewer.groups.filter(name=MANAGERS_GROUP).exists():
        if profile.department_id:
            return target_profile.department_id == profile.department_id
        return True
    return False


def _display_name(user):
    profile = getattr(user, "profile", None)
    return profile.display_name if profile and profile.display_name else user.get_full_name() or user.username


def _role_sort_key(profile):
    if profile.role == UserProfile.Role.MANAGER:
        return (0, profile.display_name or profile.user.username)
    return (1, profile.display_name or profile.user.username)


def date_relation(day):
    """How the viewed day relates to today — drives pending vs not-due vs missed labels."""
    today = timezone.localdate()
    if day > today:
        return "future"
    if day < today:
        return "past"
    return "today"


def posting_display(posted, day):
    """Human label for EOD posting state on a given calendar day."""
    if posted:
        return {"key": "posted", "label": "Posted", "css": "posted"}
    rel = date_relation(day)
    if rel == "future":
        return {"key": "not_due", "label": "Not due yet", "css": "not-due"}
    if rel == "past":
        return {"key": "missed", "label": "Not posted", "css": "missed"}
    return {"key": "pending", "label": "Pending", "css": "pending"}


def posting_summary_counts(*, posted, total, day):
    """Aggregate counts with correct labels for past / today / future."""
    not_posted = max(total - posted, 0)
    rel = date_relation(day)
    summary = {
        "posted": posted,
        "total": total,
        "date_relation": rel,
        "pending": 0,
        "not_due": 0,
        "missed": 0,
        "secondary_count": 0,
        "secondary_label": "Still pending",
        "secondary_class": "amber",
    }
    if rel == "future":
        summary["not_due"] = not_posted
        summary["secondary_count"] = not_posted
        summary["secondary_label"] = "Not due yet"
        summary["secondary_class"] = "muted"
    elif rel == "past":
        summary["missed"] = not_posted
        summary["secondary_count"] = not_posted
        summary["secondary_label"] = "Not posted"
        summary["secondary_class"] = "missed"
    else:
        summary["pending"] = not_posted
        summary["secondary_count"] = not_posted
        summary["secondary_label"] = "Still pending"
        summary["secondary_class"] = "amber"
    return summary


def date_context_for(day):
    """Metadata passed to templates and the AI assistant."""
    rel = date_relation(day)
    today = timezone.localdate()
    labels = {
        "future": "Future date — EOD is not due yet; unposted people are not 'pending'.",
        "past": "Past date — anyone without a submitted EOD did not post for that day.",
        "today": "Today — pending means submitted EOD not yet posted.",
    }
    return {
        "relation": rel,
        "today": today.isoformat(),
        "is_future": rel == "future",
        "is_past": rel == "past",
        "is_today": rel == "today",
        "guidance": labels[rel],
    }


def boards_overview(viewer, day):
    """Boss: all boards with headcount and posted count."""
    profile = viewer_profile(viewer)
    dept_ids = accessible_department_ids(profile, viewer)
    boards = []
    for dept in Department.objects.filter(pk__in=dept_ids).annotate(
        member_count=Count("members", filter=Q(members__user__is_active=True)),
    ):
        members = UserProfile.objects.filter(
            department=dept, user__is_active=True
        ).exclude(role=UserProfile.Role.BOSS)
        member_user_ids = list(members.values_list("user_id", flat=True))
        posted = EODReport.objects.filter(
            user_id__in=member_user_ids,
            date=day,
            status=EODReport.Status.SUBMITTED,
        ).values("user_id").distinct().count()
        boards.append({
            "id": dept.id,
            "name": dept.name,
            "member_count": len(member_user_ids),
            "posted_count": posted,
        })
    return [b for b in boards if b["member_count"] > 0]


def board_people(viewer, department_id, day):
    """People in a board with posted status for the date."""
    profile = viewer_profile(viewer)
    if not can_access_department(profile, viewer, department_id):
        return None

    members = (
        UserProfile.objects.filter(
            department_id=department_id,
            user__is_active=True,
        )
        .exclude(role=UserProfile.Role.BOSS)
        .select_related("user")
    )
    members = sorted(members, key=_role_sort_key)

    submitted_ids = set(
        EODReport.objects.filter(
            date=day,
            status=EODReport.Status.SUBMITTED,
            user_id__in=[m.user_id for m in members],
        ).values_list("user_id", flat=True)
    )

    people = []
    for m in members:
        posted = m.user_id in submitted_ids
        display = posting_display(posted, day)
        people.append({
            "user_id": m.user_id,
            "username": m.user.username,
            "name": _display_name(m.user),
            "role": m.role,
            "role_label": m.get_role_display(),
            "posted": posted,
            "status_key": display["key"],
            "status_label": display["label"],
            "status_class": display["css"],
        })
    return people


def person_oversight_detail(viewer, user_id, day):
    """Posted EOD + task breakdown for one person."""
    if not can_view_user_eod(viewer, user_id):
        return None

    try:
        target = User.objects.select_related("profile").get(pk=user_id, is_active=True)
    except User.DoesNotExist:
        return None

    target_profile = getattr(target, "profile", None)
    report = (
        EODReport.objects.filter(
            user=target,
            date=day,
            status=EODReport.Status.SUBMITTED,
        )
        .order_by("-submitted_at")
        .first()
    )

    tasks = Task.objects.filter(user=target, date=day).select_related(
        "assigned_by", "assigned_by__profile"
    ).prefetch_related("blockers")
    working_on = []
    blocked = []
    done = []

    for task in tasks:
        entry = {
            "id": task.id,
            "title": task.title,
            "project": task.project,
            "from_boss": bool(
                task.assigned_by_id
                and getattr(getattr(task.assigned_by, "profile", None), "role", None)
                == UserProfile.Role.BOSS
            ),
        }
        if task.status == Task.Status.DONE:
            done.append(entry)
        elif task.status == Task.Status.BLOCKED:
            blocker = active_blocker(task)
            entry["blocker"] = serialize_blocker(blocker)
            entry["age_label"] = blocker_age_label(blocker) if blocker else None
            blocked.append(entry)
        elif task.status == Task.Status.IN_PROGRESS:
            working_on.append(entry)

    posted = report is not None
    display = posting_display(posted, day)

    return {
        "user_id": target.id,
        "username": target.username,
        "name": _display_name(target),
        "role": target_profile.role if target_profile else UserProfile.Role.EMPLOYEE,
        "role_label": target_profile.get_role_display() if target_profile else "Employee",
        "department": target_profile.department_name if target_profile else "",
        "report": {
            "content": report.content,
            "format": report.format,
            "submitted_at": report.submitted_at.isoformat() if report and report.submitted_at else None,
        } if report else None,
        "working_on": working_on,
        "blocked": blocked,
        "done": done,
        "posted": posted,
        "status_key": display["key"],
        "status_label": display["label"],
        "status_class": display["css"],
    }


def manager_default_department_id(viewer):
    profile = viewer_profile(viewer)
    if is_manager_role(profile) and profile.department_id:
        return profile.department_id
    if viewer.groups.filter(name=MANAGERS_GROUP).exists() and profile.department_id:
        return profile.department_id
    return None


def archive_filter_boards(viewer):
    """Boards the viewer may filter in EOD archive."""
    profile = viewer_profile(viewer)
    dept_ids = accessible_department_ids(profile, viewer)
    return list(Department.objects.filter(pk__in=dept_ids).order_by("name").values("id", "name"))


def archive_filter_people(viewer, board_id=None):
    """People the viewer may filter in EOD archive."""
    profile = viewer_profile(viewer)
    dept_ids = accessible_department_ids(profile, viewer)
    if board_id:
        if not can_access_department(profile, viewer, board_id):
            return []
        dept_ids = [int(board_id)]

    members = (
        UserProfile.objects.filter(
            department_id__in=dept_ids,
            user__is_active=True,
        )
        .exclude(role=UserProfile.Role.BOSS)
        .select_related("user", "department")
        .order_by("department__name", "display_name", "user__username")
    )
    people = []
    for m in members:
        people.append({
            "user_id": m.user_id,
            "username": m.user.username,
            "name": _display_name(m.user),
            "board_id": m.department_id,
            "board_name": m.department.name if m.department_id else "",
            "role_label": m.get_role_display(),
        })
    return people


def eod_archive_entries(
    viewer,
    *,
    board_id=None,
    user_id=None,
    q="",
    days=30,
    limit=50,
):
    """Submitted EODs across accessible boards, newest first."""
    profile = viewer_profile(viewer)
    dept_ids = accessible_department_ids(profile, viewer)
    if not dept_ids:
        return []

    if board_id is not None:
        if not can_access_department(profile, viewer, board_id):
            return []
        dept_ids = [int(board_id)]

    if user_id is not None:
        if not can_view_user_eod(viewer, user_id):
            return []

    since = timezone.localdate() - timedelta(days=max(1, min(int(days), 365)))
    limit = max(1, min(int(limit), 100))

    qs = EODReport.objects.filter(
        status=EODReport.Status.SUBMITTED,
        date__gte=since,
    ).select_related("user", "user__profile", "user__profile__department")

    if user_id is not None:
        qs = qs.filter(user_id=user_id)
    else:
        qs = qs.filter(user__profile__department_id__in=dept_ids).exclude(
            user__profile__role=UserProfile.Role.BOSS,
        )

    q = (q or "").strip()
    if q:
        qs = qs.filter(
            Q(content__icontains=q)
            | Q(user__profile__display_name__icontains=q)
            | Q(user__username__icontains=q)
        )

    qs = qs.order_by("-date", "-submitted_at")[:limit]

    entries = []
    for report in qs:
        member = getattr(report.user, "profile", None)
        entries.append({
            "report_id": report.id,
            "user_id": report.user_id,
            "username": report.user.username,
            "name": _display_name(report.user),
            "role_label": member.get_role_display() if member else "Employee",
            "board_id": member.department_id if member else None,
            "board_name": member.department.name if member and member.department_id else "",
            "date": report.date.isoformat(),
            "date_display": report.date.strftime("%a, %b %d, %Y"),
            "excerpt": _truncate_text(report.content, 180),
            "submitted_at": report.submitted_at.isoformat() if report.submitted_at else None,
        })
    return entries


def _truncate_text(text, limit=420):
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "…"


def _serialize_person_for_ai(detail):
    report = detail.get("report")
    return {
        "name": detail["name"],
        "role": detail["role_label"],
        "department": detail["department"],
        "posted": detail["posted"],
        "eod_excerpt": _truncate_text(report["content"]) if report else None,
        "working_on": [t["title"] for t in detail["working_on"]],
        "blocked": [
            {
                "title": t["title"],
                "note": (t.get("blocker") or {}).get("note"),
                "age": t.get("age_label"),
            }
            for t in detail["blocked"]
        ],
        "done": [t["title"] for t in detail["done"]],
    }


def _people_board_snapshot(viewer, department_id, day):
    try:
        dept = Department.objects.get(pk=department_id)
    except Department.DoesNotExist:
        return None

    people = board_people(viewer, department_id, day)
    if people is None:
        return None

    posted_people = []
    pending_people = []
    not_due_people = []
    missed_people = []
    blockers = []
    working_on = []
    done_today = []
    rel = date_relation(day)

    for person in people:
        if person["posted"]:
            posted_people.append(person["name"])
        elif rel == "future":
            not_due_people.append(person["name"])
        elif rel == "past":
            missed_people.append(person["name"])
        else:
            pending_people.append(person["name"])

        detail = person_oversight_detail(viewer, person["user_id"], day)
        if not detail:
            continue
        for task in detail["blocked"]:
            blockers.append({
                "person": detail["name"],
                "title": task["title"],
                "note": (task.get("blocker") or {}).get("note"),
                "age": task.get("age_label"),
            })
        for task in detail["working_on"]:
            working_on.append({"person": detail["name"], "title": task["title"]})
        for task in detail["done"]:
            done_today.append({"person": detail["name"], "title": task["title"]})

    return {
        "name": dept.name,
        "members": len(people),
        "posted_count": len(posted_people),
        "pending_count": len(pending_people),
        "not_due_count": len(not_due_people),
        "missed_count": len(missed_people),
        "posted_names": posted_people,
        "pending_names": pending_people,
        "not_due_names": not_due_people,
        "missed_names": missed_people,
        "blockers": blockers,
        "working_on": working_on[:25],
        "done_today": done_today[:25],
    }


def build_oversight_snapshot(viewer, day, board_id=None, user_id=None):
    """Structured team data for the oversight AI assistant (role-scoped)."""
    profile = viewer_profile(viewer)
    snapshot = {
        "date": day.isoformat(),
        "viewer_role": "boss" if is_boss(profile) else "manager",
        "date_context": date_context_for(day),
    }

    if user_id:
        if not can_view_user_eod(viewer, user_id):
            return None
        detail = person_oversight_detail(viewer, user_id, day)
        if not detail:
            return None
        snapshot["focus"] = "person"
        snapshot["person"] = _serialize_person_for_ai(detail)
        return snapshot

    if board_id:
        if not can_access_department(profile, viewer, board_id):
            return None
        board = _people_board_snapshot(viewer, board_id, day)
        if not board:
            return None
        snapshot["focus"] = "board"
        snapshot["board"] = board
        return snapshot

    boards = boards_overview(viewer, day)
    board_rows = []
    all_blockers = []
    all_pending = []
    all_not_due = []
    all_missed = []
    total_members = 0
    total_posted = 0
    rel = date_relation(day)

    for board in boards:
        row = _people_board_snapshot(viewer, board["id"], day)
        if not row:
            continue
        total_members += row["members"]
        total_posted += row["posted_count"]
        all_pending.extend({"board": row["name"], "name": n} for n in row["pending_names"])
        all_not_due.extend({"board": row["name"], "name": n} for n in row["not_due_names"])
        all_missed.extend({"board": row["name"], "name": n} for n in row["missed_names"])
        for blocker in row["blockers"]:
            entry = dict(blocker)
            entry["board"] = row["name"]
            all_blockers.append(entry)
        board_rows.append({
            "name": row["name"],
            "members": row["members"],
            "posted_count": row["posted_count"],
            "pending_names": row["pending_names"],
            "not_due_names": row["not_due_names"],
            "missed_names": row["missed_names"],
            "posted_names": row["posted_names"],
        })

    counts = posting_summary_counts(posted=total_posted, total=total_members, day=day)
    snapshot["focus"] = "all_boards"
    snapshot["totals"] = {
        "boards": len(board_rows),
        "members": total_members,
        "posted": total_posted,
        "pending": counts["pending"],
        "not_due": counts["not_due"],
        "missed": counts["missed"],
    }
    snapshot["boards"] = board_rows
    snapshot["pending_people"] = all_pending
    snapshot["not_due_people"] = all_not_due
    snapshot["missed_people"] = all_missed
    snapshot["blockers"] = all_blockers
    return snapshot
