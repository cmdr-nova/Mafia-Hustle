import pytest

from mafia_hustle.oauth import safe_http


@pytest.mark.parametrize(
    "url",
    [
        "https://fedi.example.org/api/v1/apps",
        "https://bsky.social/.well-known/oauth-authorization-server",
    ],
)
def test_allows_public_https(url):
    assert safe_http.check_url(url) == url


@pytest.mark.parametrize(
    "url",
    [
        "http://fedi.example.org/",  # not https
        "https://127.0.0.1/",  # raw IP
        "https://[::1]/",
        "https://10.0.0.5/",
        "https://localhost/",
        "https://printer.local/",
        "https://fedi.example.org:8443/",  # custom port
        "https://user:pw@fedi.example.org/",
        "https://intranet/",  # no dot
        "file:///etc/passwd",
    ],
)
def test_blocks_unsafe_urls(url):
    with pytest.raises(safe_http.UnsafeURL):
        safe_http.check_url(url)
