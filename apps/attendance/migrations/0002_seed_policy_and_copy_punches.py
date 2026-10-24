from django.db import migrations


def forwards(apps, schema_editor):
    DeductionPolicy = apps.get_model("attendance", "DeductionPolicy")
    Punch = apps.get_model("attendance", "Punch")
    ArrivingLeaving = apps.get_model("users", "ArrivingLeaving")

    if not DeductionPolicy.objects.filter(department__isnull=True).exists():
        DeductionPolicy.objects.create(department=None, monthly_late_allowance=0, absence_days=1.0)

    punches = []
    for row in ArrivingLeaving.objects.all().iterator():
        punches.append(Punch(user_id=row.user_id, timestamp=row.arriving_at, source="WEB",
                             note="Migrated from legacy attendance"))
        if row.leaving_at:
            punches.append(Punch(user_id=row.user_id, timestamp=row.leaving_at, source="WEB",
                                 note="Migrated from legacy attendance"))
    Punch.objects.bulk_create(punches, batch_size=500)


class Migration(migrations.Migration):

    dependencies = [
        ("attendance", "0001_initial"),
        ("users", "0045_remove_user_password_normal"),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
