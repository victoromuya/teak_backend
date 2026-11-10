from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('accounts', '0008_customuser_is_registered')]
    operations = [migrations.AlterField(model_name='emailotp', name='purpose', field=models.CharField(
        max_length=30, default='registration', choices=[
            ('registration', 'Registration'), ('guest_checkout', 'Guest Checkout'),
            ('ticket_access', 'Ticket Access'), ('login', 'Login'),
            ('password_reset', 'Password Reset'), ('email_change', 'Email Change'),
        ],
    ))]
