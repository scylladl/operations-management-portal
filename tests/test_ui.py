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
