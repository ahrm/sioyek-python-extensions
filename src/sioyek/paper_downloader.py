'''
Allows sioyek to automatically download papers from scihub by clicking on their names.

Here is an example `prefs_user.config` file which uses this script:

    new_command _download_paper_under_cursor python -m sioyek.paper_downloader download "%{sioyek_path}" "%{selected_text}" "%{paper_name}" "[YOUR_EMAIL]"
    control_click_command _download_paper_under_cursor

Now, you can control+click on paper names to download them and open them in sioyek.

This script can also be used to copy the bibtex of paper under cursor:
    new_command _copy_bibtex python -m sioyek.paper_downloader copy download "%{sioyek_path}" "%{paper_name}"

'''

# where to put downloaded papers, if it is None, we use a default data path
PAPERS_FOLDER_PATH = None
SIOYEK_PATH = None
PYTHON_EXECUTABLE = 'python'
USER_EMAIL = ''

sioyek = None

import os
import pathlib
import subprocess
import sys
import json
import time
import regex
import urllib.request
import fitz
import requests
from difflib import SequenceMatcher
import shutil

import pyperclip
from appdirs import user_data_dir
from habanero import Crossref
from PyPaperBot.__main__ import start as start_paper_download
from libgen_api import LibgenSearch
from slugify import slugify

from .sioyek import Sioyek, clean_path


def clean_paper_name(paper_name):
    first_quote_index = -1
    last_quote_index = -1

    try:
        first_quote_index = paper_name.index('"')
        last_quote_index = paper_name.rindex('"')
    except ValueError as e:
        pass

    if first_quote_index != -1 and last_quote_index != -1 and (last_quote_index - first_quote_index) > 10:
        return paper_name[first_quote_index + 1:last_quote_index]

    paper_name = paper_name.strip()
    if paper_name.endswith('.'):
        paper_name = paper_name[:-1]

    return paper_name

def is_file_a_paper_with_name(file_name, paper_name):
    # check if the downloaded file's title matches with the query
    doc = fitz.open(file_name)
    page_text = doc.get_page_text(0)
    doc.close()
    if regex.search('(' + regex.escape(paper_name) + '){e<=6}', page_text, flags=regex.IGNORECASE):
        return True
    return False


class ListingDiff():
    def __init__(self, path):
        self.path = path

    def get_listing(self):
        return set(os.listdir(self.path))

    def __enter__(self):
        self.listing = self.get_listing()
        return self
    
    def new_files(self):
        return list(self.get_listing().difference(self.listing))
    
    def new_pdf_files(self):
        return [f for f in self.new_files() if f.endswith('.pdf')]
    
    def reset(self):
        self.listing = self.get_listing()

    def __exit__(self, exc_type, exc_value, exc_traceback):
        pass

def get_cached_doi_map():
    json_path = get_papers_folder_path() / 'doi_map.json'
    if os.path.exists(json_path):
        with open(json_path, 'r') as infile:
            return json.load(infile)
    else:
        return dict()

def write_cache_doi_map(doi_map):
    json_path = get_papers_folder_path() / 'doi_map.json'
    with open(json_path, 'w') as outfile:
        json.dump(doi_map, outfile)


def get_papers_folder_path_():
    if PAPERS_FOLDER_PATH != None:
        return pathlib.Path(PAPERS_FOLDER_PATH)
    APPNAME = 'sioyek_papers'
    return pathlib.Path(user_data_dir(APPNAME, False))

def get_papers_folder_path():
    path = get_papers_folder_path_()
    path.mkdir(parents=True, exist_ok=True)
    return path

def get_doi_with_name(paper_name):
    crossref = Crossref()
    response = crossref.works(query=paper_name)
    if len(response['message']['items']) == 0:
        return None
    
    closest_match = None
    closest_match_ratio = 0

    for item in response['message']['items']:
        title = item['title'][0]
        ratio = SequenceMatcher(None, title, paper_name).ratio()
        if ratio > closest_match_ratio:
            closest_match_ratio = ratio
            closest_match = item
        if closest_match_ratio == 1:
            break
    return closest_match['DOI']

def get_pdf_via_unpaywall(doi, paper_name):
    print(f"Getting DOI {doi} from Unpaywall")
    set_sioyek_status_if_exists(f"Getting DOI {doi} from Unpaywall")

    unpaywall_url = f"https://api.unpaywall.org/v2/{doi}?email={USER_EMAIL}"
    unpaywall_resp = requests.get(unpaywall_url)
    if unpaywall_resp.status_code == 404:
        print(f"DOI {doi} not found in Unpaywall")
        raise Exception(f"DOI {doi} not found in Unpaywall")

    print(f"Got DOI {doi} from Unpaywall")
    unpaywall_resp_json = unpaywall_resp.json()

    if(
        'best_oa_location' not in unpaywall_resp_json or
        unpaywall_resp_json['best_oa_location'] is None or
        'url_for_pdf' not in unpaywall_resp_json['best_oa_location']
    ):
        print(f"No Link for DOI {doi} in Unpaywall")
        raise Exception(f"No Link for DOI {doi} in Unpaywall")

    print(f"Got PDF URL for DOI {doi} from Unpaywall")
    pdf_url = unpaywall_resp_json['best_oa_location']['url_for_pdf']

    if pdf_url is None:
        print(f"No PDF URL for DOI {doi} in Unpaywall")
        raise Exception(f"No PDF URL for DOI {doi} in Unpaywall")

    print(f"Downloading {pdf_url} from Unpaywall")

    set_sioyek_status_if_exists(f"Downloading {pdf_url} from Unpaywall")

    valid_filename = slugify(unpaywall_resp_json['title'])
    pdf_path = get_papers_folder_path() / (valid_filename + '-Unpaywall.pdf')

    print(f"Saving {pdf_url} to {pdf_path}")
    with open(pdf_path, 'wb+') as outfile:
        outfile.write(requests.get(pdf_url).content)

    return pdf_path

def get_book_via_libgen(book_name):
    s = LibgenSearch()

    print(f"Getting book {book_name} from Libgen")

    set_sioyek_status_if_exists(f"Getting book {book_name} from Libgen")

    results = s.search_title_filtered(book_name, {"Extension": "pdf"})

    if len(results) == 0:
        print(f"Book {book_name} not found in Libgen")
        raise Exception(f"Book {book_name} not found in Libgen")

    print(f"Got book {book_name} from Libgen")

    pdf_url = s.resolve_download_links(results[0])['Cloudflare']
    print(f"Downloading {pdf_url} from Libgen")

    set_sioyek_status_if_exists(f"Downloading {pdf_url} from Libgen")

    valid_filename = slugify(results[0]["Title"])
    pdf_path = get_papers_folder_path() / (valid_filename + '-Libgen.pdf')

    print(f"Saving {pdf_url} to {pdf_path}")

    with open(pdf_path, 'wb+') as outfile:
        outfile.write(requests.get(pdf_url).content)

    return pdf_path

def get_pdf_via_crossref(doi_string, paper_name):
    crossref_url = f"https://api.crossref.org/works/{doi_string}"

    print(f"Getting DOI {doi_string} from Crossref")

    set_sioyek_status_if_exists(f"Getting DOI {doi_string} from Crossref")

    crossref_resp = requests.get(crossref_url)
    if crossref_resp.status_code == 404:
        print(f"DOI {doi_string} not found in Crossref")
        raise Exception(f"DOI {doi_string} not found in Crossref")

    print(f"Got DOI {doi_string} from Crossref")

    crossref_resp_json = crossref_resp.json()

    if 'message' not in crossref_resp_json:
        print(f"DOI {doi_string} not found in Crossref")
        raise Exception(f"DOI {doi_string} not found in Crossref")

    if 'link' not in crossref_resp_json['message'] and 'ISBN' in crossref_resp_json['message']:
        return get_book_via_libgen(paper_name)

    if 'link' not in crossref_resp_json['message']:
        print(f"No link for {doi_string} in Crossref")
        raise Exception(f"No link for {doi_string} in Crossref")

    pdf_url = None
    for link in crossref_resp_json['message']['link']:
        possible_url = link['URL']
        if possible_url.endswith('.pdf'):
            pdf_url = possible_url
            break
        
        if(
            link['content-type'] == 'application/pdf' or
            link['intended-application'] == 'similarity-checking'
        ):
            pdf_url = possible_url
            break
            
    if pdf_url is None:
        print(f"No PDF URL for {doi_string} in Crossref")
        raise Exception(f"DOI {doi_string} not found in Crossref")

    print(f"Downloading {pdf_url} from Crossref")

    set_sioyek_status_if_exists(f"Downloading {pdf_url} from Crossref")

    valid_filename = slugify(crossref_resp_json['message']['title'][0])
    pdf_path = get_papers_folder_path() / (valid_filename + '-Crossref.pdf')

    print(f"Saving {pdf_url} to {pdf_path}")

    with open(pdf_path, 'wb+') as outfile:
        outfile.write(requests.get(pdf_url).content)


    return pdf_path

def download_paper_with_doi(doi_string, paper_name, doi_map):
    download_dir = get_papers_folder_path()
    method_args_and_kwargs = [
        ("unpaywall", get_pdf_via_unpaywall, (doi_string, paper_name), {}),
        ("crossref", get_pdf_via_crossref, (doi_string, paper_name), {}),
        ("scihub", start_paper_download, ("", None, None, download_dir, None), {'DOIs': [doi_string]}),
    ]

    with ListingDiff(download_dir) as listing_diff:

        ignored_files = []

        for method_name, callback, method_args, method_kwargs in method_args_and_kwargs:
            set_sioyek_status_if_exists('trying to download "{}" from {}'.format(paper_name, method_name))
            try:
                callback(*method_args, **method_kwargs)
            except Exception as e:
                set_sioyek_status_if_exists('error in download from {}'.format(method_name))
            pdf_files = listing_diff.new_pdf_files()
            if len(pdf_files) > 0:
                returned_file = download_dir / pdf_files[0]
                if is_file_a_paper_with_name(str(returned_file), paper_name):
                    doi_map[doi_string] = str(returned_file)
                    write_cache_doi_map(doi_map)
                    return returned_file
                else:
                    ignored_files.append(returned_file)
                    listing_diff.reset()

        if len(ignored_files) > 0:
            set_sioyek_status_if_exists('could not find a suitable paper, this is a throw in the dark')
            return ignored_files[0]

    return None

def get_paper_file_name_with_doi_and_name(doi, paper_name):

    doi_map = get_cached_doi_map()
    if doi in doi_map.keys():
        if os.path.exists(doi_map[doi]):
            return doi_map[doi]
    return download_paper_with_doi(doi, paper_name, doi_map)


def get_bibtex(doi):
    BASE_URL = 'http://dx.doi.org/'
    url = BASE_URL + doi
    req = urllib.request.Request(url)
    req.add_header('Accept', 'application/x-bibtex')
    with urllib.request.urlopen(req) as f:
        bibtex = f.read().decode()
        return bibtex

def set_sioyek_status_if_exists(status):
    if sioyek:
        sioyek.set_status_string(status)

def clear_sioyek_status_path_if_exists():
    if sioyek:
        sioyek.clear_status_string()
    
if __name__ == '__main__':
    mode = sys.argv[1]
    SIOYEK_PATH = clean_path(sys.argv[2])
    sioyek = Sioyek(SIOYEK_PATH)
    selected = sys.argv[3]
    parsed = sys.argv[4]

    paper_name = ""
    chose_paper = False
    if len(selected) != 2:
        paper_name = selected
    elif len(parsed) != 2:
        paper_name = parsed
        chose_paper = True

    if chose_paper:
        paper_name = clean_paper_name(paper_name)

    if len(sys.argv) > 5:
        USER_EMAIL = sys.argv[5]

    set_sioyek_status_if_exists('finding doi ...')
    try:

        doi = get_doi_with_name(sys.argv[3])
        if doi:
            if mode == 'download':
                # show_status('downloading doi: {}'.format(doi))
                file_name = get_paper_file_name_with_doi_and_name(doi, paper_name)
                directory, file_name = os.path.split(file_name)

                valid_file_name = slugify(file_name)
                valid_file_path = os.path.join(directory, valid_file_name)
                old_file_path = os.path.join(directory, file_name)

                shutil.move(old_file_path, valid_file_path)
                clear_sioyek_status_path_if_exists()
                if file_name:
                    subprocess.run([SIOYEK_PATH, str(valid_file_path), '--new-window'])
            else:
                bibtex = get_bibtex(doi)
                pyperclip.copy(bibtex)
                clear_sioyek_status_path_if_exists()

        else:
            set_sioyek_status_if_exists('doi not found')
            time.sleep(5)
            clear_sioyek_status_path_if_exists()
    except Exception as e:
        set_sioyek_status_if_exists('error: {}'.format(str(e)))
        time.sleep(5)
        clear_sioyek_status_path_if_exists()
