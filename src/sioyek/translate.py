import sys
from googletrans import Translator

from .sioyek import Sioyek, clean_path

if __name__ == '__main__':
    sioyek_path = clean_path(sys.argv[1])
    text = sys.argv[2]
    sioyek = Sioyek(sioyek_path)
    translator = Translator()
    translation = translator.translate(text, dest='en')
    sioyek.set_status_string(translation.text)