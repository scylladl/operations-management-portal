"""User text shown through Markdown must not become links, images, HTML or Streamlit directives."""
import pytest

from portal.ui import plain


@pytest.mark.parametrize("text", ["![pixel](http://example.com/p.png)", "[click](http://example.com)",
                                  "<img src=x>", ":red[alarm]", "$x^2$", "**loud**"])
def test_markdown_is_neutralised(text):
    escaped = plain(text)
    for i, char in enumerate(escaped):
        if char in "![]()<>:$*":
            assert escaped[i - 1] == "\\", (text, escaped)


def test_empty_values_pass_through():
    assert plain(None) is None and plain("") == ""


def test_components_escape_database_values():
    from portal import components
    hostile = '<img src=x onerror=alert(1)>'
    markup = (components.timeline([(hostile, "Saved", "now", [hostile], hostile)])
              + components.facts([("Customer", hostile)]) + components.user_chip(hostile, hostile)
              + components.action_card({"ActionId": 1, "ActionTypeName": hostile, "CircuitId": hostile,
                                        "Status": "Draft", "StatusName": "Draft", "RequesterName": hostile}))
    assert "<img" not in markup and "&lt;img" in markup


@pytest.mark.parametrize("status, started, current, marked", [
    ("Submitted", False, "Submitted", "current"),
    ("Returned", False, "Returned", "stopped"),
    ("Rejected", False, "Rejected", "stopped"),
    ("Cancelled", False, "Cancelled", "stopped grey"),
    ("Cancelled", True, "Cancelled", "stopped grey"),
])
def test_stepper_marks_where_the_action_is(status, started, current, marked):
    from portal import components
    markup = components.stepper(status, started)
    assert f'ng-step {marked}"><span class="dot">' in markup and f'class="label">{current}<' in markup


def test_stepper_cancelled_after_start_stops_at_in_progress():
    from portal import components
    steps = components.stepper("Cancelled", True).split('<div class="ng-step ')[1:]   # Draft, Submitted, Approved, In progress, ...
    assert "Cancelled" in steps[3] and steps[2].startswith("done")
