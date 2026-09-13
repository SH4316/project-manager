from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("orgs", "0002_organization_governance"),
    ]

    operations = [
        migrations.AddField(
            model_name="team",
            name="discord_channel_id",
            field=models.CharField(blank=True, max_length=32, verbose_name="Discord 채널"),
        ),
    ]
