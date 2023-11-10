from requests import Response
from requests.exceptions import HTTPError, Timeout

from inventree_part_import.retries import catch_timeouts, retries

def test_max_retries():
    count = 0
    try:
        for retry in retries(5, catch_timeouts, 0):
            with retry:
                count += 1
                raise Timeout()
    except Timeout:
        assert count == 6, "1 + 5 retries"
        return

    assert False, "unreachable"

def test_error_types():
    for i, retry in enumerate(retries(3, catch_timeouts, 0)):
        with retry:
            match i:
                case 0:
                    raise Timeout()
                case 1:
                    response = Response()
                    response.status_code = 408
                    raise HTTPError(response=response)
                case 2:
                    raise HTTPError({"status_code": 500})

    try:
        for retry in retries(3, catch_timeouts, 0):
            with retry:
                raise ValueError()
    except ValueError:
        return

    assert False, "unreachable"
