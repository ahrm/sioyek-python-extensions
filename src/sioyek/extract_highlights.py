'''
Create a new document with highlights of the current document.
Can be used by adding the following to your prefs_user.config:

new_command _extract_highlights python -m sioyek.extract_highlights "%{sioyek_path}" "%{local_database}" "%{shared_database}" "%{file_path}" %{zoom_level}

'''
import os
import sys
import pathlib
import sqlite3
from copy import copy
import hashlib
import subprocess

from .sioyek import Sioyek
from PyPDF2 import PdfWriter, PdfReader

LOCAL_DATABASE_FILE = None
SHARED_DATABASE_FILE = None

sioyek = None
SELECT_DOCUMENT_HIGHLIGHTS_QUERY = "SELECT * from highlights where document_path='{}'"
SELECT_HASH_QUERY = "SELECT * from document_hash where path='{}'"
INSERT_DOCUMENT_HASH = "INSERT INTO document_hash (path, hash) VALUES ('{}', '{}')"
PORTAL_INSERT_QUERY = "INSERT INTO links (src_document, dst_document, src_offset_y, dst_offset_x, dst_offset_y, dst_zoom_level) VALUES ('{}', '{}', {}, {}, {}, {})"
PORTAL_DELETE_QUERY = "DELETE FROM links WHERE src_document='{}'"
UPDATE_DOCUMENT_HASH_QUERY = "UPDATE document_hash SET hash='{}' WHERE path='{}'"
INSERT_NEW_DOCUMENT_HASH_QUERY = "INSERT INTO document_hash (path, hash) VALUES ('{}', '{}')"

SIOYEK_PATH = None

def md5_hash(file_path):
    file_hash = hashlib.md5()

    with open(file_path, "rb") as f:
        chunk = f.read(8192)
        while chunk:
            file_hash.update(chunk)
            chunk = f.read(8192)
            
    return file_hash.hexdigest()

def delete_prev_portals_of_document(shared_cursor, document_hash):
    query = PORTAL_DELETE_QUERY.format(document_hash)
    shared_cursor.execute(query)

def get_hash_with_path(local_cursor, file_path):
    results = local_cursor.execute(SELECT_HASH_QUERY.format(file_path)).fetchall()
    if len(results) > 0:
        return results[0][-1]
    else:
        return None

def update_document_hash(local_cursor, document_path, document_hash):
    prev_hash = get_hash_with_path(local_cursor, document_path)
    if prev_hash != None and prev_hash != document_hash:
        query = UPDATE_DOCUMENT_HASH_QUERY.format(document_hash, document_path)
        local_cursor.execute(query)

    if prev_hash == None:
        query = INSERT_NEW_DOCUMENT_HASH_QUERY.format(document_path, document_hash)
        local_cursor.execute(query)


if __name__ == '__main__':

    doc_path = None
    new_file_path = None

    if len(sys.argv) > 1:
        SIOYEK_PATH = sys.argv[1]
        LOCAL_DATABASE_FILE = sys.argv[2]
        SHARED_DATABASE_FILE = sys.argv[3]
        doc_path = sys.argv[4]
        zoom_level = float(sys.argv[5])
        doc_dir = os.path.dirname(doc_path)
        doc_base_file_name = os.path.basename(doc_path).split('.')[0]
        new_file_name = doc_base_file_name + '_highlights.pdf'
        new_file_path = str(pathlib.Path(doc_dir) / new_file_name).replace('\\', '/')
    sioyek = Sioyek(SIOYEK_PATH, LOCAL_DATABASE_FILE, SHARED_DATABASE_FILE)

    # open sqlite3 database
    local_database = sqlite3.connect(LOCAL_DATABASE_FILE)
    shared_database = sqlite3.connect(SHARED_DATABASE_FILE)

    doc = sioyek.get_document(doc_path)
    document_hash = doc.get_hash()
    document_highlights = doc.get_highlights()

    highlight_bounding_boxes = [doc.get_highlight_bounding_box(highlight.get_begin_abs_pos(), highlight.get_end_abs_pos()) for highlight in document_highlights]

    highlight_bounding_boxes = sorted(highlight_bounding_boxes, key=lambda x: x[1])
    
    pdf_reader = PdfReader(doc_path)
    pdf_writer = PdfWriter()

    new_document_offsets = []

    offset = 0
    blank_height = 50
    for bounding_box, page_number in highlight_bounding_boxes:
        pdf_page = copy(pdf_reader.pages[page_number])
        h = int(pdf_page.mediabox.height)


        margin = 20
        old_mediabox = pdf_page.mediabox.copy()
        pdf_page.mediabox.upper_left = (bounding_box[0], h - bounding_box[1] + margin)
        pdf_page.mediabox.lower_right = (bounding_box[2],  h - bounding_box[3] - margin)
        pdf_writer.add_page(pdf_page)
        pdf_writer.add_blank_page(height=blank_height, width=pdf_page.mediabox.width)

        new_document_offsets.append(offset)
        offset += int(pdf_page.mediabox.height) + blank_height

    with open(new_file_path, 'wb') as f:
        pdf_writer.write(f)

    new_file_hash = md5_hash(new_file_path)

    local_cursor = local_database.cursor()
    shared_cursor = shared_database.cursor()
    local_cursor.execute('begin')
    shared_cursor.execute('begin')
    try:

        update_document_hash(local_cursor, new_file_path, new_file_hash)
        delete_prev_portals_of_document(shared_cursor, new_file_hash)
        for src_offset, highlight in zip(new_document_offsets, document_highlights):
            dst_y_offset = (highlight.selection_begin[1] + highlight.selection_end[1]) / 2
            dst_zoom_level = zoom_level / 2
            dst_document = document_hash
            src_document = new_file_hash
            query = PORTAL_INSERT_QUERY.format(src_document, dst_document, src_offset, 0, dst_y_offset, dst_zoom_level)
            shared_cursor.execute(query)

        local_cursor.execute('commit')
        shared_cursor.execute('commit')
    except sqlite3.Error as e:
        print(str(e))
        local_cursor.execute('rollback')
        shared_cursor.execute('rollback')
    
    subprocess.run([SIOYEK_PATH, new_file_path, '--new-window'])
    subprocess.run([SIOYEK_PATH, '--execute-command', 'reload'])

    local_database.close()
    shared_database.close()
