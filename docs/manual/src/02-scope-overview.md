# 2. Scope of the Manual

This manual covers the **internal system** used by DILG Caraga LGMED personnel after signing in (the pages under `/app/` and `/accounts/`), and briefly describes the **public website** that the system publishes to.

It covers every module that appears in the sidebar:

| Sidebar group | Modules covered |
|---|---|
| Main | Dashboard; Programs & Projects; PPA Review Queue; Publication Authorities; Monitoring; Incoming Monitoring; Outgoing Monitoring; Data Sync; LGU Management; Frontline Services |
| Information | Accomplishments (Updates & Accomplishments); Announcements; Document Management; Analytics; Reports; Calendar; Activity Monitoring; Public Website |
| Administration | Users & Roles; Menu Permissions; System Settings; Audit Logs |
| LGMED Innovation Action | e-SIRA (Electronic Signature, Identification, Routing and Approval) |

It also covers **My Profile**, **two-step verification**, and **Notifications**, which are reached from the top bar.

**Not covered.** Installing, configuring, backing up or deploying the system, the database, and the Django administration site (`/django-admin/`) are technical tasks for the system administrator and developer. They are described in the project's `README.md` and in `docs/`, not here.

# 3. System Overview

LGMED-iMMS is a web application. It runs on a server in the office and is opened in a web browser; nothing needs to be installed on your computer. It can also be installed as an app on a computer or phone (see Section 7.9).

## 3.1 The modules at a glance

| Module | What it is for |
|---|---|
| **Dashboard** | Headline figures, charts and the work that needs attention, calculated from the records. |
| **Programs & Projects** | The Division's Programs, Projects, Sub-projects and Activities (PPAs) under the Department's five Organizational Outcomes, their supporting documents, review and publication to the public website. |
| **PPA Review Queue** | Files and records waiting for a reviewer's decision. |
| **Publication Authorities** | Memoranda that authorise the release of files to the public. |
| **Monitoring** | Monitoring activities conducted in LGUs: findings, recommendations, follow-up and attachments. |
| **Incoming Monitoring** | Correspondence received by the Division: recorded by the encoder, reviewed and assigned by the Division Chief, acknowledged and acted on by the focal person. |
| **Outgoing Monitoring** | Action on acknowledged documents: updates, returns for revision, and the communication sent. |
| **Data Sync** | Importing the Incoming and Outgoing spreadsheet registers into the system. |
| **LGU Management** | The directory of the 78 LGUs of Region XIII and their compliance status. |
| **Frontline Services** | The Division's frontline services, published on the public website. |
| **Accomplishments** | The Division's weekly Updates & Accomplishments record, the Division Chief's review, the Monday convocation view and public disclosure. |
| **Announcements** | News, advisories, issuances, activities and commendations for the public website. |
| **Document Management** | The Division's document register: registration, review, assignment, processing, approval, archive, retention and authorised disposal. |
| **Analytics** | Performance analysis: coverage, trend, compliance and the least-monitored LGUs. |
| **Reports** | Monitoring and evaluation reports and their review status. |
| **Calendar** | Each employee's work plan: activities, ownership, assignment and visibility. |
| **Activity Monitoring** | The supervisor's view of everyone's workload. |
| **Public Website** | What the public can see, and the website's standing text. |
| **Users & Roles, Menu Permissions, System Settings, Audit Logs** | Administration of accounts, access, settings and the audit trail. |
| **e-SIRA** | Uploading or scanning documents, placing signature boxes, routing for signature or approval, digital signing with DICT PNPKI certificates, and tracking. |

## 3.2 How work flows through the Division

{{diagram:overview}}

The principle that runs through the whole system is that **the encoder records and the Division Chief decides**. Encoders can record a document but cannot name the focal person; contributors can file accomplishments but cannot select what is presented or published. Decisions are made on separate screens by the people authorised to make them, and every decision is recorded.
