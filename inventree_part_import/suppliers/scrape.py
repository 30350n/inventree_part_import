import re
import time

from fake_useragent import UserAgent
from requests import Session, Response

from ..error_helper import *

REQUEST_TIMEOUT = 10
RETRY_TIMEOUT = 5

SESSION = None

def scrape(url, extra_headers=None, fallback_domains=None, setup_hook=None) -> Response:
    global SESSION

    if not SESSION:
        SESSION = setup_session(setup_hook)

    result = SESSION.get(url, headers=extra_headers, timeout=REQUEST_TIMEOUT)
    if result.status_code == 200:
        return result

    fallback_domains = fallback_domains if fallback_domains else [None]
    for fallback in fallback_domains:
        fallback_str = f"via '{fallback}' " if fallback else ""
        warning(
            f"failed to get page, retrying in {RETRY_TIMEOUT}s {fallback_str}"
            f"with new session and user agent"
        )
        time.sleep(RETRY_TIMEOUT)

        SESSION = setup_session(setup_hook)

        fallback_url = DOMAIN_REGEX.sub(DOMAIN_SUB.format(fallback), url) if fallback else url
        result = SESSION.get(fallback_url, headers=extra_headers)
        if result.status_code == 200:
            return result

DEFAULT_HEADERS = {
    "Accept-Language": "en-US,en",
}

def setup_session(setup_hook=None) -> Session:
    session = Session()
    session.headers.update({
        "User-Agent": UserAgent().random,
        **DEFAULT_HEADERS,
    })

    if setup_hook:
        setup_hook(session)

    return session

DOMAIN_REGEX = re.compile(r"(https?://)(?:[^./]*\.?)*/")
DOMAIN_SUB = "\\g<1>{}/"
