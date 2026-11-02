"""
AC-06: follows one request from draft to verified, with a return, plus a rejection, in the running app, and saves a
screenshot of each step to docs/screenshots. Uses the Microsoft Edge installed on the machine (Playwright, no browser
download).

    streamlit run app.py --server.port 8517          (in another terminal, on a freshly built demo)
    python scripts/capture_walkthrough.py

The walkthrough adds one request to the demo data and decides on others, through the same screens a user has.
"""
import os
import pathlib
import re

import sys

from playwright.sync_api import expect, sync_playwright

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from portal import config, db  # noqa: E402

OUT = ROOT / "docs" / "screenshots"
URL = os.environ.get("PORTAL_URL", "http://localhost:8517")
PASSWORD = os.environ["PORTAL_DEMO_PASSWORD"]


def settle(page):
    page.wait_for_timeout(600)
    expect(page.get_by_test_id("stStatusWidget")).to_have_count(0, timeout=20000)
    page.wait_for_timeout(900)


def shot(page, name, scroll_to=None):
    settle(page)
    expect(page.get_by_test_id("stToast")).to_have_count(0, timeout=15000)
    if scroll_to is not None:
        scroll_to.scroll_into_view_if_needed()
        page.mouse.wheel(0, 250)
        page.wait_for_timeout(500)
    page.screenshot(path=OUT / f"{name}.png", full_page=False)
    print("saved", name)


def sign_in(page, login):
    page.goto(URL)
    page.get_by_label("Login", exact=True).fill(login)
    page.get_by_label("Password", exact=True).fill(PASSWORD)
    page.get_by_role("button", name="Sign in").click()
    settle(page)


def sign_out(page):
    page.get_by_role("button", name="Sign out").click()
    settle(page)


def go(page, link):
    page.get_by_role("link", name=link).click()
    settle(page)


def open_action(page, action_id):
    go(page, "Open an action")
    box = page.get_by_label("Go to action")
    box.fill(str(action_id))
    box.press("Enter")
    settle(page)


def link_incidents(page, count):
    """Adds up to count of the incidents not linked yet."""
    box = page.get_by_role("combobox", name="Incidents this action addresses")
    for _ in range(count):
        box.click()
        page.wait_for_timeout(400)
        tickets = page.get_by_role("option", name=re.compile("^INC"))   # the list also offers "select all"
        if not tickets.count():
            break
        tickets.first.click()
        page.keyboard.press("Escape")
    page.keyboard.press("Escape")
    settle(page)


def act(page, label, reason=None):
    """Clicks a workflow button; for those that need a reason or a date, fills the popover form."""
    page.get_by_role("button", name=label, exact=True).click()
    if reason is not None or label in ("Start work", "Record completion"):
        if reason is not None:
            page.get_by_label("Reason (the requester sees it)").fill(reason)
        page.get_by_role("button", name=re.compile(f"^Confirm: {label.lower()}")).click()
    settle(page)


def submitted_elsewhere(walkthrough_id):
    """A request of the North region waiting for a decision, from another requester, to show a rejection."""
    conn = db.connect(config.database_settings())
    return conn.execute("""
        SELECT TOP (1) a.ActionId FROM app.Action AS a
        JOIN app.UserAccount AS u ON u.UserId = a.RequesterId
        WHERE a.Status = 'Submitted' AND a.RegionCode = 'NOR' AND u.Login <> 'm.arrieta' AND a.ActionId <> ?
        ORDER BY a.LastSubmittedAt DESC""", walkthrough_id).fetchval()


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge")
        page = browser.new_page(viewport={"width": 1440, "height": 900}, device_scale_factor=1.5)

        page.goto(URL)
        page.get_by_role("button", name="Sign in").wait_for()
        shot(page, "01-sign-in")

        # Requester: a new request with its evidence
        sign_in(page, "a.etxeberria")
        shot(page, "02-my-requests")
        go(page, "New request")
        page.get_by_role("combobox", name="Circuit").fill("NG-FWA")
        page.keyboard.press("Enter")       # the fixed-wireless circuit with the most recent incidents
        settle(page)
        page.get_by_role("combobox", name="Action type").click()
        page.get_by_role("option", name="Equipment replacement").click()
        link_incidents(page, 2)
        page.get_by_role("textbox", name="Justification").fill(
            "Repeated incidents in the last three months at the same site. The customer premises unit restarts on "
            "its own and is out of support.")
        page.get_by_label("Expected outcome").fill("No equipment-related incident in the 90 days after the replacement.")
        shot(page, "03-new-request")
        page.get_by_role("button", name="Save and submit").click()
        settle(page)
        action_id = int(page.get_by_label("Go to action").input_value())
        shot(page, "04-submitted")
        sign_out(page)

        # Approver: queue, then return for changes
        sign_in(page, "m.arrieta")
        shot(page, "05-decision-queue")
        open_action(page, action_id)
        act(page, "Return for changes", "Link the other recent incidents of this circuit too, so the trend is visible.")
        shot(page, "06-returned")
        sign_out(page)

        # Requester: edits and resubmits
        sign_in(page, "a.etxeberria")
        open_action(page, action_id)
        page.get_by_role("button", name="Edit request").click()
        settle(page)
        link_incidents(page, 8)
        page.get_by_role("textbox", name="Justification").fill(
            "Repeated incidents in the last three months at the same site; all of them are now linked. The customer "
            "premises unit restarts on its own and is out of support.")
        shot(page, "07-edit-returned")
        page.get_by_role("button", name="Save and submit").click()
        settle(page)
        sign_out(page)

        # Approver: sees what changed, approves
        sign_in(page, "m.arrieta")
        open_action(page, action_id)
        shot(page, "08-version-diff")
        act(page, "Approve")
        sign_out(page)

        # Field coordinator: starts, notes, completes
        sign_in(page, "u.otaegui")
        shot(page, "09-field-work")
        open_action(page, action_id)
        act(page, "Start work")
        page.get_by_role("button", name="Add a work note").click()
        page.get_by_role("textbox", name="Note", exact=True).fill("Replacement unit installed and tested with the customer.")
        page.get_by_role("button", name="Add note").click()
        settle(page)
        act(page, "Record completion")
        shot(page, "10-completed")
        sign_out(page)

        # Approver: verifies; history; a rejection; indicators
        sign_in(page, "m.arrieta")
        go(page, "To verify")
        shot(page, "11-to-verify")
        open_action(page, action_id)
        act(page, "Verify")
        history = page.get_by_role("tab", name="History")
        history.click()
        shot(page, "12-verified-history", scroll_to=history)
        open_action(page, submitted_elsewhere(action_id))
        act(page, "Reject", "The circuit is in the regional migration plan for next quarter; a separate action would duplicate it.")
        shot(page, "13-rejected")
        go(page, "Indicators")
        shot(page, "14-indicators")
        sign_out(page)

        # Administrator: accounts and all actions
        sign_in(page, "admin")
        go(page, "Accounts")
        shot(page, "15-accounts")
        go(page, "All actions")
        shot(page, "16-all-actions")
        browser.close()


if __name__ == "__main__":
    main()
