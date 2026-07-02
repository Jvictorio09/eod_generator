from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("myApp", "0010_rename_myapp_eodar_user_id_sub_idx_myapp_eodre_user_id_0836d5_idx_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="UserProjectProgress",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("percent", models.PositiveSmallIntegerField(default=0)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "project",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="user_progress",
                        to="myApp.project",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="project_progress",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "indexes": [models.Index(fields=["user", "project"], name="myapp_userpr_user_id_6f0a0a_idx")],
            },
        ),
        migrations.AddConstraint(
            model_name="userprojectprogress",
            constraint=models.UniqueConstraint(fields=("user", "project"), name="unique_user_project_progress"),
        ),
        migrations.AddConstraint(
            model_name="userprojectprogress",
            constraint=models.CheckConstraint(
                check=models.Q(("percent__gte", 0), ("percent__lte", 100)),
                name="user_project_progress_percent_range",
            ),
        ),
    ]
