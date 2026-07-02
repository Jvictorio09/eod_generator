from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("myApp", "0008_project"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="eodreport",
            name="draft_content",
            field=models.TextField(
                blank=True,
                default="",
                help_text="Regenerated preview after an EOD was already posted for this day.",
            ),
        ),
        migrations.CreateModel(
            name="EODReportArchive",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("log_date", models.DateField(help_text="Workday the archived EOD covered.")),
                ("format", models.CharField(choices=[("PLAIN", "Plain text"), ("SLACK", "Slack"), ("EMAIL", "Manager email")], default="PLAIN", max_length=10)),
                ("tone", models.CharField(default="professional", max_length=20)),
                ("length", models.CharField(default="standard", max_length=20)),
                ("content", models.TextField()),
                ("submitted_at", models.DateTimeField()),
                ("archived_at", models.DateTimeField(auto_now_add=True)),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="eod_archives",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["-submitted_at"],
                "indexes": [
                    models.Index(fields=["user", "-submitted_at"], name="myapp_eodar_user_id_sub_idx"),
                    models.Index(fields=["user", "log_date"], name="myapp_eodar_user_id_log_idx"),
                ],
            },
        ),
    ]
