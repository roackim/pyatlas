
from pyatlas.parse_jsons import extract_sheet_infos

def extract_infos():

    json_files = None
    with open('list.txt', 'r') as file:
        # Reading the file and splitting it into a list of strings
        json_files = file.read().splitlines()

    sprite_sheets = []
    for json_file in json_files:
        sp = extract_sheet_infos(json_file)
        sprite_sheets.append(sp)

    return sprite_sheets