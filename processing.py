import time
from tqdm import tqdm
from normalizer_gemini import normalize_titles
from retry import intentar


def normalizar_lista_completa(
        titles: list[str], chunk_size: int = 20, sleep_seconds: int = 13,
) -> tuple[dict | None, str | None]:
    data_total = []
    total_chunks = (len(titles) + chunk_size - 1) // chunk_size
    for inicio in tqdm(
            range(0, len(titles), chunk_size),
            total=total_chunks,
            desc="Normalizando",
    ):
        fin = inicio + chunk_size
        chunk = titles[inicio:fin]
        resultado_chunk, error = intentar(normalize_titles, chunk)
        if error:
            return None, f"Fallo la normalización del chunk {inicio}-{fin}: {error}"
        for item in resultado_chunk:
            item["n"] = item["n"] + inicio
        data_total.extend(resultado_chunk)
        if inicio + chunk_size < len(titles):
            time.sleep(sleep_seconds)
    data_por_n = {item["n"]: item for item in data_total}
    return data_por_n, None