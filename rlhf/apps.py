from django.apps import AppConfig


class RlhfConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "rlhf"
    verbose_name = "RLHF / preference data"
