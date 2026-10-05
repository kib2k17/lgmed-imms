"""
The signing mechanisms e-SIRA can use, chosen by ESIRA_SIGNING_BACKEND.

Kept apart from the workflow so the mechanism can change - certificate file
today, a token or DICT signing agent later - without touching who may sign,
routing, versioning or the audit trail.
"""

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from .base import (  # noqa: F401 - re-exported
    CredentialError,
    OpenedCredential,
    Placement,
    SignatureRequest,
    SigningBackend,
    SigningBackendUnavailable,
    SigningError,
)
from .external import ExternalAgentBackend
from .pkcs12 import Pkcs12Backend

BACKENDS = {
    Pkcs12Backend.key: Pkcs12Backend,
    ExternalAgentBackend.key: ExternalAgentBackend,
}


def get_backend():
    key = getattr(settings, "ESIRA_SIGNING_BACKEND", Pkcs12Backend.key)
    try:
        return BACKENDS[key]()
    except KeyError:
        raise ImproperlyConfigured(
            f"ESIRA_SIGNING_BACKEND is '{key}'; expected one of "
            + ", ".join(sorted(BACKENDS))
        )
