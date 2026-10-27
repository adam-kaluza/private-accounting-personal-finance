"""Fictional, in-memory parser and export security/regression tests."""
import copy
import csv
import io
import stat
import struct
import sys
from types import SimpleNamespace
import unittest
import xml.etree.ElementTree as ET
import zipfile
from unittest.mock import patch

from app import documents as d


HEADER = "date,description,amount,account,classification,category\n"
CSV = (HEADER + "2026-10-01,Fictional pay,3200.00,Fictional checking,income,Pay\n"
       + "2026-10-02,Fictional rent,-1200.00,Fictional checking,expense,Housing\n").encode()


def zipped(parts, compression=zipfile.ZIP_STORED):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=compression) as archive:
        for name, content in parts:
            archive.writestr(name, content)
    return output.getvalue()


def workbook(sheet=None, extra=(), relationship=None):
    if sheet is None:
        cells = "".join(f'<c r="{chr(65 + i)}1" t="inlineStr"><is><t>{name}</t></is></c>' for i, name in enumerate(d.HEADERS))
        row = '<c r="A2"><v>46200</v></c><c r="B2" t="inlineStr"><is><t>Fictional item</t></is></c><c r="C2"><f>SUM(10,20)</f><v>30</v></c><c r="D2" t="inlineStr"><is><t>Checking</t></is></c><c r="E2" t="inlineStr"><is><t>expense</t></is></c><c r="F2" t="inlineStr"><is><t>Supplies</t></is></c>'
        sheet = f'<worksheet xmlns="{d.NS}"><sheetData><row r="1">{cells}</row><row r="2">{row}</row></sheetData></worksheet>'
    relationship = relationship or f'<Relationships xmlns="{d.REL_NS}"><Relationship Id="rId1" Type="{d.DOC_REL_NS}/worksheet" Target="worksheets/sheet1.xml"/></Relationships>'
    return zipped([
        ("[Content_Types].xml", '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>'),
        ("xl/workbook.xml", f'<workbook xmlns="{d.NS}" xmlns:r="{d.DOC_REL_NS}"><sheets><sheet name="Fictional" sheetId="1" r:id="rId1"/></sheets></workbook>'),
        ("xl/_rels/workbook.xml.rels", relationship),
        ("xl/worksheets/sheet1.xml", sheet),
        *extra,
    ])


def fictional_pdf(text="Fictional rent 1200.00", pages=1, action=False):
    """Small, valid PDF fixture with Helvetica and exact xref offsets."""
    font_id = 3 + pages
    first_stream = font_id + 1
    action_text = " /OpenAction << /S /JavaScript /JS (FICTIONAL ACTION NEVER EXECUTED) >>" if action else ""
    objects = [f"<< /Type /Catalog /Pages 2 0 R{action_text} >>".encode(),
               (f"<< /Type /Pages /Count {pages} /Kids [" + " ".join(f"{3 + i} 0 R" for i in range(pages)) + "] >>").encode()]
    for i in range(pages):
        objects.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 {font_id} 0 R >> >> /Contents {first_stream + i} 0 R >>".encode())
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    stream = f"BT /F1 12 Tf 72 720 Td ({escaped}) Tj ET".encode("ascii") if text else b""
    objects.extend(f"<< /Length {len(stream)} >>\nstream\n".encode() + stream + b"\nendstream" for _ in range(pages))
    output = bytearray(b"%PDF-1.4\n%FICTIONAL\n")
    offsets = [0]
    for index, obj in enumerate(objects, 1):
        offsets.append(len(output))
        output.extend(f"{index} 0 obj\n".encode() + obj + b"\nendobj\n")
    xref = len(output)
    output.extend(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
    output.extend("".join(f"{offset:010d} 00000 n \n" for offset in offsets[1:]).encode())
    output.extend(f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    return bytes(output)


class PreviewTests(unittest.TestCase):
    def test_csv_preserves_values_and_source(self):
        original = bytes(CSV)
        result = d.preview_file("fictional.csv", CSV)
        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["rows"][1]["amount"], "-1200.00")
        self.assertEqual(result["rows"][0]["source"], "fictional.csv:line 2")
        self.assertIn("column 3", result["rows"][0]["_source_refs"]["amount"])
        self.assertEqual(CSV, original)
        self.assertEqual(result["limits"]["data_rows"], 5000)

    def test_no_date_sign_or_classification_guessing(self):
        data = (HEADER + "46200,Fictional,not-a-number,Checking,,Unknown\n").encode()
        row = d.preview_file("fictional.csv", data)["rows"][0]
        self.assertEqual(row["date"], "46200")
        self.assertEqual(row["amount"], "not-a-number")
        self.assertEqual(row["classification"], "")
        self.assertTrue(any("Numeric date" in w for w in row["warnings"]))

    def test_tsv(self):
        result = d.preview_file("fictional.tsv", CSV.replace(b",", b"\t"))
        self.assertEqual(len(result["rows"]), 2)

    def test_missing_headers_are_explicit(self):
        result = d.preview_file("fictional.csv", b"date,money\n2026-10-01,1\n")
        self.assertEqual(result["status"], "preview_only")
        self.assertEqual(result["rows"], [])
        self.assertIn("Missing:", " ".join(result["warnings"]))

    def test_text_and_pdf_do_not_infer(self):
        text = d.preview_file("fictional.txt", b"Pay 3200 and rent 1200")
        with patch.object(d, "_load_pypdf", return_value=None):
            pdf = d.preview_file("fictional.pdf", b"%PDF-fictional")
        self.assertEqual(text["rows"], [])
        self.assertEqual(pdf["status"], "unsupported")
        self.assertIn("local OCR", pdf["warnings"][0])

    def test_non_utf8_and_nul_rejected(self):
        for content in (b"\xff", b"a\x00b"):
            self.assertEqual(d.preview_file("bad.txt", content)["status"], "rejected")

    def test_limits_reject_instead_of_partial_import(self):
        data = (HEADER + ("2026-10-01,Fictional,1,Cash,income,Pay\n" * 5001)).encode()
        result = d.preview_file("fictional.csv", data)
        self.assertEqual(result["status"], "rejected")
        self.assertEqual(result["rows"], [])
        with patch.object(d, "MAX_FILE_BYTES", 8):
            self.assertEqual(d.preview_file("large.txt", b"a" * 9)["status"], "rejected")

    def test_zip_members_are_separate_and_never_extracted(self):
        content = zipped([("folder/fictional.csv", CSV), ("notes.txt", "Fictional reference")])
        with patch("zipfile.ZipFile.extract", side_effect=AssertionError("Must not extract")), patch("zipfile.ZipFile.extractall", side_effect=AssertionError("Must not extract")):
            result = d.preview_file("fictional.zip", content)
        self.assertEqual(result["status"], "archive")
        self.assertEqual(result["rows"], [])
        self.assertEqual(len(result["members"]), 2)
        self.assertEqual(result["members"][0]["status"], "ready")

    def test_zip_slip_and_special_paths_rejected(self):
        for name in ("../escape.txt", "/absolute.txt", "C:/absolute.txt", "dir\\file.txt", "a//b.txt", "./file.txt", "a/" * 9 + "file.txt"):
            with self.subTest(name=name):
                content = zipped([(name, "fictional")])
                if "\\" in name:
                    # Windows ZipInfo rewrites separators when authoring, so
                    # restore the hostile spelling in both ZIP headers.
                    content = content.replace(name.replace("\\", "/").encode(), name.encode())
                result = d.preview_file("unsafe.zip", content)
                self.assertEqual(result["status"], "rejected")
                self.assertEqual(result["rows"], [])

    def test_zip_links_encryption_and_duplicate_names_rejected(self):
        link = zipfile.ZipInfo("link.txt")
        link.create_system = 3
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        self.assertEqual(d.preview_file("link.zip", zipped([(link, "target")]))["status"], "rejected")
        self.assertEqual(d.preview_file("duplicate.zip", zipped([("same.txt", "a"), ("SAME.txt", "b")]))["status"], "rejected")
        content = bytearray(zipped([("file.txt", "fictional")]))
        local = content.index(b"PK\x03\x04")
        central = content.index(b"PK\x01\x02")
        struct.pack_into("<H", content, local + 6, 1)
        struct.pack_into("<H", content, central + 8, 1)
        self.assertEqual(d.preview_file("encrypted.zip", bytes(content))["status"], "rejected")

    def test_nested_archive_and_zip_bomb_rejected(self):
        nested = zipped([("innocent.txt", zipped([("notes.txt", "fictional")]))])
        self.assertEqual(d.preview_file("nested.zip", nested)["status"], "rejected")
        bomb = zipped([("large.txt", "x" * 1_000_000)], zipfile.ZIP_DEFLATED)
        result = d.preview_file("bomb.zip", bomb)
        self.assertEqual(result["status"], "rejected")
        self.assertIn("compression ratio", result["warnings"][0])
        with patch.object(d, "MAX_EXPANDED_BYTES", 10):
            result = d.preview_file("expanded.zip", zipped([("a.txt", "abcdef"), ("b.txt", "ghijkl")]))
            self.assertEqual(result["status"], "rejected")

    def test_archive_row_budget_shared(self):
        data = (HEADER + ("2026-10-01,Fictional,1,Cash,income,Pay\n" * 2600)).encode()
        result = d.preview_file("large.zip", zipped([("first.csv", data), ("second.csv", data)]))
        self.assertEqual(result["status"], "rejected")
        self.assertEqual(result["rows"], [])

    def test_xlsx_formula_is_source_text_never_cached_value(self):
        content = workbook()
        original = bytes(content)
        result = d.preview_file("fictional.xlsx", content)
        self.assertEqual(result["status"], "ready", result)
        row = result["rows"][0]
        self.assertEqual(row["amount"], "=SUM(10,20)")
        self.assertEqual(row["date"], "46200")
        self.assertEqual(row["_source_refs"]["amount"], "fictional.xlsx:Fictional!C2")
        self.assertEqual(result["sheets"][0]["formulas"], 1)
        self.assertEqual(content, original)

    def test_xlsx_malformed_xml_entities_and_relationships_rejected(self):
        for content in (b"not a zip", zipped([("something.xml", "a")]), workbook("<not-closed>"),
                        workbook('<!DOCTYPE worksheet [<!ENTITY e "secret">]><worksheet/>'),
                        workbook(relationship=f'<Relationships xmlns="{d.REL_NS}"><Relationship Id="rId1" Type="{d.DOC_REL_NS}/worksheet" Target="../../outside.xml"/></Relationships>')):
            self.assertEqual(d.preview_file("bad.xlsx", content)["status"], "rejected")

    def test_external_parts_are_ignored(self):
        relationships = f'<Relationships xmlns="{d.REL_NS}"><Relationship Id="rId1" Type="{d.DOC_REL_NS}/worksheet" Target="worksheets/sheet1.xml"/><Relationship Id="rId2" Type="{d.DOC_REL_NS}/externalLink" Target="https://invalid.example/data" TargetMode="External"/></Relationships>'
        content = workbook(extra=[("xl/vbaProject.bin", b"FICTIONAL"), ("xl/embeddings/fake.bin", b"FICTIONAL")], relationship=relationships)
        result = d.preview_file("fictional.xlsx", content)
        self.assertEqual(result["status"], "ready")
        self.assertIn("External workbook relationship ignored", " ".join(result["warnings"]))
        self.assertIn("Ignored 2", " ".join(result["warnings"]))


class PdfTests(unittest.TestCase):
    def setUp(self):
        self.parser = d._load_pypdf()
        if self.parser is None:
            self.skipTest("Optional vendored pypdf is absent")

    def test_actual_text_extraction_is_local_page_referenced_and_nonmutating(self):
        content = fictional_pdf(action=True)
        original = bytes(content)
        with patch("subprocess.run", side_effect=AssertionError("No subprocess")), patch("socket.socket", side_effect=AssertionError("No networking")):
            result = d.preview_file("fictional.pdf", content)
        self.assertEqual(result["status"], "preview_only", result)
        self.assertEqual(result["page_count"], 1)
        self.assertEqual(result["rows"], [])
        self.assertIn("Fictional rent 1200.00", result["text"])
        self.assertIn("fictional.pdf:page 1", result["text"])
        self.assertNotIn("FICTIONAL ACTION", result["text"])
        self.assertEqual(content, original)

    def test_no_text_and_encrypted_are_explicitly_unsupported(self):
        result = d.preview_file("blank.pdf", fictional_pdf(text=""))
        self.assertEqual(result["status"], "unsupported")
        self.assertIn("scanned", " ".join(result["warnings"]))
        self.assertIn("local OCR", " ".join(result["warnings"]))
        output = io.BytesIO()
        writer = self.parser.PdfWriter()
        writer.add_blank_page(width=100, height=100)
        writer.encrypt("fictional-password", algorithm="RC4-128")
        writer.write(output)
        encrypted = d.preview_file("encrypted.pdf", output.getvalue())
        self.assertEqual(encrypted["status"], "unsupported", encrypted)
        self.assertIn("Encrypted", " ".join(encrypted["warnings"]))

    def test_pdf_page_and_character_limits_mark_partial_review(self):
        result = d.preview_file("long.pdf", fictional_pdf(pages=31))
        self.assertEqual(result["status"], "preview_only", result)
        self.assertTrue(result["truncated"])
        self.assertEqual(result["previewed_pages"], 30)
        self.assertIn("PARTIAL PREVIEW", result["text"])
        self.assertIn("not a complete document review", result["text"])
        result = d.preview_file("many.pdf", fictional_pdf(pages=101))
        self.assertEqual(result["status"], "rejected", result)
        result = d.preview_file("text.pdf", fictional_pdf(text="fictional " * 3000))
        self.assertTrue(result["truncated"])
        self.assertLessEqual(len(result["text"]), d.MAX_PDF_TEXT_CHARS)

    def test_pdf_malformed_and_stream_limit_rejected(self):
        self.assertEqual(d.preview_file("bad.pdf", b"%PDF-not-valid")["status"], "rejected")
        with patch.object(d, "MAX_PDF_STREAM_BYTES", 16):
            result = d.preview_file("large.pdf", fictional_pdf())
        self.assertEqual(result["status"], "rejected")
        self.assertEqual(result["text"], "")

    def test_global_parser_is_not_used(self):
        with patch.dict(sys.modules, {"pypdf": SimpleNamespace(__file__="C:/not-vendored/pypdf/__init__.py")}):
            self.assertIsNone(d._load_pypdf())


class ExportTests(unittest.TestCase):
    def setUp(self):
        self.state = {"setup": {"currency": "USD", "start_date": "2026-10-01", "end_date": "2026-10-31", "goals": "Fictional spending review"},
                      "transactions": d.preview_file("fictional.csv", CSV)["rows"],
                      "budgets": [{"category": "Housing", "amount": "1300.00", "start_date": "2026-10-01", "end_date": "2026-10-31"}],
                      "debts": [{"label": "Fictional loan", "balance": "450.00", "as_of": "2026-10-15", "minimum_payment": "25.00", "due_date": "2026-11-01"}]}
        self.overview = {"totals": {"income": "3200.00", "expenses": "1200.00", "net_income_expenses": "2000.00"},
                         "budgets": [{**self.state["budgets"][0], "actual": "1200.00", "remaining": "100.00", "variance": "-100.00", "status": "within budget"}]}

    def test_xlsx_valid_package_tabs_numeric_cells_no_formulas(self):
        before = copy.deepcopy(self.state)
        content = d.xlsx_bytes(self.state, self.overview)
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            self.assertIsNone(archive.testzip())
            book = ET.fromstring(archive.read("xl/workbook.xml"))
            self.assertEqual([sheet.attrib["name"] for sheet in book.findall(f"{{{d.NS}}}sheets/{{{d.NS}}}sheet")], ["Summary", "Transactions", "Budgets", "Debts"])
            sheets = [ET.fromstring(archive.read(f"xl/worksheets/sheet{i}.xml")) for i in range(1, 5)]
            self.assertEqual(sheets[0].find(f'.//{{{d.NS}}}c[@r="B7"]/{{{d.NS}}}v').text, "3200.00")
            self.assertEqual(sheets[1].find(f'.//{{{d.NS}}}c[@r="C3"]/{{{d.NS}}}v').text, "-1200.00")
            self.assertEqual(sheets[2].find(f'.//{{{d.NS}}}c[@r="F2"]/{{{d.NS}}}v').text, "100.00")
            self.assertEqual(sheets[3].find(f'.//{{{d.NS}}}c[@r="B2"]/{{{d.NS}}}v').text, "450.00")
            for root in sheets:
                self.assertEqual(root.findall(f".//{{{d.NS}}}f"), [])
        self.assertEqual(self.state, before)
        preview = d.preview_file("snapshot.xlsx", content)
        self.assertEqual(preview["status"], "ready", preview)
        self.assertEqual(len(preview["rows"]), 2)

    def test_csv_injection_neutralized_but_negative_money_numeric(self):
        transaction = {"date": "@date", "description": " =HYPERLINK(\"http://invalid.example\")", "amount": "-12.50", "account": "+cmd", "classification": "-text", "category": "\t=cmd", "source": "=cmd", "id": "@id"}
        rows = list(csv.reader(io.StringIO(d.csv_bytes([transaction]).decode("utf-8-sig"))))
        self.assertEqual(rows[1][2], "-12.50")
        for index in (0, 1, 3, 4, 5, 6, 7):
            self.assertTrue(rows[1][index].startswith("'"), rows[1][index])
        transaction["amount"] = "=1+1"
        self.assertIn("'=1+1", d.csv_bytes([transaction]).decode("utf-8-sig"))

    def test_html_escapes_all_values_and_has_no_active_content(self):
        self.state["transactions"][0]["description"] = '<script>alert("fictional")</script><img src="https://invalid.example/">'
        report = d.report_html(self.state, self.overview)
        self.assertNotIn("<script", report)
        self.assertNotIn("<img", report)
        self.assertIn("&lt;script&gt;", report)
        self.assertIn("3200.00", report)
        self.assertIn("Save as PDF", report)
        self.assertIn("default-src 'none'", report)

    def test_formula_text_typed_as_text_in_xlsx(self):
        self.state["transactions"][0]["description"] = "=1+1"
        content = d.xlsx_bytes(self.state, self.overview)
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            root = ET.fromstring(archive.read("xl/worksheets/sheet2.xml"))
            cell = root.find(f'.//{{{d.NS}}}c[@r="B2"]')
            self.assertEqual(cell.attrib["t"], "inlineStr")
            self.assertEqual(cell.find(f"{{{d.NS}}}is/{{{d.NS}}}t").text, "=1+1")


if __name__ == "__main__":
    unittest.main()
