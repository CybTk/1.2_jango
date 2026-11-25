from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0002_alter_user_role"),
    ]

    operations = [
        migrations.AlterField(
            model_name="pengajuanizin",
            name="file_bukti",
            field=models.FileField(
                blank=True,
                null=True,
                upload_to="bukti_izin/",
            ),
        ),
    ]
