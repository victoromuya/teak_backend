from django.db import migrations, models


def mark_existing_guests(apps, schema_editor):
    User = apps.get_model('accounts', 'CustomUser')
    User.objects.filter(password__startswith='!').update(is_registered=False)


class Migration(migrations.Migration):
    dependencies = [('accounts', '0007_authratelimit_emailotp_failed_attempts')]
    operations = [
        migrations.AddField(model_name='customuser', name='is_registered', field=models.BooleanField(default=True)),
        migrations.RunPython(mark_existing_guests, migrations.RunPython.noop),
    ]
