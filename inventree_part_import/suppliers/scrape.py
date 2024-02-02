import re, time

from fake_useragent import UserAgent
from requests import Response, Session

from ..config import get_config
from ..error_helper import *
from ..retries import retry_timeouts

_SESSION = None

def scrape(url, extra_headers=None, fallback_domains=None, setup_hook=None) -> Response:
    global _SESSION

    if not _SESSION:
        _SESSION = setup_session(setup_hook)

    config = get_config()
    request_timeout = config["request_timeout"]
    retry_timeout = config["retry_timeout"]

    for retry in retry_timeouts():
        with retry:
            result = _SESSION.get(url, headers=extra_headers, timeout=request_timeout)
    if result.status_code == 200:
        return result

    fallback_domains = fallback_domains if fallback_domains else [None]
    for fallback in fallback_domains:
        fallback_str = f"via '{fallback}' " if fallback else ""
        warning(
            f"failed to get page, retrying in {retry_timeout}s {fallback_str}"
            f"with new session and user agent"
        )
        time.sleep(retry_timeout)

        _SESSION = setup_session(setup_hook)

        fallback_url = DOMAIN_REGEX.sub(DOMAIN_SUB.format(fallback), url) if fallback else url
        for retry in retry_timeouts():
            with retry:
                result = _SESSION.get(fallback_url, headers=extra_headers)
        if result.status_code == 200:
            return result

_DEFAULT_HEADERS = {
    "Accept-Language": "en-US,en",
}

def setup_session(setup_hook=None) -> Session:
    session = Session()
    session.headers.update({
        "User-Agent": UserAgent().random,
        **_DEFAULT_HEADERS,
    })

    if setup_hook:
        for retry in retry_timeouts():
            with retry:
                setup_hook(session)

    return session

DOMAIN_REGEX = re.compile(r"(https?://)(?:[^./]*\.?)*/")
DOMAIN_SUB = "\\g<1>{}/"

REMOVE_HTML_TAGS = re.compile(r"<.*?>|&([a-z0-9]+|#[0-9]{1,6}|#x[0-9a-f]{1,6});")
