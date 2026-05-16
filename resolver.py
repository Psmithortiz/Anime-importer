
from normalizer_gemini import normalize_title
from thefuzz import process

from retry import intentar


def resolve_title(title):
    data, error = intentar(normalize_title, title)
    if error:
        return (None, f"Error de red al normalizar: {error}")

    is_anime = data["is_anime"]
    ambiguous = data["ambiguous"]
    if is_anime == False:
        return (None, "No es un anime")
    elif ambiguous == True:
        print(f'¿Qué quisiste decir con "{title}"?')
        for i, opcion in enumerate(data["options"]):
            print(i + 1, opcion)
        while True:
            try:
                eleccion = int(input("Ingresa el numero de opcion: "))
                return (data["options"][eleccion - 1], "ok")
            except (ValueError, IndexError):
                print("Opción inválida. Intenta de nuevo.")
    else:
        return (data["romaji"], "ok")


def select_from_results(results, title, romaji):
    match = process.extractOne(romaji, [a["title"] for a in results])
    if match[1] >= 80:
        matched_anime = next(a for a in results if a["title"] == match[0])
        return (matched_anime["id"], matched_anime["title"])

    print(f'¿Qué quisiste decir con "{title}"? MAL PREGUNTANDO ')
    for i, anime in enumerate(results):
        print(i + 1, anime["title"])
    while True:
        try:
            eleccion = int(input("Ingresa el numero de opcion: "))
            chosen = results[eleccion - 1]
            return (chosen["id"], chosen["title"])
        except (ValueError, IndexError):
            print("Opción inválida. Intenta de nuevo.")
