from django.core.management.base import BaseCommand

from myApp.models import Department

BOARDS = [
    "Copy Writing Board",
    "Design Board",
    "Development Board",
    "AI Dev Board",
    "Social Media Board",
    "CRM Board",
    "SEO/GEO Board",
]


class Command(BaseCommand):
    help = "Seed the seven organizational boards (departments)."

    def handle(self, *args, **options):
        created = 0
        for name in BOARDS:
            _, was_created = Department.objects.get_or_create(name=name)
            if was_created:
                created += 1
                self.stdout.write(self.style.SUCCESS(f"Created: {name}"))
            else:
                self.stdout.write(f"Exists: {name}")
        self.stdout.write(self.style.SUCCESS(f"Done — {created} new, {len(BOARDS)} total boards."))
