from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import User

from .models import Blocker, Department, EODReport, EODReportArchive, Project, Task, TaskNotification, UserProfile


class UserProfileInline(admin.StackedInline):
    model = UserProfile
    can_delete = False
    fk_name = "user"
    fields = (
        "display_name",
        "department",
        "role",
        "ai_model",
        "style_guide",
        "timezone",
        "default_format",
        "default_tone",
        "default_length",
        "auto_send_enabled",
        "auto_send_time",
        "quiet_hours_start",
        "quiet_hours_end",
        "notify_email",
    )


class UserAdmin(BaseUserAdmin):
    inlines = [UserProfileInline]
    list_display = ("username", "email", "first_name", "last_name", "pilot_role", "pilot_department", "is_staff")
    list_select_related = ("profile", "profile__department")

    @admin.display(description="Role", ordering="profile__role")
    def pilot_role(self, obj):
        profile = getattr(obj, "profile", None)
        return profile.get_role_display() if profile else "—"

    @admin.display(description="Department", ordering="profile__department__name")
    def pilot_department(self, obj):
        profile = getattr(obj, "profile", None)
        if profile and profile.department_id:
            return profile.department.name
        return "—"


admin.site.unregister(User)
admin.site.register(User, UserAdmin)


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ("name", "is_active", "created_by", "created_at")
    list_filter = ("is_active",)
    search_fields = ("name",)
    raw_id_fields = ("created_by",)


@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    list_display = ("name", "member_count")
    search_fields = ("name",)

    @admin.display(description="Members")
    def member_count(self, obj):
        return obj.members.count()


@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    list_display = ("title", "user", "date", "status", "assigned_by", "project_ref", "project", "updated_at")
    list_filter = ("status", "date")
    search_fields = ("title", "user__username", "project", "project_ref__name")
    raw_id_fields = ("user", "rolled_from", "assigned_by", "project_ref")


@admin.register(TaskNotification)
class TaskNotificationAdmin(admin.ModelAdmin):
    list_display = ("recipient", "kind", "message", "read_at", "created_at")
    list_filter = ("kind", "read_at")
    search_fields = ("message", "recipient__username")
    raw_id_fields = ("recipient", "task", "eod_report")


@admin.register(Blocker)
class BlockerAdmin(admin.ModelAdmin):
    list_display = ("task", "kind", "unblocker", "dependency_text", "created_at")
    list_filter = ("kind",)
    search_fields = ("dependency_text", "note", "task__title")
    raw_id_fields = ("task", "unblocker")


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "display_name", "department", "role", "notify_email", "auto_send_enabled", "timezone")
    list_filter = ("role", "department")
    search_fields = ("user__username", "display_name", "department__name")
    raw_id_fields = ("user",)


@admin.register(EODReport)
class EODReportAdmin(admin.ModelAdmin):
    list_display = ("user", "date", "format", "status", "tone", "auto_generated", "submitted_at", "created_at")
    list_filter = ("format", "status", "auto_generated", "date")
    search_fields = ("content", "user__username")
    raw_id_fields = ("user",)


@admin.register(EODReportArchive)
class EODReportArchiveAdmin(admin.ModelAdmin):
    list_display = ("user", "log_date", "format", "submitted_at", "archived_at")
    list_filter = ("format", "log_date")
    search_fields = ("content", "user__username")
    raw_id_fields = ("user",)
