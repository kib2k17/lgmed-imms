from django.apps import AppConfig
from django.contrib.staticfiles.apps import StaticFilesConfig as BaseStaticFilesConfig


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "core"
    verbose_name = "LGMED-iMMS Core"


class StaticFilesConfig(BaseStaticFilesConfig):
    """
    django.contrib.staticfiles, minus the stylesheet's source.

    static/css/app.src.css is Tailwind input, compiled to app.css by
    build-css.ps1. Collected as-is it is never served, and in production it
    stops collectstatic outright: ManifestStaticFilesStorage reads its
    `@import "tailwindcss"` as a file to fingerprint, cannot find one, and
    fails the whole deployment.
    """

    ignore_patterns = [*BaseStaticFilesConfig.ignore_patterns, "*.src.css"]
