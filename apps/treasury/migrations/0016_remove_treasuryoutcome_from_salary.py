from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("treasury", "0015_remove_treasuryoutcome_from_basic"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="treasuryoutcome",
            name="from_salary",
        ),
    ]
