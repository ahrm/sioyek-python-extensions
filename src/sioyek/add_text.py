import sys
from .sioyek import Sioyek, clean_path
from collections import defaultdict

def parse_rect(s):
    parts = s.split(',')
    page = int(parts[0])
    rect = [float(part) for part in parts[1:]]
    return page, rect

def parse_params(ps):
    res = dict()

    def default_creator():
        def default(x):
            return x
        return default

    def parse_color(s):
        return tuple(float(c) for c in s.split(','))

    key_validators = defaultdict(default_creator)
    key_validators['fontsize'] = float
    key_validators['text_color'] = parse_color
    key_validators['fill_color'] = parse_color
    key_validators['border_color'] = parse_color

    for param_string in ps:
        key, value = param_string.split('=')
        res[key] = key_validators[key](value)

    return res

if __name__ == '__main__':

    SIOYEK_PATH = clean_path(sys.argv[1])
    LOCAL_DATABASE_PATH = clean_path(sys.argv[2])
    SHARED_DATABASE_PATH = clean_path(sys.argv[3])
    FILE_PATH = clean_path(sys.argv[4])
    rect_string = sys.argv[5]
    added_text = sys.argv[6]

    params = parse_params(sys.argv[7:])

    sioyek = Sioyek(SIOYEK_PATH, LOCAL_DATABASE_PATH, SHARED_DATABASE_PATH)
    document = sioyek.get_document(FILE_PATH)
    selected_page, selected_rect = parse_rect(rect_string)

    document.embed_text_in_pdf(added_text, selected_page, selected_rect, params)
    sioyek.reload()
