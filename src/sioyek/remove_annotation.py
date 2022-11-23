
import sys
from .sioyek import Sioyek, clean_path

def parse_rect(s):
    parts = s.split(',')
    page = int(parts[0])
    rect = [float(part) for part in parts[1:]]
    return page, rect


if __name__ == '__main__':
    SIOYEK_PATH = clean_path(sys.argv[1])
    LOCAL_DATABASE_PATH = clean_path(sys.argv[2])
    SHARED_DATABASE_PATH = clean_path(sys.argv[3])
    FILE_PATH = clean_path(sys.argv[4])
    rect_string = sys.argv[5]

    sioyek = Sioyek(SIOYEK_PATH, LOCAL_DATABASE_PATH, SHARED_DATABASE_PATH)
    document = sioyek.get_document(FILE_PATH)
    selected_page, selected_rect = parse_rect(rect_string)

    document.remove_annotations(selected_page, selected_rect)
    sioyek.reload()