from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

# ARCHITECTURE.md §6.1 rule 4 — stripped because they vary per-visit/per-referrer
# without changing what page the URL points to.
_TRACKING_PARAM_PREFIXES = ("utm_",)
_TRACKING_PARAM_NAMES = frozenset({"gclid", "fbclid", "ref", "msclkid", "mc_cid", "mc_eid"})

_DEFAULT_PORTS = {"http": "80", "https": "443"}


def _is_tracking_param(name: str) -> bool:
    lowered = name.lower()
    return lowered in _TRACKING_PARAM_NAMES or lowered.startswith(_TRACKING_PARAM_PREFIXES)


def normalize_url(url: str) -> str:
    """Canonical cache key for a URL. See ARCHITECTURE.md §6.1 for the rules.

    Same normalized_url in, same normalized_url out, always — this is the
    only lookup key the research pipeline uses to decide "already cached".
    """
    parts = urlsplit(url)

    scheme = parts.scheme.lower()
    hostname = (parts.hostname or "").lower()
    port = parts.port
    netloc = hostname
    if port is not None and str(port) != _DEFAULT_PORTS.get(scheme):
        netloc = f"{hostname}:{port}"

    path = parts.path
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")

    raw_pairs = parse_qsl(parts.query, keep_blank_values=True)
    query_pairs = [(k, v) for k, v in raw_pairs if not _is_tracking_param(k)]
    query_pairs.sort(key=lambda pair: (pair[0], pair[1]))
    query = urlencode(query_pairs)

    return urlunsplit((scheme, netloc, path, query, ""))
