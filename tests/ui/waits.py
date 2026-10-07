"""Waiting for the server's work in a browser test - on a condition, not a clock.

The upload, compare and product-choice forms are plain form posts the server
answers only once it has done the work: the whole check, or the whole
recalculation. Playwright's click() waits for the navigation it starts, under
its own 30-second action timeout, so on a loaded machine - and on the first
upload of a run, which also pays the server's cold start - the click itself
timed out while the server was still working correctly.

So the click here does not wait, and the test waits instead for the thing it
actually needs: the report's address, then the report on the page. Every wait
returns the moment its condition holds; SERVER_WORK_MS is only how long it may
take to hold, sized for a slow machine running the whole suite.
"""

from __future__ import annotations

import re

#: The ceiling for one check or recalculation on a slow, loaded machine. A
#: limit, not a pause.
SERVER_WORK_MS = 120_000

#: Where a check lands: /reports/<12 hex characters>.
REPORT_URL = re.compile(r"/reports/[0-9a-f]{12}$")


def submit_for_report(page, button) -> None:
    """Submit a form the server answers with a report, and wait for the report.

    Waits for the report's address and then for its verdict to be on the page,
    so nothing after this reads the upload page by mistake - which matters,
    because the upload page mentions "Ingredients" too.
    """
    from playwright.sync_api import expect

    button.click(no_wait_after=True)
    expect(page).to_have_url(REPORT_URL, timeout=SERVER_WORK_MS)
    expect(page.locator(".verdict h2").first).to_be_visible(timeout=SERVER_WORK_MS)


def submit_and_wait_until_gone(page, button, form_selector: str) -> None:
    """Submit a form whose answer lands back on the same address without it.

    The product picker posts the choice and is redirected to the same report,
    now recalculated: the address cannot say when that has happened, but the
    picker's disappearing can.
    """
    from playwright.sync_api import expect

    button.click(no_wait_after=True)
    expect(page.locator(form_selector)).to_have_count(0, timeout=SERVER_WORK_MS)
    expect(page.locator(".verdict h2").first).to_be_visible(timeout=SERVER_WORK_MS)
