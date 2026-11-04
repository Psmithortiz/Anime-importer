"""HTTP pieces shared by the search adapters."""

import logging
import time
from collections.abc import Callable

import requests
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

logger = logging.getLogger(__name__)


def is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, (requests.ConnectionError, requests.Timeout)):
        return True
    if isinstance(exc, requests.HTTPError) and exc.response is not None:
        status = exc.response.status_code
        return status == 429 or status >= 500
    return False


http_retry = retry(
    retry=retry_if_exception(is_retryable),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=3),
    before_sleep=before_sleep_log(logger, logging.WARNING),
    reraise=True,
)


class Throttle:
    """Guarantee a minimum interval between calls to wait()."""

    def __init__(
        self,
        min_interval: float,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._min_interval = min_interval
        self._clock = clock
        self._sleep = sleep
        self._last_request: float | None = None

    def wait(self) -> None:
        if self._last_request is not None:
            elapsed = self._clock() - self._last_request
            if elapsed < self._min_interval:
                self._sleep(self._min_interval - elapsed)
        self._last_request = self._clock()
