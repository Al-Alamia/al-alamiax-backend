from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('teams', '0001_initial'),
    ]

    operations = [
        migrations.RemoveField(model_name='commissionplan', name='metric'),
        migrations.RemoveField(model_name='commissionplan', name='american_threshold_percent'),
        migrations.AddField(
            model_name='planversion', name='metric',
            field=models.CharField(choices=[('lead_count', 'Lead count'), ('deal_count', 'Deal count'), ('sales_amount', 'Sales amount')], default='lead_count', max_length=15),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='planversion', name='american_threshold_percent',
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=5, null=True),
        ),
    ]
