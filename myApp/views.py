import json
from datetime import datetime
from urllib.parse import urlencode

from django.conf import settings
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import Group, User
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from myApp.models import Blocker, Department, EODReport, EODReportArchive, Task, UserProfile
from myApp.services.ai import (
    AIError,
    generate_oversight_summary,
    generate_week_review,
    oversight_assistant_chat,
    parse_braindump,
)
from myApp.services.notifications import (
    mark_notifications_read,
    notify_task_assigned,
    notify_unblocker,
    unread_notifications,
)
from myApp.services.oversight_service import (
    archive_filter_boards,
    archive_filter_people,
    board_people,
    boards_overview,
    build_oversight_snapshot,
    can_access_department,
    can_assign_task_to_user,
    can_view_user_eod,
    date_context_for,
    eod_archive_entries,
    format_oversight_summary_from_snapshot,
    is_boss,
    is_manager_role,
    manager_default_department_id,
    person_oversight_detail,
    posting_display,
    posting_summary_counts,
    user_has_oversight,
    viewer_profile,
)
from myApp.services.project_service import (
    apply_project_fields,
    create_project,
    list_active_projects,
    list_user_project_progress,
    project_insights,
    project_eod_insights,
    set_user_project_progress,
)
from myApp.services.report_service import (
    consistency_stats,
    create_and_store_report,
    report_content_for_display,
    report_preview,
    search_content,
    serialize_archive_summary,
    serialize_history_entries,
    serialize_profile_prefs,
    serialize_report_summary,
    submit_eod,
    submitted_history_entries,
    week_review_payload,
    wins_archive,
)
from myApp.services.workspace_service import build_workspace_bootstrap
from myApp.services.task_service import (
    attach_blocker,
    clear_blockers,
    get_or_create_profile,
    rollover_tomorrow_tasks,
    serialize_task,
    stale_in_progress_tasks,
    tasks_for_report,
)

MANAGERS_GROUP = "Managers"


def _json_body(request):
    try:
        return json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return None


def _parse_date(value):
    if not value:
        return timezone.localdate()
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def _clamp_oversight_day(day):
    """EOD oversight only applies through today — never treat future days as pending."""
    today = timezone.localdate()
    if day > today:
        return today, True
    return day, False


def _require_manager(user):
    """Oversight access: MANAGER/BOSS role, or legacy Managers group / staff."""
    return user_has_oversight(user)


def _is_oversight_role(user):
    profile = get_or_create_profile(user)
    return profile.role in (UserProfile.Role.MANAGER, UserProfile.Role.BOSS)


def _is_boss_user(user):
    profile = get_or_create_profile(user)
    return profile.role == UserProfile.Role.BOSS


def _authenticate_login(request, username, password):
    """Authenticate with case-insensitive username lookup."""
    username = (username or "").strip()
    if not username:
        return None
    match = User.objects.filter(username__iexact=username).first()
    if not match:
        return None
    return authenticate(request, username=match.username, password=password)


def _registration_open():
    return getattr(settings, "ALLOW_PUBLIC_REGISTRATION", True)


def _registration_departments():
    return Department.objects.order_by("name")


def _username_available(username):
    username = (username or "").strip()
    if not username:
        return False
    return not User.objects.filter(username__iexact=username).exists()


def _safe_employee_next(next_url):
    """Employees must not be sent to the oversight dashboard after login."""
    if not next_url:
        return None
    path = next_url.split("?")[0].rstrip("/") or "/"
    if path in ("/dashboard", "/login", "/oversight/login"):
        return None
    return next_url


def _employee_landing_redirect(user, next_url=None):
    if next_url:
        return redirect(_safe_employee_next(next_url) or "home")
    return redirect("home")


def _oversight_landing_redirect(user, next_url=None):
    if next_url:
        return redirect(next_url)
    return redirect("dashboard")


@login_required
@ensure_csrf_cookie
def home(request):
    if _is_boss_user(request.user):
        return redirect("dashboard")
    bootstrap = build_workspace_bootstrap(request.user)
    return render(
        request,
        "index.html",
        {
            "initial_profile_json": json.dumps(_profile_api_payload(request.user)),
            "initial_projects_json": json.dumps(bootstrap["projects"]),
            "initial_workspace_json": json.dumps(bootstrap),
        },
    )


@login_required
@ensure_csrf_cookie
def eod_history_page(request):
    """Employee workspace — full list of past EOD reports."""
    if _is_boss_user(request.user):
        return redirect("dashboard")
    profile = get_or_create_profile(request.user)
    return render(
        request,
        "history.html",
        {
            "display_name": profile.display_name or request.user.username,
            "username": request.user.username,
            "is_boss": _is_boss_user(request.user),
            "is_manager": user_has_oversight(request.user),
        },
    )


@ensure_csrf_cookie
def login_view(request):
    """Employee portal — EMPLOYEE role only. Root URL shows this page."""
    if request.user.is_authenticated and not _is_boss_user(request.user):
        return _employee_landing_redirect(request.user, _safe_employee_next(request.GET.get("next")))
    error = ""
    msg = request.GET.get("msg", "")
    logged_in_boss = request.user.is_authenticated and _is_boss_user(request.user)
    if request.method == "POST" and not logged_in_boss:
        username = request.POST.get("username", "").strip()
        password = request.POST.get("password", "")
        user = _authenticate_login(request, username, password)
        if user is not None:
            profile = get_or_create_profile(user)
            if profile.role == UserProfile.Role.BOSS:
                error = "This account uses oversight sign-in. Go to /oversight/login/"
            else:
                login(request, user)
                return _employee_landing_redirect(user, _safe_employee_next(request.GET.get("next")))
        else:
            error = "Invalid username or password."
    return render(
        request,
        "login.html",
        {
            "error": error,
            "msg": msg,
            "logged_in_boss": logged_in_boss,
            "registration_enabled": _registration_open() and _registration_departments().exists(),
        },
    )


@ensure_csrf_cookie
def register_view(request):
    """Employee self-registration — EMPLOYEE role only, existing department required."""
    if not _registration_open():
        return redirect("login")

    if request.user.is_authenticated:
        if _is_boss_user(request.user):
            return redirect("dashboard")
        return redirect("home")

    departments = list(_registration_departments())
    error = ""
    form = {
        "username": "",
        "display_name": "",
        "department_id": "",
    }

    if not departments:
        return render(
            request,
            "register.html",
            {
                "error": "No teams are open for sign-up yet. Ask your manager to set up your board.",
                "departments": departments,
                "form": form,
                "disabled": True,
            },
        )

    if request.method == "POST":
        username = request.POST.get("username", "").strip()
        display_name = request.POST.get("display_name", "").strip()
        password = request.POST.get("password", "")
        password2 = request.POST.get("password2", "")
        department_id = request.POST.get("department_id", "").strip()
        form.update({
            "username": username,
            "display_name": display_name,
            "department_id": department_id,
        })

        if not username:
            error = "Choose a username."
        elif not _username_available(username):
            error = "That username is already taken."
        elif not department_id:
            error = "Select your team."
        elif password != password2:
            error = "Passwords do not match."
        else:
            try:
                department = Department.objects.get(pk=department_id)
            except (Department.DoesNotExist, ValueError):
                error = "Select a valid team."
            else:
                candidate = User(username=username)
                try:
                    validate_password(password, user=candidate)
                except ValidationError as exc:
                    error = " ".join(exc.messages)
                else:
                    user = User.objects.create_user(username=username, password=password)
                    user.is_staff = False
                    user.is_superuser = False
                    user.save()
                    profile = get_or_create_profile(user)
                    profile.role = UserProfile.Role.EMPLOYEE
                    profile.department = department
                    profile.display_name = display_name or username
                    profile.save()
                    login(request, user)
                    return _employee_landing_redirect(user)

    return render(
        request,
        "register.html",
        {
            "error": error,
            "departments": departments,
            "form": form,
            "disabled": False,
        },
    )


@ensure_csrf_cookie
def oversight_login_view(request):
    """Oversight portal — MANAGER and BOSS only."""
    if request.user.is_authenticated:
        if not user_has_oversight(request.user):
            return redirect("home")
        return _oversight_landing_redirect(request.user, request.GET.get("next"))
    error = request.GET.get("error", "")
    if request.method == "POST":
        username = request.POST.get("username", "").strip()
        password = request.POST.get("password", "")
        user = _authenticate_login(request, username, password)
        if user is not None:
            if not user_has_oversight(user):
                error = "Employee accounts sign in at the home page (/)."
            else:
                login(request, user)
                return _oversight_landing_redirect(user, request.GET.get("next"))
        else:
            error = "Invalid username or password."
    return render(request, "oversight_login.html", {"error": error})


def logout_view(request):
    oversight = request.user.is_authenticated and user_has_oversight(request.user)
    logout(request)
    return redirect("oversight_login" if oversight else "login")


def csrf_failure(request, reason=""):
    """Re-render sign-in pages with a fresh token instead of a bare 403."""
    path = request.path.rstrip("/") or "/"
    if path in ("/login", ""):
        return render(
            request,
            "login.html",
            {"error": "Session expired — please sign in again.", "msg": ""},
            status=200,
        )
    if path == "/oversight/login":
        return render(
            request,
            "oversight_login.html",
            {"error": "Session expired — please sign in again."},
            status=200,
        )
    from django.views.csrf import csrf_failure as default_csrf_failure

    return default_csrf_failure(request, reason=reason)


def _archive_filters_from_request(request):
    """Archive list filters preserved when drilling into a report."""
    filters = {"days": 30, "q": "", "board_id": None, "user_id": None}
    try:
        filters["days"] = int(request.GET.get("archive_days", 30))
    except (TypeError, ValueError):
        pass
    filters["days"] = max(7, min(filters["days"], 90))
    filters["q"] = (request.GET.get("archive_q") or "").strip()
    if request.GET.get("archive_board"):
        try:
            filters["board_id"] = int(request.GET.get("archive_board"))
        except (TypeError, ValueError):
            pass
    if request.GET.get("archive_user"):
        try:
            filters["user_id"] = int(request.GET.get("archive_user"))
        except (TypeError, ValueError):
            pass
    return filters


def _archive_list_url(filters):
    params = {"view": "archive", "days": filters["days"]}
    if filters["q"]:
        params["q"] = filters["q"]
    if filters["board_id"]:
        params["board"] = filters["board_id"]
    if filters["user_id"]:
        params["user"] = filters["user_id"]
    return f"{reverse('dashboard')}?{urlencode(params)}"


def _archive_report_url(entry, filters):
    """Person drill-down URL that can return to the archive."""
    params = {
        "date": entry["date"],
        "user": entry["user_id"],
        "from": "archive",
        "archive_days": filters["days"],
    }
    if entry.get("board_id"):
        params["board"] = entry["board_id"]
    if filters["q"]:
        params["archive_q"] = filters["q"]
    if filters["board_id"]:
        params["archive_board"] = filters["board_id"]
    if filters["user_id"]:
        params["archive_user"] = filters["user_id"]
    return f"{reverse('dashboard')}?{urlencode(params)}"


def _archive_nav_urls(request, viewer, day, user_id):
    """Previous / next submitted EOD within the current archive filter set."""
    filters = _archive_filters_from_request(request)
    entries = eod_archive_entries(
        viewer,
        board_id=filters["board_id"],
        user_id=filters["user_id"],
        q=filters["q"],
        days=filters["days"],
        limit=50,
    )
    day_iso = day.isoformat()
    index = next(
        (i for i, e in enumerate(entries) if e["user_id"] == user_id and e["date"] == day_iso),
        None,
    )
    if index is None:
        return None, None, _archive_list_url(filters)
    prev_url = _archive_report_url(entries[index - 1], filters) if index > 0 else None
    next_url = _archive_report_url(entries[index + 1], filters) if index < len(entries) - 1 else None
    return prev_url, next_url, _archive_list_url(filters)


def _parse_time(value):
    if not value:
        return None
    try:
        return datetime.strptime(value, "%H:%M").time()
    except ValueError:
        try:
            return datetime.strptime(value, "%H:%M:%S").time()
        except ValueError:
            return None


def _profile_api_payload(user):
    profile = get_or_create_profile(user)
    data = serialize_profile_prefs(profile)
    data["username"] = user.username
    data["is_manager"] = user_has_oversight(user)
    data["has_oversight"] = profile.has_oversight_access()
    data["role"] = profile.role
    return data


@login_required
@require_GET
def api_workspace_bootstrap(request):
    day = _parse_date(request.GET.get("date")) or timezone.localdate()
    return JsonResponse(build_workspace_bootstrap(request.user, day))


@login_required
@require_GET
def api_profile(request):
    return JsonResponse(_profile_api_payload(request.user))


@login_required
@require_http_methods(["PATCH", "POST"])
def api_profile_update(request):
    payload = _json_body(request)
    if payload is None:
        return JsonResponse({"error": "Invalid JSON"}, status=400)
    profile = get_or_create_profile(request.user)
    field_map = {
        "display_name": "display_name",
        "ai_model": "ai_model",
        "style_guide": "style_guide",
        "timezone": "timezone",
        "default_format": "default_format",
        "default_tone": "default_tone",
        "default_length": "default_length",
    }
    for key, attr in field_map.items():
        if key in payload:
            setattr(profile, attr, (payload[key] or "").strip() if key != "style_guide" else (payload[key] or ""))
    if "department_id" in payload:
        dept_id = payload["department_id"]
        if dept_id:
            try:
                profile.department = Department.objects.get(pk=dept_id)
            except Department.DoesNotExist:
                return JsonResponse({"error": "Invalid department"}, status=400)
        else:
            profile.department = None
    if "auto_send_enabled" in payload:
        profile.auto_send_enabled = bool(payload["auto_send_enabled"])
    for time_key in ("auto_send_time", "quiet_hours_start", "quiet_hours_end"):
        if time_key in payload:
            setattr(profile, time_key, _parse_time(payload[time_key]))
    profile.save()
    return JsonResponse({"ok": True})


@login_required
@require_GET
def api_users(request):
    users = User.objects.filter(is_active=True).select_related("profile").order_by("username")
    data = []
    for u in users:
        profile = getattr(u, "profile", None)
        data.append({
            "id": u.id,
            "username": u.username,
            "display_name": profile.display_name if profile else u.get_full_name() or u.username,
        })
    return JsonResponse({"users": data})


@login_required
@require_http_methods(["GET", "POST"])
def api_tasks(request):
    if request.method == "GET":
        day = _parse_date(request.GET.get("date"))
        if day is None:
            return JsonResponse({"error": "Invalid date"}, status=400)

        rolled = 0
        if day == timezone.localdate():
            rolled = rollover_tomorrow_tasks(request.user, day)

        tasks = Task.objects.filter(user=request.user, date=day).select_related(
            "assigned_by", "assigned_by__profile", "project_ref"
        ).prefetch_related("blockers")
        stale = [
            serialize_task(t, include_stale=True)
            for t in stale_in_progress_tasks(request.user, day)
        ]
        return JsonResponse({
            "date": day.isoformat(),
            "rolled_count": rolled,
            "tasks": [serialize_task(t, include_stale=True) for t in tasks],
            "stale_elsewhere": stale,
        })

    payload = _json_body(request)
    if payload is None:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    title = (payload.get("title") or "").strip()
    if not title:
        return JsonResponse({"error": "title is required"}, status=400)

    day = _parse_date(payload.get("date")) or timezone.localdate()
    status = payload.get("status") or Task.Status.IN_PROGRESS
    if status not in Task.Status.values:
        status = Task.Status.IN_PROGRESS

    task = Task.objects.create(
        user=request.user,
        date=day,
        title=title,
        status=status,
    )
    apply_project_fields(
        task,
        project_id=payload.get("project_id"),
        project_name=payload.get("project"),
    )
    task.save()
    return JsonResponse({"task": serialize_task(task)}, status=201)


@login_required
@require_http_methods(["PATCH", "DELETE"])
def api_task_detail(request, task_id):
    try:
        task = Task.objects.get(pk=task_id, user=request.user)
    except Task.DoesNotExist:
        return JsonResponse({"error": "Not found"}, status=404)

    if request.method == "DELETE":
        task.delete()
        return JsonResponse({"ok": True})

    payload = _json_body(request)
    if payload is None:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    if "title" in payload:
        task.title = (payload["title"] or "").strip()
    if "project_id" in payload or "project" in payload:
        apply_project_fields(
            task,
            project_id=payload.get("project_id"),
            project_name=payload.get("project") if "project" in payload else None,
            clear=("project_id" in payload and not payload.get("project_id") and "project" not in payload),
        )
    if "status" in payload and payload["status"] in Task.Status.values:
        new_status = payload["status"]
        if new_status != Task.Status.BLOCKED:
            clear_blockers(task)
        task.status = new_status
    task.save()
    task.refresh_from_db()
    return JsonResponse({"task": serialize_task(task)})


@login_required
@require_POST
def api_task_mark_blocked(request, task_id):
    """One-click stale nudge: convert IN_PROGRESS → BLOCKED."""
    try:
        task = Task.objects.get(pk=task_id, user=request.user)
    except Task.DoesNotExist:
        return JsonResponse({"error": "Not found"}, status=404)

    payload = _json_body(request) or {}
    task.status = Task.Status.BLOCKED
    task.save(update_fields=["status", "updated_at"])

    note = (payload.get("note") or "Marked blocked from stale-task nudge").strip()
    blocker = attach_blocker(
        task,
        kind=Blocker.Kind.BLOCKED,
        note=note,
    )
    notify_unblocker(blocker)
    return JsonResponse({"task": serialize_task(task)})


@login_required
@require_http_methods(["POST", "DELETE"])
def api_task_blocker(request, task_id):
    try:
        task = Task.objects.get(pk=task_id, user=request.user)
    except Task.DoesNotExist:
        return JsonResponse({"error": "Not found"}, status=404)

    if request.method == "DELETE":
        clear_blockers(task)
        task.refresh_from_db()
        return JsonResponse({"task": serialize_task(task)})

    payload = _json_body(request)
    if payload is None:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    clear_blockers(task)
    kind = payload.get("kind") or Blocker.Kind.BLOCKED
    if kind not in Blocker.Kind.values:
        kind = Blocker.Kind.BLOCKED

    unblocker_id = payload.get("unblocker_id")
    if unblocker_id:
        try:
            User.objects.get(pk=unblocker_id, is_active=True)
        except User.DoesNotExist:
            return JsonResponse({"error": "Invalid unblocker"}, status=400)

    blocker = attach_blocker(
        task,
        kind=kind,
        unblocker_id=unblocker_id,
        dependency_text=payload.get("dependency_text") or "",
        note=payload.get("note") or "",
    )
    notify_unblocker(blocker)
    task.refresh_from_db()
    return JsonResponse({"task": serialize_task(task)})


@login_required
@require_POST
def api_tasks_bulk(request):
    payload = _json_body(request)
    if payload is None:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    items = payload.get("tasks")
    if not isinstance(items, list):
        return JsonResponse({"error": "tasks array required"}, status=400)

    day = _parse_date(payload.get("date")) or timezone.localdate()
    created = []
    for item in items:
        title = (item.get("title") or "").strip()
        if not title:
            continue
        status = item.get("status") or Task.Status.IN_PROGRESS
        if status not in Task.Status.values:
            status = Task.Status.IN_PROGRESS
        task = Task.objects.create(
            user=request.user,
            date=day,
            title=title,
            status=status,
        )
        apply_project_fields(
            task,
            project_id=item.get("project_id"),
            project_name=item.get("project"),
        )
        task.save()
        created.append(serialize_task(task))
    return JsonResponse({"tasks": created}, status=201)


@login_required
@require_POST
def api_tasks_clear(request):
    payload = _json_body(request) or {}
    day = _parse_date(payload.get("date")) or timezone.localdate()
    qs = Task.objects.filter(user=request.user, date=day)
    if payload.get("keep_assigned"):
        qs = qs.filter(assigned_by__isnull=True)
    deleted, _ = qs.delete()
    return JsonResponse({"deleted": deleted})


@login_required
@require_POST
def braindump(request):
    payload = _json_body(request)
    if payload is None:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    text = (payload.get("text") or "").strip()
    if not text:
        return JsonResponse({"error": "text is required"}, status=400)

    profile = get_or_create_profile(request.user)
    try:
        parsed = parse_braindump(text, model=profile.ai_model)
    except AIError as exc:
        return JsonResponse({"error": str(exc)}, status=502)

    cleaned = []
    for item in parsed:
        if not isinstance(item, dict):
            continue
        title = (item.get("title") or "").strip()
        if not title:
            continue
        status = item.get("status") or Task.Status.IN_PROGRESS
        if status not in Task.Status.values:
            status = Task.Status.IN_PROGRESS
        cleaned.append({"title": title, "status": status})

    return JsonResponse({"drafts": cleaned})


@login_required
@require_POST
def generate_eod_report_view(request):
    payload = _json_body(request) or {}
    profile = get_or_create_profile(request.user)
    day = _parse_date(payload.get("date")) or timezone.localdate()

    report_format = (payload.get("format") or profile.default_format or "PLAIN").strip()
    tone = (payload.get("tone") or profile.default_tone or "professional").strip()
    length = (payload.get("length") or profile.default_length or "standard").strip()
    model = (payload.get("model") or profile.ai_model or "gpt-4o-mini").strip()

    if not Task.objects.filter(user=request.user, date=day).exists():
        return JsonResponse({"error": "No tasks for this day"}, status=400)

    try:
        report = create_and_store_report(
            request.user,
            day,
            report_format=report_format,
            tone=tone,
            length=length,
            model=model,
            project_progress=payload.get("project_progress"),
        )
    except AIError as exc:
        return JsonResponse({"error": str(exc)}, status=502)

    from myApp.services.report_service import report_display_content

    return JsonResponse({
        "report": report_display_content(report),
        "report_id": report.id,
        "format": report.format,
        "status": report.status,
        "project_progress": report.project_progress or [],
    })


@login_required
@require_POST
def api_eod_submit(request):
    payload = _json_body(request) or {}
    profile = get_or_create_profile(request.user)
    day = _parse_date(payload.get("date")) or timezone.localdate()

    report_format = (payload.get("format") or profile.default_format or "PLAIN").strip()
    tone = (payload.get("tone") or profile.default_tone or "professional").strip()
    length = (payload.get("length") or profile.default_length or "standard").strip()
    model = (payload.get("model") or profile.ai_model or "gpt-4o-mini").strip()

    try:
        report = submit_eod(
            request.user,
            day,
            content=(payload.get("content") or "").strip() or None,
            report_format=report_format,
            tone=tone,
            length=length,
            model=model,
            project_progress=payload.get("project_progress"),
        )
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    except AIError as exc:
        return JsonResponse({"error": str(exc)}, status=502)

    return JsonResponse({
        "ok": True,
        "report_id": report.id,
        "status": report.status,
        "submitted_at": report.submitted_at.isoformat() if report.submitted_at else None,
        "content": report_content_for_display(report),
    })


@login_required
@require_GET
def api_insights_consistency(request):
    return JsonResponse(consistency_stats(request.user))


@login_required
@require_GET
def api_insights_wins(request):
    return JsonResponse({"wins": wins_archive(request.user)})


@login_required
@require_GET
def api_projects(request):
    return JsonResponse({"projects": list_active_projects()})


@login_required
@require_POST
def api_projects_create(request):
    profile = viewer_profile(request.user)
    if not is_boss(profile):
        return HttpResponseForbidden("Only the boss can add projects.")
    payload = _json_body(request)
    if payload is None:
        return JsonResponse({"error": "Invalid JSON"}, status=400)
    try:
        project = create_project(request.user, payload.get("name"))
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    return JsonResponse({"project": {"id": project.id, "name": project.name}}, status=201)


@login_required
@require_GET
def api_insights_projects(request):
    days = 30
    try:
        days = int(request.GET.get("days", 30))
    except (TypeError, ValueError):
        days = 30
    days = max(7, min(days, 90))
    return JsonResponse(project_insights(request.user, days=days))


@login_required
@require_GET
def api_insights_projects_eod(request):
    days = 30
    try:
        days = int(request.GET.get("days", 30))
    except (TypeError, ValueError):
        days = 30
    days = max(7, min(days, 90))
    return JsonResponse(project_eod_insights(request.user, days=days))


@login_required
@require_http_methods(["GET", "PUT"])
def api_project_self_progress(request):
    if request.method == "GET":
        return JsonResponse({"projects": list_user_project_progress(request.user)})

    payload = _json_body(request)
    if payload is None:
        return JsonResponse({"error": "Invalid JSON"}, status=400)
    try:
        row = set_user_project_progress(
            request.user,
            project_id=payload.get("project_id"),
            percent=payload.get("percent"),
        )
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    return JsonResponse({"project": row})


@login_required
@require_POST
def api_week_review(request):
    profile = get_or_create_profile(request.user)
    payload = week_review_payload(request.user)
    name = profile.display_name or request.user.username
    try:
        review = generate_week_review(
            name=name,
            week_payload=payload,
            model=profile.ai_model,
        )
    except AIError as exc:
        return JsonResponse({"error": str(exc)}, status=502)
    return JsonResponse({"review": review})


@login_required
@require_GET
def api_search(request):
    q = request.GET.get("q", "")
    team = request.GET.get("team") == "1"
    if team and not _require_manager(request.user):
        return HttpResponseForbidden("Manager access required.")
    return JsonResponse(search_content(request.user, q, team=team, viewer=request.user))


@login_required
@require_GET
def api_reports_history(request):
    limit = min(int(request.GET.get("limit", 20)), 50)
    status = (request.GET.get("status") or "").strip().upper()
    if status == EODReport.Status.DRAFT:
        reports = (
            EODReport.objects.filter(user=request.user, status=EODReport.Status.DRAFT)
            .select_related("user", "user__profile")
            .order_by("-date", "-created_at")[:limit]
        )
        return JsonResponse({
            "reports": [serialize_report_summary(r) for r in reports],
        })
    entries = submitted_history_entries(request.user, limit=limit)
    return JsonResponse({
        "reports": serialize_history_entries(entries),
    })


@login_required
@require_http_methods(["GET", "DELETE"])
def api_report_detail(request, report_id):
    try:
        report = EODReport.objects.get(pk=report_id)
    except EODReport.DoesNotExist:
        return JsonResponse({"error": "Not found"}, status=404)
    if report.user_id != request.user.id:
        if not can_view_user_eod(request.user, report.user_id):
            return JsonResponse({"error": "Not found"}, status=404)
        if report.status != EODReport.Status.SUBMITTED:
            return JsonResponse({"error": "Not found"}, status=404)

    if request.method == "DELETE":
        if report.user_id != request.user.id:
            return JsonResponse({"error": "Not found"}, status=404)
        report.delete()
        return JsonResponse({"ok": True})

    return JsonResponse({
        "id": report.id,
        "date": report.date.isoformat(),
        "format": report.format,
        "content": report.content,
        "status": report.status,
        "author_username": report.user.username,
        "author_name": (
            report.user.profile.display_name
            if getattr(report.user, "profile", None) and report.user.profile.display_name
            else report.user.username
        ),
        "created_at": report.created_at.isoformat(),
        "is_archive": False,
    })


@login_required
@require_http_methods(["GET", "DELETE"])
def api_report_archive_detail(request, archive_id):
    try:
        archive = EODReportArchive.objects.select_related("user", "user__profile").get(pk=archive_id)
    except EODReportArchive.DoesNotExist:
        return JsonResponse({"error": "Not found"}, status=404)
    if archive.user_id != request.user.id:
        return JsonResponse({"error": "Not found"}, status=404)

    if request.method == "DELETE":
        archive.delete()
        return JsonResponse({"ok": True})

    return JsonResponse({
        "id": f"a{archive.id}",
        "date": archive.log_date.isoformat(),
        "format": archive.format,
        "content": archive.content,
        "status": EODReport.Status.SUBMITTED,
        "author_username": archive.user.username,
        "author_name": (
            archive.user.profile.display_name
            if getattr(archive.user, "profile", None) and archive.user.profile.display_name
            else archive.user.username
        ),
        "created_at": archive.archived_at.isoformat(),
        "is_archive": True,
    })


@login_required(login_url="/oversight/login/")
@ensure_csrf_cookie
def project_progress(request):
    profile = get_or_create_profile(request.user)
    if profile.role == UserProfile.Role.EMPLOYEE:
        return redirect("home")
    if not user_has_oversight(request.user):
        return redirect(
            reverse("oversight_login")
            + "?error=Your account does not have oversight access. Ask an admin to set role to Manager or Boss."
        )

    profile = viewer_profile(request.user)
    today = timezone.localdate()
    try:
        window_days = int(request.GET.get("days", 30))
    except (TypeError, ValueError):
        window_days = 30
    window_days = max(7, min(window_days, 90))

    viewer_posted = EODReport.objects.filter(
        user=request.user,
        date=today,
        status=EODReport.Status.SUBMITTED,
    ).exists()
    date_ctx = date_context_for(today)

    return render(
        request,
        "project_progress.html",
        {
            "role_label": "Boss view" if is_boss(profile) else "Manager view",
            "is_boss": is_boss(profile),
            "is_manager": is_manager_role(profile),
            "viewer_display_name": profile.display_name or request.user.username,
            "viewer_posted": viewer_posted,
            "date_relation": date_ctx["relation"],
            "window_days": window_days,
        },
    )


@login_required(login_url="/oversight/login/")
@ensure_csrf_cookie
def dashboard(request):
    profile = get_or_create_profile(request.user)
    if profile.role == UserProfile.Role.EMPLOYEE:
        return redirect("home")
    if not user_has_oversight(request.user):
        return redirect(
            reverse("oversight_login")
            + "?error=Your account does not have oversight access. Ask an admin to set role to Manager or Boss."
        )

    profile = viewer_profile(request.user)
    today = timezone.localdate()
    parsed_day = _parse_date(request.GET.get("date"))
    day = parsed_day or today
    day, _ = _clamp_oversight_day(day)
    if parsed_day and parsed_day > today:
        q = request.GET.copy()
        q["date"] = day.isoformat()
        return redirect(f"{request.path}?{q.urlencode()}")

    board_id = request.GET.get("board")
    user_id = request.GET.get("user")
    archive_mode = request.GET.get("view") == "archive"

    archive_entries = []
    archive_q = ""
    archive_days = 30
    archive_board_id = None
    archive_user_id = None
    archive_boards = []
    archive_people = []

    if archive_mode:
        archive_q = (request.GET.get("q") or "").strip()
        try:
            archive_days = int(request.GET.get("days", 30))
        except (TypeError, ValueError):
            archive_days = 30
        archive_days = max(7, min(archive_days, 90))

        if request.GET.get("board"):
            try:
                archive_board_id = int(request.GET.get("board"))
            except (TypeError, ValueError):
                return HttpResponseForbidden("Invalid board.")
            if not can_access_department(profile, request.user, archive_board_id):
                return HttpResponseForbidden("You cannot view this board.")

        if request.GET.get("user"):
            try:
                archive_user_id = int(request.GET.get("user"))
            except (TypeError, ValueError):
                return HttpResponseForbidden("Invalid user.")
            if not can_view_user_eod(request.user, archive_user_id):
                return HttpResponseForbidden("You cannot view this person.")

        archive_boards = archive_filter_boards(request.user)
        archive_people = archive_filter_people(request.user, archive_board_id)
        archive_entries = eod_archive_entries(
            request.user,
            board_id=archive_board_id,
            user_id=archive_user_id,
            q=archive_q,
            days=archive_days,
            limit=50,
        )
        archive_filters = {
            "days": archive_days,
            "q": archive_q,
            "board_id": archive_board_id,
            "user_id": archive_user_id,
        }
        for entry in archive_entries:
            entry["view_url"] = _archive_report_url(entry, archive_filters)

    view_mode = "boards"
    boards = []
    people = []
    person = None
    active_board = None

    if archive_mode:
        view_mode = "archive"
    else:
        if board_id:
            try:
                board_id = int(board_id)
            except (TypeError, ValueError):
                return HttpResponseForbidden("Invalid board.")
            if not can_access_department(profile, request.user, board_id):
                return HttpResponseForbidden("You cannot view this board.")

        if user_id:
            try:
                user_id = int(user_id)
            except (TypeError, ValueError):
                return HttpResponseForbidden("Invalid user.")
            if not can_view_user_eod(request.user, user_id):
                return HttpResponseForbidden("You cannot view this person.")

        if user_id and board_id:
            view_mode = "person"
            person = person_oversight_detail(request.user, user_id, day)
            if person is None:
                return HttpResponseForbidden("You cannot view this person.")
            try:
                active_board = Department.objects.get(pk=board_id)
            except Department.DoesNotExist:
                return HttpResponseForbidden("Invalid board.")
        elif board_id:
            view_mode = "people"
            people = board_people(request.user, board_id, day)
            if people is None:
                return HttpResponseForbidden("You cannot view this board.")
            try:
                active_board = Department.objects.get(pk=board_id)
            except Department.DoesNotExist:
                return HttpResponseForbidden("Invalid board.")
        elif is_boss(profile):
            view_mode = "boards"
            boards = boards_overview(request.user, day)
        else:
            default_board = manager_default_department_id(request.user)
            if default_board:
                return redirect(f"{request.path}?date={day.isoformat()}&board={default_board}")
            boards = boards_overview(request.user, day)

    date_display = day.strftime("%A, %B %d, %Y")
    role_label = "Boss view" if is_boss(profile) else "Manager view"
    date_ctx = date_context_for(day)
    rel = date_ctx["relation"]
    posted_label = "Posted today" if rel == "today" else "Posted"

    summary = {}
    if view_mode == "boards":
        total_members = sum(b["member_count"] for b in boards)
        total_posted = sum(b["posted_count"] for b in boards)
        for b in boards:
            b["posted_pct"] = round(b["posted_count"] / b["member_count"] * 100) if b["member_count"] else 0
        summary = posting_summary_counts(posted=total_posted, total=total_members, day=day)
        summary["boards"] = len(boards)
        summary["members"] = total_members
    elif view_mode == "people":
        posted = sum(1 for p in people if p["posted"])
        summary = posting_summary_counts(posted=posted, total=len(people), day=day)
    elif view_mode == "archive":
        summary = {"total": len(archive_entries), "posted": len(archive_entries)}

    viewer_posted = EODReport.objects.filter(
        user=request.user,
        date=day,
        status=EODReport.Status.SUBMITTED,
    ).exists()
    viewer_posting = posting_display(viewer_posted, day)

    archive_back_url = None
    archive_prev_url = None
    archive_next_url = None
    if request.GET.get("from") == "archive" and view_mode == "person" and person:
        archive_prev_url, archive_next_url, archive_back_url = _archive_nav_urls(
            request, request.user, day, person["user_id"],
        )

    return render(
        request,
        "dashboard.html",
        {
            "view_mode": view_mode,
            "boards": boards,
            "people": people,
            "person": person,
            "active_board": active_board,
            "selected_date": day.isoformat(),
            "today_date": today.isoformat(),
            "date_display": date_display,
            "date_relation": rel,
            "date_context": date_ctx,
            "posted_label": posted_label,
            "role_label": role_label,
            "is_boss": is_boss(profile),
            "is_manager": is_manager_role(profile),
            "viewer_user_id": request.user.id,
            "viewer_display_name": profile.display_name or request.user.username,
            "viewer_posted": viewer_posted,
            "viewer_posting": viewer_posting,
            "summary": summary,
            "archive_entries": archive_entries,
            "archive_q": archive_q,
            "archive_days": archive_days,
            "archive_board_id": archive_board_id,
            "archive_user_id": archive_user_id,
            "archive_boards": archive_boards,
            "archive_people": archive_people,
            "archive_back_url": archive_back_url,
            "archive_prev_url": archive_prev_url,
            "archive_next_url": archive_next_url,
            "projects": list_active_projects(),
        },
    )


def _oversight_assistant_context(request, payload):
    if not user_has_oversight(request.user):
        return None, JsonResponse({"error": "Oversight access required"}, status=403)

    day = _parse_date((payload or {}).get("date")) or timezone.localdate()
    day, _ = _clamp_oversight_day(day)
    board_id = (payload or {}).get("board")
    user_id = (payload or {}).get("user")

    if board_id is not None:
        try:
            board_id = int(board_id)
        except (TypeError, ValueError):
            return None, JsonResponse({"error": "Invalid board"}, status=400)

    if user_id is not None:
        try:
            user_id = int(user_id)
        except (TypeError, ValueError):
            return None, JsonResponse({"error": "Invalid user"}, status=400)

    snapshot = build_oversight_snapshot(request.user, day, board_id=board_id, user_id=user_id)
    if snapshot is None:
        return None, JsonResponse({"error": "Cannot access this scope"}, status=403)

    profile = get_or_create_profile(request.user)
    model = (profile.ai_model or "gpt-4o-mini").strip()
    viewer_name = profile.display_name or request.user.get_full_name() or request.user.username
    return (snapshot, model, viewer_name), None


@login_required(login_url="/oversight/login/")
@require_POST
def api_oversight_assistant_summary(request):
    payload = _json_body(request)
    if payload is None:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    ctx, err = _oversight_assistant_context(request, payload)
    if err:
        return err
    snapshot, model, viewer_name = ctx

    try:
        summary = generate_oversight_summary(
            snapshot=snapshot,
            model=model,
            viewer_name=viewer_name,
        )
        ai_generated = True
    except AIError:
        summary = format_oversight_summary_from_snapshot(snapshot, viewer_name=viewer_name)
        ai_generated = False

    return JsonResponse({"summary": summary, "ai_generated": ai_generated})


@login_required(login_url="/oversight/login/")
@require_POST
def api_oversight_assistant_chat(request):
    payload = _json_body(request)
    if payload is None:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    message = (payload.get("message") or "").strip()
    if not message:
        return JsonResponse({"error": "message is required"}, status=400)
    if len(message) > 4000:
        return JsonResponse({"error": "message too long"}, status=400)

    ctx, err = _oversight_assistant_context(request, payload)
    if err:
        return err
    snapshot, model, viewer_name = ctx

    history = payload.get("history") or []
    if not isinstance(history, list):
        return JsonResponse({"error": "history must be an array"}, status=400)

    trimmed = []
    for item in history[-12:]:
        if not isinstance(item, dict):
            continue
        role = item.get("role")
        content = (item.get("content") or "").strip()
        if role in ("user", "assistant") and content:
            trimmed.append({"role": role, "content": content[:8000]})
    trimmed.append({"role": "user", "content": message})

    try:
        reply = oversight_assistant_chat(
            snapshot=snapshot,
            messages=trimmed,
            model=model,
            viewer_name=viewer_name,
        )
    except AIError as exc:
        msg = str(exc)
        if "quota" in msg.lower():
            msg = (
                "AI chat is unavailable right now (OpenAI billing/quota). "
                "The opening summary still works from live dashboard data."
            )
        return JsonResponse({"error": msg}, status=502)

    return JsonResponse({"reply": reply})


@login_required(login_url="/oversight/login/")
@require_POST
def api_oversight_assign_task(request):
    """Boss assigns a task to a team member (lands in their daily log)."""
    profile = viewer_profile(request.user)
    if not is_boss(profile):
        return HttpResponseForbidden("Only the boss can assign tasks.")

    payload = _json_body(request)
    if payload is None:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    try:
        target_user_id = int(payload.get("user_id"))
    except (TypeError, ValueError):
        return JsonResponse({"error": "user_id is required"}, status=400)

    if not can_assign_task_to_user(request.user, target_user_id):
        return HttpResponseForbidden("You cannot assign tasks to this person.")

    title = (payload.get("title") or "").strip()
    if not title:
        return JsonResponse({"error": "title is required"}, status=400)

    day = _parse_date(payload.get("date")) or timezone.localdate()
    day, _ = _clamp_oversight_day(day)

    try:
        assignee = User.objects.get(pk=target_user_id, is_active=True)
    except User.DoesNotExist:
        return JsonResponse({"error": "User not found"}, status=404)

    status = payload.get("status") or Task.Status.IN_PROGRESS
    if status not in Task.Status.values:
        status = Task.Status.IN_PROGRESS

    task = Task.objects.create(
        user=assignee,
        date=day,
        title=title,
        status=status,
        assigned_by=request.user,
    )
    apply_project_fields(
        task,
        project_id=payload.get("project_id"),
        project_name=payload.get("project"),
    )
    task.save()

    assigner_profile = getattr(request.user, "profile", None)
    assigner_name = (
        assigner_profile.display_name
        if assigner_profile and assigner_profile.display_name
        else request.user.username
    )
    notification = notify_task_assigned(task, assigner_name=assigner_name)
    task = Task.objects.select_related("assigned_by", "assigned_by__profile").get(pk=task.pk)

    return JsonResponse({
        "task": serialize_task(task),
        "notification_id": notification.id,
    }, status=201)


@login_required(login_url="/oversight/login/")
@require_http_methods(["DELETE"])
def api_oversight_delete_task(request, task_id):
    """Boss removes a task they previously assigned."""
    profile = viewer_profile(request.user)
    if not is_boss(profile):
        return HttpResponseForbidden("Only the boss can remove assigned tasks.")

    try:
        task = Task.objects.get(pk=task_id)
    except Task.DoesNotExist:
        return JsonResponse({"error": "Not found"}, status=404)

    if task.assigned_by_id != request.user.id:
        return JsonResponse({"error": "You can only remove tasks you assigned."}, status=403)

    task.delete()
    return JsonResponse({"ok": True})


@login_required
@require_GET
def api_notifications(request):
    items = unread_notifications(request.user)
    return JsonResponse({
        "notifications": items,
        "unread_count": len(items),
    })


@login_required
@require_POST
def api_notifications_read(request):
    payload = _json_body(request) or {}
    ids = payload.get("ids")
    if ids is not None and not isinstance(ids, list):
        return JsonResponse({"error": "ids must be an array"}, status=400)
    updated = mark_notifications_read(request.user, ids)
    return JsonResponse({"updated": updated})

