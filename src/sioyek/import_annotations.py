import sys
from .sioyek import Sioyek, clean_path

if __name__ == '__main__':
    SIOYEK_PATH = clean_path(sys.argv[1])
    LOCAL_DATABASE_PATH = clean_path(sys.argv[2])
    SHARED_DATABASE_PATH = clean_path(sys.argv[3])
    FILE_PATH = clean_path(sys.argv[4])

    if len(sys.argv) > 5:
        embed_method = sys.argv[5] 
    else:
        embed_method = 'custom'

    sioyek = Sioyek(SIOYEK_PATH, LOCAL_DATABASE_PATH, SHARED_DATABASE_PATH)
    document = sioyek.get_document(FILE_PATH)
    document.import_annotations()
    document.close()
    sioyek.reload()
    sioyek.close()
