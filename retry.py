import time
from requests.exceptions import Timeout, ConnectionError, HTTPError
from json import JSONDecodeError


def intentar(func, *args, max_intentos=3, **kwargs):
    error_msg = None
    for intento in range(max_intentos):
        try:
            return (func(*args, **kwargs), None)

        except (Timeout, ConnectionError, HTTPError, JSONDecodeError) as e:
            error_msg = f"Falló: {type(e).__name__}"
            print(f"Intento {intento + 1} falló: {type(e).__name__}")
            if intento < max_intentos - 1:
                time.sleep(2 ** intento)
    return (None, error_msg)
