"""
The reference lists a fresh LGMED-IMMS starts from.

Read by `manage.py setup_reference_data` (a real, empty installation) and by
`manage.py seed_records` (the demonstration data), so the two never drift
apart. Edit the lists here, not in either command.

Every list must be checked against the office's own records before go-live.
What each one needs is noted beside it.
"""

# -- Sections of the Division ------------------------------------------------
# (name, short name). CONFIRM: the Division's current organisational units.
SECTIONS = [
    ("Local Government Capability Development Section", "LGCDS"),
    ("Local Government Monitoring and Evaluation Section", "LGMES"),
    ("Field Operations Section", "FOS"),
    ("Administrative and Records Section", "ARS"),
]

# -- Programme categories ----------------------------------------------------
# (name, description). CONFIRM: the categories the Division reports under.
CATEGORIES = [
    ("Governance", "Local governance performance and oversight"),
    ("Capacity Development", "Training and technical assistance for LGUs"),
    ("Monitoring and Evaluation", "Assessment, validation and reporting"),
    ("Fiscal Administration", "Local revenue, budgeting and expenditure"),
    ("Disaster Risk Reduction", "Preparedness and resilience programs"),
    ("Social Services", "Programs supporting local social service delivery"),
]

# -- Document types and their retention --------------------------------------
# (name, code, retention years, action at end: REVIEW / DISPOSE / PERMANENT).
#
# CONFIRM WITH THE RECORDS OFFICER. The retention periods below are
# PLACEHOLDERS, not the office's schedule. They decide when a document falls
# due for review and when it may be disposed of, so they must come from the
# approved Records Disposition Schedule (National Archives of the Philippines,
# General Records Disposition Schedule / the agency's own RDS) before any real
# document is registered. They can also be changed afterwards in System
# Settings; existing documents keep the period they were completed under.
DOCUMENT_TYPES = [
    ("Memorandum", "MEMO", 5, "REVIEW"),
    ("Memorandum Circular", "MC", 10, "REVIEW"),
    ("Advisory", "ADV", 3, "DISPOSE"),
    ("Guidelines", "GUID", 10, "PERMANENT"),
    ("Monitoring Report", "MR", 5, "REVIEW"),
    ("Minutes of Meeting", "MIN", 10, "PERMANENT"),
    ("Certification", "CERT", 3, "DISPOSE"),
]

# The LGUs of Region XIII live in lgus/management/commands/seed_lgus.py
# (CONFIRM names and income classes against DILG's official roster).
