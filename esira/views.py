"""
e-SIRA views.

Each view checks access through `esira.permissions` and changes state only by
calling `esira.workflow`, which checks again. The signing workspace is the one
page with real client-side behaviour (static/js/esira-workspace.js); it saves
box placements through a small JSON endpoint and signs through an ordinary
form post, so a signature is never applied by script alone.
"""

import io
import json
from datetime import timedelta

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.templatetags.static import static
from django.urls import reverse
from django.utils import dateformat, timezone
from django.utils.decorators import method_decorator
from django.views.decorators.clickjacking import xframe_options_sameorigin
from django.views.generic import FormView, TemplateView, View

from core.mixins import CapabilityRequiredMixin
from core.views_base import ModuleListView

from . import permissions as perms
from . import stats, workflow
from .audit import log
from .forms import (
    ActForm,
    CancelForm,
    CertificateRegisterForm,
    CertificateReviewForm,
    RouteFormSet,
    SignatureImageForm,
    SignatureStyleForm,
    SignForm,
    UploadForm,
    active_users,
)
from .models import (
    DONE_STEP_STATUSES,
    OPEN_STEP_STATUSES,
    AuditAction,
    AuditEntry,
    DocumentStatus,
    EsiraDocument,
    FileIntegrityError,
    SignatureStyle,
    SignerProfile,
    SigningCertificate,
    StepAction,
)
from .signing import get_backend
from .signing.certificates import trust_roots, untrusted_allowed


class EsiraMixin(CapabilityRequiredMixin):
    capability = "can_use_esira"
    active_nav = "esira"
    page_title = ""
    page_subtitle = ""
    tab = ""

    def get_breadcrumbs(self):
        return [{"label": "e-SIRA", "url": reverse("esira:dashboard")}, {"label": self.page_title}]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.setdefault("active_nav", self.active_nav)
        context.setdefault("page_title", self.page_title)
        context.setdefault("page_subtitle", self.page_subtitle)
        context.setdefault("breadcrumbs", self.get_breadcrumbs())
        context["esira_tab"] = self.tab
        return context


def signing_setup():
    """What the signing pages tell users about how signing works here."""
    backend = get_backend()
    roots = trust_roots()
    return {
        "backend": backend,
        "available": backend.is_available(),
        "unavailable_reason": backend.unavailable_reason(),
        "roots_installed": len(roots),
        "untrusted_allowed": untrusted_allowed(),
    }


def style_sample_context(user):
    """What the signature style previews need: the name and time zone they show."""
    stored = workflow.stored_certificate(user)
    return {
        "profile": SignerProfile.for_user(user),
        "sample_name": (stored.subject_common_name if stored else "") or user.get_display_name(),
        "sample_zone": settings.ESIRA_TIME_ZONE_LABEL or timezone.localtime().strftime("%Z"),
    }


def sign_form_for(user, backend, *args):
    """The Sign dialog's form, shaped by whether the user keeps a certificate on file."""
    stored = (
        backend.collects_credentials
        and workflow.stored_certificate(user, usable_only=True) is not None
    )
    return SignForm(
        *args,
        collects_credentials=backend.collects_credentials,
        stored=stored,
        require_passphrase=SignerProfile.for_user(user).require_passphrase,
        styles=workflow.signature_styles(user),
        initial={"style": workflow.default_style_key(user)},
    )


class DocumentMixin(EsiraMixin):
    """Loads the document named in the URL and refuses anyone who may not see it."""

    def get_document(self):
        if not hasattr(self, "_document"):
            document = get_object_or_404(
                EsiraDocument.objects.select_related("owner"), pk=self.kwargs["pk"],
            )
            if not perms.can_view(self.request.user, document):
                raise PermissionDenied("You do not have access to this document.")
            self._document = document
        return self._document

    def get_breadcrumbs(self):
        document = self.get_document()
        crumbs = [
            {"label": "e-SIRA", "url": reverse("esira:dashboard")},
            {"label": "Documents", "url": reverse("esira:list")},
            {"label": document.reference_no, "url": document.get_absolute_url()},
        ]
        if self.page_title and self.page_title != document.reference_no:
            crumbs.append({"label": self.page_title})
        return crumbs


def _flags(user, document):
    return {
        "is_owner": perms.is_owner(user, document),
        "my_step": perms.my_open_step(user, document),
        "can_sign": perms.can_sign(user, document),
        "can_edit_boxes": perms.can_edit_boxes(user, document),
        "can_route": perms.can_route(user, document),
        "can_act": perms.can_act(user, document),
        "can_reject": perms.can_reject(user, document),
        "can_complete": perms.can_complete(user, document),
        "can_cancel": perms.can_cancel(user, document),
        "can_view_audit": perms.can_view_audit(user, document),
    }


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------


class DashboardView(EsiraMixin, TemplateView):
    template_name = "dashboard/esira/dashboard.html"
    page_title = "e-SIRA"
    page_subtitle = "Electronic Signature, Identification, Routing and Approval"
    tab = "dashboard"

    def get_breadcrumbs(self):
        return [{"label": "LGMED Innovation Action"}, {"label": "e-SIRA"}]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        scope = stats.scope_for(user, self.request.GET.get("scope"))
        my_steps = (
            user.esira_steps.filter(status__in=list(OPEN_STEP_STATUSES))
            .exclude(document__status__in=[
                DocumentStatus.COMPLETED, DocumentStatus.REJECTED, DocumentStatus.CANCELLED,
            ])
            .select_related("document", "sender").order_by("routed_at")
        )
        visible = perms.visible_documents(user)
        recent = AuditEntry.objects.filter(document__in=visible).exclude(
            action__in=[AuditAction.VIEWED, AuditAction.DOWNLOADED]
        ).select_related("document")[:10]
        context.update({
            "scope": scope,
            "cards": stats.cards(user, scope),
            "my_steps": my_steps[:8],
            "my_steps_count": my_steps.count(),
            "my_out": EsiraDocument.objects.filter(
                owner=user, status__in=stats.OUT_STATUSES + [DocumentStatus.AWAITING_SIGNATURE],
            ).order_by("-updated_at")[:8],
            "ready_to_close": EsiraDocument.objects.filter(
                owner=user,
                status__in=[DocumentStatus.FULLY_SIGNED, DocumentStatus.ROUTING_COMPLETED],
            ).order_by("-updated_at")[:8],
            "drafts": EsiraDocument.objects.filter(
                owner=user, status=DocumentStatus.DRAFT,
            ).order_by("-updated_at")[:5],
            "recent": recent,
            "certificates": user.esira_certificates.all()[:5],
            "has_usable_certificate": any(
                c.is_usable for c in user.esira_certificates.filter(
                    status=SigningCertificate.Status.VERIFIED,
                )
            ),
            "setup": signing_setup(),
            "as_of": timezone.localtime(),
        })
        return context


class StatsView(EsiraMixin, View):
    """The dashboard figures as JSON, so the page can refresh them in place."""

    def get(self, request):
        scope = stats.scope_for(request.user, request.GET.get("scope"))
        return JsonResponse({
            "scope": scope,
            "as_of": dateformat.format(timezone.localtime(), "j F Y, g:i A"),
            "figures": stats.compute(request.user, scope),
        })


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------


class DocumentListView(EsiraMixin, ModuleListView):
    model = EsiraDocument
    template_name = "dashboard/esira/list.html"
    page_title = "e-SIRA Documents"
    page_subtitle = "Every document you own, have been routed, or oversee"
    module_label = "e-SIRA Documents"
    module_key = "esira"
    list_label = "Documents"
    tab = "documents"
    search_placeholder = "Search reference no., title, type, owner..."
    search_fields = (
        "reference_no", "title", "document_type", "description",
        "owner__first_name", "owner__last_name",
    )
    filter_fields = (("status", "Status", DocumentStatus.choices),)
    virtual_filters = ("view", "period", "scope")
    sort_fields = ("reference_no", "title", "status", "created_at", "updated_at", "owner__last_name")
    default_sort = "-updated_at"
    create_url_name = "esira:upload"
    create_label = "Upload / Scan Document"
    empty_icon = "file"
    export_columns = (
        ("Reference no.", "reference_no"),
        ("Title", "title"),
        ("Type", "document_type"),
        ("Owner", "owner.get_display_name"),
        ("Status", "get_status_display"),
        ("Pages", "page_count"),
        ("Uploaded", "created_at"),
        ("Routed", "routed_at"),
        ("Completed", "completed_at"),
    )

    VIEWS = {
        "awaiting_me": "Awaiting my signature",
        "needs_me": "Waiting on me",
        "mine": "Owned by me",
        "out": "Out for signature",
        "awaiting_signature": "Awaiting any signature",
        "signed_by_me": "Signed by me",
        "acted_by_me": "Approved / reviewed / acknowledged by me",
        "handled_by_me": "Signed or acted on by me",
        "signed_by_office": "Signed (office)",
        "acted_by_office": "Routed and acted on (office)",
        "handled_by_office": "Signed or acted on (office)",
    }

    def get_breadcrumbs(self):
        return [{"label": "e-SIRA", "url": reverse("esira:dashboard")}, {"label": "Documents"}]

    def get_base_queryset(self):
        return perms.visible_documents(self.request.user).select_related("owner")

    @property
    def office(self):
        return stats.scope_for(self.request.user, self.request.GET.get("scope")) == "office"

    def apply_extra_filters(self, queryset):
        user = self.request.user
        view = self.request.GET.get("view", "")
        since = None
        if self.request.GET.get("period") == "week":
            since = timezone.now() - timedelta(days=7)

        non_sign_done = [s for s in DONE_STEP_STATUSES if s != "SIGNED"]
        open_steps = list(OPEN_STEP_STATUSES)

        def signed(who):
            q = Q(signatures__isnull=False)
            if who is not None:
                q &= Q(signatures__signer=who)
            if since:
                q &= Q(signatures__signed_at__gte=since)
            return q

        def acted(who):
            q = Q(steps__status__in=non_sign_done) & ~Q(steps__action=StepAction.SIGN)
            if who is not None:
                q &= Q(steps__recipient=who)
            if since:
                q &= Q(steps__acted_at__gte=since)
            return q

        if view == "awaiting_me":
            queryset = queryset.filter(
                steps__recipient=user, steps__action=StepAction.SIGN,
                steps__status__in=open_steps,
            )
        elif view == "needs_me":
            queryset = queryset.filter(steps__recipient=user, steps__status__in=open_steps)
        elif view == "mine":
            queryset = queryset.filter(owner=user)
        elif view == "out":
            queryset = queryset.filter(status__in=stats.OUT_STATUSES)
            if not self.office:
                queryset = queryset.filter(owner=user)
        elif view == "awaiting_signature":
            queryset = queryset.filter(
                steps__action=StepAction.SIGN, steps__status__in=open_steps,
            )
        elif view == "signed_by_me":
            queryset = queryset.filter(signed(user))
        elif view == "acted_by_me":
            queryset = queryset.filter(acted(user))
        elif view == "handled_by_me":
            queryset = queryset.filter(signed(user) | acted(user))
        elif view == "signed_by_office":
            queryset = queryset.filter(signed(None))
        elif view == "acted_by_office":
            queryset = queryset.filter(acted(None))
        elif view == "handled_by_office":
            queryset = queryset.filter(signed(None) | acted(None))
        return queryset.distinct()

    def is_filtered(self):
        return super().is_filtered() or bool(self.request.GET.get("view"))

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["can_create"] = self.request.user.can_upload_esira
        context["quick_views"] = [
            (key, label) for key, label in self.VIEWS.items()
            if not key.endswith("_office") or self.request.user.can_oversee_esira
        ]
        context["current_view"] = self.request.GET.get("view", "")
        context["current_view_label"] = self.VIEWS.get(context["current_view"], "")
        context["period_week"] = self.request.GET.get("period") == "week"
        context["hidden_params"] = [
            {"name": name, "value": self.request.GET.get(name, "")}
            for name in ("view", "period", "scope")
        ]
        return context


class UploadView(EsiraMixin, FormView):
    capability = "can_upload_esira"
    form_class = UploadForm
    template_name = "dashboard/esira/upload.html"
    page_title = "Upload or Scan a Document"
    page_subtitle = "The original is kept unchanged; every signature is added as a new version"
    tab = "documents"

    def form_valid(self, form):
        data = form.cleaned_data
        try:
            document = workflow.create_document(
                self.request.user,
                title=data["title"],
                description=data["description"],
                document_type=data["document_type"],
                pdf_file=data["pdf_file"] if data["mode"] == "upload" else None,
                scan_images=data["scan_images"] if data["mode"] == "scan" else None,
            )
        except workflow.WorkflowError as exc:
            form.add_error(None, str(exc))
            return self.form_invalid(form)
        messages.success(
            self.request,
            f"{document.reference_no} uploaded. Place the signature boxes, then "
            "sign it yourself or route it for signature.",
        )
        return redirect("esira:workspace", pk=document.pk)


class DocumentDetailView(DocumentMixin, TemplateView):
    """The tracking page: status, route, signatures, versions and trail."""

    template_name = "dashboard/esira/detail.html"
    tab = "documents"

    def get_context_data(self, **kwargs):
        document = self.get_document()
        self.page_title = document.reference_no
        user = self.request.user
        workflow.record_view(document, user, self.request, what="tracking page")
        document.refresh_from_db()
        context = super().get_context_data(**kwargs)

        trail = document.audit_entries.select_related("actor")
        flags = _flags(user, document)
        if not flags["can_view_audit"]:
            trail = trail.exclude(action__in=[AuditAction.VIEWED, AuditAction.DOWNLOADED])

        context.update(flags)
        context.update({
            "document": document,
            "page_subtitle": document.title,
            "steps": document.steps.select_related("sender", "recipient").order_by("sequence"),
            "versions": document.versions.select_related("created_by").order_by("-number"),
            "signatures": document.signatures.select_related("signer", "result_version"),
            "boxes": document.boxes.select_related("signer", "signature").order_by("page", "pk"),
            "trail": trail[:200],
            "act_form": ActForm(user=user),
            "cancel_form": CancelForm(),
            "current_version": document.current_version,
        })
        return context


class WorkspaceView(DocumentMixin, TemplateView):
    """The PDF signing workspace: preview on the left, tools on the right."""

    template_name = "dashboard/esira/workspace.html"
    page_title = "Signing Workspace"
    tab = "documents"

    def get_context_data(self, **kwargs):
        document = self.get_document()
        user = self.request.user
        workflow.record_view(document, user, self.request, what="signing workspace")
        document.refresh_from_db()
        context = super().get_context_data(**kwargs)
        flags = _flags(user, document)
        setup = signing_setup()
        version = document.current_version
        context.update(flags)
        context.update({
            "document": document,
            "page_subtitle": f"{document.reference_no} - {document.title}",
            "version": version,
            "setup": setup,
            "sign_form": sign_form_for(user, setup["backend"]),
            **style_sample_context(user),
            "usable_certificates": [
                c for c in user.esira_certificates.filter(
                    status=SigningCertificate.Status.VERIFIED,
                ) if c.is_usable
            ],
            "my_box_count": document.boxes.filter(signer=user, signature__isnull=True).count(),
            "workspace_config": {
                "fileUrl": reverse("esira:file", args=[document.pk]) + f"?v={version.number}",
                "boxesUrl": reverse("esira:boxes", args=[document.pk]),
                "pdfjsUrl": static("vendor/pdfjs/pdf.min.mjs"),
                "workerUrl": static("vendor/pdfjs/pdf.worker.min.mjs"),
                "pageCount": document.page_count,
                "userId": user.pk,
                "userName": user.get_display_name(),
                "isDraft": document.is_draft,
                "canEdit": flags["can_edit_boxes"],
                "canSign": flags["can_sign"],
                "signers": (
                    [{"id": u.pk, "name": u.get_display_name()} for u in active_users()]
                    if document.is_draft and flags["can_edit_boxes"]
                    else [{"id": user.pk, "name": user.get_display_name()}]
                ),
            },
        })
        return context


class BoxesView(DocumentMixin, View):
    """GET the boxes on a document; POST the new set this user may edit."""

    def payload(self, document):
        user = self.request.user
        boxes = []
        for box in document.boxes.select_related("signer").order_by("page", "pk"):
            item = box.as_dict()
            item["editable"] = (
                not box.is_applied and perms.can_edit_boxes(user, document, box.signer)
            )
            boxes.append(item)
        return {"boxes": boxes, "status": document.get_status_display()}

    def get(self, request, pk):
        return JsonResponse(self.payload(self.get_document()))

    def post(self, request, pk):
        document = self.get_document()
        try:
            body = json.loads(request.body.decode("utf-8") or "{}")
        except (ValueError, UnicodeDecodeError):
            return JsonResponse({"error": "The request could not be read."}, status=400)
        try:
            summary = workflow.save_boxes(document, request.user, body.get("boxes"))
        except PermissionDenied as exc:
            return JsonResponse({"error": str(exc) or "Not permitted."}, status=403)
        except workflow.WorkflowError as exc:
            return JsonResponse({"error": str(exc)}, status=400)
        document.refresh_from_db()
        data = self.payload(document)
        data["saved"] = summary
        return JsonResponse(data)


@method_decorator(xframe_options_sameorigin, name="dispatch")
class FileView(DocumentMixin, View):
    """
    A stored version, streamed after its digest has been checked.

    ?v=<number> picks a version (default: the current one); ?download=1 sends
    it as an attachment and records the download.
    """

    def get(self, request, pk):
        document = self.get_document()
        versions = document.versions.all()
        number = request.GET.get("v")
        if number:
            version = get_object_or_404(versions, number=number)
        else:
            version = versions.order_by("-number").first()
        if version is None:
            raise Http404("No file.")
        try:
            data = version.read_verified()
        except FileIntegrityError:
            log(AuditAction.INTEGRITY_FAILURE, actor=request.user, document=document,
                version=version,
                detail=f"v{version.number} no longer matches its recorded SHA-256; not served")
            raise PermissionDenied(
                "This file has been altered outside the system and will not be served."
            )
        except (FileNotFoundError, OSError):
            raise Http404("The file is not present in storage.")

        download = request.GET.get("download") == "1"
        suffix = "original" if version.number == 1 else f"v{version.number}-signed"
        filename = f"{document.reference_no}-{suffix}.pdf"
        if download:
            log(AuditAction.DOWNLOADED, actor=request.user, document=document,
                version=version, detail=f"Downloaded v{version.number} ({filename})")
        response = FileResponse(
            io.BytesIO(data), as_attachment=download, filename=filename,
            content_type="application/pdf",
        )
        response["Cache-Control"] = "private, no-store"
        response["X-Content-Type-Options"] = "nosniff"
        return response


# ---------------------------------------------------------------------------
# Workflow actions
# ---------------------------------------------------------------------------


class SignView(DocumentMixin, View):
    def post(self, request, pk):
        document = self.get_document()
        backend = get_backend()
        form = sign_form_for(request.user, backend, request.POST, request.FILES)
        workspace = redirect("esira:workspace", pk=document.pk)
        if not form.is_valid():
            for field_errors in form.errors.values():
                for error in field_errors:
                    messages.error(request, error)
            return workspace
        data = form.cleaned_data
        credentials = {}
        if form.stored:
            credentials = {"stored": True, "passphrase": data["passphrase"]}
        elif backend.collects_credentials:
            credentials = {
                "pkcs12": data["certificate_file"].read(),
                "passphrase": data["passphrase"],
            }
        try:
            signature = workflow.sign(
                document, request.user, credentials=credentials,
                reason=data["reason"], remarks=data["remarks"],
                style=data["style"],
            )
        except workflow.WorkflowError as exc:
            messages.error(request, f"The document was not signed. {exc}")
            return workspace
        finally:
            credentials.clear()
        note = "" if signature.chain_trusted else (
            " This certificate is NOT verified against the DICT PNPKI chain on "
            "this server, so the signature is a test signature only."
        )
        messages.success(
            request,
            f"Signed {signature.box_count} box{'es' if signature.box_count != 1 else ''} "
            f"on {document.reference_no}. The signed file is version "
            f"{signature.result_version.number}.{note}",
        )
        return redirect("esira:detail", pk=document.pk)


class RouteView(DocumentMixin, TemplateView):
    template_name = "dashboard/esira/route.html"
    page_title = "Route for Signature and Approval"
    tab = "documents"

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            document = self.get_document()
            if not perms.can_route(request.user, document):
                messages.error(request, "Only the owner can route a draft.")
                return redirect(document.get_absolute_url())
        return super().dispatch(request, *args, **kwargs)

    def initial_steps(self, document):
        """One signature step per person with a box, in the order the boxes appear."""
        seen, initial = set(), []
        for box in document.boxes.filter(signature__isnull=True).order_by("page", "y", "pk"):
            if box.signer_id in seen:
                continue
            seen.add(box.signer_id)
            initial.append({
                "recipient": box.signer_id,
                "action": StepAction.SIGN,
                "purpose": "For signature",
            })
        return initial or [{"action": StepAction.SIGN, "purpose": "For signature"}]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        document = self.get_document()
        context["document"] = document
        context["page_subtitle"] = f"{document.reference_no} - {document.title}"
        context.setdefault("formset", RouteFormSet(initial=self.initial_steps(document), prefix="steps"))
        context["box_signers"] = (
            document.boxes.filter(signature__isnull=True)
            .values("signer__first_name", "signer__last_name", "signer__username")
            .distinct()
        )
        return context

    def post(self, request, pk):
        document = self.get_document()
        formset = RouteFormSet(request.POST, prefix="steps")
        if not formset.is_valid():
            messages.error(request, "The route could not be saved. Correct the highlighted rows.")
            return self.render_to_response(self.get_context_data(formset=formset))
        rows = sorted(
            (f for f in formset.forms if f.cleaned_data and not f.cleaned_data.get("DELETE")),
            key=lambda f: formset.forms.index(f),
        )
        steps = [
            {
                "recipient": f.cleaned_data["recipient"],
                "action": f.cleaned_data["action"],
                "purpose": f.cleaned_data["purpose"],
                "due_date": f.cleaned_data["due_date"],
            }
            for f in rows
        ]
        try:
            workflow.start_routing(document, request.user, steps)
        except workflow.WorkflowError as exc:
            messages.error(request, str(exc))
            return self.render_to_response(self.get_context_data(formset=formset))
        messages.success(request, f"{document.reference_no} is on its way to {steps[0]['recipient'].get_display_name()}.")
        return redirect(document.get_absolute_url())


class ActView(DocumentMixin, View):
    def post(self, request, pk):
        document = self.get_document()
        form = ActForm(request.POST, user=request.user)
        if not form.is_valid():
            for errors in form.errors.values():
                for error in errors:
                    messages.error(request, error)
            return redirect(document.get_absolute_url())
        data = form.cleaned_data
        try:
            workflow.act(
                document, request.user,
                decision=data["decision"],
                remarks=data["remarks"],
                forward_to=data.get("forward_to"),
                forward_action=data.get("forward_action") or None,
                forward_purpose=data.get("forward_purpose") or "",
            )
        except workflow.WorkflowError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(
                request,
                "The document was rejected and returned to its owner."
                if data["decision"] == "reject" else "Your action was recorded.",
            )
        return redirect(document.get_absolute_url())


class CompleteView(DocumentMixin, View):
    def post(self, request, pk):
        document = self.get_document()
        workflow.complete(document, request.user)
        messages.success(request, f"{document.reference_no} is completed and locked.")
        return redirect(document.get_absolute_url())


class CancelView(DocumentMixin, View):
    def post(self, request, pk):
        document = self.get_document()
        form = CancelForm(request.POST)
        if not form.is_valid():
            messages.error(request, "Give the reason for cancelling.")
            return redirect(document.get_absolute_url())
        try:
            workflow.cancel(document, request.user, form.cleaned_data["reason"])
        except workflow.WorkflowError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, f"{document.reference_no} was cancelled.")
        return redirect(document.get_absolute_url())


class VerifyView(DocumentMixin, TemplateView):
    """Check every signature in a version cryptographically, from the file itself."""

    template_name = "dashboard/esira/verify.html"
    page_title = "Signature Verification"
    tab = "documents"

    def get_context_data(self, **kwargs):
        from .verification import verify_pdf

        context = super().get_context_data(**kwargs)
        document = self.get_document()
        number = self.request.GET.get("v")
        versions = document.versions.all()
        version = (
            get_object_or_404(versions, number=number) if number
            else versions.order_by("-number").first()
        )
        integrity_ok, reports = True, []
        try:
            data = version.read_verified()
            reports = verify_pdf(data, document.signatures.all())
        except FileIntegrityError:
            integrity_ok = False
            log(AuditAction.INTEGRITY_FAILURE, actor=self.request.user, document=document,
                version=version, detail=f"v{version.number} failed its digest check during verification")
        log(
            AuditAction.SIGNATURES_VERIFIED, actor=self.request.user, document=document,
            version=version,
            detail=(
                f"v{version.number}: {len(reports)} signature(s), "
                f"{sum(1 for r in reports if r.intact and r.valid)} intact and valid"
                if integrity_ok else f"v{version.number}: digest mismatch"
            ),
        )
        context.update({
            "document": document,
            "page_subtitle": f"{document.reference_no} - version {version.number}",
            "version": version,
            "versions": versions.order_by("-number"),
            "integrity_ok": integrity_ok,
            "reports": reports,
            "roots_installed": len(trust_roots()),
        })
        return context


# ---------------------------------------------------------------------------
# Certificates
# ---------------------------------------------------------------------------


class CertificateListView(EsiraMixin, TemplateView):
    """
    My Digital Certificate: the .p12 kept on file, the signature image, and
    whether signing asks for the password. Each card posts its own `action`.
    """

    template_name = "dashboard/esira/certificates.html"
    page_title = "My Digital Certificate"
    page_subtitle = "Keep your DICT PNPKI certificate and default signature image ready for signing"
    tab = "certificates"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        profile = SignerProfile.for_user(user)
        context.setdefault("form", CertificateRegisterForm(prefix="cert"))
        context.setdefault("signature_form", SignatureImageForm(prefix="sig"))
        context.update({
            "certificates": user.esira_certificates.select_related("reviewed_by"),
            "stored": workflow.stored_certificate(user),
            "profile": profile,
            "setup": signing_setup(),
        })
        return context

    def post(self, request):
        user = request.user
        action = request.POST.get("action")
        if action == "certificate":
            form = CertificateRegisterForm(request.POST, request.FILES, prefix="cert")
            if not form.is_valid():
                return self.render_to_response(self.get_context_data(form=form))
            try:
                record = workflow.register_certificate(
                    user, pkcs12_file=form.cleaned_data["certificate_file"],
                    passphrase=form.cleaned_data["passphrase"],
                )
            except workflow.WorkflowError as exc:
                form.add_error(None, str(exc))
                return self.render_to_response(self.get_context_data(form=form))
            if record.created:
                messages.success(
                    request,
                    f"Certificate for {record.subject_common_name or record.subject} saved. "
                    "An administrator will verify it before you can sign with it.",
                )
            else:
                messages.success(request, "Your stored certificate file was replaced.")
        elif action == "signature":
            form = SignatureImageForm(request.POST, request.FILES, prefix="sig")
            if not form.is_valid():
                return self.render_to_response(self.get_context_data(signature_form=form))
            workflow.set_signature_image(user, form.cleaned_data["signature_image"])
            messages.success(request, "Your signature image was saved.")
        elif action == "remove_signature":
            workflow.set_signature_image(user, None)
            messages.success(request, "Your signature image was removed.")
        elif action == "protection":
            required = request.POST.get("require_passphrase") == "on"
            workflow.set_require_passphrase(user, required)
            messages.success(
                request,
                "Your certificate password will be asked for on every signature."
                if required else
                "Signing will use your stored password without asking.",
            )
        elif action == "remove_certificate":
            record = get_object_or_404(
                SigningCertificate, pk=request.POST.get("certificate"), user=user,
            )
            workflow.remove_stored_certificate(user, record)
            messages.success(request, "Your stored certificate file and password were deleted.")
        return redirect("esira:certificates")


class SignatureStyleView(EsiraMixin, TemplateView):
    """My Signature Style: the built-in styles and the signer's custom ones."""

    template_name = "dashboard/esira/signature_styles.html"
    page_title = "My Signature Style"
    page_subtitle = (
        "Configure the signature styles available when you sign documents. "
        "Custom styles are saved individually from each setup dialog."
    )
    tab = "styles"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        context.setdefault("form", SignatureStyleForm())
        context.update(style_sample_context(user))
        context.update({
            "styles": workflow.signature_styles(user),
            "default_key": workflow.default_style_key(user),
            "max_styles": SignatureStyle.MAX_PER_USER,
            "can_add": user.esira_signature_styles.count() < SignatureStyle.MAX_PER_USER,
        })
        return context

    def post(self, request):
        user = request.user
        action = request.POST.get("action")
        if action == "add":
            form = SignatureStyleForm(request.POST, request.FILES)
            if not form.is_valid():
                return self.render_to_response(self.get_context_data(form=form, open_dialog=True))
            try:
                row = workflow.add_signature_style(
                    user, name=form.cleaned_data["name"], content=form.cleaned_data["image"],
                )
            except workflow.WorkflowError as exc:
                form.add_error(None, str(exc))
                return self.render_to_response(self.get_context_data(form=form, open_dialog=True))
            messages.success(request, f"Signature style \u201c{row.name}\u201d saved.")
        elif action == "delete":
            row = get_object_or_404(SignatureStyle, pk=request.POST.get("style"), user=user)
            workflow.delete_signature_style(user, row)
            messages.success(request, f"Signature style \u201c{row.name}\u201d deleted.")
        return redirect("esira:signature_styles")


class SignatureStyleImageView(EsiraMixin, View):
    """The picture of one of the signed-in user's own custom styles."""

    def get(self, request, pk):
        row = get_object_or_404(SignatureStyle, pk=pk, user=request.user)
        try:
            handle = row.image.open("rb")
        except FileNotFoundError:
            raise Http404("The style image is missing from storage.")
        response = FileResponse(handle, content_type="image/png")
        response["Cache-Control"] = "private, max-age=86400"
        return response


class CertificatePasswordView(EsiraMixin, View):
    """Show the signer their own stored certificate password. POST only, logged."""

    def post(self, request):
        try:
            password = workflow.reveal_passphrase(request.user)
        except workflow.WorkflowError as exc:
            return JsonResponse({"error": str(exc)}, status=404)
        response = JsonResponse({"password": password})
        response["Cache-Control"] = "no-store"
        return response


class SignatureImageView(EsiraMixin, View):
    """The signed-in user's own signature image, from the protected root."""

    def get(self, request):
        profile = SignerProfile.objects.filter(user=request.user).first()
        if profile is None or not profile.signature_image:
            raise Http404("No signature image.")
        try:
            handle = profile.signature_image.open("rb")
        except FileNotFoundError:
            raise Http404("The signature image is missing from storage.")
        response = FileResponse(handle, content_type="image/png")
        response["Cache-Control"] = "private, no-cache"
        return response


class CertificateReviewView(EsiraMixin, TemplateView):
    capability = "can_verify_signing_certificates"
    template_name = "dashboard/esira/certificate_review.html"
    page_title = "PNPKI Certificate Verification"
    page_subtitle = (
        "Confirm each certificate was issued by DICT to the employee who registered it"
    )
    tab = "verification"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        certificates = SigningCertificate.objects.select_related("user", "reviewed_by")
        context["pending"] = certificates.filter(status=SigningCertificate.Status.PENDING)
        context["others"] = certificates.exclude(status=SigningCertificate.Status.PENDING)[:100]
        context["setup"] = signing_setup()
        return context

    def post(self, request):
        record = get_object_or_404(SigningCertificate, pk=request.POST.get("certificate"))
        form = CertificateReviewForm(request.POST)
        if not form.is_valid():
            messages.error(request, "Choose an action.")
            return redirect("esira:certificate_review")
        try:
            workflow.review_certificate(
                record, request.user,
                decision=form.cleaned_data["decision"],
                remarks=form.cleaned_data["remarks"],
            )
        except workflow.WorkflowError as exc:
            messages.error(request, str(exc))
        else:
            record.refresh_from_db()
            messages.success(
                request,
                f"{record.user.get_display_name()}'s certificate is now "
                f"{record.get_status_display().lower()}.",
            )
        return redirect("esira:certificate_review")


# ---------------------------------------------------------------------------
# Office-wide audit trail
# ---------------------------------------------------------------------------


class AuditTrailView(EsiraMixin, ModuleListView):
    capability = "can_oversee_esira"
    model = AuditEntry
    template_name = "dashboard/esira/audit.html"
    page_title = "e-SIRA Audit Trail"
    page_subtitle = "Every upload, placement, signature, routing and decision"
    module_label = "e-SIRA Audit Entries"
    module_key = "esira"
    tab = "audit"
    search_placeholder = "Search reference no., person, detail..."
    search_fields = ("document_reference", "actor_label", "detail")
    filter_fields = (("action", "Action", AuditAction.choices),)
    sort_fields = ("timestamp", "action", "actor_label", "document_reference")
    default_sort = "-timestamp"
    date_field = "timestamp__date"
    date_field_label = "Date"
    empty_icon = "audit"
    export_columns = (
        ("Timestamp", "timestamp"),
        ("Reference no.", "document_reference"),
        ("Action", "get_action_display"),
        ("Actor", "actor_label"),
        ("Role", "actor_role"),
        ("Detail", "detail"),
        ("Version", "version_number"),
        ("IP address", "ip_address"),
    )

    def get_breadcrumbs(self):
        return [{"label": "e-SIRA", "url": reverse("esira:dashboard")}, {"label": "Audit Trail"}]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["can_create"] = False
        return context
