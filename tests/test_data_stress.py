"""Bounded stress/regression cases using only generated fictional records.

All persisted fixtures are owned temporary directories under this test folder.
No real financial files, outside data folders, model service, or network is used.
"""
from __future__ import annotations

import copy
import csv
from decimal import Decimal
import io
import json
import os
from pathlib import Path
import random
import struct
import sys
import tempfile
import unittest
from unittest import mock
import xml.etree.ElementTree as ET
import zipfile

RELEASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RELEASE))
from app import documents as d
from app import finance_core as f


def record(amount="-12.34", **changes):
    result = {"date": "2026-01-12", "description": "Fictional grocery item", "amount": amount,
              "account": "Fictional checking", "classification": "expense", "category": "Food",
              "source": "Fictional source"}
    result.update(changes)
    return result


def archive_bytes(parts, compression=zipfile.ZIP_STORED):
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", compression=compression) as archive:
        for name, content in parts:
            archive.writestr(name, content)
    return out.getvalue()


def worksheet():
    rows = [list(d.HEADERS), ["2026-01-12", "Fictional grocery item", "-12.34",
                              "Fictional checking", "expense", "Food"]]
    return d._sheet_xml(rows, (2,)).decode("utf-8")


def workbook(sheet=None, book=None, relationships=None, extra=()):
    return archive_bytes([
        ("[Content_Types].xml", '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>'),
        ("xl/workbook.xml", book or f'<workbook xmlns="{d.NS}" xmlns:r="{d.DOC_REL_NS}"><sheets><sheet name="Fictional" sheetId="1" r:id="rId1"/></sheets></workbook>'),
        ("xl/_rels/workbook.xml.rels", relationships or f'<Relationships xmlns="{d.REL_NS}"><Relationship Id="rId1" Type="{d.DOC_REL_NS}/worksheet" Target="worksheets/sheet1.xml"/></Relationships>'),
        ("xl/worksheets/sheet1.xml", worksheet() if sheet is None else sheet),
        *extra,
    ])


def cells_from_sheet(content, index=1):
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        root = ET.fromstring(archive.read(f"xl/worksheets/sheet{index}.xml"))
    return {cell.attrib["r"]: cell for cell in root.findall(f".//{{{d.NS}}}c")}


def resource_pdf(forms=3, unused_image=False):
    parser = d._load_pypdf()
    if parser is None:
        raise unittest.SkipTest("Bundled PDF parser unavailable")
    from pypdf.generic import DictionaryObject, NameObject, ArrayObject, NumberObject, DecodedStreamObject
    writer = parser.PdfWriter()
    page = writer.add_blank_page(612, 792)
    font = DictionaryObject({NameObject("/Type"): NameObject("/Font"),
        NameObject("/Subtype"): NameObject("/Type1"), NameObject("/BaseFont"): NameObject("/Helvetica")})
    resources = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})})
    objects = DictionaryObject()
    for i in range(forms):
        stream = DecodedStreamObject()
        stream.set_data(b"BT /F1 12 Tf 0 0 Td (Fictional resource text) Tj ET " + b" " * 200)
        stream.update({NameObject("/Type"): NameObject("/XObject"), NameObject("/Subtype"): NameObject("/Form"),
                       NameObject("/BBox"): ArrayObject([NumberObject(value) for value in (0, 0, 200, 200)]),
                       NameObject("/Resources"): resources})
        objects[NameObject(f"/F{i}")] = writer._add_object(stream)
    if unused_image:
        image = DecodedStreamObject()
        image.set_data(b"Fictional image bytes are not text" * 50)
        image.update({NameObject("/Type"): NameObject("/XObject"), NameObject("/Subtype"): NameObject("/Image")})
        objects[NameObject("/IgnoredImage")] = writer._add_object(image)
    page[NameObject("/Resources")] = DictionaryObject({NameObject("/XObject"): objects})
    page_content = DecodedStreamObject()
    page_content.set_data(" ".join(f"/F{i} Do" for i in range(forms)).encode())
    page[NameObject("/Contents")] = writer._add_object(page_content)
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


class LedgerStressTests(unittest.TestCase):
    def setUp(self):
        self.fixture = tempfile.TemporaryDirectory(prefix="data-stress-", dir=RELEASE / "tests")
        self.addCleanup(self.fixture.cleanup)
        self.root = Path(self.fixture.name) / "fictional-records"
        self.store = f.Store(self.root)

    def approve(self, kind, data, duplicates=False):
        proposal = self.store.propose(kind, data)
        self.assertTrue(proposal["valid"], proposal["questions"])
        return self.store.approve(proposal["id"], proposal["base_revision"], duplicates)

    def immutable_bytes(self):
        return {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}

    def test_deep_and_cyclic_proposals_fail_before_copy_or_disk(self):
        nested = {}
        cursor = nested
        for _ in range(f.MAX_JSON_DEPTH + 2):
            cursor["child"] = {}
            cursor = cursor["child"]
        cyclic = {}
        cyclic["self"] = cyclic
        for value in (nested, cyclic):
            with self.subTest(case="cycle" if value is cyclic else "depth"):
                with self.assertRaisesRegex(f.FinanceError, "nesting"):
                    self.store.propose("transaction", value)
        self.assertEqual(self.store.pending(), [])
        self.assertFalse(self.root.exists())

    def test_decimal_boundaries_and_negative_zero_are_exact(self):
        for amount in ("999999999999.99", "-999999999999.99", "+0", "-0.00"):
            proposal = self.store.propose("transaction", record(amount, classification="refund"))
            self.assertTrue(proposal["valid"])
            self.assertEqual(proposal["data"]["amount"], "0.00" if Decimal(amount) == 0 else format(Decimal(amount), ".2f"))
            self.store.reject(proposal["id"])
        for amount in ("1000000000000", "-1000000000000", "Infinity", "1e10", [], {}, None, False):
            proposal = self.store.propose("transaction", record(amount, classification="refund"))
            self.assertFalse(proposal["valid"])
            with self.assertRaises(f.FinanceError):
                self.store.approve(proposal["id"], 0)
            self.store.reject(proposal["id"])

    def test_nonxml_characters_cannot_silently_disappear_from_exports(self):
        for bad in ("\ufffe", "\uffff", "\ud800", "\x00"):
            proposal = self.store.propose("transaction", record(description="Fictional " + bad))
            self.assertFalse(proposal["valid"])
            with self.assertRaises(f.FinanceError):
                self.store.approve(proposal["id"], 0)

    def test_bounded_large_ledger_exact_totals_and_xlsx_precision(self):
        # 1,001 rows produce a total beyond Excel's 15 significant digits while
        # remaining much smaller than the 10,000-row import batch ceiling.
        rows = [record("999999999999.99", classification="income", description=f"Fictional pay {i}",
                       date="2026-01-12" if i % 2 == 0 else "2026-02-12")
                for i in range(1001)]
        state = self.approve("transactions", rows)
        expected = format(Decimal("999999999999.99") * 1001, ".2f")
        overview = self.store.overview()
        self.assertEqual(overview["totals"]["income"], expected)
        self.assertEqual(overview["transaction_count"], 1001)
        exported = d.xlsx_bytes(state, overview)
        summary = cells_from_sheet(exported)
        self.assertEqual(summary["B7"].attrib["t"], "inlineStr")
        self.assertEqual(summary["B7"].findtext(f"{{{d.NS}}}is/{{{d.NS}}}t"), expected)
        transaction = cells_from_sheet(exported, 2)["C2"]
        self.assertEqual(transaction.findtext(f"{{{d.NS}}}v"), "999999999999.99")
        reopened = f.Store(self.root)
        self.assertEqual(reopened.state(), state)
        period = reopened.overview("2026-01-01", "2026-01-31")
        period_expected = format(sum((Decimal(row["amount"]) for row in rows
                                      if row["date"].startswith("2026-01")), Decimal(0)), ".2f")
        self.assertEqual(period["transaction_count"], 501)
        self.assertEqual(period["totals"]["income"], period_expected)
        period_cells = cells_from_sheet(d.xlsx_bytes(state, period))
        self.assertEqual(period_cells["B7"].findtext(f"{{{d.NS}}}is/{{{d.NS}}}t"), period_expected)
        self.assertEqual(period_cells["B4"].findtext(f"{{{d.NS}}}is/{{{d.NS}}}t"), "2026-01-01")

    def test_budget_period_signed_refunds_and_unknowns_remain_separate(self):
        self.approve("setup", {"start_date": "2026-02-01", "end_date": "2026-02-28"})
        self.approve("transactions", [record("-20", date="2026-01-01"),
            record("-30", date="2026-01-31", description="Fictional month end"),
            record("-400", date="2026-02-01", description="Fictional later item"),
            record("10", classification="refund", description="Fictional returned purchase"),
            record("-3", classification="refund", description="Fictional outgoing refund")])
        self.approve("budget", {"category": "food", "amount": "60", "start_date": "2026-01-01", "end_date": "2026-01-31"})
        self.approve("budget", {"category": "Unknown"})
        overview = self.store.overview("2026-01-01", "2026-01-31")
        self.assertEqual(overview["totals"]["expenses"], "50.00")
        self.assertEqual(overview["totals"]["refunds"], "7.00")
        self.assertEqual(overview["totals"]["net_cash_flow"], "-43.00")
        self.assertEqual(overview["budgets"][0]["actual"], "50.00")
        self.assertEqual(overview["budgets"][0]["remaining"], "10.00")
        self.assertEqual(overview["budgets"][0]["status"], "active")
        self.assertIsNone(overview["budgets"][1]["actual"])
        self.assertEqual(self.store.overview()["budgets"][0]["status"], "other_period")

    def test_edit_duplicate_review_and_stale_rejection_leave_history(self):
        state = self.approve("transactions", [record(), record(description="Fictional second item")])
        original = self.immutable_bytes()
        edited = dict(state["transactions"][1], description="  FICTIONAL   GROCERY ITEM  ")
        proposal = self.store.propose("transaction", edited)
        self.assertEqual(proposal["duplicate_count"], 1)
        with self.assertRaisesRegex(f.FinanceError, "acknowledge"):
            self.store.approve(proposal["id"], 1)
        approved = self.store.approve(proposal["id"], 1, allow_duplicates=True)
        self.assertEqual(approved["transactions"][1]["id"], state["transactions"][1]["id"])
        for relative, content in original.items():
            if relative.name != "current.json":
                self.assertEqual((self.root / relative).read_bytes(), content)
        old = self.store.propose("delete_transaction", {"id": approved["transactions"][0]["id"]})
        self.approve("setup", {"goals": "Fictional next revision"})
        before = self.immutable_bytes()
        with self.assertRaisesRegex(f.FinanceError, "stale"):
            self.store.approve(old["id"], old["base_revision"])
        self.assertEqual(self.immutable_bytes(), before)

    def test_pointer_flush_failure_is_retryable_and_preserves_original_bytes(self):
        state = self.approve("transaction", record())
        before = self.immutable_bytes()
        proposal = self.store.propose("setup", {"goals": "Fictional retry"})
        with mock.patch.object(f.os, "fsync", side_effect=[None, OSError("fictional failure")]):
            with self.assertRaisesRegex(f.FinanceError, "could not be saved"):
                self.store.approve(proposal["id"], state["revision"])
        for relative, content in before.items():
            self.assertEqual((self.root / relative).read_bytes(), content)
        self.assertEqual(self.store.state(), state)
        self.assertEqual(list(self.root.glob(".pointer-*.tmp")), [])
        self.assertEqual(len(self.store.pending()), 1)
        approved = self.store.approve(proposal["id"], state["revision"])
        self.assertEqual(approved["revision"], 2)
        self.assertEqual(self.store.pending(), [])

    def test_complete_state_limit_does_not_partially_commit_small_proposal(self):
        self.approve("transaction", record())
        before = self.immutable_bytes()
        rows = [record(description="Fictional additional " + str(i)) for i in range(6)]
        largest_saved = max(len(content) for content in before.values())
        limit = max(largest_saved, len(f._encoded(rows))) + 10
        with mock.patch.object(f, "MAX_JSON_BYTES", limit):
            proposal = self.store.propose("transactions", rows)
            with self.assertRaisesRegex(f.FinanceError, "size"):
                self.store.approve(proposal["id"], proposal["base_revision"])
        self.assertEqual(self.immutable_bytes(), before)
        self.assertEqual(len(self.store.pending()), 1)

    def test_pending_and_batch_limits_are_bounded_without_disk_mutation(self):
        with mock.patch.object(f, "MAX_PENDING", 2), mock.patch.object(f, "MAX_BATCH", 2):
            with self.assertRaises(f.FinanceError):
                self.store.propose("transactions", [record()] * 3)
            self.store.propose("setup", {"goals": "Fictional one"})
            self.store.propose("setup", {"goals": "Fictional two"})
            with self.assertRaises(f.FinanceError):
                self.store.propose("setup", {"goals": "Fictional three"})
        self.assertFalse(self.root.exists())

    def test_hard_linked_pointer_and_revision_are_rejected_without_mutation(self):
        self.approve("transaction", record())
        pointer = self.root / "current.json"
        revision = self.root / "revisions" / json.loads(pointer.read_bytes())["file"]
        for path in (pointer, revision):
            original = path.read_bytes()
            alias = Path(self.fixture.name) / ("fictional-alias-" + path.name)
            try:
                os.link(path, alias)
            except OSError:
                self.skipTest("This filesystem does not support test hard links")
            try:
                with self.assertRaisesRegex(f.FinanceError, "Hard-linked"):
                    self.store.state()
                self.assertEqual(path.read_bytes(), original)
                self.assertEqual(alias.read_bytes(), original)
            finally:
                alias.unlink()

    def test_hard_link_guard_rejects_observed_multiple_links(self):
        self.approve("transaction", record())
        pointer = self.root / "current.json"
        original_lstat = Path.lstat
        real = original_lstat(pointer)
        synthetic = mock.Mock(st_mode=real.st_mode, st_nlink=2,
                              st_file_attributes=getattr(real, "st_file_attributes", 0))
        def observed(path, *args, **kwargs):
            return synthetic if path == pointer else original_lstat(path, *args, **kwargs)
        before = self.immutable_bytes()
        with mock.patch.object(Path, "lstat", observed):
            with self.assertRaisesRegex(f.FinanceError, "Hard-linked"):
                self.store.state()
        self.assertEqual(self.immutable_bytes(), before)

    def test_malformed_saved_json_is_not_treated_as_empty_or_overwritten(self):
        self.approve("transaction", record())
        pointer = self.root / "current.json"
        # Every mutation below is to this test's own generated fixture.
        for content in (b'{"schema_version":1,"schema_version":1}', b'{"revision":NaN}', b'{broken'):
            pointer.write_bytes(content)
            with self.assertRaises(f.FinanceError):
                self.store.propose("setup", {"goals": "Fictional never saved"})
            self.assertEqual(pointer.read_bytes(), content)


class DocumentStressTests(unittest.TestCase):
    def rejected(self, content, name="fictional.xlsx"):
        before = bytes(content)
        result = d.preview_file(name, content)
        self.assertEqual(result["status"], "rejected", result)
        self.assertEqual(result["rows"], [])
        self.assertEqual(content, before)
        return result

    def test_csv_multiline_source_covers_all_physical_lines(self):
        content = (",".join(d.HEADERS) + '\r\n2026-01-12,"Fictional first\r\nsecond",-12.34,Fictional checking,expense,Food\r\n'
                   '2026-01-13,Fictional next,-1,Fictional checking,expense,Food\r\n').encode()
        rows = d.preview_file("fictional.csv", content)["rows"]
        self.assertEqual(rows[0]["source"], "fictional.csv:lines 2-3")
        self.assertEqual(rows[0]["_source_refs"]["amount"], "fictional.csv:lines 2-3, column 3")
        self.assertEqual(rows[1]["source"], "fictional.csv:line 4")

    def test_zip_noncanonical_tables_still_share_row_budget(self):
        with mock.patch.object(d, "MAX_ROWS", 3):
            content = archive_bytes([("one.csv", "unknown\na\nb\n"), ("two.csv", "unknown\nc\nd\n")])
            result = self.rejected(content, "fictional.zip")
        self.assertIn("Row limit", result["warnings"][0])

    def test_xlsx_cell_row_mismatch_and_duplicate_rows_are_rejected(self):
        sheet = worksheet()
        for changed in (sheet.replace('r="A2"', 'r="A3"'),
                        sheet.replace('<row r="2">', '<row r="1">'),
                        sheet.replace('<row r="2">', '<row>'),
                        sheet.replace('r="2"', 'r="1048577"')):
            with self.subTest(sheet=changed[-100:]):
                self.rejected(workbook(sheet=changed))

    def test_xlsx_sparse_row_metadata_is_accurate(self):
        sheet = worksheet().replace('r="2"', 'r="42"')
        for letter in "ABCDEF":
            sheet = sheet.replace(f'r="{letter}2"', f'r="{letter}42"')
        preview = d.preview_file("fictional.xlsx", workbook(sheet=sheet))
        self.assertEqual(preview["status"], "ready")
        self.assertEqual(preview["rows"][0]["source"], "fictional.xlsx:Fictional!row 42")
        self.assertEqual(preview["rows"][0]["_source_refs"]["amount"], "fictional.xlsx:Fictional!C42")

    def test_xlsx_duplicate_relationship_ids_and_targets_are_rejected(self):
        relationship = f'<Relationship Id="rId1" Type="{d.DOC_REL_NS}/worksheet" Target="worksheets/sheet1.xml"/>'
        self.rejected(workbook(relationships=f'<Relationships xmlns="{d.REL_NS}">{relationship}{relationship}</Relationships>'))
        book = f'<workbook xmlns="{d.NS}" xmlns:r="{d.DOC_REL_NS}"><sheets><sheet name="One" sheetId="1" r:id="rId1"/><sheet name="Two" sheetId="2" r:id="rId1"/></sheets></workbook>'
        self.rejected(workbook(book=book))

    def test_xlsx_wrong_roots_and_namespaces_are_rejected(self):
        for kwargs in ({"sheet": '<wrong/>'}, {"book": '<workbook/>'}, {"relationships": '<Relationships/>'},
                       {"extra": [("xl/sharedStrings.xml", '<sst/>')]}):
            with self.subTest(kwargs=kwargs):
                self.rejected(workbook(**kwargs))

    def test_hidden_sheets_are_explicit_without_dropping_their_rows(self):
        book = f'<workbook xmlns="{d.NS}" xmlns:r="{d.DOC_REL_NS}"><sheets><sheet name="Fictional" sheetId="1" r:id="rId1" state="veryHidden"/></sheets></workbook>'
        result = d.preview_file("fictional.xlsx", workbook(book=book))
        self.assertEqual(result["status"], "ready")
        self.assertEqual(len(result["rows"]), 1)
        self.assertTrue(any("hidden worksheet" in value for value in result["warnings"]))

    def test_xml_element_and_depth_limits_refuse_before_unbounded_allocation(self):
        with mock.patch.object(d, "MAX_XML_ELEMENTS", 40):
            self.rejected(workbook(sheet=f'<worksheet xmlns="{d.NS}">' + '<unused/>' * 41 + '</worksheet>'))
        with mock.patch.object(d, "MAX_XML_DEPTH", 6):
            self.rejected(workbook(sheet=f'<worksheet xmlns="{d.NS}">' + '<node>' * 7 + '</node>' * 7 + '</worksheet>'))

    def test_xml_element_budget_is_shared_across_workbook_parts(self):
        # Each part is individually small, but their aggregate exceeds this cap.
        with mock.patch.object(d, "MAX_XML_ELEMENTS", 45):
            self.rejected(workbook(extra=[("xl/sharedStrings.xml", f'<sst xmlns="{d.NS}">' + '<si><t>x</t></si>' * 8 + '</sst>')]))

    def test_shared_strings_are_exact_and_invalid_indexes_rejected(self):
        sheet = worksheet().replace('<c r="B2" t="inlineStr" s="0"><is><t xml:space="preserve">Fictional grocery item</t></is></c>', '<c r="B2" t="s"><v>0</v></c>')
        self.assertIn('t="s"', sheet)
        shared = f'<sst xmlns="{d.NS}"><si><r><t>Fictional </t></r><r><t>rich text</t></r><rPh sb="0" eb="1"><t>phonetic annotation</t></rPh></si></sst>'
        result = d.preview_file("fictional.xlsx", workbook(sheet=sheet, extra=[("xl/sharedStrings.xml", shared)]))
        self.assertEqual(result["rows"][0]["description"], "Fictional rich text")
        for value in ("-1", "1000", "bad"):
            self.rejected(workbook(sheet=sheet.replace('<v>0</v>', f'<v>{value}</v>'), extra=[("xl/sharedStrings.xml", shared)]))

    def test_inline_phonetic_annotations_do_not_change_source_cell_text(self):
        sheet = worksheet().replace('Fictional grocery item</t></is>',
                                    'Fictional grocery item</t><rPh sb="0" eb="1"><t>annotation</t></rPh></is>')
        result = d.preview_file("fictional.xlsx", workbook(sheet=sheet))
        self.assertEqual(result["rows"][0]["description"], "Fictional grocery item")

    def test_zip_bad_crc_and_invalid_utf8_names_return_rejections(self):
        content = bytearray(archive_bytes([("fictional.txt", b"Fictional known payload")]))
        offset = content.index(b"Fictional known payload")
        content[offset] ^= 1
        self.rejected(bytes(content), "fictional.zip")
        content = bytearray(archive_bytes([("x.txt", b"Fictional")]))
        local = content.index(b"PK\x03\x04")
        central = content.index(b"PK\x01\x02")
        for offset in (local + 6, central + 8):
            flags = struct.unpack_from("<H", content, offset)[0]
            struct.pack_into("<H", content, offset, flags | 0x800)
        content[local + 30] = 0xFF
        content[central + 46] = 0xFF
        self.rejected(bytes(content), "fictional.zip")

    def test_filename_controls_cannot_forge_source_locations(self):
        for name in ("fictional\nother.csv", "fictional\x1b.csv", "fictional\ud800.csv"):
            self.rejected(b"Fictional", name)

    def test_summary_period_matches_overview_and_detail_scope_is_explicit(self):
        state = {"setup": {"currency": "USD", "start_date": "2026-02-01", "end_date": "2026-02-28"},
                 "transactions": [record()], "budgets": [], "debts": []}
        overview = {"start_date": "2026-01-01", "end_date": "2026-01-31", "totals": {"income": "0.00"}}
        summary = dict(d._export_tables(state, overview)[0][1][1:])
        self.assertEqual(summary["Start date"], "2026-01-01")
        self.assertEqual(summary["End date"], "2026-01-31")
        self.assertIn("All approved transactions", summary["Transaction detail scope"])
        report = d.report_html(state, overview)
        self.assertIn("2026-01-31", report)
        self.assertNotIn("2026-02-28", report)

    def test_excel_high_precision_budget_totals_are_literal_exact_text(self):
        state = {"setup": {}, "transactions": [record()], "debts": []}
        overview = {"budgets": [{"category": "Fictional", "actual": "10000000000000.01",
                                  "remaining": "-10000000000000.01", "variance": "10000000000000.01"}]}
        cells = cells_from_sheet(d.xlsx_bytes(state, overview), 3)
        for reference, value in (("E2", "10000000000000.01"), ("F2", "-10000000000000.01"), ("G2", "10000000000000.01")):
            self.assertEqual(cells[reference].attrib["t"], "inlineStr")
            self.assertEqual(cells[reference].findtext(f"{{{d.NS}}}is/{{{d.NS}}}t"), value)

    def test_csv_formula_safety_keeps_exact_approved_money_and_source_bytes(self):
        rows = [record(description="\ufeff  =HYPERLINK(\"fictional\")", amount="-999999999999.99", source="@Fictional")]
        before = copy.deepcopy(rows)
        result = list(csv.DictReader(io.StringIO(d.csv_bytes(rows).decode("utf-8-sig"))))[0]
        self.assertEqual(result["amount"], "-999999999999.99")
        self.assertTrue(result["description"].startswith("'"))
        self.assertEqual(result["source"], "'@Fictional")
        self.assertEqual(rows, before)

    def test_seeded_malformed_binary_inputs_never_escape_preview_api(self):
        generator = random.Random(78231)
        for extension in ("xlsx", "zip", "pdf"):
            for size in (0, 1, 31, 127, 511):
                content = bytes(generator.randrange(256) for _ in range(size))
                with self.subTest(extension=extension, size=size):
                    result = d.preview_file("fictional." + extension, content)
                    self.assertIn(result["status"], ("rejected", "unsupported"))
                    self.assertEqual(result["rows"], [])

    def test_pdf_form_streams_consume_shared_expansion_budget(self):
        content = resource_pdf()
        with mock.patch.object(d, "MAX_EXPANDED_BYTES", 200):
            result = self.rejected(content, "fictional.pdf")
        self.assertIn("shared", result["warnings"][0])
        self.assertGreater(result["expanded_bytes"], 200)

    def test_pdf_resource_object_limit_is_enforced(self):
        content = resource_pdf()
        with mock.patch.object(d, "MAX_PDF_RESOURCE_OBJECTS", 2):
            result = self.rejected(content, "fictional.pdf")
        self.assertIn("object limit", result["warnings"][0])

    def test_pdf_forms_extract_text_and_images_are_not_decoded(self):
        content = resource_pdf(forms=1, unused_image=True)
        with mock.patch.object(d, "MAX_EXPANDED_BYTES", 400):
            result = d.preview_file("fictional.pdf", content)
        self.assertEqual(result["status"], "preview_only", result)
        self.assertIn("Fictional resource text", result["text"])
        self.assertLess(result["expanded_bytes"], 400)
        self.assertGreater(result["expanded_bytes"], 200)


if __name__ == "__main__":
    unittest.main()
