"""捐款人加上「比對用名稱」，並把同一位的不同寫法合成一筆（LK-16）。"""

from django.db import migrations, models


def merge(apps, schema_editor):
    from orgs.donor_merge import merge_donors

    merge_donors(apps.get_model("orgs", "Donor"), apps.get_model("orgs", "Donation"))


class Migration(migrations.Migration):

    dependencies = [
        ("orgs", "0006_project_channel"),
    ]

    operations = [
        migrations.AddField(
            model_name="donor",
            name="name_key",
            field=models.CharField(default="", editable=False, max_length=200, verbose_name="比對用名稱"),
            preserve_default=False,
        ),
        migrations.RunPython(merge, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="donor",
            name="name_key",
            field=models.CharField(editable=False, max_length=200, unique=True, verbose_name="比對用名稱"),
        ),
    ]
