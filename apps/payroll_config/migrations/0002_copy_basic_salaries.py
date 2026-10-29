import datetime

from django.db import migrations

from apps.payroll_config.services import copy_basic_salaries


def copy(apps, schema_editor):
    copy_basic_salaries(apps, datetime.date.today())


class Migration(migrations.Migration):

    dependencies = [
        ("payroll_config", "0001_initial"),
        ("commission", "0039_auto_20261029_1704"),
    ]

    operations = [
        migrations.RunPython(copy, migrations.RunPython.noop),
    ]
