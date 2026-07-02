from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("myApp", "0006_rename_myapp_taskn_recipie_idx_myapp_taskn_recipie_2bcece_idx"),
    ]

    operations = [
        migrations.AddField(
            model_name="userprofile",
            name="notify_email",
            field=models.BooleanField(
                default=True,
                help_text="Send Gmail/email alerts for team EOD posts (boss/manager).",
            ),
        ),
        migrations.AddField(
            model_name="tasknotification",
            name="eod_report",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="notifications",
                to="myApp.eodreport",
            ),
        ),
        migrations.AlterField(
            model_name="tasknotification",
            name="kind",
            field=models.CharField(
                choices=[
                    ("TASK_ASSIGNED", "Task assigned"),
                    ("EOD_POSTED", "EOD posted"),
                ],
                default="TASK_ASSIGNED",
                max_length=32,
            ),
        ),
    ]
