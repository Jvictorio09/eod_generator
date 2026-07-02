from django.core.management import call_command
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Idempotent pilot bootstrap: Core Team + boss + manager accounts."

    def handle(self, *args, **options):
        call_command("ensure_department", "Core Team")
        call_command("seed_boss_account")
        call_command("seed_lead_account")
        from myApp.services.project_service import ensure_default_projects

        ensure_default_projects()
        self.stdout.write(self.style.SUCCESS("Pilot seed complete."))
        self.stdout.write("")
        self.stdout.write("Next: create employee users in /admin/ (Core Team, Employee role).")
        self.stdout.write("Then run: python manage.py check_pilot")
