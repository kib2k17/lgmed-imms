from django.apps import AppConfig


class OutgoingConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "outgoing"
    verbose_name = "Outgoing Monitoring"
