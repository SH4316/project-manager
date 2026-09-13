from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("projects", "0003_apispec"),
    ]

    operations = [
        migrations.AddField(
            model_name="project",
            name="discord_channel_id",
            field=models.CharField(blank=True, max_length=32, verbose_name="Discord 채널"),
        ),
    ]
