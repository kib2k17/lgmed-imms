"""
JSON that can sit inside a <script> element.

`json.dumps` leaves "<", ">" and "&" alone, so a chart label such as an
office name containing "</script><script>..." closes the data block and runs
as code on every page that shows the chart. Escaping those three characters
as \\u003C, \\u003E and \\u0026 keeps the JSON identical to JSON.parse while
leaving the HTML parser nothing to act on - the same thing Django's own
`json_script` filter does.
"""

import json

from django.core.serializers.json import DjangoJSONEncoder

_ESCAPES = {ord("<"): r"\u003C", ord(">"): r"\u003E", ord("&"): r"\u0026"}


def script_json(value):
    return json.dumps(value, cls=DjangoJSONEncoder).translate(_ESCAPES)
