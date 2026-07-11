from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ('shop', '0023_alter_customer_options_customer_address_and_more'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='customer',
            name='email',
        ),
        migrations.RemoveField(
            model_name='order',
            name='email',
        ),
    ]
