from django.conf import settings
from django.db import models
from django.utils import timezone


class Department(models.Model):
    """Organizational board (shown as "Board" in the UI)."""

    name = models.CharField(max_length=200, unique=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class UserProfile(models.Model):
    class Role(models.TextChoices):
        EMPLOYEE = "EMPLOYEE", "Employee"
        MANAGER = "MANAGER", "Manager"
        BOSS = "BOSS", "Boss"

    class ReportFormat(models.TextChoices):
        PLAIN = "PLAIN", "Plain text"
        SLACK = "SLACK", "Slack"
        EMAIL = "EMAIL", "Manager email"

    class Tone(models.TextChoices):
        PROFESSIONAL = "professional", "Professional"
        CASUAL = "casual", "Casual"
        CONCISE = "concise", "Concise"

    class Length(models.TextChoices):
        BRIEF = "brief", "Brief"
        STANDARD = "standard", "Standard"
        DETAILED = "detailed", "Detailed"

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="profile",
    )
    display_name = models.CharField(max_length=200, blank=True, default="")
    department = models.ForeignKey(
        Department,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="members",
    )
    role = models.CharField(
        max_length=20,
        choices=Role.choices,
        default=Role.EMPLOYEE,
    )
    ai_model = models.CharField(max_length=50, default="gpt-4o-mini")
    style_guide = models.TextField(blank=True, default="")
    timezone = models.CharField(max_length=64, default="UTC")
    default_format = models.CharField(
        max_length=10,
        choices=ReportFormat.choices,
        default=ReportFormat.PLAIN,
    )
    default_tone = models.CharField(
        max_length=20,
        choices=Tone.choices,
        default=Tone.PROFESSIONAL,
    )
    default_length = models.CharField(
        max_length=20,
        choices=Length.choices,
        default=Length.STANDARD,
    )
    auto_send_enabled = models.BooleanField(default=False)
    auto_send_time = models.TimeField(null=True, blank=True)
    quiet_hours_start = models.TimeField(null=True, blank=True)
    quiet_hours_end = models.TimeField(null=True, blank=True)
    last_auto_send_date = models.DateField(null=True, blank=True)
    notify_email = models.BooleanField(
        default=True,
        help_text="Send Gmail/email alerts for team EOD posts (boss/manager).",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["department"],
                condition=models.Q(role="MANAGER", department__isnull=False),
                name="unique_manager_per_department",
            ),
        ]

    def __str__(self):
        return self.display_name or self.user.username

    @property
    def department_name(self):
        return self.department.name if self.department_id else ""

    def has_oversight_access(self):
        return self.role in (self.Role.MANAGER, self.Role.BOSS)


class Project(models.Model):
    """Team-wide project tag for tasks (boss can add more over time)."""

    name = models.CharField(max_length=200, unique=True)
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="created_projects",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class UserProjectProgress(models.Model):
    """Employee self-reported completion % on a team project."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="project_progress",
    )
    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name="user_progress",
    )
    percent = models.PositiveSmallIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "project"], name="unique_user_project_progress"),
            models.CheckConstraint(
                check=models.Q(percent__gte=0) & models.Q(percent__lte=100),
                name="user_project_progress_percent_range",
            ),
        ]
        indexes = [
            models.Index(fields=["user", "project"]),
        ]

    def __str__(self):
        return f"{self.user.username} · {self.project.name} · {self.percent}%"


class Task(models.Model):
    class Status(models.TextChoices):
        DONE = "DONE", "Done"
        IN_PROGRESS = "IN_PROGRESS", "In progress"
        BLOCKED = "BLOCKED", "Blocked"
        TOMORROW = "TOMORROW", "Tomorrow"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="tasks",
    )
    date = models.DateField(default=timezone.localdate)
    title = models.CharField(max_length=500)
    project = models.CharField(max_length=200, blank=True, default="")
    project_ref = models.ForeignKey(
        Project,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="tasks",
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.IN_PROGRESS,
    )
    rolled_from = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="rollovers",
    )
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="delegated_tasks",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "date", "rolled_from"],
                condition=models.Q(rolled_from__isnull=False),
                name="unique_rollover_per_day",
            ),
        ]
        indexes = [
            models.Index(fields=["user", "date"]),
            models.Index(fields=["user", "status", "updated_at"]),
        ]

    def __str__(self):
        return f"{self.title} ({self.get_status_display()})"


class Blocker(models.Model):
    class Kind(models.TextChoices):
        BLOCKED = "BLOCKED", "Blocked"
        NEEDS_FROM_OTHERS = "NEEDS_FROM_OTHERS", "Needs from others"

    task = models.ForeignKey(
        Task,
        on_delete=models.CASCADE,
        related_name="blockers",
    )
    kind = models.CharField(
        max_length=20,
        choices=Kind.choices,
        default=Kind.BLOCKED,
    )
    unblocker = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="blockers_to_clear",
    )
    dependency_text = models.CharField(max_length=500, blank=True, default="")
    note = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        target = self.unblocker or self.dependency_text or "unknown"
        return f"{self.get_kind_display()} → {target}"


class EODReport(models.Model):
    class Format(models.TextChoices):
        PLAIN = "PLAIN", "Plain text"
        SLACK = "SLACK", "Slack"
        EMAIL = "EMAIL", "Manager email"

    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        SUBMITTED = "SUBMITTED", "Submitted"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="eod_reports",
    )
    date = models.DateField(default=timezone.localdate)
    format = models.CharField(max_length=10, choices=Format.choices, default=Format.PLAIN)
    tone = models.CharField(max_length=20, default="professional")
    length = models.CharField(max_length=20, default="standard")
    content = models.TextField()
    draft_content = models.TextField(
        blank=True,
        default="",
        help_text="Regenerated preview after an EOD was already posted for this day.",
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
    )
    submitted_at = models.DateTimeField(null=True, blank=True)
    auto_generated = models.BooleanField(default=False)
    project_progress = models.JSONField(
        default=list,
        blank=True,
        help_text="Snapshot of self-reported % per project at post time.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["user", "date"], name="unique_eod_per_user_per_day"),
        ]
        indexes = [
            models.Index(fields=["user", "date"]),
            models.Index(fields=["user", "-created_at"]),
            models.Index(fields=["status", "date"]),
        ]

    def __str__(self):
        return f"EOD {self.user.username} {self.date} ({self.format}, {self.status})"


class EODReportArchive(models.Model):
    """Immutable snapshot when an employee re-posts an EOD for the same day."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="eod_archives",
    )
    log_date = models.DateField(help_text="Workday the archived EOD covered.")
    format = models.CharField(max_length=10, choices=EODReport.Format.choices, default=EODReport.Format.PLAIN)
    tone = models.CharField(max_length=20, default="professional")
    length = models.CharField(max_length=20, default="standard")
    content = models.TextField()
    project_progress = models.JSONField(default=list, blank=True)
    submitted_at = models.DateTimeField()
    archived_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-submitted_at"]
        indexes = [
            models.Index(fields=["user", "-submitted_at"]),
            models.Index(fields=["user", "log_date"]),
        ]

    def __str__(self):
        return f"EOD archive {self.user.username} {self.log_date}"


class TaskNotification(models.Model):
    class Kind(models.TextChoices):
        TASK_ASSIGNED = "TASK_ASSIGNED", "Task assigned"
        EOD_POSTED = "EOD_POSTED", "EOD posted"

    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="task_notifications",
    )
    task = models.ForeignKey(
        Task,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="notifications",
    )
    eod_report = models.ForeignKey(
        EODReport,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="notifications",
    )
    kind = models.CharField(
        max_length=32,
        choices=Kind.choices,
        default=Kind.TASK_ASSIGNED,
    )
    message = models.CharField(max_length=500)
    read_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["recipient", "read_at", "-created_at"]),
        ]

    def __str__(self):
        return f"{self.recipient.username}: {self.message[:40]}"
