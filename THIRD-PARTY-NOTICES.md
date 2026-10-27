# Third-party components

The application source is MIT licensed. Third-party components retain their original terms; the application's license does not replace them.

| Component | Included | License and provenance |
|---|---|---|
| CPython 3.14.10 Windows x64 embeddable distribution | Yes, unchanged official files under runtime/ | PSF-2.0 and incorporated component licenses in runtime/LICENSE.txt, licenses/Python-LICENSE.txt and licenses/Python-history-and-licenses.html. Official component inventory: licenses/CPython-SBOM.spdx.json. |
| pypdf 6.21.2 | Yes, unchanged pure-Python wheel contents under third_party/ | BSD-3-Clause, full license in its `.dist-info/licenses` directory. Download URL and SHA-256 in licenses/pypdf-provenance.json. |
| Windows/Edge/default browser | No | Supplied by the user's operating system/vendor, separate terms. |
| Ollama and model weights | No | User installs separately. Ollama source is MIT licensed; model licenses vary and must be reviewed separately. |

Python binaries are redistributed without modification. The application adds its own source directory to its process import path; it does not patch Python. The Windows runtime includes Microsoft redistributable DLLs subject to the restrictions reproduced in its LICENSE.txt; retain those notices and use them only as permitted for Microsoft platforms. Python and Microsoft do not endorse this application. Preserve all dependency notices when redistributing this ZIP.

Runtime archive source: https://www.python.org/ftp/python/3.14.10/python-3.14.10-embed-amd64.zip

Runtime archive SHA-256: `90905e64a840557d8c1bc4f5b74db3d7ee85e3ffb217611cac1c7813acea4159`

Release source: https://www.python.org/downloads/release/python-31410/

App provenance: selected pure finance-validation and revision-control patterns were adapted into the new standalone engine. No previous application directory, private record, user configuration, session token or historical output is bundled.
