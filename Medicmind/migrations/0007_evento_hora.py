from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('Medicmind', '0006_evento_estado_respuesta_sms_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='evento',
            name='hora',
            field=models.TimeField(blank=True, null=True),
        ),
    ]
