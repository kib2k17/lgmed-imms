# Removing the public Staff Sign In links

**Status:** Implemented, 23 September 2026. Not yet rolled out — see
[Rollout](#rollout); the address has still to reach staff.
**Raised by:** the Chief — the Staff Sign In button should not be presented to
the public.
**Decision date:** 21 September 2026.

---

## The decision

The public website and the staff login become **two separate doorways**. The
public types (or searches for) the website address; staff type the login
address. Nothing on the public site links inward.

Every public-facing link to `accounts:login` is removed. Staff reach the system
by typing a short URL, which is bookmarked on the office machines.

## Why this shape

The button at the top right of `public_base.html` is styled `btn btn-primary` —
the same visual weight normally reserved for a page's main call to action — and
because it lives in the shared public base template it appears on **every**
public page. The loudest element on a citizen-facing government site was an
invitation to log in, which frames the site as a portal to enter rather than a
place where the Division publishes information.

Since the system is staff-only by design, no public visitor ever needs that
button. Removing it costs the public nothing.

Two alternatives were considered and set aside:

- **A settings toggle** (`SystemSetting.show_staff_login`, next to
  `public_site_enabled`). Cheap to build — the settings form at
  `administration/views.py` generates its own admin UI — but its main value was
  giving staff a findable path, which typing the URL replaces. Not worth a
  migration and four template conditionals for a decision nobody intends to
  reverse.
- **A greyed-out, non-clickable button.** A visible dead control reads as broken
  software, confuses staff, and is worse for screen readers than an absent one.
  The site publishes an accessibility statement, so this matters.

## What is already in place

Worth knowing before discussing "security" with the Chief — the staff-only
boundary is better protected than it may appear:

| Concern | State |
|---|---|
| Login page appearing in search results | Handled — `noindex, nofollow` in `templates/registration/login.html` |
| Internal system pages indexed | Handled — `templates/base.html` |
| Scripted / bot login attempts | Partly handled — reCAPTCHA v3 is wired into the login form |
| Brute force against a known username | **Gap** — no lockout or rate limiting anywhere in `accounts/` |

Removing the button does **not** restrict access to `/accounts/login/`. Scanners
find login endpoints by probing well-known paths, not by reading the homepage.
This change is about presentation, not access control. Say so plainly if the
question comes up.

---

## The changes

### 1. Delete the four public links

| File | What is there now |
|---|---|
| `templates/public_base.html` | Solid blue masthead button, appears on every public page |
| `templates/public/about.html` | Full-width secondary button in the "About LGMED-IMMS" sidebar card |
| `templates/public/contact.html` | Primary button in the "LGMED personnel" card |
| `templates/public/unavailable.html` | Inline text link on the maintenance page |

Each is a small block wrapping `{% url 'accounts:login' %}`. The masthead one
sits in the `ml-auto` flex container beside `#public-nav-toggle` — remove the
anchor, leave the menu toggle and the container.

On `about.html` and `contact.html`, the surrounding `<section>` cards carried
explanatory copy addressed to staff ("Division staff can sign in to LGMED-IMMS
to encode monitoring records…"). **Decided:** both cards were removed entirely.
Each existed to carry its button; without it, About's card only restated the
page and Contact's told staff to sign in with no way to. Office details,
Privacy and Accessibility are untouched.

`unavailable.html` can go too. The earlier objection to removing it — that staff
need a way in while the public site is down — dissolves once everyone types the
URL.

### 2. Add a short login alias

`config/urls.py` currently routes login under `accounts/`, so the address staff
would type is:

    /accounts/login/

Three segments, an easily misspelled word, and a trailing slash people forget.
If the plan rests on people typing it, it should be worth typing. Add a redirect
from a short path — `/staff` or `/signin` — to the canonical view. One line in
the root URLconf. `/accounts/login/` keeps working, so nothing else changes.

**Decided:** `/staff`. It survives being dictated over the phone and says who
it is for. Both `/staff` and `/staff/` are registered in `config/urls.py`, so a
forgotten trailing slash does not 404, and both redirect to the canonical
`/accounts/login/`.

### 3. Point logout back at the login page

`config/settings.py` set:

    LOGOUT_REDIRECT_URL = "core:home"

That is the **public homepage**. Once the links are gone, a staff member who
signs out lands on a page with no way back in and has to retype the URL — many
times a day. For a staff-only system, logout should return to the login page.
That is also the conventional behaviour and gives a clear "you are signed out"
signal.

It is now `accounts:login`. **The setting was not enough:** `LogoutView` in
`accounts/views.py` carried `next_page = reverse_lazy("core:home")`, which
overrides `LOGOUT_REDIRECT_URL` silently. The attribute was removed so the
setting governs, and a test now asserts where signing out lands.

### 4. Nothing needed for session expiry

`LOGIN_URL = "accounts:login"` in `config/settings.py` already redirects anyone
hitting an internal page without a valid session, and `?next=` returns them to
where they were. The only moment anyone types the URL is a cold start — the
first login of the day. This is what makes the plan workable; do not build
anything extra for it.

---

## Open questions

Items 2 and 3 are settled and folded into the sections above. Item 1 is still
open and is the only thing needing the Chief.

1. **Same site or separate addresses?** "The link of the login and the public
   website" could mean two paths on one site (what this plan assumes) or two
   hostnames. The second is achievable — `ALLOWED_HOSTS` and
   `CSRF_TRUSTED_ORIGINS` are already environment-driven in `config/settings.py`
   — but involves DNS and possibly certificates, not template edits. Confirm
   with the Chief. The goal is fully met by the same-site version; the separate
   hostname is mostly cosmetic on top of it.
2. ~~**Which short path** for the alias (§2).~~ Settled: `/staff`.
3. ~~**Whether the About and Contact cards stay**~~ Settled: both removed.

## Rollout

The technical change is small; staff not knowing the URL is the failure mode.
Before this goes live:

- [ ] Bookmark the login URL on the office machines staff actually use. This
      makes the typing question moot for daily use.
- [ ] One announcement with the new address.
- [ ] Add the address to whatever orientation material new staff receive.
- [ ] Tell the Chief the address — they will be asked for it.

## Verification

Automated, in `core/tests.py` — the whole suite passes apart from one
pre-existing failure in `programs` unrelated to this work:

- [x] `grep -rn "accounts:login" templates/` returns only
      `templates/registration/login.html` (the form's own `action`).
- [x] No public page carries a sign-in control —
      `test_no_public_page_links_to_the_staff_login` walks every route in
      `PUBLIC_ROUTES`.
- [x] The short alias resolves to the login page, with and without the trailing
      slash — `test_the_short_alias_reaches_the_login_page`.
- [x] Signing out lands on the login page, not the public homepage —
      `test_signing_out_lands_on_the_login_page`.
- [x] Session expiry still redirects to login and returns to the original page
      after signing in — covered by the existing
      `test_staff_routes_require_authentication`; nothing was changed here.
- [x] The maintenance page carries no sign-in link —
      `test_the_maintenance_page_carries_no_sign_in_link`.

Still to check by eye, since no test can see it:

- [ ] The masthead has no broken spacing where the button was. The `ml-auto`
      flex container and the menu toggle were left in place, so the toggle
      should still sit hard right at mobile width; at desktop width the
      container is empty by design (the toggle is `lg:hidden`).

## Out of scope

**Login rate limiting.** No lockout exists after repeated failed passwords —
reCAPTCHA v3 scores traffic but does not lock an account. This is the only item
in this area that affects actual security, and it is worth doing, but it has a
different risk profile: a misconfiguration locks out real staff. Separate piece
of work, separate testing. Raise it with the Chief if their concern turns out to
be unauthorised access rather than public presentation.
