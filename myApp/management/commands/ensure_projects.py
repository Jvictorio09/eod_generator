from django.core.management.base import BaseCommand

from myApp.services.project_service import ensure_default_projects


class Command(BaseCommand):
    help = "Ensure default team projects exist (idempotent)."

    def handle(self, *args, **options):
        ensure_default_projects()
        self.stdout.write(self.style.SUCCESS("Default projects ready."))
