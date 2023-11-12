from contextlib import contextmanager
import time

from inventree.api import InvenTreeAPI
from requests.exceptions import HTTPError, Timeout

class retries:
    def __init__(self, n, context_manager, timeout):
        self.context_manager = context_manager
        self.retries = 0
        self.max_retries = n
        self.timeout = timeout

    def __iter__(self):
        return self

    def __next__(self):
        if self.retries > self.max_retries:
            raise StopIteration

        if self.retries > 0:
            time.sleep(self.timeout)

        if self.retries == self.max_retries:
            self.retries += 1
            return self._dummy_manager()
        else:
            self.retries += 1
            return self.context_manager(self)

    def stop(self):
        self.retries = self.max_retries + 1

    @contextmanager
    def _dummy_manager(self):
        yield

@contextmanager
def catch_timeouts(_retries: retries):
    try:
        yield
        _retries.stop()
    except (Timeout, ConnectionError):
        pass
    except HTTPError as e:
        status_code = None
        if e.response is not None:
            status_code = e.response.status_code
        elif e.args:
            status_code = e.args[0].get("status_code")
        if status_code not in {408, 409, 500, 502, 503, 504}:
            raise e

class retry_timeouts(retries):
    def __init__(self, n=3, context_manager=catch_timeouts):
        from .config import get_config
        super().__init__(n, context_manager, timeout=get_config()["retry_timeout"])

class RetryInvenTreeAPI(InvenTreeAPI):
    def testServer(self):
        for retry in retry_timeouts():
            with retry:
                return super().testServer()

    def request(self, api_url, **kwargs):
        for retry in retry_timeouts():
            with retry:
                return super().request(api_url, **kwargs)

    def downloadFile(self, url, destination, overwrite=False, params=None, proxies=...):
        for retry in retry_timeouts():
            with retry:
                return super().downloadFile(url, destination, overwrite, params, proxies)
