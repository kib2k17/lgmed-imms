"""
Signing through an agent on the signer's own computer. NOT YET CONNECTED.

Some PNPKI certificates live on a hardware token or smart card, where the
private key cannot leave the device, or are meant to be used only through a
DICT-provided signing application. For those, the server must never see the
key at all; the signing has to happen on the signer's machine. That needs
three things this server cannot supply by itself:

  1. A local signing agent installed on each signer's computer - DICT's own
     PNPKI signing middleware if it offers an API, or a PKCS#11-capable agent
     for the token vendor's driver - listening on a local address the browser
     can reach (for example https://127.0.0.1:<port>).
  2. The token driver (PKCS#11 module) and the signer's token or card.
  3. The agent's API contract: how it is asked to sign a digest and how it
     returns the CMS signature and certificate chain.

With those in place the flow is pyHanko's "interrupted signing":

  server  prepares the signature field and computes the document digest
          (PdfSigner.digest_doc_for_signing)       -> sends digest to browser
  browser passes the digest to the local agent     -> signer enters their PIN
  agent   returns the signature + certificate      -> browser posts to server
  server  checks the certificate exactly as for PKCS#12 (the same
          `workflow.sign` authorisation) and embeds the signature
          (PdfTBSDocument.finish_signing)

Until the agent and its API are chosen, this backend refuses to sign and says
why. It does not pretend. See docs/esira.md, "Connecting a token or DICT
signing agent".
"""

from .base import SigningBackend, SigningBackendUnavailable

REASON = (
    "Signing through a PNPKI token or DICT signing agent is not connected on "
    "this server yet. Ask the system administrator to install the signing "
    "agent (see docs/esira.md), or to switch e-SIRA to certificate-file "
    "signing."
)


class ExternalAgentBackend(SigningBackend):
    key = "external"
    label = "PNPKI token / DICT signing agent"
    collects_credentials = False
    instructions = (
        "Your PNPKI token or DICT signing application signs on your own "
        "computer. The private key never leaves it."
    )

    def is_available(self):
        return False

    def unavailable_reason(self):
        return REASON

    def open(self, credentials):
        raise SigningBackendUnavailable(REASON)

    def sign(self, opened, request):
        raise SigningBackendUnavailable(REASON)
