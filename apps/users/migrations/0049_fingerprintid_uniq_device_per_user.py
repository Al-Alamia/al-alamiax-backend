from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0048_device_status_fields_and_approve_existing'),
    ]

    operations = [
        migrations.AddConstraint(
            model_name='fingerprintid',
            constraint=models.UniqueConstraint(fields=('user', 'unique_id'), name='uniq_device_per_user'),
        ),
    ]
