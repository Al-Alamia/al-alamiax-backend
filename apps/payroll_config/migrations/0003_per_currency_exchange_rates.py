from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('payroll_config', '0002_copy_basic_salaries'),
    ]

    operations = [
        migrations.RenameField(
            model_name='exchangerate',
            old_name='sar_to_egp',
            new_name='rate_to_egp',
        ),
        migrations.AddField(
            model_name='exchangerate',
            name='currency',
            field=models.CharField(
                choices=[('SAR', 'SAR'), ('USD', 'USD'), ('AED', 'AED')],
                default='SAR', max_length=3),
        ),
        migrations.AlterField(
            model_name='exchangerate',
            name='month',
            field=models.DateField(),
        ),
        migrations.AlterModelOptions(
            name='exchangerate',
            options={'ordering': ['-month', 'currency']},
        ),
        migrations.AddConstraint(
            model_name='exchangerate',
            constraint=models.UniqueConstraint(
                fields=('month', 'currency'), name='unique_rate_per_month_currency'),
        ),
    ]
