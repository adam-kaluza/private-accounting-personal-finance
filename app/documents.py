"""Bounded, local-only document previews and inert snapshot exports.

No parser extracts files, evaluates spreadsheet formulas, follows relationships to
external resources, or changes source bytes. A preview never approves an import.
"""
from __future__ import annotations

import csv
from decimal import Decimal, InvalidOperation
import html
import importlib
import importlib.util
import io
import json
from pathlib import Path
import posixpath
import re
import stat
import sys
import threading
import zipfile
import xml.etree.ElementTree as ET

MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_EXPANDED_BYTES = 32 * 1024 * 1024
MAX_ROWS = 5000
MAX_COLUMNS = 100
MAX_ARCHIVE_MEMBERS = 128
MAX_WORKBOOK_MEMBERS = 1024
MAX_SHEETS = 16
MAX_PATH_DEPTH = 8
MAX_COMPRESSION_RATIO = 200
MAX_TEXT_CHARS = 200_000
MAX_CELL_CHARS = 32_767
MAX_XML_ELEMENTS = 250_000
MAX_XML_DEPTH = 64
MAX_PDF_PAGES = 100
MAX_PDF_PREVIEW_PAGES = 30
MAX_PDF_TEXT_CHARS = 24_000
MAX_PDF_STREAM_BYTES = 2 * 1024 * 1024
MAX_PDF_RESOURCE_OBJECTS = 1000
_PDF_IMPORT_LOCK = threading.Lock()
HEADERS = ("date", "description", "amount", "account", "classification", "category")
NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
DOC_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
CELL_RE = re.compile(r"^([A-Z]{1,3})([1-9][0-9]{0,6})$")
LIMITS = {
    "file_bytes": MAX_FILE_BYTES, "expanded_bytes": MAX_EXPANDED_BYTES,
    "data_rows": MAX_ROWS, "columns": MAX_COLUMNS,
    "archive_members": MAX_ARCHIVE_MEMBERS, "workbook_members": MAX_WORKBOOK_MEMBERS,
    "sheets": MAX_SHEETS, "archive_path_depth": MAX_PATH_DEPTH,
    "compression_ratio": MAX_COMPRESSION_RATIO, "text_preview_characters": MAX_TEXT_CHARS,
    "cell_characters": MAX_CELL_CHARS,
    "xml_elements": MAX_XML_ELEMENTS, "xml_depth": MAX_XML_DEPTH,
    "pdf_pages": MAX_PDF_PAGES, "pdf_preview_pages": MAX_PDF_PREVIEW_PAGES,
    "pdf_text_preview_characters": MAX_PDF_TEXT_CHARS, "pdf_content_stream_bytes": MAX_PDF_STREAM_BYTES,
    "pdf_resource_objects": MAX_PDF_RESOURCE_OBJECTS,
}


class PreviewError(ValueError):
    """A malformed or unsafe document that must not be partially imported."""


class _Budget:
    def __init__(self):
        self.expanded = 0
        self.rows = 0
        self.xml_elements = 0

    def add_rows(self, count=1):
        self.rows += count
        if self.rows > MAX_ROWS:
            raise PreviewError(f"Row limit exceeded: at most {MAX_ROWS} data rows per upload.")


def _result(name, status="preview_only", **extra):
    return {"name": name, "status": status, "text": "", "rows": [],
            "warnings": [], "limits": dict(LIMITS), **extra}


def _text(value):
    if value is None:
        return ""
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def _clip_text(value, warnings):
    if len(value) > MAX_TEXT_CHARS:
        warnings.append(f"Text preview truncated at {MAX_TEXT_CHARS} characters; source bytes are unchanged.")
        return value[:MAX_TEXT_CHARS]
    return value


def _decode(content):
    try:
        decoded = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise PreviewError("Only UTF-8 text is supported. Save a separate UTF-8 copy to review it.") from exc
    if "\x00" in decoded:
        raise PreviewError("Text contains NUL bytes; binary or UTF-16 content is not accepted as UTF-8.")
    return decoded


def _safe_member_name(name):
    if not name or "\\" in name or ":" in name or "\x00" in name or name.startswith("/"):
        raise PreviewError("Archive contains an unsafe absolute, backslash, or special member path.")
    parts = name.rstrip("/").split("/")
    if any(part in ("", ".", "..") for part in parts) or len(parts) > MAX_PATH_DEPTH:
        raise PreviewError("Archive contains traversal, empty path components, or excessive path nesting.")
    if any(any(ord(c) < 32 for c in part) for part in parts):
        raise PreviewError("Archive member names contain control characters.")


def _archive(content, budget, workbook=False):
    try:
        archive = zipfile.ZipFile(io.BytesIO(content))
    except (zipfile.BadZipFile, OSError) as exc:
        raise PreviewError("Malformed ZIP container.") from exc
    try:
        members = archive.infolist()
        cap = MAX_WORKBOOK_MEMBERS if workbook else MAX_ARCHIVE_MEMBERS
        if len(members) > cap:
            raise PreviewError(f"Archive member limit exceeded ({cap}).")
        seen = set()
        total = 0
        for info in members:
            # ZipInfo normalizes backslashes on Windows and truncates NULs.
            # Validate the original central-directory spelling as well.
            _safe_member_name(info.orig_filename)
            _safe_member_name(info.filename)
            key = info.filename.casefold().rstrip("/")
            if key in seen:
                raise PreviewError("Archive contains duplicate or case-colliding member names.")
            seen.add(key)
            mode = (info.external_attr >> 16) & 0xFFFF
            kind = stat.S_IFMT(mode)
            if kind not in (0, stat.S_IFREG, stat.S_IFDIR):
                raise PreviewError("Archive links and special files are not accepted.")
            if info.flag_bits & 1:
                raise PreviewError("Encrypted archive members are not accepted.")
            if info.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
                raise PreviewError("Only stored and deflate ZIP compression are supported.")
            if info.file_size and info.file_size / max(1, info.compress_size) > MAX_COMPRESSION_RATIO:
                raise PreviewError(f"Archive compression ratio exceeds {MAX_COMPRESSION_RATIO}:1.")
            if not workbook and not info.is_dir() and info.file_size > MAX_FILE_BYTES:
                raise PreviewError("An archive member exceeds the 10 MiB file limit.")
            total += info.file_size
        if total + budget.expanded > MAX_EXPANDED_BYTES:
            raise PreviewError("Archive expansion exceeds the shared 32 MiB limit.")
        return archive
    except Exception:
        archive.close()
        raise


def _read_member(archive, name, budget):
    info = archive.getinfo(name)
    remaining = MAX_EXPANDED_BYTES - budget.expanded
    if info.file_size > remaining:
        raise PreviewError("Archive expansion exceeds the shared 32 MiB limit.")
    with archive.open(info) as stream:
        data = stream.read(remaining + 1)
    budget.expanded += len(data)
    if budget.expanded > MAX_EXPANDED_BYTES or len(data) != info.file_size:
        raise PreviewError("Archive expansion limit or member size validation failed.")
    return data


def _xml(data, budget):
    decoded = _decode(data)
    if re.search(r"<!\s*(DOCTYPE|ENTITY)\b", decoded, re.I):
        raise PreviewError("XML DTDs and entity declarations are not accepted.")
    try:
        # Incremental feeding bounds the number of nodes allocated before a
        # maliciously dense or deeply nested XML document is refused.
        parser = ET.XMLPullParser(events=("start", "end"))
        root, depth = None, 0
        for offset in range(0, len(decoded), 16_384):
            parser.feed(decoded[offset:offset + 16_384])
            for event, element in parser.read_events():
                if event == "start":
                    depth += 1
                    budget.xml_elements += 1
                    if depth > MAX_XML_DEPTH or budget.xml_elements > MAX_XML_ELEMENTS:
                        raise PreviewError("Workbook XML exceeds the shared element or nesting limit.")
                    if root is None:
                        root = element
                else:
                    depth -= 1
        parser.close()
        if root is None:
            raise PreviewError("Malformed workbook XML.")
        return root
    except ET.ParseError as exc:
        raise PreviewError("Malformed workbook XML.") from exc


def _formula_warning(values):
    return any(isinstance(v, str) and v.lstrip().startswith(("=", "+", "@")) for v in values)


def _rows_from_table(name, table, locations, budget, warnings):
    if not table:
        return []
    # Noncanonical tables still consume the upload's shared row budget; a ZIP
    # must not bypass it merely by giving every table unrecognized headers.
    budget.add_rows(sum(bool(any(values)) for values in table[1:]))
    headers = [cell.strip().lower() for cell in table[0]]
    if len(set(headers)) != len(headers):
        raise PreviewError("Duplicate table headers prevent an unambiguous import.")
    missing = [key for key in HEADERS if key not in headers]
    if missing:
        warnings.append("No transaction rows prepared. Required headers: " + ", ".join(HEADERS)
                        + ". Missing: " + ", ".join(missing) + ". Map columns in a separate copy or enter rows manually.")
        return []
    rows = []
    for index, values in enumerate(table[1:], 1):
        if not any(values):
            continue
        if len(values) > len(headers):
            raise PreviewError("A table row has more fields than its header. Correct a separate copy before import.")
        padded = values + [""] * (len(headers) - len(values))
        raw = dict(zip(headers, padded))
        source = locations[index]
        row = {key: raw[key] for key in HEADERS}
        row["source"] = source["row"]
        row["_source_refs"] = {key: source["cells"].get(headers.index(key), source["row"]) for key in HEADERS}
        row["_raw"] = raw
        row["warnings"] = []
        if _formula_warning(padded):
            row["warnings"].append("Formula-like source text is preserved literally and has not been evaluated.")
        if row["date"].strip().isdigit():
            row["warnings"].append("Numeric date preserved without guessing its format or Excel date system.")
        rows.append(row)
    return rows


def _delimited(name, content, delimiter, budget):
    decoded = _decode(content)
    result = _result(name)
    result["warnings"].append("Preview only until you explicitly approve selected rows. Dates and classifications are never inferred.")
    table, locations = [], []
    try:
        reader = csv.reader(io.StringIO(decoded, newline=""), delimiter=delimiter, strict=True)
        previous_line = 0
        for fields in reader:
            if len(fields) > MAX_COLUMNS:
                raise PreviewError(f"Column limit exceeded ({MAX_COLUMNS}).")
            if any(len(field) > MAX_CELL_CHARS for field in fields):
                raise PreviewError(f"A field exceeds {MAX_CELL_CHARS} characters.")
            if len(table) > MAX_ROWS:
                raise PreviewError(f"Row limit exceeded ({MAX_ROWS} data rows).")
            table.append(fields)
            first_line = previous_line + 1
            previous_line = reader.line_num
            ref = (f"{name}:line {first_line}" if first_line == reader.line_num
                   else f"{name}:lines {first_line}-{reader.line_num}")
            locations.append({"row": ref, "cells": {i: f"{ref}, column {i + 1}" for i in range(len(fields))}})
    except csv.Error as exc:
        raise PreviewError("Malformed delimited text or a field exceeds the CSV parser limit.") from exc
    result["rows"] = _rows_from_table(name, table, locations, budget, result["warnings"])
    result["status"] = "ready" if result["rows"] else "preview_only"
    result["text"] = _clip_text(decoded, result["warnings"])
    result["headers"] = table[0] if table else []
    return result


def _column_index(letters):
    number = 0
    for letter in letters:
        number = number * 26 + ord(letter) - 64
    return number - 1


def _rich_text(element):
    if element is None:
        return ""
    # Phonetic guides (rPh) annotate displayed text; concatenating every nested
    # <t> would silently alter descriptions, categories, and other source values.
    return "".join(child.text or "" if child.tag == f"{{{NS}}}t" else
                   "".join(node.text or "" for node in child.findall(f"{{{NS}}}t"))
                   for child in element if child.tag in (f"{{{NS}}}t", f"{{{NS}}}r"))


def _cell_value(cell, shared):
    formula = cell.find(f"{{{NS}}}f")
    if formula is not None:
        return "=" + (formula.text or ""), True
    kind = cell.attrib.get("t", "n")
    value = cell.findtext(f"{{{NS}}}v", "")
    if kind == "s":
        try:
            index = int(value)
            if index < 0:
                raise ValueError
            return shared[index], False
        except (ValueError, IndexError) as exc:
            raise PreviewError("Invalid workbook shared-string reference.") from exc
    if kind == "inlineStr":
        return _rich_text(cell.find(f"{{{NS}}}is")), False
    return value, False


def _xlsx(name, content, budget):
    result = _result(name, sheets=[])
    result["warnings"].append("Read-only values preview. Formulas are literal source text; cached formula results are ignored. Numeric dates are not converted.")
    lines = []
    with _archive(content, budget, workbook=True) as archive:
        names = set(archive.namelist())
        required = {"[Content_Types].xml", "xl/workbook.xml", "xl/_rels/workbook.xml.rels"}
        if not required.issubset(names):
            raise PreviewError("Not a supported XLSX workbook: required package parts are missing.")
        for part in required:
            if part == "[Content_Types].xml":
                _xml(_read_member(archive, part, budget), budget)
        workbook = _xml(_read_member(archive, "xl/workbook.xml", budget), budget)
        relationships = _xml(_read_member(archive, "xl/_rels/workbook.xml.rels", budget), budget)
        if workbook.tag != f"{{{NS}}}workbook" or relationships.tag != f"{{{REL_NS}}}Relationships":
            raise PreviewError("Workbook package XML has an unsupported root or namespace.")
        targets = {}
        relationship_ids = set()
        for relationship in relationships:
            relation_id = relationship.attrib.get("Id", "")
            if relationship.tag != f"{{{REL_NS}}}Relationship" or not relation_id or relation_id in relationship_ids:
                raise PreviewError("Workbook relationships have missing or duplicate identifiers.")
            relationship_ids.add(relation_id)
            if relationship.attrib.get("TargetMode", "").lower() == "external":
                result["warnings"].append("External workbook relationship ignored.")
                continue
            target = relationship.attrib.get("Target", "")
            relation_type = relationship.attrib.get("Type", "")
            if relation_type.endswith("/worksheet"):
                if not target or "\\" in target or ":" in target or ".." in target.split("/"):
                    raise PreviewError("Unsafe worksheet relationship target.")
                target = target.lstrip("/") if target.startswith("/xl/") else posixpath.join("xl", target)
                _safe_member_name(target)
                if not target.startswith("xl/worksheets/") or target not in names:
                    raise PreviewError("Worksheet relationship points outside supported workbook parts.")
                targets[relation_id] = target
        excluded = [n for n in names if any(s in n.lower() for s in ("vbaproject", "externallinks/", "embeddings/", "activex/"))]
        if excluded:
            result["warnings"].append(f"Ignored {len(excluded)} VBA, external-link, embedded-object, or ActiveX package parts.")
        shared = []
        if "xl/sharedStrings.xml" in names:
            root = _xml(_read_member(archive, "xl/sharedStrings.xml", budget), budget)
            if root.tag != f"{{{NS}}}sst":
                raise PreviewError("Workbook shared strings have an unsupported root or namespace.")
            for item in root.findall(f"{{{NS}}}si"):
                value = _rich_text(item)
                if len(value) > MAX_CELL_CHARS:
                    raise PreviewError("A workbook shared string exceeds the cell character limit.")
                shared.append(value)
        sheets = workbook.findall(f"{{{NS}}}sheets/{{{NS}}}sheet")
        if len(sheets) > MAX_SHEETS:
            raise PreviewError(f"Workbook sheet limit exceeded ({MAX_SHEETS}).")
        physical_rows = 0
        sheet_names, sheet_ids, sheet_targets = set(), set(), set()
        for sheet in sheets:
            sheet_name = sheet.attrib.get("name", "")
            sheet_id = sheet.attrib.get("sheetId", "")
            relation_id = sheet.attrib.get(f"{{{DOC_REL_NS}}}id")
            if relation_id not in targets:
                raise PreviewError("Workbook sheet has no supported local worksheet relationship.")
            if (not sheet_name or len(sheet_name) > 31 or sheet_name.casefold() in sheet_names
                    or not re.fullmatch(r"[1-9][0-9]{0,9}", sheet_id) or sheet_id in sheet_ids
                    or targets[relation_id] in sheet_targets):
                raise PreviewError("Workbook has invalid or duplicate sheet names, identifiers, or targets.")
            sheet_names.add(sheet_name.casefold())
            sheet_ids.add(sheet_id)
            sheet_targets.add(targets[relation_id])
            if sheet.attrib.get("state", "visible") != "visible":
                result["warnings"].append(f"{sheet_name}: hidden worksheet included in this preview; review before approval.")
            root = _xml(_read_member(archive, targets[relation_id], budget), budget)
            if root.tag != f"{{{NS}}}worksheet":
                raise PreviewError("Worksheet XML has an unsupported root or namespace.")
            table, locations, sheet_warnings = [], [], []
            formula_count = 0
            previous_row = 0
            for row_node in root.findall(f"{{{NS}}}sheetData/{{{NS}}}row"):
                physical_rows += 1
                if physical_rows > MAX_ROWS + len(sheets):
                    raise PreviewError(f"Workbook row limit exceeded ({MAX_ROWS} data rows plus headers).")
                row_number = row_node.attrib.get("r", "")
                if (not re.fullmatch(r"[1-9][0-9]{0,6}", row_number)
                        or not previous_row < int(row_number) <= 1_048_576):
                    raise PreviewError("Workbook row references are missing, repeated, or out of order.")
                previous_row = int(row_number)
                cells, refs = {}, {}
                for cell in row_node.findall(f"{{{NS}}}c"):
                    reference = cell.attrib.get("r", "")
                    match = CELL_RE.fullmatch(reference)
                    if not match or match.group(2) != row_number:
                        raise PreviewError("Worksheet cell reference is missing, invalid, or contradicts its row.")
                    column = _column_index(match.group(1))
                    if column >= MAX_COLUMNS or column in cells:
                        raise PreviewError("Workbook has duplicate cells or exceeds the column limit.")
                    value, formula = _cell_value(cell, shared)
                    if len(value) > MAX_CELL_CHARS:
                        raise PreviewError("A workbook cell exceeds the cell character limit.")
                    cells[column] = value
                    refs[column] = f"{name}:{sheet_name}!{reference}"
                    formula_count += int(formula)
                    if value:
                        lines.append(f"{refs[column]}: {value}")
                if not cells or not any(cells.values()):
                    continue
                table.append([cells.get(i, "") for i in range(max(cells) + 1)])
                locations.append({"row": f"{name}:{sheet_name}!row {row_number}", "cells": refs})
            if table:
                width = max(len(row) for row in table)
                table = [row + [""] * (width - len(row)) for row in table]
                # Trailing blank headers do not obscure a canonical six-column table.
                while table[0] and table[0][-1] == "" and all(row[-1] == "" for row in table):
                    for row in table:
                        row.pop()
            if formula_count:
                sheet_warnings.append(f"{formula_count} formula cells preserved literally without evaluation or cached values.")
            rows = _rows_from_table(name, table, locations, budget, sheet_warnings)
            result["rows"].extend(rows)
            result["sheets"].append({"name": sheet_name, "rows": len(table), "transaction_rows": len(rows),
                                     "formulas": formula_count, "warnings": sheet_warnings})
            result["warnings"].extend(f"{sheet_name}: {warning}" for warning in sheet_warnings)
    result["status"] = "ready" if result["rows"] else "preview_only"
    result["text"] = _clip_text("\n".join(lines), result["warnings"])
    return result


def _zip_preview(name, content, budget):
    result = _result(name, "archive", members=[])
    result["warnings"].append("Archive preview only. Select and approve each supported member separately; no files have been extracted or imported.")
    with _archive(content, budget) as archive:
        for info in archive.infolist():
            if info.is_dir():
                result["members"].append({"name": info.filename, "size": 0, "status": "directory", "preview": None})
                continue
            content = _read_member(archive, info.filename, budget)
            if info.filename.lower().endswith(".zip") or (zipfile.is_zipfile(io.BytesIO(content)) and not info.filename.lower().endswith(".xlsx")):
                raise PreviewError("Nested archives are not accepted. Upload a selected source file separately.")
            preview = _preview(info.filename, content, budget, nested=True)
            result["members"].append({"name": info.filename, "size": info.file_size,
                                      "status": preview["status"], "preview": preview})
    return result


def _load_pypdf():
    """Only load this release's optional vendored parser, never a global install."""
    vendor = Path(__file__).resolve().parent.parent / "third_party"
    package = vendor / "pypdf"
    entry = package / "__init__.py"
    if not entry.is_file() or not entry.resolve().is_relative_to(vendor.resolve()):
        return None
    with _PDF_IMPORT_LOCK:
        existing = sys.modules.get("pypdf")
        if existing is not None:
            origin = getattr(existing, "__file__", "")
            return existing if origin and Path(origin).resolve().is_relative_to(package.resolve()) else None
        vendor_path = str(vendor)
        if vendor_path not in sys.path:
            sys.path.insert(0, vendor_path)
        spec = importlib.util.spec_from_file_location("pypdf", entry, submodule_search_locations=[str(package)])
        if spec is None or spec.loader is None:
            return None
        module = importlib.util.module_from_spec(spec)
        sys.modules["pypdf"] = module
        try:
            spec.loader.exec_module(module)
        except ImportError:
            sys.modules.pop("pypdf", None)
            return None
        origin = getattr(module, "__file__", "")
        if not origin or not Path(origin).resolve().is_relative_to(package.resolve()):
            return None
        if not hasattr(module, "apply_configuration"):
            return None
        return module


def _pdf(name, content, budget):
    parser = _load_pypdf()
    if parser is None:
        return _result(name, "unsupported", warnings=["The bundled PDF text parser is unavailable. Enter values manually, or use a trusted local OCR tool and review a UTF-8 text/CSV copy."])
    result = _result(name, pages=[], truncated=False, page_count=0, previewed_pages=0)
    result["warnings"].append("PDF text only: layout, tables, handwriting, and OCR accuracy are not verified. Check values against the original; no transaction rows were inferred.")
    sections, blank_pages = [], []
    remaining = MAX_PDF_TEXT_CHARS - 2000
    # Retain decoded stream objects so transient ContentStream identities cannot
    # be recycled and accidentally bypass the shared expansion counter.
    checked_streams, checked_resources, checked_objects = {}, set(), set()

    def resolve(value):
        return value.get_object() if hasattr(value, "get_object") else value

    def count_stream(value):
        stream = resolve(value)
        if stream is None or not hasattr(stream, "get_data") or id(stream) in checked_streams:
            return
        checked_streams[id(stream)] = stream
        size = len(stream.get_data())
        if size > MAX_PDF_STREAM_BYTES:
            raise PreviewError("PDF text content exceeds the 2 MiB decoded stream limit.")
        budget.expanded += size
        if budget.expanded > MAX_EXPANDED_BYTES:
            raise PreviewError("PDF text-content expansion exceeds the shared 32 MiB limit.")

    def count_resources(value, depth=0):
        resources = resolve(value)
        if resources is None or id(resources) in checked_resources:
            return
        if depth > 20 or not hasattr(resources, "get"):
            raise PreviewError("PDF text resources exceed the supported nesting limit or are malformed.")
        checked_resources.add(id(resources))
        for group in ("/XObject", "/Font"):
            entries = resolve(resources.get(group))
            if entries is None:
                continue
            if not hasattr(entries, "values"):
                raise PreviewError("PDF text resources are malformed.")
            for reference in entries.values():
                item = resolve(reference)
                if item is None or not hasattr(item, "get"):
                    raise PreviewError("PDF text resources are malformed.")
                if id(item) in checked_objects:
                    continue
                checked_objects.add(id(item))
                if len(checked_objects) > MAX_PDF_RESOURCE_OBJECTS:
                    raise PreviewError("PDF text resources exceed the shared object limit.")
                if group == "/XObject" and item.get("/Subtype") == "/Form":
                    count_stream(item)
                    count_resources(item.get("/Resources"), depth + 1)
                elif group == "/Font":
                    count_stream(item.get("/ToUnicode"))
                    count_stream(item.get("/Encoding"))
        # Images, embedded files and executable actions are not decoded.

    try:
        # These context-local limits apply to decompression and content parsing.
        # No render, image extraction, external program, URI action, attachment,
        # form action, or JavaScript execution is requested.
        with parser.apply_configuration(
            maximum_declared_stream_length=MAX_PDF_STREAM_BYTES,
            array_based_stream_maximum_output_length=MAX_PDF_STREAM_BYTES,
            zlib_maximum_output_length=MAX_PDF_STREAM_BYTES,
            lzw_maximum_output_length=MAX_PDF_STREAM_BYTES,
            run_length_maximum_output_length=MAX_PDF_STREAM_BYTES,
            brotli_maximum_output_length=MAX_PDF_STREAM_BYTES,
            jbig2_maximum_output_length=MAX_PDF_STREAM_BYTES,
            image_maximum_buffer_size=MAX_PDF_STREAM_BYTES,
            stream_decoding_work_maximum_length=MAX_PDF_STREAM_BYTES * 2,
            stream_parsing_work_maximum_count=50_000,
            array_maximum_element_count=10_000, dictionary_maximum_element_count=10_000,
            page_tree_maximum_entries=256, page_tree_maximum_depth=20,
            xform_maximum_invocations_per_extraction=100, jbig2dec_binary=None,
        ):
            reader = parser.PdfReader(io.BytesIO(content), strict=True)
            if reader.is_encrypted:
                return _result(name, "unsupported", warnings=["Encrypted PDFs are not read. Use an authorized unencrypted local copy or enter values manually."])
            count = len(reader.pages)
            result["page_count"] = count
            if count > MAX_PDF_PAGES:
                raise PreviewError(f"PDF has {count} pages; the limit is {MAX_PDF_PAGES}. Select a smaller local copy.")
            for index in range(min(count, MAX_PDF_PREVIEW_PAGES)):
                page = reader.pages[index]
                count_stream(page.get_contents())
                count_resources(page.get("/Resources"))
                text = page.extract_text() or ""
                source = f"{name}:page {index + 1}"
                if not text.strip():
                    blank_pages.append(index + 1)
                if len(text) > remaining:
                    text = text[:remaining]
                    result["truncated"] = True
                result["pages"].append({"page": index + 1, "source": source, "text": text})
                result["previewed_pages"] = index + 1
                sections.append(f"{source}\n{text}")
                remaining -= len(text) + len(source) + 2
                if remaining <= 0 or result["truncated"]:
                    result["truncated"] = True
                    break
            if result["previewed_pages"] < count:
                result["truncated"] = True
            if result["truncated"]:
                result["warnings"].append(f"PARTIAL PREVIEW: included {result['previewed_pages']} of {count} pages, capped at {MAX_PDF_PREVIEW_PAGES} pages and {MAX_PDF_TEXT_CHARS} characters. This is not a complete document review.")
            if blank_pages:
                result["warnings"].append("No extractable text on pages " + ", ".join(map(str, blank_pages)) + ". These may be scanned, image-only, or blank. Use trusted local OCR or manual input for missing text.")
            if not any(page["text"].strip() for page in result["pages"]):
                result["status"] = "unsupported"
                result["warnings"].append("No readable text layer was found in the previewed pages; no OCR was performed.")
            else:
                # Include scope warnings in text passed to the local model too.
                result["text"] = ("\n".join(result["warnings"]) + "\n\n" + "\n\n".join(sections))[:MAX_PDF_TEXT_CHARS]
            return result
    except PreviewError:
        raise
    except Exception:
        # Parser error messages can contain source snippets. Keep them private.
        raise PreviewError("PDF text could not be read safely: malformed, unsupported, or parser resource limit reached. Use a smaller local copy, local OCR, or manual input.") from None


def _preview(name, content, budget, nested=False):
    suffix = posixpath.splitext(name)[1].lower()
    if suffix in (".csv", ".tsv"):
        return _delimited(name, content, "\t" if suffix == ".tsv" else ",", budget)
    if suffix == ".txt":
        result = _result(name)
        result["text"] = _clip_text(_decode(content), result["warnings"])
        result["warnings"].append("Text is reference material only; no transaction rows were inferred.")
        return result
    if suffix == ".xlsx":
        return _xlsx(name, content, budget)
    if suffix == ".pdf":
        return _pdf(name, content, budget)
    if suffix == ".zip" and not nested:
        return _zip_preview(name, content, budget)
    message = "Unsupported file type. Supported previews: UTF-8 TXT, CSV, TSV, XLSX, text PDF when the bundled parser is present, and ZIP containing supported files."
    return _result(name, "unsupported", warnings=[message])


def preview_file(name: str, content: bytes) -> dict:
    """Return a bounded preview. Never mutate bytes, extract, import, or evaluate.

    Status: ready, preview_only, archive, unsupported, or rejected. Archive rows
    remain empty; callers must present and approve each member independently.
    """
    if not isinstance(name, str) or not isinstance(content, bytes):
        return _result(str(name), "rejected", warnings=["Expected a filename string and immutable bytes."])
    if len(content) > MAX_FILE_BYTES:
        return _result(name, "rejected", warnings=["File exceeds the 10 MiB upload limit."])
    if not name or len(name) > 1024 or re.search(r"[\x00-\x1f\x7f\ud800-\udfff\ufffe\uffff]", name):
        return _result(name, "rejected", warnings=["Invalid filename."])
    budget = _Budget()
    try:
        result = _preview(name, content, budget)
        result["expanded_bytes"] = budget.expanded
        return result
    except (PreviewError, zipfile.BadZipFile, RuntimeError, NotImplementedError, EOFError, OSError,
            KeyError, OverflowError, UnicodeError) as exc:
        return _result(name, "rejected", warnings=[str(exc) or "Malformed or unsupported document."], expanded_bytes=budget.expanded)


def _number(value):
    if value is None or isinstance(value, bool):
        return None
    value = _text(value).strip()
    # Explicit decimal values only, never spreadsheet formulas or locale guessing.
    if not re.fullmatch(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)", value):
        return None
    try:
        number = Decimal(value)
        if not number.is_finite() or abs(number) > Decimal("1e100"):
            return None
        return format(number, "f")
    except InvalidOperation:
        return None


def _excel_number(value):
    number = _number(value)
    if number is None:
        return None
    # Excel stores only 15 significant decimal digits. A large approved total
    # may exceed that even when each individual transaction fits exactly.
    significant = Decimal(number).as_tuple().digits
    while len(significant) > 1 and significant[-1] == 0:
        significant = significant[:-1]
    return number if len(significant) <= 15 else None


def _csv_text(value):
    value = _text(value)
    if value.lstrip(" \t\r\n\ufeff").startswith(("=", "+", "-", "@")) or value.startswith(("\t", "\r", "\n")):
        return "'" + value
    return value


def csv_bytes(transactions) -> bytes:
    """Export inert UTF-8 CSV; valid monetary negatives remain numeric."""
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\r\n")
    fields = HEADERS + ("source", "id")
    writer.writerow(fields)
    for transaction in transactions:
        writer.writerow([(_number(transaction.get(key)) if key == "amount" and _number(transaction.get(key)) is not None
                          else _csv_text(transaction.get(key))) for key in fields])
    return output.getvalue().encode("utf-8-sig")


def _column_letters(index):
    result = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        result = chr(65 + remainder) + result
    return result


def _clean_xml_text(value):
    value = _text(value)
    # XML 1.0 excludes most controls and surrogate code points.
    return "".join(c for c in value if c in "\t\n\r" or (0x20 <= ord(c) <= 0xD7FF) or (0xE000 <= ord(c) <= 0xFFFD) or (0x10000 <= ord(c) <= 0x10FFFF))[:MAX_CELL_CHARS]


def _sheet_xml(rows, numeric_columns=()):
    root = ET.Element("worksheet", xmlns=NS)
    views = ET.SubElement(root, "sheetViews")
    view = ET.SubElement(views, "sheetView", workbookViewId="0")
    ET.SubElement(view, "pane", ySplit="1", topLeftCell="A2", activePane="bottomLeft", state="frozen")
    cols = ET.SubElement(root, "cols")
    width = max((len(row) for row in rows), default=1)
    for column in range(1, width + 1):
        ET.SubElement(cols, "col", min=str(column), max=str(column), width="24" if column != 2 else "42", customWidth="1")
    data = ET.SubElement(root, "sheetData")
    for r, values in enumerate(rows, 1):
        row = ET.SubElement(data, "row", r=str(r))
        for c, value in enumerate(values, 1):
            ref = f"{_column_letters(c)}{r}"
            number = _excel_number(value) if r > 1 and c - 1 in numeric_columns else None
            if number is not None:
                cell = ET.SubElement(row, "c", r=ref, s="2")
                ET.SubElement(cell, "v").text = number
            else:
                cell = ET.SubElement(row, "c", r=ref, t="inlineStr", s="1" if r == 1 else "0")
                inline = ET.SubElement(cell, "is")
                ET.SubElement(inline, "t", {"{http://www.w3.org/XML/1998/namespace}space": "preserve"}).text = _clean_xml_text(value)
    if len(rows) > 1:
        ET.SubElement(root, "autoFilter", ref=f"A1:{_column_letters(width)}{len(rows)}")
    ET.SubElement(root, "pageMargins", left="0.3", right="0.3", top="0.5", bottom="0.5", header="0.2", footer="0.2")
    ET.SubElement(root, "pageSetup", orientation="landscape", paperSize="9", fitToWidth="1", fitToHeight="0")
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def _export_tables(state, overview):
    setup = state.get("setup", {})
    summary = [["Metric", "Value"], ["Report type", "Static snapshot. No formulas or automatic refresh."],
               ["Currency", overview.get("currency", setup.get("currency", ""))],
               ["Start date", overview.get("start_date", setup.get("start_date", ""))],
               ["End date", overview.get("end_date", setup.get("end_date", ""))],
               ["Goals", _text(setup.get("goals", ""))]]
    for key, value in overview.get("totals", {}).items():
        summary.append([key.replace("_", " ").capitalize(), value])
    summary.extend([["Transaction detail scope", "All approved transactions. Summary totals use the start/end dates above; blank dates are unbounded."],
                    ["Workbook precision", "Amounts exceeding 15 significant digits are stored as exact text to preserve cents."],
                    ["Account balances", "Not inferred from imported cash flow."],
                    ["Debt balances", "Only explicitly entered balances with an as-of date."],
                    ["Validation", "Review application flags before relying on this snapshot."]])
    transactions = [list(HEADERS) + ["source", "id"]]
    for row in state.get("transactions", []):
        transactions.append([row.get(key, "") for key in HEADERS + ("source", "id")])
    budget_fields = ("category", "amount", "start_date", "end_date", "actual", "remaining", "variance", "status", "id")
    budgets = [list(budget_fields)]
    for row in overview.get("budgets", state.get("budgets", [])):
        budgets.append([row.get(key, "") for key in budget_fields])
    debt_fields = ("label", "balance", "as_of", "minimum_payment", "due_date", "source", "id")
    debts = [list(debt_fields)]
    for row in state.get("debts", []):
        debts.append([row.get(key, "") for key in debt_fields])
    return [("Summary", summary, (1,)), ("Transactions", transactions, (2,)),
            ("Budgets", budgets, (1, 4, 5, 6)), ("Debts", debts, (1, 3))]


def xlsx_bytes(state, overview) -> bytes:
    """Return an OOXML snapshot with typed money and text, never formulas."""
    tables = _export_tables(state, overview)
    content = ET.Element("Types", xmlns="http://schemas.openxmlformats.org/package/2006/content-types")
    ET.SubElement(content, "Default", Extension="rels", ContentType="application/vnd.openxmlformats-package.relationships+xml")
    ET.SubElement(content, "Default", Extension="xml", ContentType="application/xml")
    ET.SubElement(content, "Override", PartName="/xl/workbook.xml", ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml")
    ET.SubElement(content, "Override", PartName="/xl/styles.xml", ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml")
    workbook = ET.Element("workbook", xmlns=NS, attrib={"xmlns:r": DOC_REL_NS})
    sheets = ET.SubElement(workbook, "sheets")
    rels = ET.Element("Relationships", xmlns=REL_NS)
    root_rels = ET.Element("Relationships", xmlns=REL_NS)
    ET.SubElement(root_rels, "Relationship", Id="rId1", Type=DOC_REL_NS + "/officeDocument", Target="xl/workbook.xml")
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for index, (name, rows, numeric_columns) in enumerate(tables, 1):
            path = f"xl/worksheets/sheet{index}.xml"
            ET.SubElement(sheets, "sheet", name=name, sheetId=str(index), attrib={"r:id": f"rId{index}"})
            ET.SubElement(rels, "Relationship", Id=f"rId{index}", Type=DOC_REL_NS + "/worksheet", Target=f"worksheets/sheet{index}.xml")
            ET.SubElement(content, "Override", PartName="/" + path, ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml")
            archive.writestr(path, _sheet_xml(rows, numeric_columns))
        ET.SubElement(rels, "Relationship", Id="rId5", Type=DOC_REL_NS + "/styles", Target="styles.xml")
        styles = '''<?xml version="1.0" encoding="UTF-8"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
<fonts count="2"><font><sz val="11"/><name val="Calibri"/></font><font><b/><sz val="11"/><color rgb="FFFFFFFF"/><name val="Calibri"/></font></fonts>
<fills count="3"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill><fill><patternFill patternType="solid"><fgColor rgb="FF164E63"/><bgColor indexed="64"/></patternFill></fill></fills>
<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>
<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
<cellXfs count="3"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0" applyAlignment="1"><alignment vertical="top" wrapText="1"/></xf><xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1" applyAlignment="1"><alignment vertical="top" wrapText="1"/></xf><xf numFmtId="4" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/></cellXfs>
<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>'''
        archive.writestr("xl/styles.xml", styles)
        for path, element in (("[Content_Types].xml", content), ("_rels/.rels", root_rels),
                              ("xl/workbook.xml", workbook), ("xl/_rels/workbook.xml.rels", rels)):
            archive.writestr(path, ET.tostring(element, encoding="utf-8", xml_declaration=True))
    return output.getvalue()


def report_html(state, overview) -> str:
    """Escaped static printable report suitable for the browser's Save as PDF."""
    sections = []
    for title, rows, numeric_columns in _export_tables(state, overview):
        head = "".join(f"<th scope=\"col\">{html.escape(_text(value))}</th>" for value in rows[0])
        body = []
        for row in rows[1:]:
            cells = "".join(f'<td class="{"number" if i in numeric_columns and _number(value) is not None else "text"}">{html.escape(_text(value))}</td>' for i, value in enumerate(row))
            body.append("<tr>" + cells + "</tr>")
        sections.append(f"<section><h2>{html.escape(title)}</h2><table><thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table></section>")
    return '''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'">
<title>Personal finance snapshot</title><style>
body{font:13px/1.45 system-ui,sans-serif;color:#132b36;margin:32px;max-width:1400px}h1{font-size:26px}h2{font-size:19px;margin-top:28px}
table{border-collapse:collapse;width:100%;table-layout:fixed}th,td{padding:8px;border-bottom:1px solid #cbd5db;vertical-align:top;overflow-wrap:anywhere}th{text-align:left;background:#e8f1f4}.number{text-align:right;font-variant-numeric:tabular-nums}thead{display:table-header-group}tr{break-inside:avoid}
@media print{body{margin:0;font-size:9pt}section{break-before:page}section:first-of-type{break-before:auto}h2{break-after:avoid}}@page{size:landscape;margin:12mm}
</style></head><body><h1>Personal finance snapshot</h1><p>Use your browser's Print menu and Save as PDF. This report is a static snapshot of saved entries and calculated totals.</p>''' + "".join(sections) + "</body></html>"
