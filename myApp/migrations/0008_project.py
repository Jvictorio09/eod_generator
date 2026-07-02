from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


DEFAULT_PROJECTS = [
    "airamed",
    "neuromed website",
    "neuromed app",
    "patchwork",
    "mepkin abbey",
]


def seed_projects(apps, schema_editor):
    Project = apps.get_model("myApp", "Project")
    Task = apps.get_model("myApp", "Task")
    for name in DEFAULT_PROJECTS:
        Project.objects.get_or_create(name=name)
    for task in Task.objects.exclude(project="").iterator():
        match = Project.objects.filter(name__iexact=task.project.strip()).first()
        if match:
            task.project_ref_id = match.id
            task.project = match.name
            task.save(update_fields=["project_ref", "project"])


def unseed_projects(apps, schema_editor):
    Project = apps.get_model("myApp", "Project")
    Project.objects.filter(name__in=DEFAULT_PROJECTS).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("myApp", "0007_oversight_notify_email"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Project",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=200, unique=True)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="created_projects",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["name"],
            },
        ),
        migrations.AddField(
            model_name="task",
            name="project_ref",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="tasks",
                to="myApp.project",
            ),
        ),
        migrations.RunPython(seed_projects, unseed_projects),
    ]
