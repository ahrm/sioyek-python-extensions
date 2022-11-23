from contextlib import redirect_stdout
from dataclasses import dataclass
from functools import lru_cache
import os
import regex
import sqlite3
import subprocess
import sys
import math
from collections import defaultdict

import fitz

COLOR_MAP = {'a': (0.94, 0.64, 1.00),
            'b': (0.00, 0.46, 0.86),
            'c': (0.60, 0.25, 0.00),
            'd': (0.30, 0.00, 0.36),
            'e': (0.10, 0.10, 0.10),
            'f': (0.00, 0.36, 0.19),
            'g': (0.17, 0.81, 0.28),
            'h': (1.00, 0.80, 0.60),
            'i': (0.50, 0.50, 0.50),
            'j': (0.58, 1.00, 0.71),
            'k': (0.56, 0.49, 0.00),
            'l': (0.62, 0.80, 0.00),
            'm': (0.76, 0.00, 0.53),
            'n': (0.00, 0.20, 0.50),
            'o': (1.00, 0.64, 0.02),
            'p': (1.00, 0.66, 0.73),
            'q': (0.26, 0.40, 0.00),
            'r': (1.00, 0.00, 0.06),
            's': (0.37, 0.95, 0.95),
            't': (0.00, 0.60, 0.56),
            'u': (0.88, 1.00, 0.40),
            'v': (0.45, 0.04, 1.00),
            'w': (0.60, 0.00, 0.00),
            'x': (1.00, 1.00, 0.50),
            'y': (1.00, 1.00, 0.00),
            'z': (1.00, 0.31, 0.02)
}


def color_distance(color1, color2):
    return sum([(x-y)**2 for (x,y) in zip(color1, color2)])

def find_highlight_type_with_color(color, color_map):

    min_dist = color_distance(color, color_map['a'])
    min_type = 'a'

    for highlight_type, type_color in color_map.items():
        dist = color_distance(color, type_color)
        if dist < min_dist:
            min_dist = dist
            min_type = highlight_type

    return min_type

def clean_path(path):
    if len(path) > 0:
        if path[0] == "'" or path[0] == '"':
            path = path[1:]
        if path[-1] == "'" or path[-1] == '"':
            path = path[:-1]
        return path
    else:
        return ""

def get_pdf_highlight_text(pdf_highlight, page):
    return page.get_text_selection(pdf_highlight.rect.tl, pdf_highlight.rect.br)

def are_highlights_same(pdf_highlight, sioyek_highlight, pdf_highlight_text):
    sioyek_highlight_document_pos = sioyek_highlight.get_begin_document_pos()
    return abs(sioyek_highlight_document_pos.offset_y - pdf_highlight.rect[1]) < 50 and is_text_close_fuzzy(pdf_highlight_text, sioyek_highlight.text)

def are_bookmarks_same(pdf_bookmark, sioyek_bookmark):
    pdf_bookmark_text = pdf_bookmark.info['content']
    pdf_bookmark_location_y = pdf_bookmark.rect.top_left.y
    docpos = sioyek_bookmark.get_document_position()
    return ((docpos[1] - pdf_bookmark_location_y) < 50) and is_text_close_fuzzy(pdf_bookmark_text, sioyek_bookmark.description)


def is_text_close_fuzzy(str1, str2):
    len1 = len(str1)
    len2 = len(str2)
    if max(len1, len2) < 10:
        l = min(len(str1), len(str2))
        num_errors = int(l * 0.2)
        #todo: this is *extremely* slow, do something better, e.g. levenshtein distance
        match1 = regex.search('(' + regex.escape(str1) + '){e<=' + str(num_errors) +'}', str2)
        match2 = regex.search('(' + regex.escape(str1) + '){e<=' + str(num_errors) +'}', str1)
        if match1 and match2:
            return True
        else:
            return False
    else:
        # return True
        ratio = min(len1 / len2, len2/ len1)
        return ratio > 0.8


def merge_rects(rects):
    '''
    Merge close rectangles in a line (e.g. rectangles corresponding to a single character or word)
    '''
    if len(rects) == 0:
        return []

    resulting_rects = [rects[0]]
    y_threshold = abs(rects[0].y1 - rects[0].y0) * 0.3

    def extend_last_rect(new_rect):
        resulting_rects[-1].x1 = max(resulting_rects[-1].x1, new_rect.x1)
        resulting_rects[-1].y0 = min(resulting_rects[-1].y0, new_rect.y0)
        resulting_rects[-1].y1 = min(resulting_rects[-1].y1, new_rect.y1)

    for rect in rects[1:]:
        if abs(rect.y0 - resulting_rects[-1].y0) < y_threshold:
            extend_last_rect(rect)
        else:
            resulting_rects.append(rect)
    return resulting_rects

def point_distance(p1, p2):
    return math.sqrt((p1[0] - p2[0]) ** 2 + (p1[1] - p2[1]) ** 2)

def rect_distance(rect, point):
    if rect.contains(point):
        return 0
    else:
        center = rect.x0 + rect.width / 2, rect.y0 + rect.height / 2
        return point_distance(center, point)

def get_closest_rect_to_point(rects, point):
    closest_rect = None
    closest_distance = None
    for rect in rects:
        distance = rect_distance(rect, point)
        if closest_distance == None or distance < closest_distance:
            closest_distance = distance
            closest_rect = rect
    return closest_rect

def get_bounding_box(rects):
    if len(rects) == 0:
        return fitz.Rect(0, 0, 0, 0)

    ll_x, ll_y, ur_x, ur_y = rects[0]

    for rect in rects[1:]:
        ll_x = min(ll_x, rect[0])
        ur_x = max(ur_x, rect[2])

        ll_y = min(ll_y, rect[1])
        ur_y = max(ur_y, rect[3])

    return fitz.Rect(ll_x, ll_y, ur_x, ur_y)
class Sioyek:

    def __init__(self, sioyek_path, local_database_path=None, shared_database_path=None):
        self.path = sioyek_path
        self.is_dummy_mode = False

        self.local_database = None
        self.shared_database = None
        self.cached_path_hash_map = None
        self.highlight_embed_method = 'fitz'

        if local_database_path != None:
            self.local_database_path = local_database_path
            self.local_database = sqlite3.connect(self.local_database_path)

        if shared_database_path != None:
            self.shared_database_path = shared_database_path
            self.shared_database = sqlite3.connect(self.shared_database_path)
    
    def set_highlight_embed_method(self, method):
        self.highlight_embed_method = method

    def get_local_database(self):
        return self.local_database

    def get_shared_database(self):
        return self.shared_database

    def set_dummy_mode(self, mode):
        '''
        dummy mode prints commands instead of executing them on sioyek
        '''
        self.is_dummy_mode = mode
    
    def get_path_hash_map(self):

        if self.cached_path_hash_map == None:
            query = 'SELECT * from document_hash'
            cursor = self.get_local_database().execute(query)
            results = cursor.fetchall()
            res = dict()
            for _, path, hash_ in results:
                res[path] = hash_
            self.cached_path_hash_map = res

        return self.cached_path_hash_map

    def run_command(self, command_name, text=None, focus=False):
        if text == None:
            params = [self.path, '--execute-command', command_name]
        else:
            params = [self.path, '--execute-command', command_name, '--execute-command-data', str(text)]
        
        if focus == False:
            params.append('--nofocus')
        
        if self.is_dummy_mode:
            print('dummy mode, executing: ', params)
        else:
            subprocess.run(params)

    def goto_begining(self, focus=False):
        self.run_command("goto_begining", None, focus=focus)

    def goto_end(self, focus=False):
        self.run_command("goto_end", None, focus=focus)

    def goto_definition(self, focus=False):
        self.run_command("goto_definition", None, focus=focus)

    def overview_definition(self, focus=False):
        self.run_command("overview_definition", None, focus=focus)

    def portal_to_definition(self, focus=False):
        self.run_command("portal_to_definition", None, focus=focus)

    def next_item(self, focus=False):
        self.run_command("next_item", None, focus=focus)

    def previous_item(self, focus=False):
        self.run_command("previous_item", None, focus=focus)

    def set_mark(self, symbol, focus=False):
        self.run_command("set_mark", symbol, focus=focus)

    def goto_mark(self, symbol, focus=False):
        self.run_command("goto_mark", symbol, focus=focus)

    def goto_page_with_page_number(self, text, focus=False):
        self.run_command("goto_page_with_page_number", text, focus=focus)

    def search(self, text, focus=False):
        self.run_command("search", text, focus=focus)

    def ranged_search(self, text, focus=False):
        self.run_command("ranged_search", text, focus=focus)

    def chapter_search(self, text, focus=False):
        self.run_command("chapter_search", text, focus=focus)

    def move_down(self, focus=False):
        self.run_command("move_down", None, focus=focus)

    def move_up(self, focus=False):
        self.run_command("move_up", None, focus=focus)

    def move_left(self, focus=False):
        self.run_command("move_left", None, focus=focus)

    def move_right(self, focus=False):
        self.run_command("move_right", None, focus=focus)

    def zoom_in(self, focus=False):
        self.run_command("zoom_in", None, focus=focus)

    def zoom_out(self, focus=False):
        self.run_command("zoom_out", None, focus=focus)

    def fit_to_page_width(self, focus=False):
        self.run_command("fit_to_page_width", None, focus=focus)

    def fit_to_page_height(self, focus=False):
        self.run_command("fit_to_page_height", None, focus=focus)

    def fit_to_page_height_smart(self, focus=False):
        self.run_command("fit_to_page_height_smart", None, focus=focus)

    def fit_to_page_width_smart(self, focus=False):
        self.run_command("fit_to_page_width_smart", None, focus=focus)

    def next_page(self, focus=False):
        self.run_command("next_page", None, focus=focus)

    def previous_page(self, focus=False):
        self.run_command("previous_page", None, focus=focus)

    def open_document(self, filename, focus=False):
        self.run_command("open_document", filename, focus=focus)

    def debug(self, focus=False):
        self.run_command("debug", None, focus=focus)

    def add_bookmark(self, text, focus=False):
        self.run_command("add_bookmark", text, focus=focus)

    def add_highlight(self, symbol, focus=False):
        self.run_command("add_highlight", symbol, focus=focus)

    def goto_toc(self, focus=False):
        self.run_command("goto_toc", None, focus=focus)

    def goto_highlight(self, focus=False):
        self.run_command("goto_highlight", None, focus=focus)

    def goto_bookmark(self, focus=False):
        self.run_command("goto_bookmark", None, focus=focus)

    def goto_bookmark_g(self, focus=False):
        self.run_command("goto_bookmark_g", None, focus=focus)

    def goto_highlight_g(self, focus=False):
        self.run_command("goto_highlight_g", None, focus=focus)

    def goto_highlight_ranged(self, focus=False):
        self.run_command("goto_highlight_ranged", None, focus=focus)

    def link(self, focus=False):
        self.run_command("link", None, focus=focus)

    def portal(self, focus=False):
        self.run_command("portal", None, focus=focus)

    def next_state(self, focus=False):
        self.run_command("next_state", None, focus=focus)

    def prev_state(self, focus=False):
        self.run_command("prev_state", None, focus=focus)

    def pop_state(self, focus=False):
        self.run_command("pop_state", None, focus=focus)

    def test_command(self, focus=False):
        self.run_command("test_command", None, focus=focus)

    def delete_link(self, focus=False):
        self.run_command("delete_link", None, focus=focus)

    def delete_portal(self, focus=False):
        self.run_command("delete_portal", None, focus=focus)

    def delete_bookmark(self, focus=False):
        self.run_command("delete_bookmark", None, focus=focus)

    def delete_highlight(self, focus=False):
        self.run_command("delete_highlight", None, focus=focus)

    def goto_link(self, focus=False):
        self.run_command("goto_link", None, focus=focus)

    def goto_portal(self, focus=False):
        self.run_command("goto_portal", None, focus=focus)

    def edit_link(self, focus=False):
        self.run_command("edit_link", None, focus=focus)

    def edit_portal(self, focus=False):
        self.run_command("edit_portal", None, focus=focus)

    def open_prev_doc(self, focus=False):
        self.run_command("open_prev_doc", None, focus=focus)

    def open_document_embedded(self, focus=False):
        self.run_command("open_document_embedded", None, focus=focus)

    def open_document_embedded_from_current_path(self, focus=False):
        self.run_command("open_document_embedded_from_current_path", None, focus=focus)

    def copy(self, focus=False):
        self.run_command("copy", None, focus=focus)

    def toggle_fullscreen(self, focus=False):
        self.run_command("toggle_fullscreen", None, focus=focus)

    def toggle_one_window(self, focus=False):
        self.run_command("toggle_one_window", None, focus=focus)

    def toggle_highlight(self, focus=False):
        self.run_command("toggle_highlight", None, focus=focus)

    def toggle_synctex(self, focus=False):
        self.run_command("toggle_synctex", None, focus=focus)

    def command(self, focus=False):
        self.run_command("command", None, focus=focus)

    def external_search(self, symbol, focus=False):
        self.run_command("external_search", symbol, focus=focus)

    def open_selected_url(self, focus=False):
        self.run_command("open_selected_url", None, focus=focus)

    def screen_down(self, focus=False):
        self.run_command("screen_down", None, focus=focus)

    def screen_up(self, focus=False):
        self.run_command("screen_up", None, focus=focus)

    def next_chapter(self, focus=False):
        self.run_command("next_chapter", None, focus=focus)

    def prev_chapter(self, focus=False):
        self.run_command("prev_chapter", None, focus=focus)

    def toggle_dark_mode(self, focus=False):
        self.run_command("toggle_dark_mode", None, focus=focus)

    def toggle_presentation_mode(self, focus=False):
        self.run_command("toggle_presentation_mode", None, focus=focus)

    def toggle_mouse_drag_mode(self, focus=False):
        self.run_command("toggle_mouse_drag_mode", None, focus=focus)

    def close_window(self, focus=False):
        self.run_command("close_window", None, focus=focus)

    def quit(self, focus=False):
        self.run_command("quit", None, focus=focus)

    def open_link(self, text, focus=False):
        self.run_command("open_link", text, focus=focus)

    def keyboard_select(self, text, focus=False):
        self.run_command("keyboard_select", text, focus=focus)

    def keyboard_smart_jump(self, text, focus=False):
        self.run_command("keyboard_smart_jump", text, focus=focus)

    def keyboard_overview(self, text, focus=False):
        self.run_command("keyboard_overview", text, focus=focus)

    def keys(self, focus=False):
        self.run_command("keys", None, focus=focus)

    def keys_user(self, focus=False):
        self.run_command("keys_user", None, focus=focus)

    def prefs(self, focus=False):
        self.run_command("prefs", None, focus=focus)

    def prefs_user(self, focus=False):
        self.run_command("prefs_user", None, focus=focus)

    def import_(self, focus=False):
        self.run_command("import", None, focus=focus)

    def export(self, focus=False):
        self.run_command("export", None, focus=focus)

    def enter_visual_mark_mode(self, focus=False):
        self.run_command("enter_visual_mark_mode", None, focus=focus)

    def move_visual_mark_down(self, focus=False):
        self.run_command("move_visual_mark_down", None, focus=focus)

    def move_visual_mark_up(self, focus=False):
        self.run_command("move_visual_mark_up", None, focus=focus)

    def set_page_offset(self, text, focus=False):
        self.run_command("set_page_offset", text, focus=focus)

    def toggle_visual_scroll(self, focus=False):
        self.run_command("toggle_visual_scroll", None, focus=focus)

    def toggle_horizontal_scroll_lock(self, focus=False):
        self.run_command("toggle_horizontal_scroll_lock", None, focus=focus)

    def toggle_custom_color(self, focus=False):
        self.run_command("toggle_custom_color", None, focus=focus)

    def execute(self, text, focus=False):
        self.run_command("execute", text, focus=focus)

    def execute_predefined_command(self, symbol, focus=False):
        self.run_command("execute_predefined_command", symbol, focus=focus)

    def embed_annotations(self, focus=False):
        self.run_command("embed_annotations", None, focus=focus)

    def copy_window_size_config(self, focus=False):
        self.run_command("copy_window_size_config", None, focus=focus)

    def toggle_select_highlight(self, focus=False):
        self.run_command("toggle_select_highlight", None, focus=focus)

    def set_select_highlight_type(self, symbol, focus=False):
        self.run_command("set_select_highlight_type", symbol, focus=focus)

    def open_last_document(self, focus=False):
        self.run_command("open_last_document", None, focus=focus)

    def toggle_window_configuration(self, focus=False):
        self.run_command("toggle_window_configuration", None, focus=focus)

    def prefs_user_all(self, focus=False):
        self.run_command("prefs_user_all", None, focus=focus)

    def keys_user_all(self, focus=False):
        self.run_command("keys_user_all", None, focus=focus)

    def fit_to_page_width_ratio(self, focus=False):
        self.run_command("fit_to_page_width_ratio", None, focus=focus)

    def smart_jump_under_cursor(self, focus=False):
        self.run_command("smart_jump_under_cursor", None, focus=focus)

    def overview_under_cursor(self, focus=False):
        self.run_command("overview_under_cursor", None, focus=focus)

    def close_overview(self, focus=False):
        self.run_command("close_overview", None, focus=focus)

    def visual_mark_under_cursor(self, focus=False):
        self.run_command("visual_mark_under_cursor", None, focus=focus)

    def close_visual_mark(self, focus=False):
        self.run_command("close_visual_mark", None, focus=focus)

    def zoom_in_cursor(self, focus=False):
        self.run_command("zoom_in_cursor", None, focus=focus)

    def zoom_out_cursor(self, focus=False):
        self.run_command("zoom_out_cursor", None, focus=focus)

    def goto_left(self, focus=False):
        self.run_command("goto_left", None, focus=focus)

    def goto_left_smart(self, focus=False):
        self.run_command("goto_left_smart", None, focus=focus)

    def goto_right(self, focus=False):
        self.run_command("goto_right", None, focus=focus)

    def goto_right_smart(self, focus=False):
        self.run_command("goto_right_smart", None, focus=focus)

    def rotate_clockwise(self, focus=False):
        self.run_command("rotate_clockwise", None, focus=focus)

    def rotate_counterclockwise(self, focus=False):
        self.run_command("rotate_counterclockwise", None, focus=focus)

    def goto_next_highlight(self, focus=False):
        self.run_command("goto_next_highlight", None, focus=focus)

    def goto_prev_highlight(self, focus=False):
        self.run_command("goto_prev_highlight", None, focus=focus)

    def goto_next_highlight_of_type(self, focus=False):
        self.run_command("goto_next_highlight_of_type", None, focus=focus)

    def goto_prev_highlight_of_type(self, focus=False):
        self.run_command("goto_prev_highlight_of_type", None, focus=focus)

    def add_highlight_with_current_type(self, focus=False):
        self.run_command("add_highlight_with_current_type", None, focus=focus)

    def enter_password(self, text, focus=False):
        self.run_command("enter_password", text, focus=focus)

    def toggle_fastread(self, focus=False):
        self.run_command("toggle_fastread", None, focus=focus)

    def goto_top_of_page(self, focus=False):
        self.run_command("goto_top_of_page", None, focus=focus)

    def goto_bottom_of_page(self, focus=False):
        self.run_command("goto_bottom_of_page", None, focus=focus)

    def new_window(self, focus=False):
        self.run_command("new_window", None, focus=focus)

    def toggle_statusbar(self, focus=False):
        self.run_command("toggle_statusbar", None, focus=focus)

    def reload(self, focus=False):
        self.run_command("reload", None, focus=focus)

    def synctex_under_cursor(self, focus=False):
        self.run_command("synctex_under_cursor", None, focus=focus)

    def set_status_string(self, text, focus=False):
        self.run_command("set_status_string", text, focus=focus)

    def focus_text(self, text, focus=False):
        self.run_command("focus_text", text, focus=focus)

    def clear_status_string(self, focus=False):
        self.run_command("clear_status_string", None, focus=focus)

    def toggle_titlebar(self, focus=False):
        self.run_command("toggle_titlebar", None, focus=focus)

    def next_preview(self, focus=False):
        self.run_command("next_preview", None, focus=focus)

    def previous_preview(self, focus=False):
        self.run_command("previous_preview", None, focus=focus)

    def goto_overview(self, focus=False):
        self.run_command("goto_overview", None, focus=focus)

    def portal_to_overview(self, focus=False):
        self.run_command("portal_to_overview", None, focus=focus)

    def goto_selected_text(self, focus=False):
        self.run_command("goto_selected_text", None, focus=focus)
    
    def get_document(self, path):
        return Document(path, self)
    
    def close(self):
        self.local_database.close()
        self.shared_database.close()


    def statusbar_output(self):

        class StatusBarOutput(object):
            def __init__(self, sioyek):
                self.old_stdout = sys.stdout
                self.sioyek = sioyek
            
            def write(self, text):
                if text.strip() != '':
                    self.sioyek.set_status_string(text)
        return redirect_stdout(StatusBarOutput(self))

@dataclass
class DocumentPos:
    page: int
    offset_x: float
    offset_y: float

@dataclass
class AbsoluteDocumentPos:
    offset_x: float
    offset_y: float


class Highlight:

    def __init__(self, document, text, highlight_type, begin, end):
        self.doc = document
        self.text = text
        self.highlight_type = highlight_type
        self.selection_begin = begin
        self.selection_end = end

    def insert(self, document):
        INSERT_QUERY = "INSERT INTO highlights (document_path, desc, type, begin_x, begin_y, end_x, end_y) VALUES (?, ?, ?, ?, ?, ?, ?)"
        path_hash_map = document.sioyek.get_path_hash_map()
        document_hash = path_hash_map[document.path.replace('\\', '/')]

        begin_abs_pos = self.get_begin_abs_pos()
        end_abs_pos = self.get_end_abs_pos()

        cursor = self.doc.sioyek.shared_database.cursor()
        cursor.execute(INSERT_QUERY, (
            document_hash,
            self.text,
            self.highlight_type,
            begin_abs_pos.offset_x,
            begin_abs_pos.offset_y,
            end_abs_pos.offset_x,
            end_abs_pos.offset_y
        ))
        cursor.close()

    
    def get_begin_document_pos(self):
        begin_page, begin_offset_y = self.doc.absolute_to_document_y(self.selection_begin[1])
        return DocumentPos(begin_page, self.selection_begin[0], begin_offset_y)

    def get_end_document_pos(self):
        end_page, end_offset_y = self.doc.absolute_to_document_y(self.selection_end[1])
        return DocumentPos(end_page, self.selection_end[0], end_offset_y)
    
    def get_begin_abs_pos(self):
        return AbsoluteDocumentPos(self.selection_begin[0], self.selection_begin[1])

    def get_end_abs_pos(self):
        return AbsoluteDocumentPos(self.selection_end[0], self.selection_end[1])

    
    def __repr__(self):
        return f"Highlight of type {self.highlight_type}: {self.text}"

class Bookmark:

    def __init__(self, document, description, y_offset):
        self.doc = document
        self.description = description
        self.y_offset = y_offset

    def insert(self, document):
        INSERT_QUERY = "INSERT INTO bookmarks (document_path, desc, offset_y) VALUES (?, ?, ?)"
        path_hash_map = document.sioyek.get_path_hash_map()
        document_hash = path_hash_map[document.path.replace('\\', '/')]

        cursor = self.doc.sioyek.shared_database.cursor()
        cursor.execute(INSERT_QUERY, (document_hash, self.description, self.y_offset))
        cursor.close()
    
    @lru_cache(maxsize=None)
    def get_document_position(self):
        return self.doc.absolute_to_document_y(self.y_offset)
    

    def __repr__(self):
        return f"Bookmark at {self.y_offset}: {self.description}"

class Document:

    def __init__(self, path, sioyek):
        self.path = path
        self.doc = fitz.open(self.path)
        self.set_page_dimensions()
        self.sioyek = sioyek
        self.cached_hash = None

    def to_absolute(self, document_pos):
        offset_x = document_pos.offset_x
        offset_y = document_pos.offset_y + self.cum_page_heights[document_pos.page]
        return AbsoluteDocumentPos(offset_x, offset_y)
        

    def absolute_to_document_y(self, offset_y):
        page = 0
        while offset_y > self.page_heights[page]:
            offset_y -= self.page_heights[page]
            page += 1
        return (page, offset_y)

    def to_document(self, absolute_document_pos, pypdf=False):
        page, offset_y = self.absolute_to_document_y(absolute_document_pos.offset_y)
        if pypdf:
            return DocumentPos(page, absolute_document_pos.offset_x + self.page_widths[page] / 2, offset_y)
        else:
            return DocumentPos(page, absolute_document_pos.offset_x, offset_y)

    
    @lru_cache(maxsize=None)
    def get_page(self, page_number):
        return self.doc.load_page(page_number)
    
    @lru_cache(maxsize=None)
    def get_page_pdf_annotations(self, page_number):
        page = self.get_page(page_number)
        res = []
        annot = page.first_annot
        while annot != None:
            res.append(annot)
            annot = annot.next

        return res

    @lru_cache(maxsize=None)
    def get_page_pdf_bookmarks(self, page_number):
        def is_bookmark(annot):
            return annot.type[1] in ['Text', 'FreeText']
        return [annot for annot in self.get_page_pdf_annotations(page_number) if is_bookmark(annot)]

    @lru_cache(maxsize=None)
    def get_page_pdf_highlights(self, page_number):
        def is_highlight(annot):
            return annot.type[1] == 'Highlight'
        return [annot for annot in self.get_page_pdf_annotations(page_number) if is_highlight(annot)]

    def remove_annotations(self, page_number, rect):
        annots = self.get_page_pdf_annotations(page_number)
        page = self.get_page(page_number)

        rect = fitz.Rect(rect)

        annots_to_delete = []
        for annot in annots:
            if annot.rect.intersects(rect):
                annots_to_delete.append(annot)
        
        for annot in annots_to_delete:
            page.delete_annot(annot)
        self.save_changes()

    def embed_text_in_pdf(self, text, page_number, rect, params):
        pdf_page = self.get_page(page_number)
        annot = pdf_page.add_freetext_annot(rect, text, **params)
        annot.update()
        self.save_changes()

    def embed_highlight(self, highlight, colormap=None):
        """Embed sioyek highlights into the PDF document

        Parameters:
        highligtht: The highlight to embed
        colormap: A dictionary mapping highlight types to colors
        method: Can be 'fitz' or 'custom'. 'fitz' uses mupdf text search to embed the highlights (which might result in duplicate highlights).
        'custom' uses a custom algorithm based on highlight location to embed the highlights.
        """

        if colormap is None:
            colormap = COLOR_MAP

        method = self.sioyek.highlight_embed_method
        docpos = highlight.get_begin_document_pos()
        page = self.get_page(docpos.page)
        # quads = page.search_for(highlight.text, flags=fitz.TEXT_PRESERVE_WHITESPACE, hit_max=50)
        if method == 'fitz':
            quads = self.get_best_selection_rects(docpos.page, highlight.text, merge=True)
        else:
            selection_begin_abs = AbsoluteDocumentPos(highlight.selection_begin[0], highlight.selection_begin[1])
            selection_end_abs = AbsoluteDocumentPos(highlight.selection_end[0], highlight.selection_end[1])

            selected_words = self.get_selected_words(selection_begin_abs, selection_end_abs)
            selected_rects = [fitz.Rect(*word[:4]) for word in selected_words[0]]
            merged_rects = merge_rects(selected_rects)
            quads = [rect.quad for rect in merged_rects]

        annot = page.add_highlight_annot(quads)
        if colormap is not None:
            if highlight.highlight_type in colormap.keys():
                color = colormap[highlight.highlight_type]
                annot.set_colors(stroke=color, fill=color)
                annot.update()

    def embed_bookmark(self, bookmark):
        page_number, offset_y = bookmark.get_document_position()
        page = self.get_page(page_number)
        # print((0, offset_y), bookmark.description)
        page.add_text_annot((0, offset_y), bookmark.description)
    
    def embed_new_bookmarks(self):
        new_bookmarks = self.get_non_embedded_bookmarks()
        for bookmark in new_bookmarks:
            self.embed_bookmark(bookmark)
    
    def embed_new_highlights(self, colormap=None):
        new_highlights = self.get_non_embedded_highlights()
        for highlight in new_highlights:
            self.embed_highlight(highlight, colormap)
    
    def embed_new_annotations(self, save=False, colormap=None):
        self.embed_new_bookmarks()
        self.embed_new_highlights(colormap=colormap)

        if save:
            self.save_changes()

    
    def save_changes(self):
        self.doc.saveIncr()

    def add_imported_bookmark(self, page, bookmark):
        document_pos = DocumentPos(page, 0, bookmark.rect.top_left.y)
        absolute_pos = self.to_absolute(document_pos)
        # self.to_absolute(bookmark.)
        new_bookmark = Bookmark(self, bookmark.info['content'], absolute_pos.offset_y)
        new_bookmark.insert(self)

    def add_imported_highlight(self, page, highlight_rect, highlight_text, highlight_type):

        highlight_text = highlight_text.replace('\n', '')
        begin_document_pos = DocumentPos(page, highlight_rect.tl.x, highlight_rect.tl.y)
        end_document_pos = DocumentPos(page, highlight_rect.br.x, highlight_rect.br.y)

        begin_abs_pos = self.to_absolute(begin_document_pos)
        end_abs_pos = self.to_absolute(end_document_pos)

        page_width = self.page_widths[page]
        new_highlight = Highlight(
            self,
            highlight_text,
            highlight_type,
            (begin_abs_pos.offset_x - page_width/2, begin_abs_pos.offset_y),
            (end_abs_pos.offset_x - page_width/2, end_abs_pos.offset_y)
        )
        new_highlight.insert(self)

    def import_annotations(self, colormap=None):
        if colormap is None:
            colormap = COLOR_MAP

        new_highlights = self.get_non_sioyek_highlights()
        new_bookmarks = self.get_non_sioyek_bookmarks()

        for page, text, hl in new_highlights:
            color = hl.colors['stroke']
            if colormap:
                highlight_type = find_highlight_type_with_color(color, colormap)
            else:
                highlight_type = 'a'

            self.add_imported_highlight(page, hl.rect, text, highlight_type)

        for page, bm in new_bookmarks:
            self.add_imported_bookmark(page, bm)

        self.sioyek.shared_database.commit()
        self.sioyek.reload()
        # self.sioyek.shared_database.close()

    def get_non_sioyek_bookmarks(self):
        num_pages = len(self.page_heights)
        sioyek_bookmarks = self.get_bookmarks()
        page_sioyek_bookmarks = defaultdict(list)

        for sioyek_bookmark in sioyek_bookmarks:
            bookmark_page = sioyek_bookmark.get_document_position()[0]
            page_sioyek_bookmarks[bookmark_page].append(sioyek_bookmark)

        new_bookmarks = []

        for page_number in range(num_pages):
            page = self.get_page(page_number)
            pdf_bookmarks = self.get_page_pdf_bookmarks(page_number)
            sioyek_bookmarks = page_sioyek_bookmarks[page_number]
            for pdf_bm in pdf_bookmarks:
                found = False
                for sioyek_bm in sioyek_bookmarks:
                    if are_bookmarks_same(pdf_bm, sioyek_bm):
                        found = True
                        break
                if not found:
                    new_bookmarks.append((page_number, pdf_bm))
        return new_bookmarks

    def get_non_sioyek_highlights(self):
        num_pages = len(self.page_heights)
        sioyek_highlights = self.get_highlights()
        page_sioyek_highlights = defaultdict(list)

        for sioyek_highlight in sioyek_highlights:
            highlight_page = sioyek_highlight.get_begin_document_pos().page
            page_sioyek_highlights[highlight_page].append(sioyek_highlight)

        new_highlights = []

        for page_number in range(num_pages):
            page = self.get_page(page_number)
            pdf_highlights = self.get_page_pdf_highlights(page_number)
            sioyek_highlights = page_sioyek_highlights[page_number]
            for pdf_hl in pdf_highlights:
                pdf_highlight_text = get_pdf_highlight_text(pdf_hl, page)
                found = False
                for sioyek_hl in sioyek_highlights:
                    if are_highlights_same(pdf_hl, sioyek_hl, pdf_highlight_text):
                        found = True
                        break
                if not found:
                    new_highlights.append((page_number, pdf_highlight_text, pdf_hl))
        return new_highlights


    def get_non_embedded_highlights(self):

        candidate_highlights = self.get_highlights()
        new_highlights = []

        for highlight in candidate_highlights:
            highlight_document_pos = highlight.get_begin_document_pos()
            pdf_page_highlights = self.get_page_pdf_highlights(highlight_document_pos.page)
            document_page = self.get_page(highlight_document_pos.page)
            found = False
            for pdf_highlight in pdf_page_highlights:
                #todo: swap the order of for loops so we don't compute highlight_text every iteration
                highlight_text = get_pdf_highlight_text(pdf_highlight, document_page)
                if are_highlights_same(pdf_highlight, highlight, highlight_text):
                    found = True
                    break
            if not found:
                new_highlights.append(highlight)
        return new_highlights

    def get_non_embedded_bookmarks(self):

        candidate_bookmarks = self.get_bookmarks()
        new_bookmarks = []

        for bookmark in candidate_bookmarks:
            pdf_page_bookmarks = self.get_page_pdf_bookmarks(bookmark.get_document_position()[0])
            found = False
            for pdf_bookmark in pdf_page_bookmarks:
                if bookmark.description == pdf_bookmark.info['content']:
                    found = True
                    break
            if not found:
                new_bookmarks.append(bookmark)
        return new_bookmarks
            
    def get_page_text_and_rects(self, page_number):
        page = self.get_page(page_number)
        word_data = page.get_text('words')

        word_texts = []
        word_rects = []
        resulting_string = ""
        string_rects = []

        for i in range(len(word_data)):
            word_text = word_data[i][4]
            block_no = word_data[i][5]
            line_no = word_data[i][6]
            if i > 0:
                if block_no != word_data[i-1][5]:
                    word_text = word_text + '\n'
            word_texts.append(word_text)
            word_rects.append(fitz.Rect(word_data[i][0:4]))

            additional_string = word_text

            if word_text[-1] != '\n':
                additional_string += ' '
            
            resulting_string += additional_string
            string_rects.extend([fitz.Rect(word_data[i][0:4])] * len(additional_string))
        
        return resulting_string, string_rects, word_texts, word_rects

    def set_page_dimensions(self):
        self.page_heights = []
        self.page_widths = []
        self.cum_page_heights = []

        cum_height = 0
        for i in range(self.doc.page_count):
            page = self.doc.load_page(i)
            width, height = page.mediabox_size
            self.page_heights.append(height)
            self.page_widths.append(width)
            self.cum_page_heights.append(cum_height)
            cum_height += height
    
    def get_best_selection_rects(self, page_number, text, merge=False):
        for i in range(10):
            rects = self.get_text_selection_rects(page_number, text, num_errors=i)
            if len(rects) > 0:
                if i > 0 and merge == True:
                    rects = merge_rects(rects)
                return rects
        return None

    def get_best_selection(self, page_number, text):
        for i in range(10):
            res = self.get_text_selection_begin_and_end(page_number, text, num_errors=i)
            if res[0][0] != None:
                return res
        return None

    def get_text_selection_rects(self, page_number, text, num_errors=0):
        if num_errors == 0:
            page = self.get_page(page_number)
            rects = page.search_for(text)
            return rects
        else:
            page_text, page_rects, _, _ = self.get_page_text_and_rects(page_number)
            match = regex.search('(' + regex.escape(text) + '){e<=' + str(num_errors) +'}', page_text)
            if match:
                match_begin, match_end = match.span()
                # print('match: ')
                # print(page_text[match_begin + 1: match_end+1])
                rects = page_rects[match_begin + 1: match_end+1]
                return list(dict.fromkeys(rects))
            else:
                return []

    def get_text_selection_begin_and_end(self, page_number, text, num_errors=0):
        rects = self.get_text_selection_rects(page_number, text, num_errors)
        if len(rects) > 0:
            begin_x, begin_y = rects[0].top_left
            end_x, end_y = rects[-1].bottom_right
            return (begin_x, begin_y), (end_x, end_y)
        else:
            return (None, None), (None, None)

    def highlight_selection(self, page_number, selection_begin, selection_end, focus=False):
        highlight_string = '{},{},{} {},{},{}'.format(
            page_number,
            selection_begin[0], selection_begin[1],
            page_number,
            selection_end[0], selection_end[1])

        self.sioyek.keyboard_select(highlight_string, focus=focus)

    def highlight_page_text(self, page_number, text, focus=False):
        (begin_x, begin_y), (end_x, end_y) = self.get_text_selection_begin_and_end(page_number, text)
        if begin_x:
            self.highlight_selection(page_number, (begin_x, begin_y), (end_x, end_y), focus=focus)

    def highlight_page_text_fault_tolerant(self, page_number, text, focus=False):
        best_selection = self.get_best_selection(page_number, text)
        if best_selection:
            self.highlight_selection(page_number, best_selection[0], best_selection[1], focus=focus)
    
    def get_sentences(self):
        res = []
        for i in range(self.doc.page_count):
            page = self.doc.load_page(i)
            sentences = page.get_text().replace('\n', '').split('.')
            res.extend([(s, i) for s in sentences])
        return res
    
    def get_hash(self):
        path_hash_map = self.sioyek.get_path_hash_map()

        for path, hash_ in path_hash_map.items():
            if os.path.normpath(self.path) == os.path.normpath(path):
                self.cached_hash = hash_
        return self.cached_hash
    
    def get_bookmarks(self):
        doc_hash = self.get_hash()
        BOOKMARK_SELECT_QUERY = "select * from bookmarks where document_path='{}'".format(doc_hash)
        shared_database = self.sioyek.get_shared_database()
        cursor = shared_database.execute(BOOKMARK_SELECT_QUERY)
        bookmarks = [Bookmark(self, desc, y_offset) for _, _, desc, y_offset in cursor.fetchall()]
        return bookmarks

    def get_highlights(self):
        doc_hash = self.get_hash()
        HIGHLIGHT_SELECT_QUERY = "select * from highlights where document_path='{}'".format(doc_hash)

        shared_database = self.sioyek.get_shared_database()
        cursor = shared_database.execute(HIGHLIGHT_SELECT_QUERY)
        highlights = [Highlight(self, text, highlight_type, (begin_x, begin_y), (end_x, end_y)) for _, _, text, highlight_type, begin_x, begin_y, end_x, end_y in cursor.fetchall()]
        return highlights
    
    def get_page_selection(self, page_number, selection_begin_x, selection_begin_y, selection_end_x, selection_end_y):
        in_range = False
        page = self.get_page(page_number)
        words = page.get_text_words()

        selected_words = []
        word_rects = [fitz.Rect(*word[:4]) for word in words]
        start_closest_rect = get_closest_rect_to_point(word_rects, (selection_begin_x, selection_begin_y))
        end_closest_rect = get_closest_rect_to_point(word_rects, (selection_end_x, selection_end_y))

        for word_item, word_rect in zip(words, word_rects):
            if start_closest_rect == word_rect:
                in_range = True
            if in_range:
                selected_words.append(word_item)
            if end_closest_rect == word_rect:
                in_range = False

        return selected_words, page_number

    def get_selected_words(self, selection_begin, selection_end):

        selection_begin_doc = self.to_document(selection_begin, pypdf=True)
        selection_end_doc = self.to_document(selection_end, pypdf=True)

        if selection_begin_doc.page == selection_end_doc.page:
            return self.get_page_selection(selection_begin_doc.page,
                                           selection_begin_doc.offset_x,
                                           selection_begin_doc.offset_y,
                                           selection_end_doc.offset_x,
                                           selection_end_doc.offset_y)
        return [], -1

    def get_highlight_bounding_box(self, selection_begin, selection_end):

        words, page_number = self.get_selected_words(selection_begin, selection_end)
        word_bounding_boxes = [fitz.Rect(*x[:4]) for x in words]
        highlight_bounding_box = get_bounding_box(word_bounding_boxes)
        return highlight_bounding_box, page_number
    def close(self):
        self.doc.close()
