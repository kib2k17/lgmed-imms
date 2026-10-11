"""
Exports that cannot carry a spreadsheet formula.

A CSV is opened in Excel, and Excel runs a cell that begins with "=", "+",
"-", "@" (or a tab or carriage return ahead of one) as a formula. Record text
is typed by staff and, through Data Sync and the public forms, by people
outside the office; a subject line of `=HYPERLINK("http://...","Open")` would
otherwise become a working link - or worse - in the Chief's spreadsheet.
Such a cell is written with a leading apostrophe, which Excel shows as plain
text. Numbers, including negative ones, are left alone.
"""

import csv

_TRIGGERS = ("=", "+", "-", "@", "\t", "\r")


def neutralise(value):
    if not isinstance(value, str) or not value.startswith(_TRIGGERS):
        return value
    try:
        float(value)
        return value               # a plain number such as "-12.5"
    except ValueError:
        return "'" + value


class _SafeWriter:
    def __init__(self, fileobj, **kwargs):
        self._writer = csv.writer(fileobj, **kwargs)

    def writerow(self, row):
        return self._writer.writerow([neutralise(cell) for cell in row])

    def writerows(self, rows):
        for row in rows:
            self.writerow(row)


def writer(fileobj, **kwargs):
    """A drop-in for csv.writer whose cells are neutralised."""
    return _SafeWriter(fileobj, **kwargs)
