from datetime import datetime

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from django.utils import timezone

from myApp.models import Department, EODReport, UserProfile


class Command(BaseCommand):
    help = "Read-only pilot roster: username, role, department, posted today."

    def add_arguments(self, parser):
        parser.add_argument(
            "--date",
            default=None,
            help="Date to check (YYYY-MM-DD). Defaults to today.",
        )

    def handle(self, *args, **options):
        day = timezone.localdate()
        if options["date"]:
            try:
                day = datetime.strptime(options["date"], "%Y-%m-%d").date()
            except ValueError:
                self.stderr.write(self.style.ERROR("Invalid --date; use YYYY-MM-DD"))
                return

        core = Department.objects.filter(name="Core Team").first()
        if core:
            self.stdout.write(self.style.SUCCESS(f'Core Team department: id={core.id}'))
        else:
            self.stdout.write(
                self.style.WARNING('Core Team not found — run: python manage.py ensure_department "Core Team"')
            )
        self.stdout.write(f"Checking EOD posted status for {day.isoformat()}\n")
        self.stdout.write(f"{'Username':<22} {'Role':<12} {'Department':<22} {'Posted today'}")
        self.stdout.write("-" * 72)

        users = (
            User.objects.filter(is_active=True)
            .select_related("profile", "profile__department")
            .order_by("username")
        )
        if not users.exists():
            self.stdout.write(self.style.WARNING("No active users in the database."))
            return

        for user in users:
            profile = getattr(user, "profile", None)
            if profile:
                role = profile.get_role_display()
                dept = profile.department.name if profile.department_id else "(none)"
            else:
                role = "(no profile)"
                dept = "(none)"

            posted = EODReport.objects.filter(
                user=user,
                date=day,
                status=EODReport.Status.SUBMITTED,
            ).exists()
            flag = "yes" if posted else "no"
            style = self.style.SUCCESS if posted else self.style.WARNING
            self.stdout.write(
                f"{user.username:<22} {role:<12} {dept:<22} {style(flag)}"
            )

        self.stdout.write("")
        self.stdout.write("Pilot expectations:")
        self.stdout.write("  Boss     -> role Boss, department blank")
        self.stdout.write("  Lead     -> role Manager, department Core Team")
        self.stdout.write("  Reports  -> role Employee, department Core Team")
