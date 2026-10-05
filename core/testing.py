"""
Helpers the test suites share.

Nothing here is imported by the running system - it exists so that a test can
say what it means without repeating the reason each time.
"""

from django.core.signals import request_finished
from django.db import close_old_connections


def close_response(response):
    """
    Release a streaming response's file handle without dropping the database
    connection underneath the test.

    A ``FileResponse`` holds the file open until the response is closed, and on
    Windows an open handle stops ``tearDownClass`` from removing the temporary
    media directory. So the tests close the response by hand.

    ``HttpResponse.close()`` also sends ``request_finished``, and Django's
    receiver for that signal closes the database connection - correct in a real
    server, where the connection belongs to the request that has just ended.
    Inside a ``TestCase`` it is not: the test runs in a transaction on that very
    connection, so closing it rolls the transaction back and every query after
    it raises ``TransactionManagementError``. The test client disconnects the
    receiver while it handles a request, but a ``close()`` written afterwards in
    the test body happens after the client has restored it.

    SQLite never showed this. Django refuses to close an in-memory test
    database, because doing so would discard it, so the same call was harmless
    there and the fault only appeared once the tests ran against MySQL.
    """
    request_finished.disconnect(close_old_connections)
    try:
        response.close()
    finally:
        request_finished.connect(close_old_connections)
