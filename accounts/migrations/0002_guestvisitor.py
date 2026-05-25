from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="GuestVisitor",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("visitor_key", models.CharField(db_index=True, max_length=36, unique=True)),
                ("first_seen", models.DateTimeField(auto_now_add=True)),
                ("last_seen", models.DateTimeField(auto_now=True)),
                ("visit_count", models.PositiveIntegerField(default=1)),
                ("first_ip", models.GenericIPAddressField(blank=True, null=True)),
                ("last_ip", models.GenericIPAddressField(blank=True, null=True)),
                ("country", models.CharField(blank=True, default="", max_length=64)),
                ("region", models.CharField(blank=True, default="", max_length=128)),
                ("city", models.CharField(blank=True, default="", max_length=128)),
                ("user_agent", models.TextField(blank=True, default="")),
                (
                    "linked_user",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="linked_visitors",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["-last_seen"],
            },
        ),
        migrations.AddIndex(
            model_name="guestvisitor",
            index=models.Index(fields=["-last_seen"], name="accounts_gu_last_se_idx"),
        ),
        migrations.AddIndex(
            model_name="guestvisitor",
            index=models.Index(fields=["country"], name="accounts_gu_country_idx"),
        ),
    ]
