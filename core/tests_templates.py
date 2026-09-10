"""
Guards against template mistakes that fail silently.

These are not tests of behaviour so much as tripwires. Each one exists because
the mistake it catches was actually made during development and was invisible
until someone looked at a rendered page.
"""

import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

TEMPLATE_DIR = Path(settings.BASE_DIR) / "templates"

# A {# ... #} comment that spans a newline. Django's comment syntax is
# single-line only: such a block is NOT a comment. Its text is printed into
# the page, and any {% ... %} inside it is executed.
MULTILINE_COMMENT = re.compile(r"\{#(?:(?!#\}).)*?\n.*?#\}", re.DOTALL)

# {% comment %} blocks hold documentation, including illustrative tags. Django
# treats their contents as raw text, so the balance check must too.
COMMENT_BLOCK = re.compile(
    r"\{%\s*comment\s*%\}.*?\{%\s*endcomment\s*%\}", re.DOTALL
)


class TemplateHygieneTests(SimpleTestCase):
    def templates(self):
        return sorted(TEMPLATE_DIR.rglob("*.html"))

    def test_no_multiline_hash_comments(self):
        """
        `{# ... #}` is a single-line comment.

        Spanning one across several lines prints the text to the page and runs
        any tag inside it. An `{% include %}` written inside such a block once
        made a component include itself until the dashboard exhausted Python's
        recursion limit; another leaked a paragraph of developer notes into the
        audit log page. Use `{% comment %} ... {% endcomment %}`.
        """
        offenders = []
        for path in self.templates():
            text = path.read_text(encoding="utf-8")
            for match in MULTILINE_COMMENT.finditer(text):
                line = text[: match.start()].count("\n") + 1
                offenders.append(f"{path.relative_to(TEMPLATE_DIR)}:{line}")

        self.assertEqual(
            offenders,
            [],
            "Multi-line {# #} comments are not comments. Use "
            "{% comment %}...{% endcomment %} instead. Found at: "
            + ", ".join(offenders),
        )

    def test_the_page_shells_do_not_clamp_the_body_to_one_viewport(self):
        """
        `h-full` on <body> breaks every sticky element on the page.

        A sticky element cannot leave its containing block, and for the header
        that block is the body. Pinned to 100% of the viewport, the body ended
        one screen down: scrolling past that point slid the header out of view
        while the sidebar - whose containing block is the full-height row
        below it - stayed pinned, leaving a white band across the top of the
        page. `min-h-full` still fills a short page, and grows with a long one.
        """
        offenders = []
        for name in ("base.html", "public_base.html"):
            text = (TEMPLATE_DIR / name).read_text(encoding="utf-8")
            body = re.search(r"<body[^>]*>", text)
            self.assertIsNotNone(body, f"{name} has no <body> tag")
            if re.search(r"(?<![-\w])h-full\b", body.group(0)):
                offenders.append(name)

        self.assertEqual(
            offenders,
            [],
            "A page shell must use min-h-full on <body>, never h-full - it "
            "clamps sticky positioning to the first viewport. Found in: "
            + ", ".join(offenders),
        )

    def test_every_template_loads_the_tags_it_uses(self):
        """A missing {% load ui %} makes tags render as nothing, not as an error."""
        offenders = []
        for path in self.templates():
            text = path.read_text(encoding="utf-8")
            uses_ui = re.search(
                r"\{%\s*(icon|status_badge|sort_link|sort_state|query_string)\b", text
            )
            if not uses_ui:
                continue
            if not re.search(r"\{%\s*load[^%]*\bui\b", text):
                offenders.append(str(path.relative_to(TEMPLATE_DIR)))

        self.assertEqual(
            offenders,
            [],
            "These templates use ui tags without {% load ui %}: "
            + ", ".join(offenders),
        )

    def test_no_template_uses_the_reserved_name_site(self):
        """
        The agency identity is published as `agency`, never `site`.

        Django's `auth.views.LoginView` puts a `site` object into its own
        context, and view context beats a context processor. Under the name
        `site`, every identity value on the sign-in page rendered as an empty
        string - no error, no warning, just a page that had quietly lost the
        department name, the system name and the contact address.
        """
        offenders = []
        tag = re.compile(r"\{\{.*?\}\}|\{%.*?%\}", re.DOTALL)
        for path in self.templates():
            text = path.read_text(encoding="utf-8")
            for match in tag.finditer(text):
                if re.search(r"\bsite\.", match.group(0)):
                    line = text[: match.start()].count("\n") + 1
                    offenders.append(f"{path.relative_to(TEMPLATE_DIR)}:{line}")

        self.assertEqual(
            offenders,
            [],
            "Use `agency.*`, not `site.*` - Django's LoginView overrides `site`. "
            "Found at: " + ", ".join(offenders),
        )

    def test_blocks_are_balanced(self):
        """
        An unclosed {% block %} fails at render time, not at import time.

        Tags inside {% comment %} documentation are stripped first: those are
        examples, not markup.
        """
        offenders = []
        paired = ("block", "if", "for", "with", "spaceless")
        for path in self.templates():
            source = path.read_text(encoding="utf-8")
            comments = len(COMMENT_BLOCK.findall(source))
            if comments != len(re.findall(r"\{%\s*endcomment\s*%\}", source)):
                offenders.append(f"{path.relative_to(TEMPLATE_DIR)}: unbalanced comment")
                continue
            text = COMMENT_BLOCK.sub("", source)
            for tag in paired:
                opens = len(re.findall(rf"\{{%\s*{tag}\b", text))
                closes = len(re.findall(rf"\{{%\s*end{tag}\s*%\}}", text))
                if opens != closes:
                    offenders.append(
                        f"{path.relative_to(TEMPLATE_DIR)}: "
                        f"{opens} {{% {tag} %}} vs {closes} {{% end{tag} %}}"
                    )
        self.assertEqual(offenders, [], "Unbalanced template tags: " + "; ".join(offenders))
