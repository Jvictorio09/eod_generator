"""Team projects for task tagging and insights."""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db.models import Count, Q
from django.utils import timezone

from myApp.models import EODReport, Project, Task, UserProfile, UserProjectProgress
from myApp.services.oversight_service import is_boss, is_manager_role, viewer_profile

User = get_user_model()

DEFAULT_PROJECTS = [
    "airamed",
    "neuromed website",
    "neuromed app",
    "patchwork",
    "mepkin abbey",
]

INSIGHT_WINDOW_DAYS = 30
PROJECTS_CACHE_KEY = "closeout:active_projects"
PROJECTS_CACHE_SECONDS = 120


def ensure_default_projects():
    for name in DEFAULT_PROJECTS:
        Project.objects.get_or_create(name=name)


def serialize_project(project):
    return {
        "id": project.id,
        "name": project.name,
    }


def list_active_projects():
    cached = cache.get(PROJECTS_CACHE_KEY)
    if cached is not None:
        return cached
    data = [serialize_project(p) for p in Project.objects.filter(is_active=True)]
    cache.set(PROJECTS_CACHE_KEY, data, PROJECTS_CACHE_SECONDS)
    return data


def _bust_projects_cache():
    cache.delete(PROJECTS_CACHE_KEY)


def create_project(user, name):
    name = (name or "").strip()
    if not name:
        raise ValueError("name is required")
    if len(name) > 200:
        raise ValueError("name is too long")
    existing = Project.objects.filter(name__iexact=name).first()
    if existing:
        if not existing.is_active:
            existing.is_active = True
            existing.save(update_fields=["is_active"])
            _bust_projects_cache()
        return existing
    project = Project.objects.create(name=name, created_by=user)
    _bust_projects_cache()
    return project


def resolve_project(*, project_id=None, project_name=None):
    if project_id is not None:
        try:
            return Project.objects.get(pk=int(project_id), is_active=True)
        except (Project.DoesNotExist, ValueError, TypeError):
            return None
    name = (project_name or "").strip()
    if not name:
        return None
    return Project.objects.filter(name__iexact=name, is_active=True).first()


def apply_project_fields(task, *, project_id=None, project_name=None, clear=False):
    """Set project_ref and mirrored project string on a task."""
    if clear:
        task.project_ref = None
        task.project = ""
        return task

    project = resolve_project(project_id=project_id, project_name=project_name)
    if project:
        task.project_ref = project
        task.project = project.name
        return task

    if project_id is not None:
        task.project_ref = None
        task.project = ""
        return task

    if project_name is not None:
        task.project_ref = None
        task.project = (project_name or "").strip()
    return task


def insight_user_ids(viewer):
    profile = viewer_profile(viewer)
    if is_boss(profile):
        return list(
            User.objects.filter(is_active=True)
            .exclude(profile__role=UserProfile.Role.BOSS)
            .values_list("pk", flat=True)
        )
    if is_manager_role(profile) and profile.department_id:
        return list(
            UserProfile.objects.filter(
                department_id=profile.department_id,
                user__is_active=True,
            )
            .exclude(role=UserProfile.Role.BOSS)
            .values_list("user_id", flat=True)
        )
    return [viewer.pk]


def project_insights(viewer, *, days=INSIGHT_WINDOW_DAYS):
    profile = viewer_profile(viewer)
    today = timezone.localdate()
    start = today - timedelta(days=days - 1)
    team_scope = profile.has_oversight_access()
    user_ids = insight_user_ids(viewer) if team_scope else [viewer.pk]

    counts = {
        row["project_ref_id"]: row
        for row in (
            Task.objects.filter(
                user_id__in=user_ids,
                date__gte=start,
                date__lte=today,
                project_ref__isnull=False,
            )
            .values("project_ref_id")
            .annotate(
                total=Count("id"),
                done=Count("id", filter=Q(status=Task.Status.DONE)),
                in_progress=Count("id", filter=Q(status=Task.Status.IN_PROGRESS)),
                blocked=Count("id", filter=Q(status=Task.Status.BLOCKED)),
                tomorrow=Count("id", filter=Q(status=Task.Status.TOMORROW)),
            )
        )
    }

    projects = []
    for project in Project.objects.filter(is_active=True):
        row = counts.get(project.id, {})
        projects.append({
            "id": project.id,
            "name": project.name,
            "total": row.get("total", 0),
            "done": row.get("done", 0),
            "in_progress": row.get("in_progress", 0),
            "blocked": row.get("blocked", 0),
            "tomorrow": row.get("tomorrow", 0),
        })
    projects.sort(key=lambda item: (-item["total"], item["name"].lower()))

    return {
        "window_days": days,
        "scope": "team" if team_scope else "personal",
        "projects": projects,
    }


def _display_name(user):
    profile = getattr(user, "profile", None)
    return profile.display_name if profile and profile.display_name else user.username


def user_self_progress_map(user_ids):
    """Map (user_id, project_id) -> percent for active projects."""
    if not user_ids:
        return {}
    rows = UserProjectProgress.objects.filter(
        user_id__in=user_ids,
        project__is_active=True,
    ).values_list("user_id", "project_id", "percent")
    return {(uid, pid): pct for uid, pid, pct in rows}


def list_user_project_progress(user):
    """Self-reported % for every active project."""
    saved = {
        row.project_id: row.percent
        for row in UserProjectProgress.objects.filter(user=user, project__is_active=True)
    }
    return [
        {
            "project_id": project["id"],
            "name": project["name"],
            "percent": saved.get(project["id"], 0),
        }
        for project in list_active_projects()
    ]


def projects_from_tasks(user, day):
    """Unique projects referenced on a user's tasks for a given day."""
    tasks = Task.objects.filter(user=user, date=day).select_related("project_ref")
    seen = {}
    for task in tasks:
        if task.project_ref_id:
            seen[f"id:{task.project_ref_id}"] = {
                "project_id": task.project_ref_id,
                "name": task.project_ref.name,
            }
        else:
            name = (task.project or "").strip()
            if name:
                seen[f"name:{name.lower()}"] = {
                    "project_id": None,
                    "name": name,
                }
    rows = list(seen.values())
    rows.sort(key=lambda row: row["name"].lower())
    return rows


def prefill_project_progress(user, day, projects):
    """Merge task projects with saved draft/submitted EOD or latest self-reported %."""
    saved = {
        row.project_id: row.percent
        for row in UserProjectProgress.objects.filter(user=user, project__is_active=True)
    }
    report = EODReport.objects.filter(user=user, date=day).first()
    report_map = {}
    if report and report.project_progress:
        for item in report.project_progress:
            pid = item.get("project_id")
            if pid:
                report_map[pid] = item.get("percent", 0)

    rows = []
    for project in projects:
        pid = project.get("project_id")
        percent = 0
        if pid and pid in report_map:
            percent = report_map[pid]
        elif pid and pid in saved:
            percent = saved[pid]
        rows.append({**project, "percent": max(0, min(int(percent or 0), 100))})
    return rows


def normalize_project_progress(entries):
    if not isinstance(entries, list):
        return []
    cleaned = []
    for item in entries:
        if not isinstance(item, dict):
            continue
        name = (item.get("name") or "").strip()
        if not name:
            continue
        try:
            percent = int(item.get("percent", 0))
        except (TypeError, ValueError):
            percent = 0
        percent = max(0, min(percent, 100))
        pid = item.get("project_id")
        cleaned.append({
            "project_id": int(pid) if pid else None,
            "name": name,
            "percent": percent,
        })
    return cleaned


def persist_eod_project_progress(user, report, entries):
    """Save progress snapshot on the EOD and sync latest % for oversight views."""
    progress = normalize_project_progress(entries)
    report.project_progress = progress
    report.save(update_fields=["project_progress"])
    for item in progress:
        if item["project_id"]:
            set_user_project_progress(user, project_id=item["project_id"], percent=item["percent"])
    return progress


def set_user_project_progress(user, *, project_id, percent):
    try:
        percent = int(percent)
    except (TypeError, ValueError):
        raise ValueError("percent must be a number")
    percent = max(0, min(percent, 100))
    try:
        project = Project.objects.get(pk=int(project_id), is_active=True)
    except (Project.DoesNotExist, ValueError, TypeError):
        raise ValueError("Invalid project")
    row, _ = UserProjectProgress.objects.update_or_create(
        user=user,
        project=project,
        defaults={"percent": percent},
    )
    return {
        "project_id": project.id,
        "name": project.name,
        "percent": row.percent,
    }


def project_eod_insights(viewer, *, days=INSIGHT_WINDOW_DAYS):
    """Completion % per project from tasks on days each employee posted an EOD."""
    profile = viewer_profile(viewer)
    today = timezone.localdate()
    start = today - timedelta(days=days - 1)
    user_ids = insight_user_ids(viewer)
    team_scope = profile.has_oversight_access()

    eod_days = set(
        EODReport.objects.filter(
            user_id__in=user_ids,
            status=EODReport.Status.SUBMITTED,
            date__gte=start,
            date__lte=today,
        ).values_list("user_id", "date")
    )
    if not eod_days:
        return {
            "window_days": days,
            "scope": "team" if team_scope else "personal",
            "projects": [],
        }

    self_progress = user_self_progress_map(user_ids)

    tasks = (
        Task.objects.filter(
            user_id__in=user_ids,
            date__gte=start,
            date__lte=today,
        )
        .filter(Q(project_ref__isnull=False) | ~Q(project=""))
        .select_related("project_ref", "user", "user__profile")
    )

    projects_acc = {}
    for task in tasks:
        if (task.user_id, task.date) not in eod_days:
            continue
        if task.project_ref_id:
            key = f"id:{task.project_ref_id}"
            name = task.project_ref.name
            pid = task.project_ref_id
        else:
            name = (task.project or "").strip()
            if not name:
                continue
            key = f"name:{name.lower()}"
            pid = None

        bucket = projects_acc.setdefault(
            key,
            {"id": pid, "name": name, "done": 0, "total": 0, "employees": {}},
        )
        is_done = task.status == Task.Status.DONE
        bucket["total"] += 1
        if is_done:
            bucket["done"] += 1

        emp = bucket["employees"].setdefault(
            task.user_id,
            {"user_id": task.user_id, "name": _display_name(task.user), "done": 0, "total": 0},
        )
        emp["total"] += 1
        if is_done:
            emp["done"] += 1

    projects = []
    for bucket in projects_acc.values():
        total = bucket["total"]
        done = bucket["done"]
        employees = []
        for emp in bucket["employees"].values():
            emp_total = emp["total"]
            self_pct = None
            if bucket["id"]:
                self_pct = self_progress.get((emp["user_id"], bucket["id"]))
            employees.append({
                **emp,
                "pct": round(emp["done"] * 100 / emp_total) if emp_total else 0,
                "self_pct": self_pct,
            })
        employees.sort(key=lambda row: (-row["pct"], row["name"].lower()))
        projects.append({
            "id": bucket["id"],
            "name": bucket["name"],
            "total": total,
            "done": done,
            "pct": round(done * 100 / total) if total else 0,
            "self_pct": self_progress.get((viewer.pk, bucket["id"])) if bucket["id"] else None,
            "employees": employees,
        })
    projects.sort(key=lambda row: (-row["pct"], -row["total"], row["name"].lower()))

    return {
        "window_days": days,
        "scope": "team" if team_scope else "personal",
        "projects": projects,
    }
