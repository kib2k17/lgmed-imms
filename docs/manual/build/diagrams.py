"""
Workflow diagrams for the manual, described as data and drawn to PNG.

Each diagram is a sequence of steps; a step names who does it (the lane
colour) and what they do. build.py renders them with the same browser that
prints the PDF, so the diagrams match the manual's typography, and the PNGs
are reused unchanged in the Word and PowerPoint versions.
"""

ACTORS = {
    "Encoder": "#1e40af",
    "Contributors": "#1e40af",
    "Owner": "#1e40af",
    "Division Chief": "#9a3412",
    "Reviewer": "#9a3412",
    "Administrator": "#7c2d12",
    "Focal person": "#166534",
    "Recipient": "#166534",
    "System": "#475569",
    "Public": "#6b21a8",
}

DIAGRAMS = {
    "overview": {
        "title": "How work flows through LGMED-iMMS",
        "steps": [
            ("Encoder", "Records what arrived or what was done"),
            ("Division Chief", "Reviews, decides and assigns"),
            ("Focal person", "Acknowledges, acts and reports progress"),
            ("Division Chief", "Monitors, returns for revision, approves"),
            ("System", "Notifies, records the trail, counts the figures"),
            ("Public", "Sees only what was cleared and published"),
        ],
    },
    "incoming": {
        "title": "Incoming and Outgoing Monitoring workflow",
        "steps": [
            ("Encoder", "Record Incoming Document - status: For Division Chief review"),
            ("Division Chief", "Save review notes (what the document requires)"),
            ("Division Chief", "Assign and notify - focal person, priority, due date"),
            ("Focal person", "Acknowledge receipt - continues in Outgoing Monitoring"),
            ("Focal person", "Record update - In progress / For action / Pending"),
            ("Division Chief", "Optional: Return to focal person (for revision)"),
            ("Focal person", "Record communication sent (reply / transmittal)"),
            ("Focal person", "Record update with status Completed"),
            ("System", "Dashboard, overdue notices and the ten monitoring reports"),
        ],
    },
    "documents": {
        "title": "Document Management lifecycle",
        "steps": [
            ("Encoder", "Register Document - control number and version 1"),
            ("Owner", "Submit for review"),
            ("Reviewer", "Mark reviewed - For assignment"),
            ("Division Chief", "Assign the focal person - Assigned"),
            ("Focal person", "Start processing; upload new versions with reasons"),
            ("Focal person", "Submit for approval"),
            ("Reviewer", "Approve and complete - retention clock starts"),
            ("Reviewer", "Record retention decision; Archive document"),
            ("Administrator", "Permanent preservation, or Dispose permanently under a recorded authority"),
        ],
    },
    "ppa": {
        "title": "Programs, Projects and Activities: from draft to the public website",
        "steps": [
            ("Encoder", "Create the record (Draft)"),
            ("Encoder", "Upload and screen supporting files"),
            ("Encoder", "Submit for review"),
            ("Reviewer", "Read the screening; decide on each file"),
            ("Reviewer", "Approve the content / Request revision / Reject"),
            ("Reviewer", "Record the memorandum (publication authority) and cite it"),
            ("Administrator", "Publish to the public website"),
            ("Administrator", "Take off the public website, or Archive"),
        ],
    },
    "updates": {
        "title": "The weekly Updates & Accomplishments cycle",
        "steps": [
            ("Contributors", "Add entries to the week (Monday to Thursday)"),
            ("Contributors", "File the means of verification"),
            ("Contributors", "Add POPS Plan progress, ways forward, upcoming work"),
            ("Contributors", "Submit for review (Thursday)"),
            ("Division Chief", "Remarks and theme; select major accomplishments"),
            ("Division Chief", "Clear entries and photographs for the public"),
            ("Division Chief", "Present at the Monday convocation"),
            ("Division Chief", "Publish to the public website"),
            ("Public", "Sees cleared items of published weeks inside the disclosure window"),
        ],
    },
    "esira": {
        "title": "e-SIRA: electronic signature and routing",
        "steps": [
            ("Owner", "Upload a PDF or scan pages"),
            ("Owner", "Place signature boxes for each signer"),
            ("Owner", "Route: recipients, actions and order"),
            ("Recipient", "Approve / Mark reviewed / Acknowledge, or Reject and return"),
            ("Recipient", "Sign with a verified PNPKI certificate"),
            ("System", "New signed version; trail and notifications"),
            ("Owner", "Mark as completed; Download signed PDF"),
        ],
    },
}


def html(key):
    d = DIAGRAMS[key]
    rows = []
    for i, (actor, text) in enumerate(d["steps"], 1):
        colour = ACTORS.get(actor, "#334155")
        rows.append(f"""
        <div class="step">
          <div class="num" style="background:{colour}">{i}</div>
          <div class="body">
            <div class="actor" style="color:{colour}">{actor}</div>
            <div class="text">{text}</div>
          </div>
        </div>""")
    steps = '<div class="arrow">&#8595;</div>'.join(rows)
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>
    body {{ margin:0; font-family:'Segoe UI', Arial, sans-serif; background:#fff; }}
    #d {{ display:inline-block; padding:22px 26px; width:760px; box-sizing:border-box;
          border:1.5px solid #cbd5e1; border-radius:10px; background:#f8fafc; }}
    h3 {{ margin:0 0 14px; font-size:17px; color:#0f2a5c; }}
    .step {{ display:flex; align-items:center; gap:14px; background:#fff; border:1px solid #e2e8f0;
             border-radius:8px; padding:9px 14px; }}
    .num {{ flex:none; width:30px; height:30px; border-radius:50%; color:#fff; font-weight:700;
            display:flex; align-items:center; justify-content:center; font-size:14px; }}
    .actor {{ font-size:11px; font-weight:700; text-transform:uppercase; letter-spacing:.04em; }}
    .text {{ font-size:14.5px; color:#0f172a; }}
    .arrow {{ text-align:left; padding-left:22px; color:#94a3b8; font-size:16px; line-height:18px; }}
    </style></head><body><div id="d"><h3>{d['title']}</h3>{steps}</div></body></html>"""


def render_all(browser, out_dir):
    out_dir.mkdir(parents=True, exist_ok=True)
    page = browser.new_page(device_scale_factor=2)
    for key in DIAGRAMS:
        page.set_content(html(key))
        page.locator("#d").screenshot(path=str(out_dir / f"{key}.png"))
    page.close()
