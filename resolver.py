from thefuzz import process

DEBUG = False


def resolve_title(title: str, data: dict) -> tuple:
    is_anime = data["is_anime"]
    ambiguous = data["ambiguous"]
    if is_anime == False:
        return (None, "No es un anime")
    elif ambiguous == True:
        print()
        print("-" * 50)
        print(f'¿Qué quisiste decir con "{title}"?(original) LLM pregruntando')
        for i, opcion in enumerate(data["options"]):
            print(f"({i + 1})- {opcion}")
        print("(X)  Descartar")
        while True:
            try:
                eleccion = (input("Ingresa el numero de opcion: "))
                if eleccion.upper() == "X":
                    return (None, "Descartado")
                eleccion = int(eleccion)
                if eleccion < 1 or eleccion > len(data["options"]):
                    print("Fuera de rango. Intenta de nuevo.")
                    continue
                return (data["options"][eleccion - 1], "ok")
            except (ValueError, IndexError):
                print("Opción inválida. Intenta de nuevo.")
    else:
        return (data["romaji"], "ok")


def select_from_results(results, title, romaji):
    match = process.extractOne(romaji, [a["title"] for a in results])

    if DEBUG and 90 <= match[1] < 100:
        print(f"SCORE={match[1]} | romaji={repr(romaji)} | mal={repr(match[0])}")  # debug

    if match[1] >= 95:
        matched_anime = next(a for a in results if a["title"] == match[0])
        return (matched_anime["id"], matched_anime["title"])
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
    while True:
        try:
            eleccion = (input("Ingresa el numero de opcion (1-5): "))
            if eleccion.upper() == "X":
                return None

            eleccion = int(eleccion)
            if eleccion < 1 or eleccion > len(top_5_animes):
                print("Fuera de rango. Intenta de nuevo.")
                continue
            chosen = top_5_animes[eleccion - 1]
            return (chosen["id"], chosen["title"])
        except ValueError:
            print("No es un número. Intenta de nuevo.")
