from app.services.document.normalize import normalize_url


def test_lowercases_scheme_and_host():
    assert normalize_url("HTTPS://Example.COM/path") == "https://example.com/path"


def test_strips_default_port():
    assert normalize_url("https://example.com:443/path") == "https://example.com/path"
    assert normalize_url("http://example.com:80/path") == "http://example.com/path"


def test_keeps_non_default_port():
    assert normalize_url("https://example.com:8443/path") == "https://example.com:8443/path"


def test_strips_fragment():
    assert normalize_url("https://example.com/path#section-2") == "https://example.com/path"


def test_strips_trailing_slash_except_root():
    assert normalize_url("https://example.com/path/") == "https://example.com/path"
    assert normalize_url("https://example.com/") == "https://example.com/"


def test_strips_tracking_params():
    assert (
        normalize_url("https://example.com/path?utm_source=x&utm_medium=y&gclid=z")
        == "https://example.com/path"
    )


def test_sorts_remaining_query_params():
    assert (
        normalize_url("https://example.com/path?b=2&a=1")
        == normalize_url("https://example.com/path?a=1&b=2")
    )


def test_same_input_same_output():
    url = "https://Example.com:443/Path/?utm_source=x&b=2&a=1#frag"
    assert normalize_url(url) == normalize_url(url)
