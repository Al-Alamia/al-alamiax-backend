from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("commission", "0041_remove_basicrecord"),
        ("treasury", "0016_remove_treasuryoutcome_from_salary"),
    ]

    operations = [
        migrations.DeleteModel(
            name="Commission",
        ),
    ]
