from django.core.management.base import BaseCommand

from myApp.models import Department


class Command(BaseCommand):
    help = 'Ensure one or more departments exist (idempotent). Example: ensure_department "Core Team"'

    def add_arguments(self, parser):
        parser.add_argument(
            "names",
            nargs="*",
            help='Department names to create if missing (default: "Core Team")',
        )

    def handle(self, *args, **options):
        names = options["names"] or ["Core Team"]
        for name in names:
            name = name.strip()
            if not name:
                continue
            _, created = Department.objects.get_or_create(name=name)
            if created:
                self.stdout.write(self.style.SUCCESS(f"Created department: {name}"))
            else:
                self.stdout.write(f"Already exists: {name}")
