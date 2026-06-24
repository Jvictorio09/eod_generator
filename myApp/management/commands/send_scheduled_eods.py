from django.core.management.base import BaseCommand

from myApp.services.report_service import run_auto_send_for_profile, users_due_for_auto_send


class Command(BaseCommand):
    help = "Send scheduled EOD reports for users due at their configured local time."

    def handle(self, *args, **options):
        due = users_due_for_auto_send()
        sent = 0
        for profile, local_date in due:
            if run_auto_send_for_profile(profile, local_date):
                sent += 1
                self.stdout.write(f"Sent auto EOD for {profile.user.username}")
        if not due:
            self.stdout.write("No users due for auto-send.")
        else:
            self.stdout.write(self.style.SUCCESS(f"Completed: {sent}/{len(due)} sent."))
