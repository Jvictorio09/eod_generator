from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("myApp", "0011_userprojectprogress"),
    ]

    operations = [
        migrations.AddField(
            model_name="eodreport",
            name="project_progress",
            field=models.JSONField(
                blank=True,
                default=list,
                help_text="Snapshot of self-reported % per project at post time.",
            ),
        ),
        migrations.AddField(
            model_name="eodreportarchive",
            name="project_progress",
            field=models.JSONField(blank=True, default=list),
        ),
    ]
