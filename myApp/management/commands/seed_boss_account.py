from django.contrib.auth.models import User
from django.core.management.base import BaseCommand

from myApp.models import Department, UserProfile

# Dev/pilot defaults — change after first login in production.
BOSS_USERNAME = "boss"
BOSS_PASSWORD = "boss-oversight-2026"


class Command(BaseCommand):
    help = "Create or reset the boss oversight account (separate from employee login)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--password",
            default=BOSS_PASSWORD,
            help="Password to set for the boss oversight account.",
        )

    def handle(self, *args, **options):
        password = options["password"]
        user, created = User.objects.get_or_create(
            username=BOSS_USERNAME,
            defaults={"is_staff": True},
        )
        user.set_password(password)
        user.is_active = True
        user.save()

        profile, _ = UserProfile.objects.get_or_create(user=user)
        profile.role = UserProfile.Role.BOSS
        profile.department = None
        profile.display_name = profile.display_name or "Boss"
        profile.save()

        verb = "Created" if created else "Updated"
        self.stdout.write(self.style.SUCCESS(f"{verb} oversight account."))
        self.stdout.write("")
        self.stdout.write("  Oversight sign-in:  /oversight/login/")
        self.stdout.write(f"  Username:           {BOSS_USERNAME}")
        self.stdout.write(f"  Password:           {password}")
        self.stdout.write("")
        self.stdout.write("  Employee sign-in:     /login/  (boss account blocked there)")
