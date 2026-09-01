from django.db import migrations


def verify_existing_users(apps, schema_editor):
    CustomUser = apps.get_model("accounts", "CustomUser")
    CustomUser.objects.filter(is_email_verified=False).update(is_email_verified=True)


class Migration(migrations.Migration):
    dependencies = [("accounts", "0005_alter_emailotp_purpose")]

    operations = [migrations.RunPython(verify_existing_users, migrations.RunPython.noop)]
