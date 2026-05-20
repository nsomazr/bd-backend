from django.db import migrations, models

from chat.ids import assign_unique_public_id


def backfill_public_ids(apps, schema_editor):
    Conversation = apps.get_model("chat", "Conversation")
    for convo in Conversation.objects.filter(public_id__isnull=True).iterator():
        assign_unique_public_id(convo)
        convo.save(update_fields=["public_id"])


class Migration(migrations.Migration):
    dependencies = [
        ("chat", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="conversation",
            name="public_id",
            field=models.CharField(
                blank=True,
                db_index=True,
                editable=False,
                max_length=16,
                null=True,
            ),
        ),
        migrations.RunPython(backfill_public_ids, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="conversation",
            name="public_id",
            field=models.CharField(
                db_index=True,
                editable=False,
                max_length=16,
                unique=True,
            ),
        ),
    ]
