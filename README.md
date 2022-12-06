Python wrapper and simple addons for the sioyek PDF viewer. Install using:
```
python -m pip install sioyek
```
Note that python executable name might be different in your system, for example it might be `python3` instead of `python`.
Also note that in some AppImage builds of sioyek, `"%{sioyek_path}"` doesn't expand to correct AppImage, you just have to replace `"%{sioyek_path}"` with the exact path of sioyek AppImage on your filesystem.

Addons:

### -`paper_downloader`
Download the paper name under cursor from google scholar or scihub and open the document. To enable add this to your `prefs_user.config`:
```
new_command _download_paper python -m sioyek.paper_downloader download "%{sioyek_path}" "%{paper_name}"
control_click_command _download_paper
```
Now you can download papers by control-clicking on their names like this:


https://user-images.githubusercontent.com/6392321/185757545-117b00d5-23bf-433f-8d50-6e193ef3deee.mp4


### -`dual_panelify`
Create a dual panel version of the current PDF file.


https://user-images.githubusercontent.com/6392321/185757596-681c6bde-7297-4a9d-a5bc-02819208b3de.mp4

Config:
```
new_command _dual_panelify python -m sioyek.dual_panelify "%{sioyek_path}" "%{file_path}" "%{command_text}"
```

### -`embed_annotations`
Embed the sioyek bookmarks and highlights into the current file.


https://user-images.githubusercontent.com/6392321/185757605-dc277f2e-5b73-49e1-98f1-57c83417f07b.mp4

Config:
```
new_command _embed_annotations python -m sioyek.embed_annotations "%{sioyek_path}" "%{local_database}" "%{shared_database}" "%{file_path}"
```

### -`extract_highlights`
Create a new document with the highlights of the current document with pre-inserted portal into the corresponding location in the original document.


https://user-images.githubusercontent.com/6392321/185757614-c8ff1c83-fe80-4ee8-8b39-477b67fd8ffa.mp4

Config:
```
new_command _extract_highlights python -m sioyek.extract_highlights "%{sioyek_path}" "%{local_database}" "%{shared_database}" "%1" %{zoom_level}
```


### -`translate`
Translate the text and display it in sioyek statusbar.


https://user-images.githubusercontent.com/6392321/185757622-98b9b4e2-e421-451a-8cd3-fa2af43c4986.mp4

Config:
```
new_command _translate_selected_text python -m sioyek.translate "%{sioyek_path}" "%{selected_text}"
new_command _translate_current_line_text python -m sioyek.translate "%{sioyek_path}" "%{line_text}"
```

### -`import_annotations`
Import PDF bookmarks and highlights into sioyek so that they are searchable.

https://user-images.githubusercontent.com/6392321/205930859-79b5efb9-d159-4d92-9382-1641ae3cf01d.mp4

Config:
```
new_command _import_annotations python -m sioyek.import_annotations "%{sioyek_path}" "%{local_database}" "%{shared_database}" "%{file_path}"
```

### -`remove_annotation`
Remove PDF annotations.

https://user-images.githubusercontent.com/6392321/205931274-ef2b20e5-0aec-478c-9dd8-ff83a5ba498b.mp4

Config:
```
new_command _remove_annotations python -m sioyek.remove_annotation "%{sioyek_path}" "%{local_database}" "%{shared_database}" "%{file_path}" "%{selected_rect}"
```

### -`add_text`
Add text annotation to the PDF.



https://user-images.githubusercontent.com/6392321/205931938-938da231-8f2c-4f85-92a3-d7adf320f5f2.mp4


Config:
```
new_command _add_text python -m sioyek.add_text "%{sioyek_path}" "%{local_database}" "%{shared_database}" "%{file_path}" "%{selected_rect}" "%{command_text}"
new_command _add_red_text python -m sioyek.add_text "%{sioyek_path}" "%{local_database}" "%{shared_database}" "%{file_path}" "%{selected_rect}" "%{command_text}" fontsize=5 text_color=255,0,0
```


## User Scripts
Here is a list of scripts created by sioyek users:
* A script to import annotations for koreader: https://github.com/blob42/koreader-sioyek-import

## Donation
If you enjoy sioyek, please consider donating to support its development.

<a href="https://www.buymeacoffee.com/ahrm" target="_blank"><img src="https://cdn.buymeacoffee.com/buttons/default-orange.png" alt="Buy Me A Coffee" height="41" width="174"></a>
