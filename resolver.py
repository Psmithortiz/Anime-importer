from normalizer import normalize_title


def resolve_title(title):
    data = normalize_title(title)
    is_anime = data["is_anime"]
    ambiguous = data["ambiguous"]
    print(data)

    if is_anime == False:
        return title
    elif ambiguous == True:
        print(f'¿Qué quisiste decir con "{title}"?')
        for i, opcion in enumerate(data["options"]):
            print(i+1, opcion)
        eleccion = int(input("Ingresa el numero de opcion: "))
        return data["options"][eleccion-1]

    else:
        return data["romaji"]

def select_from_results(results, title):
    print(f'¿Qué quisiste decir con "{title}"? MAL PREGUNTANDO ')
    for i, anime in enumerate(results):
        print(i + 1, anime["title"])
    eleccion = int(input("Ingresa el numero de opcion: "))
    return results[eleccion - 1]["id"]



#Testing
if __name__ == "__main__":
    print(resolve_title("ghost in the shell"))