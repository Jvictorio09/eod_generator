from django.core.management.base import BaseCommand
from django.contrib.auth.models import Group


class Command(BaseCommand):
    help = "Create the Managers group for dashboard access."

    def handle(self, *args, **options):
        group, created = Group.objects.get_or_create(name="Managers")
        if created:
            self.stdout.write(self.style.SUCCESS("Created Managers group."))
        else:
            self.stdout.write("Managers group already exists.")
