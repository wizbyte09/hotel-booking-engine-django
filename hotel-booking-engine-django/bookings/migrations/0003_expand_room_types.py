from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('bookings', '0002_contactinquiry'),
    ]

    operations = [
        migrations.AlterField(
            model_name='room',
            name='room_type',
            field=models.CharField(
                choices=[
                    ('economy', 'Economy'),
                    ('standard', 'Standard'),
                    ('deluxe', 'Deluxe'),
                    ('executive', 'Executive'),
                    ('premium', 'Premium'),
                    ('suite', 'Suite'),
                    ('family', 'Family'),
                    ('villa', 'Villa'),
                    ('presidential', 'Presidential'),
                ],
                default='deluxe',
                max_length=20,
            ),
        ),
    ]