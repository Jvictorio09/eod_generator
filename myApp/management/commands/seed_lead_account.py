from django.contrib.auth.models import User
from django.core.management.base import BaseCommand

from myApp.models import Department, UserProfile

LEAD_USERNAME = "Julia"
LEAD_PASSWORD = "lead-oversight-2026"
CORE_TEAM = "Core Team"


class Command(BaseCommand):
    help = "Create or reset the pilot lead (manager) account for Core Team."

    def add_arguments(self, parser):
        parser.add_argument(
            "--username",
            default=LEAD_USERNAME,
            help="Manager username (default: Julia).",
        )
        parser.add_argument(
            "--password",
            default=LEAD_PASSWORD,
            help="Password to set for the manager account.",
        )

    def handle(self, *args, **options):
        username = options["username"]
        password = options["password"]
        dept, _ = Department.objects.get_or_create(name=CORE_TEAM)

        user, created = User.objects.get_or_create(
            username=username,
            defaults={"is_staff": False},
        )
        user.set_password(password)
        user.is_active = True
        user.save()

        profile, _ = UserProfile.objects.get_or_create(user=user)
        profile.role = UserProfile.Role.MANAGER
        profile.department = dept
        profile.display_name = profile.display_name or "Lead"
        profile.save()

        verb = "Created" if created else "Updated"
        self.stdout.write(self.style.SUCCESS(f"{verb} lead (manager) account."))
        self.stdout.write("")
        self.stdout.write("  Oversight sign-in:  /oversight/login/")
        self.stdout.write(f"  Username:           {username}")
        self.stdout.write(f"  Password:           {password}")
        self.stdout.write(f"  Department:         {CORE_TEAM}")
        self.stdout.write("")
        self.stdout.write("  Own EOD log:        /login/  (managers can use employee workspace too)")
