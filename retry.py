import time
from google.genai.errors import ClientError, ServerError
from json import JSONDecodeError
import requests
from normalizer_gemini import BatchValidationError


def intentar(func, *args, max_intentos=3, **kwargs):
    error_msg = None
    for intento in range(max_intentos):
        try:
            return (func(*args, **kwargs), None)

        except requests.exceptions.HTTPError as e:
            error_msg = f"Falló: HTTPError {e.response.status_code}"
            print(f"Intento {intento + 1} falló: HTTPError {e.response.status_code}")
            if intento < max_intentos - 1:
                time.sleep(3 * (2 ** intento))

        except BatchValidationError as e:
            error_msg = f"Falló: {str(e)}"
            print(f"Intento {intento + 1} falló: {type(e).__name__} / {e}")
            if intento < max_intentos - 1:
                time.sleep(5)

        except ClientError as e:
            if e.code == 429:
                error_msg = f"Falló: ClientError {e.code}"
                print(f"Intento {intento + 1} falló: {type(e).__name__}")
                print(e)
                if intento < max_intentos - 1:
                    time.sleep(60 * (intento + 1))
            else:
                error_msg = f"Falló: ClientError {e.code}"
                print(f"Intento {intento + 1} falló: {type(e).__name__}")
                if intento < max_intentos - 1:
                    time.sleep(3 * (2 ** intento))

        except (ServerError, JSONDecodeError) as e:
            error_msg = f"Falló: {type(e).__name__}"
            print(f"Intento {intento + 1} falló: {type(e).__name__}")
            if intento < max_intentos - 1:
                time.sleep(3 * (2 ** intento))
    return (None, error_msg)

