#!/usr/bin/env python3
"""Build the Joomla extension from source; never include environment secrets."""
from pathlib import Path
import zipfile
import xml.etree.ElementTree as ET
base=Path(__file__).resolve().parent
version=ET.parse(base/'plugin/gordalenlive.xml').getroot().findtext('version')
output=base/f'plg_system_gordalenlive-{version}.zip'
with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as archive:
    for path in sorted((base/'plugin').rglob('*')):
        if path.is_file(): archive.write(path,path.relative_to(base/'plugin'))
print(output)
