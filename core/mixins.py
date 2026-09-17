"""
Authorization mixins.

The sidebar and the action buttons hide what a user cannot do, but that is a
usability courtesy only. These mixins are the actual control: every view that
changes data declares the capability it needs, and a request without it is
refused with 403 whether or not the user was ever shown a button.
"""

from functools import wraps

from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied


class CapabilityRequiredMixin(LoginRequiredMixin):
    """Require a named capability (a property on the user model)."""

    capability = None

    def dispatch(self, request, *args, **kwargs):
        if self.capability and request.user.is_authenticated:
            if not getattr(request.user, self.capability, False):
                raise PermissionDenied(
                    "Your role does not permit this action."
                )
        return super().dispatch(request, *args, **kwargs)


class CanEncodeMixin(CapabilityRequiredMixin):
    """Create and edit operational records."""

    capability = "can_encode"


class CanApproveMixin(CapabilityRequiredMixin):
    """Approve monitoring records, publish documents and reports."""

    capability = "can_approve"


class CanReviewIncomingMixin(CapabilityRequiredMixin):
    """Review an incoming document and assign its focal person."""

    capability = "can_review_incoming"


class CanSuperviseMixin(CapabilityRequiredMixin):
    """Monitor the work of other employees. The Division Chief and above."""

    capability = "can_supervise"


class CanAssignDocumentsMixin(CapabilityRequiredMixin):
    """Name the focal person responsible for a registered document."""

    capability = "can_assign_documents"


class CanArchiveDocumentsMixin(CapabilityRequiredMixin):
    """Archive a completed document, and restore an archived one."""

    capability = "can_archive_documents"


class CanDisposeDocumentsMixin(CapabilityRequiredMixin):
    """Authorise the permanent disposal of an archived document."""

    capability = "can_dispose_documents"


class CanEncodePPAMixin(CapabilityRequiredMixin):
    """Describe a programme, project or activity, and upload its papers."""

    capability = "can_encode_ppa"


class CanReviewPPAMixin(CapabilityRequiredMixin):
    """Read a security screening and clear, reject or return a document."""

    capability = "can_review_ppa"


class CanPublishPPAMixin(CapabilityRequiredMixin):
    """Publish approved PPA content to the public website, and withdraw it."""

    capability = "can_publish_ppa"


class CanDeleteMixin(CapabilityRequiredMixin):
    """Delete records. Administrators only."""

    capability = "can_delete"


class CanAdministerMixin(CapabilityRequiredMixin):
    """Users, roles, settings, audit."""

    capability = "can_administer"


def capability_required(capability):
    """
    The function-view equivalent of `CapabilityRequiredMixin`.

        @capability_required("can_administer")
        def reference_delete(request, ...):
    """

    def decorator(view):
        @wraps(view)
        @login_required
        def wrapper(request, *args, **kwargs):
            if not getattr(request.user, capability, False):
                raise PermissionDenied("Your role does not permit this action.")
            return view(request, *args, **kwargs)

        return wrapper

    return decorator


administrator_required = capability_required("can_administer")
