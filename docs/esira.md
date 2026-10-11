# e-SIRA — Electronic Signature, Identification, Routing and Approval

An LGMED Innovation Action module of LGMED-IMMS. Reached from the **LGMED
Innovation Action** button at the foot of the sidebar, at `/app/esira/`.

Workflow: **Upload/Scan → Preview PDF → Place signature boxes → Choose signers
→ Sign with PNPKI certificate → Route/Approve → Track → Complete → Download
signed PDF**.

---

## 1. What is real and what is not

e-SIRA keeps two things apart:

| | What it is | What it proves |
|---|---|---|
| **Signature box** (placement) | A rectangle on a page, stored as fractions of the page (`esira.SignatureBox`). | Nothing. It only says *where* a signature will go and *whose* it is to be. |
| **Digital signature** | A PAdES signature (`ETSI.CAdES.detached`, SHA-256) made with the signer's own private key, embedded in the PDF as a signature field whose visible appearance is drawn inside the box (`esira.DigitalSignature`). | That the holder of that PNPKI certificate signed exactly these bytes. |

There is **no simulated signing path**. A document is marked signed only after
a private-key operation has produced a signature that pyHanko then finds in the
output file (`workflow._confirm_signatures`). If the key, certificate or chain
check fails, nothing is saved.

A certificate counts as **PNPKI** only if it chains, by cryptographic
signature, to a DICT PNPKI root certificate installed on the server. An issuer
*name* containing "PNPKI" proves nothing and is not checked.

## 2. How signing works today (`ESIRA_SIGNING_BACKEND=pkcs12`)

DICT issues PNPKI individual certificates to government employees as a
password-protected **PKCS#12 file (.p12 / .pfx)**. The signer keeps that file
and its password on file on the **My Digital Certificate** page (encrypted,
see below), or selects the file and types its password in the Sign dialog.

1. With a certificate on file, the Sign dialog asks only for the password —
   and only when **Require .p12 password when signing** is on (the default).
   With it off, the stored password is used and no prompt appears.
2. The server opens the key **in memory** for that one request. The decrypted
   key is never written to disk, the database or a log.
3. Before the key is used, `workflow.authorise_certificate` requires that the
   certificate:
   - is **registered to this user's account** (by SHA-256 fingerprint),
   - has been **verified by an administrator** (a different person),
   - is **in date** and has a key usage that permits signing, and
   - **chains to an installed DICT PNPKI root** (`ESIRA_PNPKI_TRUST_ROOTS`),
     with OCSP/CRL revocation checked when `ESIRA_CHECK_REVOCATION=1`.
4. It must also be this user's turn: the open routing step is theirs and asks
   for a signature (or the user owns a draft on which every box is theirs).
5. Each of the signer's boxes becomes its own signature field, applied as an
   **incremental update**, so every earlier signature stays valid.
6. The result is stored as a new `DocumentVersion`; the original (v1) is never
   touched. Every version's SHA-256 is recorded and re-checked each time the
   file is read.

### Certificate registration and verification

- **My Digital Certificate**: the employee uploads their .p12/.pfx with its
  password. The file is opened to prove the password, then kept with it, both
  encrypted. Uploading the same certificate again replaces the stored copy.
  The page also holds the **signature image** (PNG/JPG, re-drawn as a PNG and
  drawn inside every signature box behind the signature text), the
  **require password** switch, and **Show my certificate password** (every
  reveal is logged as `CERT_PASSWORD_VIEWED`).

### Signature styles (**My Signature Style**)

A style decides only how a signature box *looks*; the PAdES signature behind
it is identical whichever is chosen. The signer picks one in the Sign dialog,
which starts on the style they last signed with.

| Style | Box shows | Available |
|---|---|---|
| Description Only | `Digitally signed by <certificate name>` / `Date: YYYY.MM.DD HH:MM:SS PST` | Always |
| Signature and Description | The signature image (My Digital Certificate) beside that text | Once a signature image is uploaded |
| Custom (`esira.SignatureStyle`) | A graphic alone — e.g. a signature over a printed name | Added one at a time from the setup dialog; up to 10 per person |

The name is the certificate's common name, written by pyHanko; the date is the
office's local time followed by `ESIRA_TIME_ZONE_LABEL` (default `PST`).
Uploaded graphics are re-drawn as PNGs with empty margins trimmed
(`esira/signature_images.py`) and served only to their owner.

### Stored certificates (`esira/signing/vault.py`)

The .p12 and password are stored as Fernet tokens (AES-128 + HMAC-SHA256) in
`SigningCertificate.pkcs12_sealed` / `passphrase_sealed`. The key comes from
`ESIRA_CREDENTIAL_KEY`; if that is unset it is derived from
`DJANGO_SECRET_KEY`. Either way a copy of the database alone opens nothing —
but **anyone with the database and the key can sign as every employee who
keeps a certificate on file**, and with protection off so can anyone who gets
into their account. Keep the key out of database backups and back it up
separately: losing or changing it makes every stored certificate unreadable,
and signers must upload their files again.
- **Certificate Verification** (administrators): confirm the certificate was
  issued by DICT to that employee — compare name, email and serial number with
  the PNPKI issuance record — then **Verify**. An administrator cannot verify
  their own certificate (a superuser can, and it is logged). Verified
  certificates can be **revoked**.
- One certificate cannot be registered to two accounts.

## 3. Configuration (`<venv>/lgmed.env`)

| Setting | Default | Purpose |
|---|---|---|
| `ESIRA_SIGNING_BACKEND` | `pkcs12` | `pkcs12` or `external` (§4). |
| `ESIRA_PNPKI_TRUST_ROOTS` | *(empty)* | Comma-separated paths to the DICT PNPKI **root and intermediate CA certificates** (PEM or DER), as published by DICT. **Signing is refused until this is set.** |
| `ESIRA_CHECK_REVOCATION` | `0` | `1` to fetch OCSP/CRL during validation (hard-fail). Needs outbound access to the PNPKI responders. |
| `ESIRA_TSA_URL` | *(empty)* | RFC 3161 time-stamping authority URL. Empty signs with the server clock. |
| `ESIRA_SIGNATURE_LOCATION` | `DILG Regional Office XIII - Caraga` | Written into each signature. |
| `ESIRA_MAX_UPLOAD_MB` | `25` | Upload size limit. |
| `ESIRA_TIME_ZONE_LABEL` | `PST` | Written after the time in each signature box. |
| `ESIRA_CREDENTIAL_KEY` | *(derived from `DJANGO_SECRET_KEY`)* | Fernet key encrypting stored .p12 files and passwords. Generate with `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`. |
| `ESIRA_ALLOW_UNTRUSTED_CERTIFICATES` | `0` | **Development/training only; ignored unless `DJANGO_DEBUG=1`.** Lets a test certificate sign before the PNPKI chain is installed. Such signatures are recorded and shown everywhere as *NOT PNPKI-verified*. |

Example:

```
ESIRA_PNPKI_TRUST_ROOTS=C:\lgmed\pnpki\PNPKI-Root-CA.cer,C:\lgmed\pnpki\PNPKI-Government-CA.cer
ESIRA_CHECK_REVOCATION=1
```

**Obtaining the roots:** download the PNPKI root and issuing CA certificates
from DICT's official PNPKI repository, or request them from DICT PNPKI, and
confirm their fingerprints with DICT before installing them. Anything signed by
a certificate in this list will be shown as a trusted PNPKI signature.

Dependencies (in `requirements.txt`): `pyHanko`, `pyhanko-certvalidator`,
`cryptography`. The PDF viewer is **pdf.js 6.3.289** (legacy build), vendored
under `static/vendor/pdfjs/` so the workspace needs no internet access.

## 4. Connecting a token or DICT signing agent (`external` backend — not yet connected)

Some PNPKI certificates sit on a hardware token/smart card whose key cannot
leave the device, or must be used through DICT's own signing application. For
these the server must never see the key. **This is not implemented yet, and
the `external` backend refuses to sign and says so.** It needs:

1. **A local signing agent** on each signer's PC — DICT's PNPKI signing
   middleware if it exposes an API, or a PKCS#11-capable agent for the token
   vendor's driver — reachable from the browser (e.g. `https://127.0.0.1:<port>`).
2. **The token driver** (PKCS#11 module) and the signer's token/card.
3. **The agent's API contract**: how to ask it to sign a digest, and how it
   returns the CMS signature and certificate chain.

With those, implement `esira/signing/external.py` using pyHanko's *interrupted
signing*:

```
server   PdfSigner.digest_doc_for_signing(...)  -> digest + prepared document
browser  send digest to local agent; signer enters PIN on their own PC
agent    returns CMS signature + certificate chain
server   run workflow.authorise_certificate on the returned certificate,
         then PdfTBSDocument.finish_signing(...) and store the new version
```

Everything else — routing, permissions, the certificate registry, versioning
and the audit trail — is shared and unchanged; only the backend's `open()` and
`sign()` differ. The `SigningBackend` contract is in `esira/signing/base.py`.

A server-side PKCS#11 HSM (one key for the office, not per person) is **not**
suitable for personal signatures and is deliberately not offered.

## 5. Security notes

- **Serve over HTTPS in production.** The .p12 and password cross the network
  when uploaded, when typed at signing, and when revealed.
- **Stored certificates are a signing capability.** See §2, *Stored
  certificates*. Encourage signers to leave *Require .p12 password when
  signing* on.
- Files live under `PROTECTED_MEDIA_ROOT` (never web-served) and are streamed
  only by `esira:file`, which re-checks access and the SHA-256 on every read. A
  mismatch is refused and logged as `INTEGRITY_FAILURE`.
- `DocumentVersion`, `DigitalSignature` and `AuditEntry` are write-once: their
  `save()` refuses updates and `delete()` refuses outright. The Django admin
  shows e-SIRA read-only.
- Recipients see a document only once it has been routed to them.
- Refused signing attempts are logged (`SIGN_FAILED`) even though the attempt
  itself is rolled back.

## 6. Roles

| Capability (on `accounts.User`) | Who | Allows |
|---|---|---|
| `can_use_esira` | every active account | Open e-SIRA; act on and sign documents routed to you |
| `can_upload_esira` | Encoder, LGMED Staff, Administrator | Upload/scan, place boxes, route |
| `can_oversee_esira` | Administrator (Division Chief) | See every document, office-wide figures, the full audit trail; cancel |
| `can_verify_signing_certificates` | Administrator | Verify / reject / revoke registered certificates |

Signing a particular document is never granted by role alone: it also takes
being the recipient whose turn it is and holding a verified certificate.

## 7. Statuses

| Status | Meaning |
|---|---|
| Draft | Uploaded, being prepared; not sent. |
| Awaiting Signature | The owner's own signature is next. |
| Out for Signature | With someone else to sign; no signature yet. |
| Partially Signed | At least one signature applied, more due. |
| Routed | With someone for approval/review/acknowledgement. |
| Fully Signed | Every step done, including at least one signature. |
| Routing Completed | Every step done; none was a signature. |
| Completed | Closed by the owner; locked. |
| Rejected | A recipient rejected it; the route stopped. |
| Cancelled | The owner or an overseer cancelled it. |

## 8. Code map

```
esira/models.py          documents, versions, boxes, steps, signatures, certificates, audit
esira/permissions.py     who may see / place / sign / act / complete / cancel
esira/workflow.py        every state change (upload, boxes, route, act, sign, certificates)
esira/signing/           backends: pkcs12 (live), external (declared), certificates (chain checks)
esira/pdf.py             PDF inspection, scans -> PDF, on-screen box -> PDF rectangle
esira/verification.py    verifies signatures from the file itself
esira/stats.py           dashboard figures
static/js/esira-workspace.js   pdf.js viewer and box placement
```

Tests: `python manage.py test esira` — signing is tested for real against a
throw-away CA installed as the trust root.
