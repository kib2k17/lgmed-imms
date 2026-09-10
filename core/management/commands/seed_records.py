"""
Populate the Phase 2 modules with illustrative records for demonstration.

    python manage.py seed_records

This creates reference data (program categories, document types) plus a spread
of programs, monitoring activities, services, reports and calendar entries, so
the modules, the dashboard charts and the public site can be shown working.

These are ILLUSTRATIVE records, not real ones. Clear them before the system
carries live data:

    python manage.py seed_records --clear

The LGU directory is not touched by this command - it is real reference data,
loaded by `seed_lgus`.
"""

import datetime
import random

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from activities.models import (
    ActivityStatus,
    ActivityType,
    CalendarActivity,
    Visibility,
)
from activities.models import Priority as ActivityPriority
from announcements.models import Announcement, AnnouncementCategory
from documents.models import Document, DocumentStatus, DocumentType
from incoming.models import IncomingDocument, IncomingStatus, IncomingUpdate, Priority
from lgus.models import LGU, ComplianceStatus
from monitoring.models import MonitoringActivity, MonitoringStatus
from programs.models import Program, ProgramCategory, ProgramStatus
from reports.models import Report, ReportPeriod, ReportStatus
from services.models import FrontlineService, ServiceType
from updates.models import ActivityType as UpdateActivityType
from updates.models import (
    DivisionUpdate,
    PopsPlanUpdate,
    ReportingPeriod,
    UpdateCategory,
    UpdateStatus,
    WayForward,
    week_bounds,
)

CATEGORIES = [
    ("Governance", "Local governance performance and oversight"),
    ("Capacity Development", "Training and technical assistance for LGUs"),
    ("Monitoring and Evaluation", "Assessment, validation and reporting"),
    ("Fiscal Administration", "Local revenue, budgeting and expenditure"),
    ("Disaster Risk Reduction", "Preparedness and resilience programs"),
    ("Social Services", "Programs supporting local social service delivery"),
]

SECTIONS = [
    ("Local Government Capability Development Section", "LGCDS"),
    ("Local Government Monitoring and Evaluation Section", "LGMES"),
    ("Field Operations Section", "FOS"),
    ("Administrative and Records Section", "ARS"),
]

# (name, code, retention years, action at end of retention). The periods are
# illustrative demo values - the Division sets its own in System Settings.
DOCUMENT_TYPES = [
    ("Memorandum", "MEMO", 5, "REVIEW"),
    ("Memorandum Circular", "MC", 10, "REVIEW"),
    ("Advisory", "ADV", 3, "DISPOSE"),
    ("Guidelines", "GUID", 10, "PERMANENT"),
    ("Monitoring Report", "MR", 5, "REVIEW"),
    ("Minutes of Meeting", "MIN", 10, "PERMANENT"),
    ("Certification", "CERT", 3, "DISPOSE"),
]

# (headline, category, days before today, lead paragraph, location, featured)
NEWS = [
    ("DILG Caraga strengthens anti-illegal drug advocacy in Butuan City",
     AnnouncementCategory.NEWS, 2,
     "The Division joined the regional anti-illegal drug advocacy caravan, "
     "briefing barangay officials on the reporting requirements of the "
     "Barangay Anti-Drug Abuse Council and the assistance available to them.",
     "Butuan City", True),
    ("Regional Peace and Order Council convenes for the third quarter",
     AnnouncementCategory.NEWS, 9,
     "LGMED presented the compliance figures of the region's cities and "
     "municipalities on the functionality of their local peace and order "
     "councils, together with the assistance planned for those still lagging.",
     "Butuan City", False),
    ("Advisory: submission of third quarter monitoring reports",
     AnnouncementCategory.ADVISORY, 14,
     "All city and municipal local government operations officers are "
     "reminded to submit their third quarter monitoring reports through the "
     "provincial offices on or before the end of the month.",
     "", False),
    ("Local governance audit begins in Agusan del Norte",
     AnnouncementCategory.ACTIVITY, 21,
     "Field validation teams started the annual local governance audit, "
     "covering financial administration, disaster preparedness and social "
     "protection services in the province's municipalities.",
     "Agusan del Norte", False),
    ("Crisis management training held for municipal officers",
     AnnouncementCategory.ACTIVITY, 30,
     "Municipal local government operations officers completed a three-day "
     "crisis management training covering incident command, public "
     "information and the coordination of local response.",
     "Surigao City", False),
    ("Region XIII cited for full compliance with the Full Disclosure Policy",
     AnnouncementCategory.COMMENDATION, 45,
     "The National Office commended the region for the complete and timely "
     "posting of local budget and procurement documents by all its cities "
     "and municipalities.",
     "", False),
]

PROGRAMS = [
    ("Seal of Good Local Governance", "Governance", ProgramStatus.ACTIVE),
    ("Barangay Development Plan Review", "Monitoring and Evaluation", ProgramStatus.ACTIVE),
    ("Full Disclosure Policy Compliance Monitoring", "Governance", ProgramStatus.ACTIVE),
    ("Local Governance Capacity Development Program", "Capacity Development", ProgramStatus.ACTIVE),
    ("Local Development Council Functionality Assessment", "Governance", ProgramStatus.ACTIVE),
    ("Annual Investment Program Validation", "Fiscal Administration", ProgramStatus.ACTIVE),
    ("Local Disaster Risk Reduction Fund Utilisation Review", "Disaster Risk Reduction", ProgramStatus.ACTIVE),
    ("Community-Based Monitoring System Rollout", "Monitoring and Evaluation", ProgramStatus.PENDING),
    ("Local Revenue Mobilisation Assistance", "Fiscal Administration", ProgramStatus.PENDING),
    ("Barangay Officials Orientation", "Capacity Development", ProgramStatus.COMPLETED),
    ("Local Nutrition Program Monitoring", "Social Services", ProgramStatus.COMPLETED),
    ("Katarungang Pambarangay Performance Review", "Governance", ProgramStatus.ARCHIVED),
]

ACTIVITY_TITLES = [
    "SGLG Assessment - Table Validation",
    "Barangay Development Plan Review",
    "Full Disclosure Policy Compliance Check",
    "Local Development Council Functionality Assessment",
    "Annual Investment Program Validation",
    "LDRRM Fund Utilisation Review",
    "Local Revenue Performance Monitoring",
    "Citizen's Charter Compliance Inspection",
]

TEAMS = [
    "M. Salazar, R. Antonio",
    "J. Bacon, L. Mendoza",
    "A. Dela Cruz, M. Salazar",
    "R. Antonio, C. Villareal",
    "L. Mendoza, J. Bacon, A. Dela Cruz",
]

FINDINGS = [
    "The LGU has substantially complied with the posting requirements. Three of "
    "the required documents were posted after the prescribed deadline.",
    "Records were complete and available for inspection. The local development "
    "council convened the required number of times during the period.",
    "Supporting documents for two projects could not be produced at the time of "
    "the visit. The LGU committed to submit them within fifteen days.",
    "The LGU demonstrated consistent compliance across all assessed areas. No "
    "material exceptions were noted.",
]

RECOMMENDATIONS = [
    "Post the remaining documents within the prescribed period and designate a "
    "focal person responsible for compliance monitoring.",
    "Sustain current practice and document the process for continuity across "
    "changes of administration.",
    "Submit the outstanding supporting documents and institute a filing system "
    "for project records.",
    "No further action required for this reporting period.",
]

SERVICES = [
    (
        "Issuance of Certification of Compliance",
        ServiceType.SIMPLE,
        "Certification that an LGU has complied with a specified reporting or "
        "posting requirement.",
        "Local government units, national government agencies",
        "Letter request addressed to the Regional Director\n"
        "Valid government-issued identification of the requesting officer\n"
        "Authorisation letter, if filed by a representative",
        "3 working days",
    ),
    (
        "Technical Assistance on Local Development Planning",
        ServiceType.COMPLEX,
        "Guidance to LGUs in the preparation, updating and review of local "
        "development plans and investment programs.",
        "Cities, municipalities and barangays",
        "Written request from the local chief executive\n"
        "Copy of the current local development plan\n"
        "Proposed schedule of the assistance",
        "7 working days",
    ),
    (
        "Request for Monitoring Records",
        ServiceType.SIMPLE,
        "Provision of copies of monitoring findings and recommendations "
        "concerning a particular LGU.",
        "Local government units, the public",
        "Accomplished request form\n"
        "Valid government-issued identification\n"
        "Statement of purpose",
        "5 working days",
    ),
    (
        "Validation of Local Governance Performance Data",
        ServiceType.TECHNICAL,
        "Field validation of data submitted by LGUs for governance performance "
        "assessment.",
        "Provinces, cities and municipalities",
        "Complete submission of the required assessment forms\n"
        "Supporting documentary requirements\n"
        "Confirmation of the validation schedule",
        "20 working days",
    ),
]


class Command(BaseCommand):
    help = "Create illustrative records so the Phase 2 modules can be demonstrated."

    def add_arguments(self, parser):
        parser.add_argument(
            "--clear",
            action="store_true",
            help="Delete the illustrative records instead of creating them.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        from django.conf import settings

        if not settings.DEBUG:
            raise CommandError(
                "seed_records refuses to run with DEBUG=False. It creates "
                "illustrative records, which must never enter a live system."
            )

        if options["clear"]:
            return self.clear()

        if not LGU.objects.exists():
            raise CommandError(
                "The LGU directory is empty. Run `manage.py seed_lgus` first."
            )

        random.seed(20260907)  # reproducible demonstrations
        today = timezone.localdate()

        self.seed_reference_data()
        programs = self.seed_programs(today)
        self.seed_monitoring(programs, today)
        self.seed_services()
        self.seed_documents(today)
        self.seed_reports(programs, today)
        self.seed_incoming(today)
        self.seed_calendar(today)
        self.seed_updates(today)
        self.seed_news(today)

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Illustrative records created:"))
        for label, count in [
            ("Programs", Program.objects.count()),
            ("Monitoring activities", MonitoringActivity.objects.count()),
            ("Frontline services", FrontlineService.objects.count()),
            ("Documents", Document.objects.count()),
            ("Incoming documents", IncomingDocument.objects.count()),
            ("Reports", Report.objects.count()),
            ("Calendar activities", CalendarActivity.objects.count()),
            ("Reporting weeks", ReportingPeriod.objects.count()),
            ("Division updates", DivisionUpdate.objects.count()),
            ("Announcements", Announcement.objects.count()),
        ]:
            self.stdout.write(f"  {label:24} {count}")
        self.stdout.write("")
        self.stdout.write(
            self.style.WARNING(
                "These records are illustrative. Run `seed_records --clear` "
                "before the system carries live data."
            )
        )

    # -- individual modules --------------------------------------------

    def seed_reference_data(self):
        from accounts.models import Section

        for name, short_name in SECTIONS:
            Section.objects.get_or_create(
                name=name, defaults={"short_name": short_name}
            )
        for name, description in CATEGORIES:
            ProgramCategory.objects.get_or_create(
                name=name, defaults={"description": description}
            )
        for name, code, years, action in DOCUMENT_TYPES:
            DocumentType.objects.get_or_create(
                name=name,
                defaults={
                    "code": code,
                    "retention_years": years,
                    "retention_action": action,
                },
            )

    def seed_programs(self, today):
        created = []
        for index, (title, category_name, status) in enumerate(PROGRAMS):
            category = ProgramCategory.objects.get(name=category_name)
            start = today.replace(month=1, day=15) - datetime.timedelta(days=index * 21)
            end = None
            if status in (ProgramStatus.COMPLETED, ProgramStatus.ARCHIVED):
                end = start + datetime.timedelta(days=180)

            program, is_new = Program.objects.get_or_create(
                title=title,
                defaults={
                    "category": category,
                    "status": status,
                    "start_date": start,
                    "end_date": end,
                    "reference_number": f"LGMED-{start.year}-{index + 1:03d}",
                    "focal_person": random.choice(
                        ["M. Salazar", "R. Antonio", "J. Bacon", "L. Mendoza"]
                    ),
                    "description": (
                        f"{title} is administered by the Division across Region "
                        "XIII. It covers assessment, technical assistance and "
                        "the reporting of results to regional management."
                    ),
                    "objectives": (
                        "Assess the compliance and performance of covered local "
                        "government units, provide technical assistance where "
                        "gaps are identified, and report the results."
                    ),
                },
            )
            if is_new and index % 3 == 0:
                program.covered_lgus.set(
                    random.sample(list(LGU.objects.all()), k=min(8, LGU.objects.count()))
                )
            created.append(program)
        return created

    def seed_monitoring(self, programs, today):
        if MonitoringActivity.objects.exists():
            return

        lgus = list(LGU.objects.select_related("province"))
        active_programs = [p for p in programs if p.status == ProgramStatus.ACTIVE]
        statuses = (
            [MonitoringStatus.COMPLETED] * 6
            + [MonitoringStatus.FOR_REVIEW] * 3
            + [MonitoringStatus.IN_PROGRESS] * 2
            + [MonitoringStatus.SCHEDULED] * 2
        )

        for index in range(90):
            lgu = random.choice(lgus)
            when = today - datetime.timedelta(days=random.randint(0, 250))
            status = random.choice(statuses)
            has_findings = status in (
                MonitoringStatus.COMPLETED,
                MonitoringStatus.FOR_REVIEW,
            )

            MonitoringActivity.objects.create(
                title=random.choice(ACTIVITY_TITLES),
                reference_number=f"MON-{when.year}-{index + 1:04d}",
                lgu=lgu,
                program=random.choice(active_programs) if active_programs else None,
                monitoring_date=when,
                monitoring_team=random.choice(TEAMS),
                findings=random.choice(FINDINGS) if has_findings else "",
                recommendations=random.choice(RECOMMENDATIONS) if has_findings else "",
                follow_up_action=(
                    "Submit the outstanding documents to the Division."
                    if has_findings and random.random() < 0.4 else ""
                ),
                follow_up_date=(
                    when + datetime.timedelta(days=30)
                    if has_findings and random.random() < 0.4 else None
                ),
                status=status,
            )

        # Compliance status follows from whether an LGU has been assessed.
        for lgu in lgus:
            completed = lgu.monitoring_activities.filter(
                status=MonitoringStatus.COMPLETED
            ).count()
            if completed >= 2:
                lgu.compliance_status = ComplianceStatus.COMPLIANT
            elif completed == 1:
                lgu.compliance_status = ComplianceStatus.PARTIAL
            else:
                lgu.compliance_status = ComplianceStatus.NOT_ASSESSED
            lgu.save(update_fields=["compliance_status"])

    def seed_services(self):
        for name, service_type, description, clients, requirements, duration in SERVICES:
            FrontlineService.objects.get_or_create(
                name=name,
                defaults={
                    "service_type": service_type,
                    "description": description,
                    "clients": clients,
                    "requirements": requirements,
                    "processing_time": duration,
                    "fees": "None",
                    "responsible_person": "LGMED Frontline Services Desk",
                    "is_published": True,
                },
            )

    @staticmethod
    def _placeholder_pdf(title):
        """
        A minimal but genuinely openable one-page PDF carrying the title.

        Built by hand rather than pulled from a library because the project
        has no PDF dependency and does not need one for this: the seeded
        documents exist so the register has something real to serve, not so
        the office can read them.
        """
        newline = "\n"
        safe = title.replace("(", "").replace(")", "").replace("\\", "")[:80]
        content = (
            f"BT /F1 12 Tf 60 760 Td ({safe}) Tj 0 -20 Td "
            "(Illustrative document - LGMED-iMMS demonstration data.) Tj ET"
        ).encode("latin-1", "replace")

        objects = [
            b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
            b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
            (
                f"<< /Length {len(content)} >>{newline}stream{newline}".encode()
                + content
                + f"{newline}endstream".encode()
            ),
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        ]

        out = bytearray(f"%PDF-1.4{newline}".encode())
        offsets = []
        for number, body in enumerate(objects, start=1):
            offsets.append(len(out))
            out += f"{number} 0 obj{newline}".encode()
            out += body
            out += f"{newline}endobj{newline}".encode()

        start = len(out)
        out += f"xref{newline}0 {len(objects) + 1}{newline}".encode()
        out += f"0000000000 65535 f {newline}".encode()
        for offset in offsets:
            out += f"{offset:010d} 00000 n {newline}".encode()
        out += (
            f"trailer{newline}<< /Size {len(objects) + 1} /Root 1 0 R >>{newline}"
            f"startxref{newline}{start}{newline}%%EOF{newline}"
        ).encode()
        return bytes(out)

    def seed_documents(self, today):
        """
        A spread of documents across the whole lifecycle.

        Walked through `documents.workflow` rather than written straight into
        the table, so every seeded record carries a real trail, a version
        history and - where it is completed - a retention period worked out
        from its own document type.
        """
        if Document.objects.exists():
            return

        from django.core.files.base import ContentFile

        from accounts.models import Role, User
        from documents import workflow as documents_workflow

        placeholder_pdf = self._placeholder_pdf

        chief = (
            User.objects.filter(role=Role.ADMIN, is_active=True).first()
            or User.objects.filter(is_superuser=True).first()
        )
        staff = list(
            User.objects.filter(
                role__in=(Role.LGMED_STAFF, Role.ENCODER), is_active=True
            )
        )
        if chief is None:
            return
        approver = (
            User.objects.filter(role=Role.LGMED_STAFF, is_active=True).first() or chief
        )

        # (title, type, sender, how far through the lifecycle to take it, public)
        script = [
            ("Guidelines on the Seal of Good Local Governance Assessment",
             "Guidelines", "DILG Central Office", "completed", True),
            ("Advisory on the Submission of Barangay Development Plans",
             "Advisory", "DILG Regional Office XIII", "completed", True),
            ("Memorandum on Full Disclosure Policy Compliance",
             "Memorandum", "Office of the Regional Director", "completed", True),
            ("Regional Monitoring Report - First Semester",
             "Monitoring Report", "LGMED", "completed", True),
            ("Minutes of the Quarterly Performance Review",
             "Minutes of Meeting", "LGMED", "for_approval", False),
            ("Memorandum Circular on Local Development Councils",
             "Memorandum Circular", "DILG Central Office", "in_progress", False),
            ("Certification of Compliance Template",
             "Certification", "LGMED", "assigned", False),
            ("Advisory on Barangay Assembly Day Observance",
             "Advisory", "DILG Central Office", "for_review", False),
            ("Draft Guidelines on Local Special Bodies",
             "Guidelines", "", "draft", False),
        ]

        for index, (title, type_name, sender, stage, publish) in enumerate(script):
            received = today - datetime.timedelta(days=(index + 1) * 11)
            document = Document(
                title=title,
                document_type=DocumentType.objects.get(name=type_name),
                subject=title,
                sender=sender,
                date_received=received if sender else None,
                date_created=received - datetime.timedelta(days=3),
                year=received.year,
                owner=staff[index % len(staff)] if staff else chief,
                description=(
                    "Issued by the Local Government Monitoring and Evaluation "
                    "Division for the guidance of all concerned."
                ),
                status=(
                    DocumentStatus.DRAFT if stage == "draft"
                    else DocumentStatus.RECEIVED
                ),
                created_by=chief,
            )
            document.save()
            # A real file, not just a path in a column. The register serves
            # every download through a view that opens the file and logs it,
            # so a seeded record pointing at nothing would demonstrate a
            # broken Download button rather than a working one.
            document.file.save(
                f"placeholder-{index + 1}.pdf",
                ContentFile(placeholder_pdf(title)),
                save=True,
            )
            documents_workflow.register(document, chief)

            if stage == "draft":
                continue

            documents_workflow.submit_for_review(document, document.owner)
            if stage == "for_review":
                continue

            documents_workflow.review(
                document, chief, notes="Noted. For action by the focal person."
            )
            focal = staff[(index + 1) % len(staff)] if staff else chief
            documents_workflow.assign(
                document,
                chief,
                assignee=focal,
                remarks="Please prepare the required action and report back.",
                due_date=received + datetime.timedelta(days=15),
            )
            if stage == "assigned":
                continue

            documents_workflow.start_processing(document, focal)
            if stage == "in_progress":
                continue

            documents_workflow.submit_for_approval(
                document, focal, notes="Action completed, submitted for approval."
            )
            if stage == "for_approval":
                continue

            documents_workflow.complete(document, approver, notes="Approved.")
            if publish:
                document.is_public = True
                document.save(update_fields=["is_public", "updated_at"])

    def seed_incoming(self, today):
        """
        A spread of incoming documents across the whole workflow.

        Walked through `incoming.workflow` rather than written straight into
        the table, so the seeded records carry a real trail and the Chief's
        dashboard has something honest to show.
        """
        from accounts.models import Role, User
        from incoming import workflow

        if IncomingDocument.objects.exists():
            return

        chief = User.objects.filter(role=Role.ADMIN, is_active=True).first()
        encoder = (
            User.objects.filter(role=Role.ENCODER, is_active=True).first() or chief
        )
        focals = list(
            User.objects.filter(
                role__in=(Role.LGMED_STAFF, Role.ENCODER), is_active=True
            )
        )
        if chief is None or encoder is None or not focals:
            self.stdout.write(
                self.style.WARNING(
                    "  Incoming documents skipped - run `bootstrap_demo` first "
                    "so there is a Division Chief and a focal person."
                )
            )
            return

        # (subject, type, source, days ago, how far it has got)
        arrivals = [
            ("Request for validation of SGLG documentary requirements",
             "Memorandum", "Office of the Regional Director", 2, "recorded"),
            ("Query on the utilisation of the Local Disaster Risk Reduction Fund",
             "Advisory", "Municipality of Carmen", 3, "recorded"),
            ("Submission of the Barangay Development Plan for review",
             "Memorandum", "City Government of Cabadbaran", 6, "assigned"),
            ("Request for technical assistance on local revenue generation",
             "Memorandum Circular", "Provincial Government of Surigao del Sur",
             9, "acknowledged"),
            ("Compliance report on the Full Disclosure Policy",
             "Monitoring Report", "Municipality of Buenavista", 14, "in_progress"),
            ("Endorsement of the Local Development Council reorganisation",
             "Guidelines", "DILG Central Office", 21, "overdue"),
            ("Invitation to the Regional Peace and Order Council meeting",
             "Minutes of Meeting", "Regional Peace and Order Council", 27,
             "completed"),
            ("Certification request for local government officials",
             "Certification", "Municipality of Sibagat", 33, "completed"),
            ("Follow-up on the submission of quarterly accomplishment reports",
             "Memorandum", "Office of the Regional Director", 11, "returned"),
        ]

        for index, (subject, type_name, source, days, stage) in enumerate(arrivals):
            received = today - datetime.timedelta(days=days)
            document = IncomingDocument.objects.create(
                docket_number=f"{received.year}-{index + 1:04d}",
                subject=subject,
                document_type=DocumentType.objects.get(name=type_name),
                date_received=received,
                source_office=source,
                initial_remarks="Received at the records counter.",
                created_by=encoder,
            )
            workflow.record_received(document, encoder)
            if stage == "recorded":
                continue

            focal = focals[index % len(focals)]
            overdue = stage == "overdue"
            workflow.assign(
                document,
                chief,
                assignee=focal,
                remarks=(
                    "Prepare the appropriate response and submit the draft for "
                    "my signature."
                ),
                priority=Priority.HIGH if overdue else Priority.NORMAL,
                due_date=(
                    received + datetime.timedelta(days=5 if overdue else 20)
                ),
            )
            if stage == "assigned":
                continue

            workflow.acknowledge(document, focal)
            if stage == "acknowledged":
                continue

            workflow.add_update(
                document,
                focal,
                IncomingUpdate(
                    action_taken=(
                        "Coordinated with the LGU and requested the outstanding "
                        "attachments."
                    ),
                    remarks="Awaiting the LGU's reply.",
                    status=IncomingStatus.IN_PROGRESS,
                ),
            )
            if stage in ("in_progress", "overdue"):
                continue

            workflow.add_update(
                document,
                focal,
                IncomingUpdate(
                    action_taken="Reply prepared, signed and transmitted.",
                    status=IncomingStatus.COMPLETED,
                ),
            )
            if stage == "returned":
                workflow.return_for_revision(
                    document,
                    chief,
                    "Recheck the figures in the attachment before this is closed.",
                )

    def seed_reports(self, programs, today):
        if Report.objects.exists():
            return

        for index in range(14):
            month = (index % 9) + 1
            status = random.choice(
                [ReportStatus.PUBLISHED] * 5
                + [ReportStatus.APPROVED] * 2
                + [ReportStatus.FOR_REVIEW] * 2
                + [ReportStatus.SUBMITTED, ReportStatus.DRAFT, ReportStatus.RETURNED]
            )
            report = Report(
                title=(
                    f"Monitoring and Evaluation Report - "
                    f"{datetime.date(today.year, month, 1):%B} {today.year}"
                ),
                reference_number=f"LGMED-RPT-{today.year}-{index + 1:03d}",
                period=ReportPeriod.MONTHLY if index % 2 else ReportPeriod.QUARTERLY,
                year=today.year,
                program=random.choice(programs) if programs else None,
                summary=(
                    "Consolidated results of the monitoring activities conducted "
                    "during the period, with the findings, recommendations and "
                    "follow-up actions arising from them."
                ),
                prepared_by=random.choice(["M. Salazar", "R. Antonio", "J. Bacon"]),
                status=status,
            )
            if status != ReportStatus.DRAFT:
                report.submitted_on = datetime.date(today.year, month, 10)
            if status == ReportStatus.PUBLISHED:
                report.published_on = datetime.date(today.year, month, 20)
            report.save()

    def seed_calendar(self, today):
        """
        A month of the Division's work, spread across the staff.

        Seeded with owners, assignees and a mix of visibility levels rather
        than as one anonymous list, because an ownership model demonstrated on
        records that all belong to nobody demonstrates nothing.
        """
        from accounts.models import Role, Section, User

        if CalendarActivity.objects.exists():
            return

        staff = list(
            User.objects.filter(
                is_active=True,
                role__in=(Role.LGMED_STAFF, Role.ENCODER, Role.ADMIN),
            ).order_by("pk")
        )
        if not staff:
            self.stdout.write(
                self.style.WARNING(
                    "  Calendar activities skipped - run `bootstrap_demo` "
                    "first so there are employees to own them."
                )
            )
            return

        chief = User.objects.filter(role=Role.ADMIN, is_active=True).first()
        sections = list(Section.objects.all())
        for index, person in enumerate(staff):
            if person.section_id is None and sections:
                person.section = sections[index % len(sections)]
                person.save(update_fields=["section"])

        lgus = list(LGU.objects.all())

        # (title, type, day offset, location, visibility, priority, status)
        entries = [
            ("SGLG Regional Validation", ActivityType.MONITORING, 4,
             "DILG Provincial Office, Cabadbaran City",
             Visibility.ORGANIZATION, ActivityPriority.HIGH,
             ActivityStatus.PLANNED),
            ("LGMED Quarterly Performance Review", ActivityType.MEETING, 8,
             "Regional Office Conference Room",
             Visibility.ORGANIZATION, ActivityPriority.NORMAL,
             ActivityStatus.PLANNED),
            ("Barangay Development Plan Orientation", ActivityType.TRAINING, 11,
             "Butuan City", Visibility.TEAM, ActivityPriority.NORMAL,
             ActivityStatus.PLANNED),
            ("Deadline: Third Quarter Report Submission", ActivityType.DEADLINE, 15,
             "Regional Office", Visibility.ORGANIZATION, ActivityPriority.URGENT,
             ActivityStatus.PLANNED),
            ("Field Validation - Surigao del Sur", ActivityType.FIELDWORK, 18,
             "Tandag City", Visibility.TEAM, ActivityPriority.HIGH,
             ActivityStatus.PLANNED),
            ("Local Development Council Assessment", ActivityType.MONITORING, 22,
             "Bislig City", Visibility.TEAM, ActivityPriority.NORMAL,
             ActivityStatus.PLANNED),
            ("Capacity Development Workshop", ActivityType.TRAINING, 26,
             "Butuan City", Visibility.ORGANIZATION, ActivityPriority.NORMAL,
             ActivityStatus.PLANNED),
            ("Drafting of the LGMED work and financial plan",
             ActivityType.OFFICE_WORK, 2, "Regional Office",
             Visibility.PRIVATE, ActivityPriority.NORMAL,
             ActivityStatus.IN_PROGRESS),
            ("Consolidation of SGLG documentary requirements",
             ActivityType.OFFICE_WORK, 1, "Regional Office",
             Visibility.ASSIGNED, ActivityPriority.HIGH,
             ActivityStatus.IN_PROGRESS),
            ("Regional Directors Meeting", ActivityType.MEETING, -6,
             "Regional Office Conference Room", Visibility.ORGANIZATION,
             ActivityPriority.NORMAL, ActivityStatus.COMPLETED),
            ("Fiscal Administration Review", ActivityType.MONITORING, -12,
             "Prosperidad, Agusan del Sur", Visibility.TEAM,
             ActivityPriority.NORMAL, ActivityStatus.COMPLETED),
            ("Validation report write-up - Agusan del Norte",
             ActivityType.OFFICE_WORK, -4, "Regional Office",
             Visibility.PRIVATE, ActivityPriority.HIGH,
             ActivityStatus.IN_PROGRESS),
            ("Submission of BDP monitoring matrix", ActivityType.DEADLINE, -9,
             "Regional Office", Visibility.TEAM, ActivityPriority.URGENT,
             ActivityStatus.PLANNED),
        ]

        for index, entry in enumerate(entries):
            title, kind, offset, location, visibility, priority, status = entry
            owner = staff[index % len(staff)]
            # Every third activity is carried out by somebody other than its
            # owner, so the distinction between the two is visible in the
            # seeded data rather than only in the model.
            assignee = None
            if index % 3 == 2 and len(staff) > 1:
                assignee = staff[(index + 1) % len(staff)]
                if assignee == owner:
                    assignee = None

            activity = CalendarActivity(
                title=title,
                activity_type=kind,
                description=(
                    "Scheduled activity of the Local Government Monitoring and "
                    "Evaluation Division."
                ),
                owner=owner,
                assigned_to=assignee,
                section=owner.section,
                start_date=today + datetime.timedelta(days=offset),
                start_time=datetime.time(8, 0) if offset % 2 else datetime.time(13, 30),
                end_time=datetime.time(12, 0) if offset % 2 else datetime.time(17, 0),
                location=location,
                lgu=random.choice(lgus) if kind == ActivityType.MONITORING and lgus else None,
                participants="LGMED personnel and LGU representatives",
                priority=priority,
                status=status,
                visibility=(
                    Visibility.ASSIGNED
                    if assignee and visibility == Visibility.PRIVATE
                    else visibility
                ),
                remarks=(
                    "Completed as scheduled."
                    if status == ActivityStatus.COMPLETED
                    else ""
                ),
                # Only what is office-wide and still ahead is offered to the
                # public site, matching the rule the form enforces.
                is_published=(
                    offset > 0 and visibility == Visibility.ORGANIZATION
                ),
                created_by=owner,
            )
            activity.save()

        if chief:
            self.stdout.write(
                f"  Calendar owners spread across {len(staff)} employees"
            )

    def seed_updates(self, today):
        """
        Three weeks of the Division's own record.

        Seeded as *division* weeks rather than as one person's log: several
        contributors feeding one weekly record each, one of them reviewed and
        published, so the convocation view and the public accomplishments page
        both have something real to show.
        """
        from accounts.models import Role, User

        if ReportingPeriod.objects.exists():
            return

        staff = list(
            User.objects.filter(
                is_active=True,
                role__in=(Role.LGMED_STAFF, Role.ENCODER, Role.ADMIN),
            ).order_by("pk")
        )
        chief = User.objects.filter(role=Role.ADMIN, is_active=True).first()
        lgus = list(LGU.objects.all()[:12])

        # (title, category, how the Division took part, status, day of the week)
        week_work = [
            ("Conducted the SGLGB orientation for the first district",
             UpdateCategory.ACTIVITY, UpdateActivityType.CONDUCTED,
             UpdateStatus.COMPLETED, 0),
            ("Facilitated the barangay assembly monitoring briefing",
             UpdateCategory.ACTIVITY, UpdateActivityType.FACILITATED,
             UpdateStatus.COMPLETED, 1),
            ("Attended the regional management conference",
             UpdateCategory.ACTIVITY, UpdateActivityType.ATTENDED,
             UpdateStatus.COMPLETED, 1),
            ("Participated in the provincial peace and order council session",
             UpdateCategory.ACTIVITY, UpdateActivityType.PARTICIPATED,
             UpdateStatus.COMPLETED, 2),
            ("Coordination meeting with the Provincial Devolution Management Unit",
             UpdateCategory.ACTIVITY, UpdateActivityType.MEETING,
             UpdateStatus.COMPLETED, 2),
            ("Seminar on the Full Disclosure Policy portal",
             UpdateCategory.ACTIVITY, UpdateActivityType.TRAINING,
             UpdateStatus.ONGOING, 3),
            ("Memorandum from the Office of the Regional Director",
             UpdateCategory.INCOMING, UpdateActivityType.NOT_APPLICABLE,
             UpdateStatus.COMPLETED, 0),
            ("Advisory received on the SGLG assessment calendar",
             UpdateCategory.INCOMING, UpdateActivityType.NOT_APPLICABLE,
             UpdateStatus.COMPLETED, 2),
            ("Reply to the Office of the City Mayor on the FDP findings",
             UpdateCategory.OUTGOING, UpdateActivityType.NOT_APPLICABLE,
             UpdateStatus.COMPLETED, 3),
            ("Endorsement letter to the Provincial Governor",
             UpdateCategory.OUTGOING, UpdateActivityType.NOT_APPLICABLE,
             UpdateStatus.PENDING, 4),
            ("Technical assistance on the Barangay Development Plan",
             UpdateCategory.TECHNICAL_ASSISTANCE, UpdateActivityType.NOT_APPLICABLE,
             UpdateStatus.COMPLETED, 1),
            ("Technical assistance on local revenue code updating",
             UpdateCategory.TECHNICAL_ASSISTANCE, UpdateActivityType.NOT_APPLICABLE,
             UpdateStatus.ONGOING, 3),
            ("Weekly accomplishment report consolidated",
             UpdateCategory.DELIVERABLE, UpdateActivityType.NOT_APPLICABLE,
             UpdateStatus.COMPLETED, 4),
            ("POPS Plan quarterly monitoring submitted",
             UpdateCategory.POPS_PLAN, UpdateActivityType.NOT_APPLICABLE,
             UpdateStatus.COMPLETED, 4),
        ]

        pops_work = [
            ("Drug-cleared barangays validated", 12, 9),
            ("Anti-illegal drugs operations monitored", 8, 8),
            ("Peace and order councils convened", 5, 3),
        ]

        ways = [
            "Draft the district-wide Full Disclosure Policy advisory",
            "Follow through on the outstanding SGLGB submissions",
            "Schedule the second-district validation with the PDMU",
        ]

        places = ["Butuan City", "Surigao City", "Bayugan City", "Tandag City",
                  "Regional Office"]

        monday, _friday = week_bounds(today)
        for weeks_back in (2, 1, 0):
            start = monday - datetime.timedelta(weeks=weeks_back)
            period = ReportingPeriod.objects.create(
                start_date=start,
                end_date=start + datetime.timedelta(days=4),
                theme=(
                    "SGLGB assessment and Full Disclosure Policy monitoring"
                    if weeks_back == 2
                    else ""
                ),
                created_by=chief,
            )

            for index, (title, category, kind, status, day) in enumerate(week_work):
                # The current week is still being filled in, which is what a
                # week in progress actually looks like on the dashboard.
                if weeks_back == 0 and index % 3 == 2:
                    continue
                contributor = staff[index % len(staff)] if staff else None
                DivisionUpdate.objects.create(
                    period=period,
                    title=title,
                    category=category,
                    activity_type=kind,
                    status=status,
                    activity_date=period.start_date + datetime.timedelta(days=day),
                    location=random.choice(places),
                    lgu=random.choice(lgus) if lgus and index % 2 == 0 else None,
                    narrative=(
                        "Recorded as part of the Division's weekly updates and "
                        "accomplishments for the period."
                    ),
                    # The focal person is who to ask about the item; the
                    # accomplishment itself belongs to the Division.
                    focal_person=contributor,
                    created_by=contributor,
                    is_public=category != UpdateCategory.INCOMING,
                )

            DivisionUpdate.objects.create(
                period=period,
                title="SGLG validation of the second district",
                category=UpdateCategory.ACTIVITY,
                activity_type=UpdateActivityType.CONDUCTED,
                status=UpdateStatus.UPCOMING,
                activity_date=period.end_date + datetime.timedelta(days=11),
                location="Cabadbaran City",
                focal_person=chief,
                created_by=chief,
                is_public=True,
            )

            for commitment, target, done in pops_work:
                PopsPlanUpdate.objects.create(
                    period=period,
                    commitment=commitment,
                    target=target,
                    accomplished=done if weeks_back == 2 else max(done - 2, 0),
                    recorded_by=chief,
                    is_public=True,
                )

            for description in ways[: 3 - weeks_back]:
                WayForward.objects.create(
                    period=period,
                    description=description,
                    target_date=period.end_date + datetime.timedelta(days=7),
                    recorded_by=chief,
                    is_public=True,
                )

            # The oldest week was reviewed and published, so the public page
            # and the convocation view have content; the middle week is
            # reviewed but unpublished; the current one is still open.
            if weeks_back == 2 and chief:
                for order, entry in enumerate(
                    period.updates.order_by("activity_date")[:3], start=1
                ):
                    entry.is_major = True
                    entry.convocation_order = order
                    entry.save(update_fields=["is_major", "convocation_order"])
                period.chief_remarks = (
                    "A strong week for the Division. My thanks to everyone who "
                    "took part in the first-district orientation."
                )
                period.publish(chief)
            elif weeks_back == 1 and chief:
                period.mark_reviewed(chief)

    def seed_news(self, today):
        """Illustrative news items, so the public news feed can be shown working."""
        if Announcement.objects.exists():
            return

        for title, category, days_ago, summary, location, featured in NEWS:
            Announcement.objects.create(
                title=title,
                category=category,
                published_on=today - datetime.timedelta(days=days_ago),
                summary=summary,
                location=location,
                is_published=True,
                is_featured=featured,
            )

    # -- teardown -------------------------------------------------------

    def clear(self):
        counts = {
            "Announcements": Announcement.objects.all().delete()[0],
            # Takes the entries, POPS figures and ways forward with it.
            "Reporting weeks": ReportingPeriod.objects.all().delete()[0],
            "Calendar activities": CalendarActivity.objects.all().delete()[0],
            "Reports": Report.objects.all().delete()[0],
            "Incoming documents": IncomingDocument.objects.all().delete()[0],
            "Documents": Document.objects.all().delete()[0],
            "Frontline services": FrontlineService.objects.all().delete()[0],
            "Monitoring activities": MonitoringActivity.objects.all().delete()[0],
            "Programs": Program.objects.all().delete()[0],
        }
        LGU.objects.update(compliance_status=ComplianceStatus.NOT_ASSESSED)
        for label, count in counts.items():
            self.stdout.write(f"  removed {count:>4} {label.lower()}")
        self.stdout.write(
            self.style.SUCCESS(
                "Illustrative records cleared. The LGU directory and reference "
                "lists were left in place."
            )
        )
