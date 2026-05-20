from thefuzz import process

DEBUG = False


def resolve_title(title: str, data: dict) -> tuple:
    is_anime = data["is_anime"]
    ambiguous = data["ambiguous"]
    if not is_anime:
        return None, "No es un anime"
    elif ambiguous:
        print()
        print("-" * 50)
        print(f'¿Qué quisiste decir con "{title}"?(original) LLM preguntando')
        for i, opcion in enumerate(data["options"]):
            print(f"({i + 1})- {opcion}")
        print("(X)  Descartar")
        indice = pedir_opcion(data["options"])
        if indice is None:
            return None, "Descartado"
        return data["options"][indice], "ok"
    else:
        return data["romaji"], "ok"


def select_from_results(results, title, romaji):
    match = process.extractOne(romaji, [a["title"] for a in results])

    if DEBUG and 90 <= match[1] < 100:
        print(f"SCORE={match[1]} | romaji={repr(romaji)} | mal={repr(match[0])}")  # debug

    if match[1] >= 95:
        matched_anime = next(a for a in results if a["title"] == match[0])
        return matched_anime["id"], matched_anime["title"]
    print()
    print("-" * 50)
    print(
        f'¿Qué quisiste decir con "{title}"/"{romaji}"? (Original/Gemini) MAL preguntando')
    top_5_matches = process.extract(romaji, [a["title"] for a in results], limit=5)
    top_5_animes = [next(a for a in results if a["title"] == titulo)
                    for titulo, score in top_5_matches]

    for i, anime in enumerate(top_5_animes):
        print(f"({i + 1})- {anime["title"]}")
    print("(X)  Descartar")
    indice = pedir_opcion(top_5_animes, "Ingresa el numero de opcion (1-5): ")
    if indice is None:
        return None
    chosen = top_5_animes[indice]
    return chosen["id"], chosen["title"]


def pedir_opcion(opciones: list, prompt: str = "Ingresa el numero de opcion: ") -> int | None:
    while True:
        try:
            eleccion = input(prompt)
            if eleccion.upper() == "X":
                return None

            eleccion = int(eleccion)
            if eleccion < 1 or eleccion > len(opciones):
                print("Fuera de rango. Intenta de nuevo.")
                continue
            return eleccion - 1
        except ValueError:
            print("No es un número. Intenta de nuevo.")