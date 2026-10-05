import json, os, tempfile
from types import SimpleNamespace

import watcher

PAGE = """<html><head><script>var n="{nonce}";</script></head><body>
<!-- generated {nonce} -->
<input type="hidden" name="_wpnonce" value="{nonce}">
<h1>Event</h1><p>Registration opens soon</p>
<a href="/about?_wpnonce={nonce}">About</a>
{extra}
</body></html>"""


def page(nonce="aaa", extra=""):
    return PAGE.format(nonce=nonce, extra=extra)


def test_normalize_ignores_noise():
    assert watcher.normalize(page("aaa")) == watcher.normalize(page("bbb"))


def test_normalize_detects_new_link_and_text():
    base = watcher.normalize(page())
    new = watcher.normalize(page(extra='<a href="/register">Register now</a>'))
    assert watcher.signature(*base) != watcher.signature(*new)
    assert "/register" in new[1]
    assert "Register now" in new[0]


def test_normalize_selector():
    html = '<div id="a">one</div><div id="b">two</div>'
    assert watcher.normalize(html, "#a")[0] == "one"


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
