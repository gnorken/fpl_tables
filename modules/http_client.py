# modules/http_client.py
from requests import Session
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


def make_session(pool=60, retries=2, backoff=0.2):
    s = Session()

    retry = Retry(
        total=retries,
        connect=retries,
        read=retries,
        status=retries,
        backoff_factor=backoff,
        status_forcelist=(429, 500, 502, 503, 504),
        raise_on_status=False,
    )

    adapter = HTTPAdapter(
        pool_connections=pool,
        pool_maxsize=pool,
        max_retries=retry,
        pool_block=True,  # <- don't discard; wait for a free connection
    )

    s.mount("https://", adapter)
    s.mount("http://", adapter)
    s.headers.update({
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json",
        "Connection": "keep-alive",
    })
    return s


HTTP = make_session(pool=60)
