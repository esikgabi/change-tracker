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


def test_build_body():
    body = watcher.build_body("http://x/e", "a\nb", "a\nc", ["/a"], ["/a", "/register"])
    assert "http://x/e" in body
    assert "-b" in body and "+c" in body
    assert "/register" in body and "New links" in body


def make_cfg():
    d = tempfile.mkdtemp()
    return SimpleNamespace(url="http://x", selector=None, state_path=os.path.join(d, "s.json"))


def run(cfg, html=None, boom=False, send_fails=False):
    sent = []

    def fetch_fn(url):
        if boom:
            raise RuntimeError("down")
        return html

    def send(cfg_, subject, body):
        if send_fails:
            raise OSError("smtp down")
        sent.append(subject)

    try:
        watcher.check(cfg, fetch_fn, send)
    except OSError:
        pass
    return sent


def test_baseline_then_no_change_then_change():
    cfg = make_cfg()
    assert run(cfg, page("a")) == ["Watcher started"]
    assert run(cfg, page("b")) == []  # nonce noise only
    assert run(cfg, page(extra='<a href="/r">Register</a>')) == ["Page changed"]
    assert run(cfg, page(extra='<a href="/r">Register</a>')) == []


def test_smtp_failure_retries_change():
    cfg = make_cfg()
    run(cfg, page())
    assert run(cfg, page(extra="<p>new</p>"), send_fails=True) == []
    assert run(cfg, page(extra="<p>new</p>")) == ["Page changed"]


def test_failure_alert_once_then_recovery():
    cfg = make_cfg()
    run(cfg, page())
    assert run(cfg, boom=True) == []
    assert run(cfg, boom=True) == []
    assert run(cfg, boom=True) == ["Watcher failing"]
    assert run(cfg, boom=True) == []
    assert run(cfg, page()) == ["Watcher recovered"]


def test_selector_mismatch_counts_as_failure():
    cfg = make_cfg()
    run(cfg, page())
    cfg.selector = "#nope"
    assert [run(cfg, page()) for _ in range(4)] == [[], [], ["Watcher failing"], []]


def test_recovered_sent_once_even_if_next_send_fails():
    cfg = make_cfg()
    run(cfg, page())
    for _ in range(3):
        run(cfg, boom=True)
    sent = []

    def send(c, subject, body):
        if sent:
            raise OSError("smtp down")
        sent.append(subject)

    try:
        watcher.check(cfg, lambda u: page(extra="<p>new</p>"), send)
    except OSError:
        pass
    assert sent == ["Watcher recovered"]
    assert run(cfg, page(extra="<p>new</p>")) == ["Page changed"]


def test_nonce_keeps_rest_of_href():
    assert watcher.normalize('<a href="/p?_wpnonce=x&a=1">a</a><a href="/about?_wpnonce=x">b</a>')[1] == ["/about", "/p?a=1"]


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
