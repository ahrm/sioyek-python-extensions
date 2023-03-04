'''
Create a dual panel version of the PDF file.

Here is an example `prefs_user.config` file which uses this script:

    new_command _dual_panelify python -m sioyek.dual_panelify "%{sioyek_path}" "%{file_path}"

You can optionally specify side and middle margins in the command line:
    new_command _dual_panelify python -m sioyek.dual_panelify "%{sioyek_path}" "%{file_path}" "25 -40"

Or you can enter them as text in sioyek:
    new_command _dual_panelify python -m sioyek.dual_panelify "%{sioyek_path}" "%{file_path}" "%{command_text}"
'''

import sys
import random
import subprocess
import datetime
import fitz
from copy import copy
import numpy as np

from .sioyek import Sioyek, clean_path

from PyPDF2 import PdfWriter, PdfReader, PageObject, Transformation

UPDATE_EVERY_SECONDS = 3
SIDE_MARGIN = 25
MIDDLE_MARGIN = 25
sioyek = None

def first_and_last_nonzero(arr):
    first_index = -1
    last_index=-1
    index = 0

    while arr[index] == 0 and index < arr.size:
        index += 1
    
    if index < arr.size:
        first_index = index-1
    
    index = arr.size - 1
    while arr[index] == 0 and index >= 0:
        index -= 1
    last_index = index + 1
    return first_index, last_index

def get_pixmap_bounding_box(pixmap):
    pixmap_np = np.frombuffer(pixmap.samples, dtype=np.uint8).reshape(pixmap.height, pixmap.width, 3).mean(axis=2)

    vertical_hist = 255 - pixmap_np.sum(axis=0)
    vertical_hist_copy = vertical_hist.copy()
    v_nth = vertical_hist.size // 3
    vertical_hist_copy.partition(v_nth)
    v_thresh = vertical_hist_copy[v_nth]
    v_foreground = vertical_hist > v_thresh
    v_first_nonzero, v_last_nonzero = first_and_last_nonzero(v_foreground)

    bottom_right_x = v_last_nonzero
    bottom_right_y = pixmap.height
    
    top_left_x = v_first_nonzero
    top_left_y = 0

    return fitz.Rect(top_left_x, top_left_y, bottom_right_x, bottom_right_y)

def rect_union(rect1, rect2):
    return fitz.Rect(min(rect1.x0, rect2.x0), min(rect1.y0, rect2.y0), max(rect1.x1, rect2.x1), max(rect1.y1, rect2.y1))

def get_document_cropbox(doc):
    pages = [random.randint(0, doc.page_count-1) for _ in range(5)]
    boxes = []

    for i in pages:
        page = doc.load_page(i)
        pixmap = page.get_pixmap()
        boxes.append(get_pixmap_bounding_box(pixmap))
    
    res = boxes[0]
    for box in boxes[1:]:
        res = rect_union(res, box)
    
    res.x0 -= 5
    res.x1 += 5
    return res

if __name__ == '__main__':
    last_update_time = datetime.datetime.now()

    sioyek_path = clean_path(sys.argv[1])
    sioyek = Sioyek(sioyek_path)
    single_panel_file_path = clean_path(sys.argv[2])
    if len(sys.argv) > 3:
        margin_string = sys.argv[3]
        parts = margin_string.split(' ')
        if len(parts) > 1:
            SIDE_MARGIN = int(parts[0])
            MIDDLE_MARGIN = int(parts[1])

    dual_panel_file_path = single_panel_file_path.replace('.pdf', '_dual_panel.pdf')

    pdf_reader = PdfReader(single_panel_file_path)
    pdf_writer = PdfWriter()

    doc = fitz.open(single_panel_file_path)
    cropbox = get_document_cropbox(doc)

    for i in range(len(pdf_reader.pages) // 2):
        if (datetime.datetime.now() - last_update_time).seconds > UPDATE_EVERY_SECONDS:
            last_update_time = datetime.datetime.now()
            # subprocess.run([sioyek_path, '--execute-command', 'set_status_string', '--execute-command-data', 'Dual panelifying {} / {}'.format((i+1) * 2, pdf_reader.numPages)])
            sioyek.set_status_string('Dual panelifying {} / {}'.format((i+1) * 2, len(pdf_reader.pages)))

        page1 = copy(pdf_reader.pages[2 * i])
        page2 = copy(pdf_reader.pages[2 * i+1])

        original_width1 = page1.mediabox.width
        original_width2 = page2.mediabox.width

        llx = page1.cropbox.lower_right[0]
        lly = page1.cropbox.lower_right[1]
        page2.cropbox.lower_left = (llx, lly)

        urx = page1.cropbox.lower_right[0] + page2.cropbox.lower_right[0]
        ury = page2.cropbox.upper_right[1]
        page2.cropbox.upper_right = (urx, ury)


        # total_width = original_width1 + original_width2
        total_width = page1.mediabox.width + page2.mediabox.width + 2 * SIDE_MARGIN + MIDDLE_MARGIN
        total_height = max([page1.mediabox.height, page2.mediabox.height])
        new_page = PageObject.create_blank_page(None, total_width, total_height)

        # new_page.mergeTranslatedPage(page1, -page1.mediabox.left + SIDE_MARGIN, 0)
        page1.add_transformation(Transformation().translate( SIDE_MARGIN, 0))
        new_page.merge_page(page1)

        # new_page.mergeTranslatedPage(page2, page1.mediabox.width - page1.mediabox.left + SIDE_MARGIN + MIDDLE_MARGIN, 0)
        page2.add_transformation(Transformation().translate(page1.mediabox.width + SIDE_MARGIN + MIDDLE_MARGIN, 0))
        new_page.merge_page(page2)

        pdf_writer.add_page(new_page)
    
    if len(pdf_reader.pages) % 2 == 1:
        pdf_writer.add_page(pdf_reader.pages[len(pdf_reader.pages) - 1])

    sioyek.set_status_string('Writing new file to disk')
    with open(dual_panel_file_path, 'wb') as f:
        pdf_writer.write(f)

    sioyek.clear_status_string()
    subprocess.run([sioyek_path, '--new-window', dual_panel_file_path])