

def read_list(filepath):
    with open(filepath, "r", encoding="utf-8") as f:
        datos = f.readlines()
        datos_limpios = [s.strip() for s in datos]
        return datos_limpios



#Testing
if __name__ == "__main__":
    print (read_list("anime_list.txt"))