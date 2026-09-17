"""
Where internal documents live.

`MEDIA_ROOT` is served: the development server publishes it wholesale and the
production web server is configured to do the same. A file written there is
reachable by anyone who can guess or is given its path, with no view, no login
and no role check in the way.

Internal supporting documents therefore do not go there. They are written to
`PROTECTED_MEDIA_ROOT`, a sibling directory that nothing maps to a URL, and are
read back only by `programs.views.DocumentDownloadView`, which re-checks the
user's role on every request.

The storage is deliberately configured with no `base_url`. Asking a protected
file for its `.url` raises, which is what should happen: a template that tries
to link straight to an internal document is a bug, and it should fail on the
developer's screen rather than quietly emit a working path.
"""

from django.conf import settings
from django.core.files.storage import FileSystemStorage, storages
from django.core.signals import setting_changed
from django.utils.functional import cached_property


class ProtectedFileSystemStorage(FileSystemStorage):
    """
    A filesystem storage rooted at `PROTECTED_MEDIA_ROOT` rather than at
    `MEDIA_ROOT`, resolved when it is used rather than when it is built.

    The lateness matters twice. Django serialises a `FileField`'s storage into
    the migration that creates it, so a storage carrying a literal path would
    freeze whichever machine generated the migration into it - a production
    server following a migration written on a laptop would be pointed at a
    directory under that developer's home. And the test suite has to be able to
    redirect the protected root into a temporary directory, which it cannot do
    if the location was fixed at import time.

    So the root is read from settings on first use and dropped again whenever
    the setting changes, which is what `override_settings` announces.
    """

    def __init__(self, **kwargs):
        # Never a public URL. `.url()` on a protected file must raise rather
        # than hand a caller a path that a web server might one day serve.
        kwargs.setdefault("base_url", None)
        super().__init__(**kwargs)
        setting_changed.connect(self._clear_protected_root)

    @cached_property
    def base_location(self):
        return self._value_or_setting(self._location, settings.PROTECTED_MEDIA_ROOT)

    def _clear_protected_root(self, setting=None, **kwargs):
        if setting == "PROTECTED_MEDIA_ROOT":
            self.__dict__.pop("base_location", None)
            self.__dict__.pop("location", None)


def protected_storage():
    """
    The storage internal documents are written to.

    A callable rather than an instance so that Django records it in the
    migration as a reference to this function - see the class above.
    """
    return storages["protected"]
