from django.apps import AppConfig


class DatasyncConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "datasync"
    verbose_name = "Spreadsheet Sync"
