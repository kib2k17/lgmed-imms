# URL → File Map

Where the code behind each page lives. Paths are relative to the project root. Template names in the tables are relative to `templates/`, and `module_form.html` / `module_confirm_delete.html` mean `templates/dashboard/...`.

## How to trace any page

1. **Root routing:** [config/urls.py](../config/urls.py) sends each prefix to an app (`/app/incoming/` → `incoming/urls.py`).
2. **App routing:** `<app>/urls.py` maps the rest of the path to a view.
3. **View:** `<app>/views.py` has the logic, permissions and context.
4. **Form:** `<app>/forms.py` sets the fields shown on create/edit pages.
5. **Model:** `<app>/models.py` holds the database fields, choices and statuses.
6. **Template:** `templates/...` holds the HTML.

**Shared templates.** Most *create*, *edit* and *delete* pages don't have a template of their own. They use the generic ones from [core/views_base.py](../core/views_base.py):

| Page type | Template | Base view |
|---|---|---|
| New / Edit form | [templates/dashboard/module_form.html](../templates/dashboard/module_form.html) | `ModuleCreateView`, `ModuleUpdateView` |
| Delete confirm | [templates/dashboard/module_confirm_delete.html](../templates/dashboard/module_confirm_delete.html) | `ModuleDeleteView` |
| Plain list (fallback) | [templates/dashboard/module_list.html](../templates/dashboard/module_list.html) | `ModuleListView` |

To change the **fields** on a form, edit the app's `forms.py`. To change the **layout** of every form, edit `module_form.html`.

**Page frame (all internal pages):** [templates/base.html](../templates/base.html), [templates/includes/sidebar.html](../templates/includes/sidebar.html), [templates/includes/topbar.html](../templates/includes/topbar.html), [templates/includes/footer_app.html](../templates/includes/footer_app.html). Sidebar menu items are defined in [core/navigation.py](../core/navigation.py).
**Styles / scripts:** [static/css/app.css](../static/css/app.css), [static/js/app.js](../static/js/app.js).

---

## Example: `/app/incoming/new/` (Record Incoming Document)

| Part | File |
|---|---|
| Route | [incoming/urls.py](../incoming/urls.py): `path("new/", ..., name="create")` |
| View | [incoming/views.py](../incoming/views.py): `IncomingCreateView` (page title, subtitle, success message) |
| Form fields | [incoming/forms.py](../incoming/forms.py): `IncomingDocumentForm` |
| Model | [incoming/models.py](../incoming/models.py): `IncomingDocument`, `IncomingStatus`, `Priority` |
| After saving | [incoming/workflow.py](../incoming/workflow.py): `record_received()` |
| Template | [templates/dashboard/module_form.html](../templates/dashboard/module_form.html) (shared) |

---

## Internal system (`/app/...`, login required)

### Dashboard & core: `core/`
| URL | View | Template |
|---|---|---|
| `/app/` | `dashboard` | `dashboard/dashboard.html` |
| `/app/design-system/` | `components` | `dashboard/components.html` |

### Incoming Monitoring: `/app/incoming/` → `incoming/`
Forms: `incoming/forms.py`. Workflow: `incoming/workflow.py`. Reports logic: `incoming/reports.py`.
| URL | View | Template / Form |
|---|---|---|
| `/app/incoming/` | `IncomingListView` | `dashboard/incoming/list.html` |
| `/app/incoming/new/` | `IncomingCreateView` | `module_form.html` · `IncomingDocumentForm` |
| `/app/incoming/dashboard/` | `IncomingDashboardView` | `dashboard/incoming/dashboard.html` |
| `/app/incoming/reports/` | `IncomingReportsView` | `dashboard/incoming/reports.html` |
| `/app/incoming/<id>/` | `IncomingDetailView` | `dashboard/incoming/detail.html` |
| `/app/incoming/<id>/edit/` | `IncomingUpdateView` | `module_form.html` · `IncomingDocumentForm` |
| `/app/incoming/<id>/delete/` | `IncomingDeleteView` | `module_confirm_delete.html` |
| `/app/incoming/<id>/review/` | `ReviewView` (POST) | `ReviewForm` |
| `/app/incoming/<id>/assign/` | `AssignView` (POST) | `AssignmentForm` |
| `/app/incoming/<id>/acknowledge/` | `AcknowledgeView` (POST) — moves the document to Outgoing | |

### Outgoing: `/app/outgoing/` → `outgoing/`
Acknowledged documents continue here under their LGMED code; `<id>` is the outgoing record.
| URL | View | Template |
|---|---|---|
| `/app/outgoing/` | `OutgoingListView` | `dashboard/outgoing/list.html` |
| `/app/outgoing/<id>/` | `OutgoingDetailView` | `dashboard/outgoing/detail.html` |
| `/app/outgoing/<id>/update/` | `AddUpdateView` (POST) | `IncomingUpdateForm` |
| `/app/outgoing/<id>/return/` | `ReturnView` (POST) | `ReturnForm` |
| `/app/outgoing/<id>/sent/` | `TransmittalView` | `module_form.html` · `OutgoingResponseForm` |

### Data Sync (spreadsheet import): `/app/sync/` → `datasync/`
Import engine: `datasync/engine.py`, `reader.py`, `profiles.py`, `targets.py`.
| URL | View | Template |
|---|---|---|
| `/app/sync/` | `SyncHomeView` | `dashboard/sync/home.html` |
| `/app/sync/<id>/` | `BatchView` | `dashboard/sync/batch.html` |
| `/app/sync/<id>/sheets/` · `commit/` · `discard/` | `SheetSelectionView` · `CommitView` · `DiscardView` (POST) | |

### Programs / PPA: `/app/programs/` → `programs/`
`<level>` is one of `program`, `project`, `sub-project`, `activity`. Forms: `programs/forms.py`. Publishing rules: `programs/publishing.py`, `screening.py`, `public.py`.
| URL | View | Template |
|---|---|---|
| `/app/programs/` | `WorkbenchView` | `dashboard/ppa/workbench.html` |
| `/app/programs/queue/` | `ReviewQueueView` | `dashboard/ppa/queue.html` |
| `/app/programs/program/new/` | `RecordCreateView` | `module_form.html` |
| `/app/programs/<level>/<id>/add/<level>/` | `RecordCreateView` | `module_form.html` |
| `/app/programs/<level>/<id>/` | `RecordDetailView` | `dashboard/ppa/detail.html` |
| `/app/programs/<level>/<id>/edit/` | `RecordUpdateView` | `module_form.html` |
| `/app/programs/<level>/<id>/delete/` | `RecordDeleteView` | `module_confirm_delete.html` |
| `/app/programs/<level>/<id>/preview/` | `RecordPreviewView` | `public/ppa_detail.html` |
| `/app/programs/<level>/<id>/submit/` · `decide/` · `publish/` · `unpublish/` · `archive/` · `restore/` | `Record*View` (POST) | |
| `/app/programs/<level>/<id>/documents/new/` | `DocumentUploadView` | `dashboard/ppa/document_upload.html` |
| `/app/programs/<level>/<id>/photographs/arrange/` | `PhotoArrangeView` | `dashboard/ppa/photo_arrange.html` |
| `/app/programs/documents/<id>/` | `DocumentReviewView` | `dashboard/ppa/document_review.html` |
| `/app/programs/documents/<id>/delete/` | `DocumentDeleteView` | `module_confirm_delete.html` |
| `/app/programs/documents/<id>/rescreen/` · `authority/` · `publish/` · `withdraw/` · `file/` | `Document*View` | |
| `/app/programs/authorities/` | `AuthorityListView` | `dashboard/ppa/authority_list.html` |
| `/app/programs/authorities/new/` · `<id>/edit/` | `AuthorityCreateView` · `AuthorityUpdateView` | `module_form.html` |
| `/app/programs/authorities/<id>/` | `AuthorityDetailView` | `dashboard/ppa/authority_detail.html` |

### Monitoring: `/app/monitoring/` → `monitoring/`
| URL | View | Template / Form |
|---|---|---|
| `/app/monitoring/` | `MonitoringListView` | `dashboard/monitoring/list.html` |
| `/app/monitoring/new/` · `<id>/edit/` | `MonitoringCreateView` · `MonitoringUpdateView` | `module_form.html` · `MonitoringActivityForm` |
| `/app/monitoring/<id>/` | `MonitoringDetailView` | `dashboard/monitoring/detail.html` |
| `/app/monitoring/<id>/delete/` | `MonitoringDeleteView` | `module_confirm_delete.html` |
| `/app/monitoring/<id>/attachments/add/` · `.../<aid>/delete/` | `AttachmentCreateView` · `AttachmentDeleteView` | |

### Documents: `/app/documents/` → `documents/`
Workflow: `documents/workflow.py`.
| URL | View | Template / Form |
|---|---|---|
| `/app/documents/` | `DocumentListView` | `dashboard/documents/list.html` |
| `/app/documents/new/` · `<id>/edit/` | `DocumentCreateView` · `DocumentUpdateView` | `module_form.html` · `DocumentForm` |
| `/app/documents/monitoring/` | `DocumentDashboardView` | `dashboard/documents/dashboard.html` |
| `/app/documents/retention/` | `RetentionRegisterView` | `dashboard/documents/retention.html` |
| `/app/documents/<id>/` | `DocumentDetailView` | `dashboard/documents/detail.html` |
| `/app/documents/<id>/delete/` | `DocumentDeleteView` | `module_confirm_delete.html` |
| `/app/documents/<id>/download/` · `versions/<vid>/` | `DocumentDownloadView` · `VersionDownloadView` | |
| `/app/documents/<id>/submit-review/` · `review/` · `assign/` · `start/` · `submit-approval/` · `complete/` · `cancel/` · `upload-version/` · `retention/` · `archive/` · `restore/` · `dispose/` | workflow views (POST) | |

### Standard CRUD modules
Each follows the same pattern: list, `new/`, `<id>/`, `<id>/edit/`, `<id>/delete/`. New/edit use `module_form.html` and delete uses `module_confirm_delete.html`.
| URL prefix | App | List / Detail templates | Form (`forms.py`) | Model |
|---|---|---|---|---|
| `/app/lgus/` | `lgus/` | `dashboard/lgus/list.html`, `detail.html` | `LGUForm` | `LGU` |
| `/app/services/` | `services/` | `dashboard/services/list.html`, `detail.html` | `FrontlineServiceForm` | `FrontlineService` |
| `/app/announcements/` | `announcements/` | `dashboard/announcements/list.html`, `detail.html` | `AnnouncementForm` | `Announcement` |
| `/app/reports/` | `reports/` | `dashboard/reports/list.html`, `detail.html` | `ReportForm` | `Report` |

### Calendar: `/app/calendar/` → `activities/`
| URL | View | Template |
|---|---|---|
| `/app/calendar/` | `CalendarView` | `dashboard/activities/calendar.html` |
| `/app/calendar/monitor/` | `ActivityMonitorView` | `dashboard/activities/monitor.html` |
| `/app/calendar/new/` · `<id>/edit/` | `ActivityCreateView` · `ActivityUpdateView` | `module_form.html` · `CalendarActivityForm` |
| `/app/calendar/<id>/` | `ActivityDetailView` | `dashboard/activities/detail.html` |
| `/app/calendar/<id>/delete/` | `ActivityDeleteView` | `module_confirm_delete.html` |
| `/app/calendar/<id>/progress/` | `ActivityProgressView` (POST) | |

### Division Updates / Accomplishments: `/app/updates/` → `updates/`
| URL | View | Template / Form |
|---|---|---|
| `/app/updates/` | `DivisionDashboardView` | `dashboard/updates/dashboard.html` |
| `/app/updates/entries/` | `DivisionUpdateListView` | `dashboard/updates/list.html` |
| `/app/updates/entries/new/` · `<id>/edit/` | `DivisionUpdateCreateView` · `DivisionUpdateUpdateView` | `module_form.html` · `DivisionUpdateForm` |
| `/app/updates/entries/<id>/` | `DivisionUpdateDetailView` | `dashboard/updates/detail.html` |
| `/app/updates/entries/<id>/attach/` | `AttachmentCreateView` | `UpdateAttachmentForm` |
| `/app/updates/weeks/` | `PeriodListView` | `dashboard/updates/period_list.html` |
| `/app/updates/weeks/new/` · `<id>/edit/` | `PeriodCreateView` · `PeriodUpdateView` | `module_form.html` · `ReportingPeriodForm` |
| `/app/updates/weeks/<id>/` | `PeriodDetailView` | `dashboard/updates/period_detail.html` |
| `/app/updates/weeks/<id>/submit/` | `PeriodSubmitView` | |
| `/app/updates/weeks/<id>/review/` | `PeriodReviewView` | `dashboard/updates/review.html` |
| `/app/updates/convocation/` · `weeks/<id>/convocation/` | `ConvocationView` | `dashboard/updates/convocation.html` |
| `/app/updates/public-disclosure/` | `PublicDisclosureView` | `dashboard/updates/disclosure.html` · `PublicDisclosureForm` |
| `/app/updates/weeks/<id>/pops/new/`, `pops/<id>/edit/` | `PopsCreateView` · `PopsUpdateView` | `PopsPlanUpdateForm` |
| `/app/updates/weeks/<id>/ways-forward/new/`, `ways-forward/<id>/edit/` | `WayForwardCreateView` · `WayForwardUpdateView` | `WayForwardForm` |

### Notifications, Analytics
| URL | App · View | Template |
|---|---|---|
| `/app/notifications/` | `notifications/` · `NotificationListView` | `dashboard/notifications/list.html` |
| `/app/notifications/<id>/open/` · `dismiss/` · `read-all/` | `open_notification` · `dismiss_notification` · `mark_all_read` | |
| `/app/analytics/` | `analytics/` · `AnalyticsView` (metrics in `analytics/metrics.py`) | `dashboard/analytics/analytics.html` |

### Administration
| URL | App · View | Template |
|---|---|---|
| `/app/settings/` | `administration/` · `SettingsView` | `dashboard/settings/settings.html` |
| `/app/settings/public-site/` | `PublicSiteView` | `dashboard/settings/public_site.html` |
| `/app/settings/reference/<slug>/...` | `reference_form` · `reference_delete` (lists in `administration/reference.py`) | |
| `/app/audit-logs/` | `audit/` · `AuditListView` | `dashboard/audit/list.html` |
| `/app/audit-logs/<id>/` | `AuditDetailView` | `dashboard/audit/detail.html` |

### Accounts, Users & Roles: `/accounts/` → `accounts/`
MFA logic: `accounts/mfa.py`, `totp.py`. Emails: `accounts/emails.py`. Privacy notice: `accounts/privacy.py`.
| URL | View | Template / Form |
|---|---|---|
| `/accounts/login/` (alias `/staff`) | `LoginView` | `registration/login.html` |
| `/accounts/login/verify/` | `MFAVerifyView` | `registration/mfa_verify.html` |
| `/accounts/mfa/setup/` | `MFASetupView` | `registration/mfa_setup.html` or `accounts/mfa_setup.html` |
| `/accounts/mfa/recovery-codes/` | `mfa_recovery_codes` | `accounts/mfa_recovery_codes.html` |
| `/accounts/profile/` | `profile` | `accounts/profile.html` |
| `/accounts/users/` | `UserListView` | `dashboard/users/list.html` |
| `/accounts/users/new/` · `<id>/edit/` | `UserCreateView` · `UserUpdateView` | `module_form.html` · `UserCreateForm` / `UserForm` |
| `/accounts/users/<id>/` | `UserDetailView` | `dashboard/users/detail.html` |
| `/accounts/users/<id>/password/` | `UserPasswordResetView` | `dashboard/users/password.html` |
| `/accounts/roles/` | `RoleListView` | `dashboard/roles/list.html` |
| `/django-admin/` | Django admin (each app's `admin.py`) | |

---

## Public website: `core/`
Views are in [core/views.py](../core/views.py) and routes in [core/urls.py](../core/urls.py). Frame: [templates/public_base.html](../templates/public_base.html), [templates/includes/footer.html](../templates/includes/footer.html), [templates/includes/public_page_header.html](../templates/includes/public_page_header.html).

| URL | View | Template |
|---|---|---|
| `/` | `home` | `public/home.html` |
| `/about/` | `public_about` | `public/about.html` |
| `/programs/` | `public_programs` | `public/programs.html` |
| `/programs/outcome/<slug>/` | `public_outcome` | `public/ppa_outcome.html` |
| `/programs/program\|project\|sub-project\|activity/<slug>/` | `public_program` etc. | `public/ppa_detail.html` |
| `/services/` | `public_services` | `public/services.html` |
| `/announcements/` | `public_announcements` | `public/news.html` |
| `/announcements/<slug>/` | `public_announcement` | `public/news_detail.html` |
| `/accomplishments/` | `public_updates` | `public/updates.html` |
| `/accomplishments/<id>/` | `public_update_week` | `public/update_week.html` |
| `/statistics/` | `public_statistics` | `public/statistics.html` |
| `/reports/` | `public_reports` | `public/reports.html` |
| `/documents/` | `public_documents` | `public/documents.html` |
| `/calendar/` | `public_calendar` | `public/calendar.html` |
| `/contact/` | `public_contact` | `public/contact.html` |
| (site switched off) | `public_view` wrapper | `public/unavailable.html` |

Error pages (403/404/500): [core/errors.py](../core/errors.py) → `templates/errors/`.
