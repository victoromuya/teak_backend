from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("accounts", "0004_emailotp_first_name_emailotp_last_name")]

    operations = [
        migrations.AlterField(
            model_name="emailotp",
            name="purpose",
            field=models.CharField(
                choices=[
                    ("registration", "Registration"),
                    ("guest_checkout", "Guest Checkout"),
                    ("login", "Login"),
                    ("password_reset", "Password Reset"),
                    ("email_change", "Email Change"),
                ],
                default="registration",
                max_length=30,
            ),
        ),
    ]
