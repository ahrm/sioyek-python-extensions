import sys
import asyncio
from googletrans import Translator

from .sioyek import Sioyek, clean_path

async def translate_text(text):
    async with Translator() as translator:
        result = await translator.translate(text, dest='en')
        return result

if __name__ == '__main__':
    sioyek_path = clean_path(sys.argv[1])
    text = sys.argv[2]
    sioyek = Sioyek(sioyek_path)
    translation = asyncio.run(translate_text(text)).text
    sioyek.set_status_string(translation)
