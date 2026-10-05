from django.apps import AppConfig


class AccountsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "accounts"
    verbose_name = "Accounts & Roles"

    def ready(self):
        # Connects the signal that puts the Data Privacy Act notice in front
        # of everyone who signs in.
        from . import privacy  # noqa: F401
