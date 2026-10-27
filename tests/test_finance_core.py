"""Behavioral tests use only fictional records in newly created temporary roots."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.finance_core import FinanceError, Store


def row(amount="-12.34", **changes):
    record = {"date": "2026-01-12", "description": "Fictional groceries", "amount": amount,
              "account": "Fictional checking", "classification": "expense", "category": "Groceries",
              "source": "Fictional fixture"}
    record.update(changes)
    return record


class FinanceCoreTests(unittest.TestCase):
    def setUp(self):
        # Keep every generated fixture inside this checkout, including in a
        # desktop sandbox whose redirected system temp directory is read-only.
        self.temporary = tempfile.TemporaryDirectory(prefix="finance-test-", dir=Path(__file__).resolve().parent)
        self.addCleanup(self.temporary.cleanup)
        self.parent = Path(self.temporary.name)
        self.root = self.parent / "owned-finance"
        self.store = Store(self.root)

    def approve(self, kind, data):
        proposal = self.store.propose(kind, data)
        self.assertTrue(proposal["valid"], proposal["questions"])
        return self.store.approve(proposal["id"], proposal["base_revision"])

    def test_empty_and_drafts_are_lazy_and_not_saved(self):
        self.assertFalse(self.root.exists())
        state = self.store.state()
        self.assertEqual(state["revision"], 0)
        self.assertEqual(state["transactions"], [])
        self.assertEqual(state["setup"]["currency"], "USD")
        proposal = self.store.propose("transaction", {"description": "Incomplete model output"})
        self.assertFalse(proposal["valid"])
        self.assertTrue(proposal["questions"])
        self.assertFalse(self.root.exists())
        with self.assertRaises(FinanceError):
            self.store.approve(proposal["id"], 0)
        self.assertFalse(self.root.exists())

    def test_exact_money_and_flow_separation(self):
        self.approve("transactions", [
            row("0.10", classification="income", description="Pay one"),
            row("0.20", classification="income", description="Pay two"),
            row("-0.07"), row("-80", classification="transfer", description="Transfer"),
            row("100", classification="loan", description="Loan"),
            row("0.03", classification="refund", description="Refund"),
            row("-1.00", classification="unclassified", description="Unknown"),
        ])
        result = self.store.overview()
        self.assertEqual(result["totals"], {"income": "0.30", "expenses": "0.07",
                         "net_income_expenses": "0.23", "transfers": "-80.00", "loans": "100.00",
                         "refunds": "0.03", "unclassified": "-1.00", "net_cash_flow": "19.26"})
        self.assertIsNone(result["accounts"][0]["balance"])
        self.assertTrue(result["unknowns"]["net_worth"])
        self.assertEqual(result["review"]["unclassified_count"], 1)

    def test_invalid_values_remain_reviewable_and_cannot_be_approved(self):
        invalid = [
            row(-12.34), row(True), row("-1.001"), row("NaN"), row("-1e2"), row("-01.00"),
            row("-$1.00"), row("-1,000.00"), row("-1000000000000.00"),
            row("2.00"), row("-2.00", classification="income"), row(date="2026-02-30"),
            row(date="2026-1-12"), row(date="1899-12-31"), row(classification="invented"),
            row(extra_field="not supported"), row(account=""), row(description="bad\x00text"),
        ]
        for value in invalid:
            with self.subTest(value=value):
                proposal = self.store.propose("transaction", value)
                self.assertFalse(proposal["valid"])
                self.assertTrue(proposal["questions"])
                with self.assertRaises(FinanceError):
                    self.store.approve(proposal["id"], 0)
                self.store.reject(proposal["id"])
        self.assertEqual(self.store.state()["revision"], 0)
        self.assertFalse(self.root.exists())

    def test_batch_with_one_bad_row_is_not_partially_saved(self):
        proposal = self.store.propose("transactions", [row(), {"description": "Unknown amount and date"}])
        self.assertIn("Row 2:", proposal["questions"][0])
        self.assertEqual(len(proposal["data"]), 2)
        with self.assertRaises(FinanceError):
            self.store.approve(proposal["id"], 0)
        self.assertEqual(self.store.state()["transactions"], [])

    def test_unknown_classification_is_separate_and_not_inferred(self):
        value = row("-9.10")
        del value["classification"]
        state = self.approve("transaction", value)
        self.assertEqual(state["transactions"][0]["classification"], "unclassified")
        self.assertEqual(self.store.overview()["totals"]["unclassified"], "-9.10")
        self.assertEqual(self.store.overview()["totals"]["expenses"], "0.00")

    def test_duplicate_acknowledgement_and_canonical_signature(self):
        self.approve("transaction", row())
        duplicate = row("-12.340".removesuffix("0"), account="fictional checking",
                        description=" FICTIONAL   GROCERIES ")
        proposal = self.store.propose("transaction", duplicate)
        self.assertEqual(proposal["duplicate_count"], 1)
        self.assertTrue(proposal["warnings"])
        with self.assertRaises(FinanceError):
            self.store.approve(proposal["id"], 1)
        with self.assertRaises(FinanceError):
            self.store.approve(proposal["id"], 1, allow_duplicates="true")
        self.store.approve(proposal["id"], 1, allow_duplicates=True)
        self.assertEqual(self.store.overview()["review"]["duplicate_count"], 2)

    def test_duplicates_within_one_import_need_acknowledgement(self):
        proposal = self.store.propose("transactions", [row(), row()])
        self.assertEqual(proposal["duplicate_count"], 1)
        with self.assertRaises(FinanceError):
            self.store.approve(proposal["id"], 0)
        state = self.store.approve(proposal["id"], 0, allow_duplicates=True)
        self.assertEqual(len(state["transactions"]), 2)

    def test_returned_data_cannot_mutate_drafts_or_state(self):
        proposal = self.store.propose("transaction", row())
        proposal["data"]["amount"] = "-999.00"
        self.store.pending()[0]["data"]["description"] = "mutated"
        saved = self.store.approve(proposal["id"], 0)
        self.assertEqual(saved["transactions"][0]["amount"], "-12.34")
        saved["transactions"].clear()
        self.store.export_state()["setup"]["goals"] = "mutated"
        self.assertEqual(len(self.store.state()["transactions"]), 1)
        self.assertEqual(self.store.state()["setup"]["goals"], "")

    def test_stale_approval_and_double_approval_are_refused(self):
        first = self.store.propose("transaction", row())
        second = self.store.propose("transaction", row(description="Second"))
        self.store.approve(first["id"], 0)
        with self.assertRaisesRegex(FinanceError, "stale"):
            self.store.approve(second["id"], 0)
        with self.assertRaisesRegex(FinanceError, "stale"):
            self.store.approve(second["id"], 1)
        with self.assertRaises(FinanceError):
            self.store.approve(first["id"], 1)
        self.assertEqual(len(self.store.state()["transactions"]), 1)

    def test_concurrent_instances_allow_only_one_approval_at_revision(self):
        other = Store(self.root)
        first = self.store.propose("transaction", row(description="First"))
        second = other.propose("transaction", row(description="Second"))
        barrier = threading.Barrier(2)

        def approve_in_thread(store, proposal):
            barrier.wait(timeout=5)
            try:
                store.approve(proposal["id"], 0)
                return "approved"
            except FinanceError as error:
                return str(error)

        with ThreadPoolExecutor(max_workers=2) as pool:
            tasks = [pool.submit(approve_in_thread, self.store, first),
                     pool.submit(approve_in_thread, other, second)]
            outcomes = [future.result(timeout=10) for future in tasks]
        self.assertEqual(outcomes.count("approved"), 1)
        self.assertEqual(sum("stale" in outcome for outcome in outcomes), 1)
        self.assertEqual(self.store.state()["revision"], 1)
        self.assertEqual(len(self.store.state()["transactions"]), 1)

    def test_reopen_persists_approved_data_and_prior_revision_bytes(self):
        sibling = self.parent / "original-source.bin"
        original = b"Untouched fictional source\r\n\x00\xff"
        sibling.write_bytes(original)
        self.approve("transaction", row())
        previous = {path: path.read_bytes() for path in (self.root / "revisions").glob("*.json")}
        self.approve("transaction", row("-1.00", description="Second"))
        reopened = Store(self.root)
        self.assertEqual(reopened.export_state(), self.store.state())
        self.assertEqual(reopened.state()["revision"], 2)
        for path, content in previous.items():
            self.assertEqual(path.read_bytes(), content)
        self.assertEqual(sibling.read_bytes(), original)

    def test_budget_variance_uses_its_own_period_and_expenses_only(self):
        self.approve("transactions", [row("-40.00"), row("-70.00", date="2026-02-12"),
                                       row("-20.00", classification="transfer", description="Transfer"),
                                       row("5.00", classification="refund", description="Refund")])
        self.approve("budget", {"category": "groceries", "amount": "50.00",
                                "start_date": "2026-01-01", "end_date": "2026-01-31"})
        january = self.store.overview("2026-01-01", "2026-01-31")
        self.assertEqual(january["budgets"][0]["actual"], "40.00")
        self.assertEqual(january["budgets"][0]["remaining"], "10.00")
        self.assertEqual(january["budgets"][0]["variance"], "-10.00")
        self.assertEqual(january["budgets"][0]["status"], "active")
        february = self.store.overview("2026-02-01", "2026-02-28")
        self.assertEqual(february["totals"]["expenses"], "70.00")
        self.assertEqual(february["budgets"][0]["actual"], "40.00")
        self.assertEqual(february["budgets"][0]["status"], "other_period")

    def test_unknown_budget_and_debt_values_remain_null(self):
        self.approve("budget", {"category": "Travel"})
        self.approve("debt", {"label": "Fictional debt"})
        self.approve("transaction", row("800.00", classification="loan", description="Proceeds"))
        overview = self.store.overview()
        self.assertIsNone(overview["budgets"][0]["actual"])
        self.assertIsNone(overview["budgets"][0]["variance"])
        self.assertEqual(overview["budgets"][0]["status"], "unknown")
        self.assertIsNone(overview["debts"][0]["balance"])
        self.assertIsNone(overview["debts"][0]["as_of"])
        self.assertEqual(overview["unknowns"]["debt_balances"], 1)

    def test_debt_balance_requires_as_of_date_and_retains_source(self):
        bad = self.store.propose("debt", {"label": "Fictional loan", "balance": "100.00"})
        self.assertFalse(bad["valid"])
        self.assertIn("as-of", bad["questions"][0])
        state = self.approve("debt", {"label": "Fictional loan", "balance": "100.00",
                                     "as_of": "2026-01-31", "minimum_payment": "20.00",
                                     "due_date": None, "source": "Manual fictional report"})
        self.assertEqual(state["debts"][0]["source"], "Manual fictional report")
        self.assertIsNone(state["debts"][0]["due_date"])
        old_id = state["debts"][0]["id"]
        state = self.approve("debt", {"label": "fictional LOAN", "balance": "80.00", "as_of": "2026-02-28"})
        self.assertEqual(len(state["debts"]), 1)
        self.assertEqual(state["debts"][0]["id"], old_id)
        self.assertEqual(state["debts"][0]["balance"], "80.00")

    def test_setup_defaults_scope_and_reversed_dates(self):
        self.approve("transactions", [row(), row(date="2026-02-12")])
        self.approve("setup", {"goals": "Track fictional spending", "start_date": "2026-01-01", "end_date": "2026-01-31"})
        self.assertEqual(self.store.overview()["transaction_count"], 1)
        self.approve("setup", {"goals": "Updated fictional goal"})
        self.assertEqual(self.store.state()["setup"]["start_date"], "2026-01-01")
        proposal = self.store.propose("setup", {"start_date": "2026-02-01"})
        self.assertFalse(proposal["valid"])
        with self.assertRaises(FinanceError):
            self.store.overview("2026-03-01", "2026-01-31")

    def test_deletion_is_reviewed_and_preserves_immutable_history(self):
        state = self.approve("transaction", row())
        identifier = state["transactions"][0]["id"]
        previous = {path: path.read_bytes() for path in (self.root / "revisions").glob("*.json")}
        proposal = self.store.propose("delete_transaction", {"id": identifier})
        self.assertEqual(proposal["before"], state["transactions"][0])
        self.assertEqual(len(self.store.state()["transactions"]), 1)
        self.store.approve(proposal["id"], 1)
        self.assertEqual(self.store.state()["transactions"], [])
        for path, data in previous.items():
            self.assertEqual(path.read_bytes(), data)

    def test_atomic_pointer_failure_preserves_last_approved_state(self):
        self.approve("transaction", row())
        original_pointer = (self.root / "current.json").read_bytes()
        proposal = self.store.propose("transaction", row(description="New"))
        with mock.patch("app.finance_core.os.replace", side_effect=OSError("Fictional failure")):
            with self.assertRaises(FinanceError):
                self.store.approve(proposal["id"], 1)
        self.assertEqual((self.root / "current.json").read_bytes(), original_pointer)
        self.assertEqual(self.store.state()["revision"], 1)
        self.assertTrue(any(p["id"] == proposal["id"] for p in self.store.pending()))
        self.store.approve(proposal["id"], 1)
        self.assertEqual(self.store.state()["revision"], 2)

    def test_pointer_cannot_reference_an_external_file(self):
        self.root.mkdir()
        external = self.parent / "external.json"
        original = b'{"private":"fictional sentinel"}'
        external.write_bytes(original)
        (self.root / "current.json").write_text(json.dumps({"schema_version": 1, "revision": 1,
                                                          "file": "../../external.json"}), encoding="utf-8")
        with self.assertRaises(FinanceError):
            self.store.state()
        self.assertEqual(external.read_bytes(), original)

    def test_reopen_revalidates_saved_record_fields(self):
        self.approve("transaction", row())
        pointer = json.loads((self.root / "current.json").read_text(encoding="utf-8"))
        revision_path = self.root / "revisions" / pointer["file"]
        modified = json.loads(revision_path.read_text(encoding="utf-8"))
        modified["transactions"][0]["amount"] = "-1.001"
        revision_path.write_text(json.dumps(modified), encoding="utf-8")
        with self.assertRaises(FinanceError):
            Store(self.root).state()

    def test_demo_is_fictional_and_requires_explicit_approval(self):
        proposal = self.store.demo()
        self.assertEqual(proposal["kind"], "transactions")
        self.assertTrue(all("Fictional" in value["description"] for value in proposal["data"]))
        self.assertFalse(self.root.exists())
        self.assertEqual(self.store.state()["transactions"], [])
        self.store.reject(proposal["id"])
        self.assertFalse(self.root.exists())
        self.assertEqual(self.store.pending(), [])
        with self.assertRaises(FinanceError):
            self.store.approve(proposal["id"], 0)

    def test_transaction_update_preserves_id_and_prior_revision(self):
        original = self.approve("transaction", row())["transactions"][0]
        history = {p: p.read_bytes() for p in (self.root / "revisions").glob("*.json")}
        edited = dict(original, amount="-18.25", category="Food")
        proposal = self.store.propose("transaction", edited)
        self.assertTrue(proposal["valid"])
        self.assertEqual(proposal["before"], original)
        self.assertEqual(self.store.state()["transactions"][0], original)
        state = self.store.approve(proposal["id"], proposal["base_revision"])
        self.assertEqual(state["transactions"], [edited])
        self.assertEqual(state["transactions"][0]["id"], original["id"])
        for path, content in history.items():
            self.assertEqual(path.read_bytes(), content)

    def test_update_excludes_own_signature_but_checks_other_transactions(self):
        state = self.approve("transactions", [row(), row(description="Another purchase")])
        first, second = state["transactions"]
        unchanged = self.store.propose("transaction", dict(first))
        self.assertEqual(unchanged["duplicate_count"], 0)
        self.store.reject(unchanged["id"])
        duplicate = self.store.propose("transaction", dict(second, id=first["id"]))
        self.assertEqual(duplicate["duplicate_count"], 1)
        with self.assertRaises(FinanceError):
            self.store.approve(duplicate["id"], 1)
        state = self.store.approve(duplicate["id"], 1, allow_duplicates=True)
        self.assertEqual(len(state["transactions"]), 2)
        self.assertEqual(state["transactions"][0]["id"], first["id"])

    def test_unknown_update_id_and_stale_update_cannot_modify_state(self):
        original = self.approve("transaction", row())["transactions"][0]
        unknown = self.store.propose("transaction", row(id="0" * 32))
        self.assertFalse(unknown["valid"])
        with self.assertRaises(FinanceError):
            self.store.approve(unknown["id"], 1)
        update = self.store.propose("transaction", dict(original, amount="-40.00"))
        self.approve("setup", {"goals": "A concurrent reviewed change"})
        with self.assertRaisesRegex(FinanceError, "stale"):
            self.store.approve(update["id"], 1)
        self.assertEqual(self.store.state()["transactions"][0], original)

    def test_batch_imports_cannot_silently_update_existing_transactions(self):
        original = self.approve("transaction", row())["transactions"][0]
        proposal = self.store.propose("transactions", [dict(original, amount="-20.00")])
        self.assertFalse(proposal["valid"])
        with self.assertRaises(FinanceError):
            self.store.approve(proposal["id"], 1)
        self.assertEqual(self.store.state()["transactions"][0], original)

    def test_annotations_survive_snapshot_and_questions_block_approval(self):
        proposal = self.store.propose("transaction", row())
        annotated = self.store.annotate(proposal["id"], warnings=["Verify the quoted source."],
                                        questions=["Which account paid this amount?"])
        self.assertFalse(annotated["valid"])
        self.assertEqual(annotated, self.store.pending()[0])
        annotated["questions"].clear()
        self.assertTrue(self.store.pending()[0]["questions"])
        with self.assertRaisesRegex(FinanceError, "review questions"):
            self.store.approve(proposal["id"], 0)
        self.assertFalse(self.root.exists())
        self.store.annotate(proposal["id"], warnings=[], questions=[])
        self.assertTrue(self.store.pending()[0]["questions"])
        self.store.reject(proposal["id"])
        corrected = self.store.propose("transaction", row(account="Explicitly confirmed fictional checking"))
        self.store.approve(corrected["id"], 0)
        self.assertEqual(self.store.state()["revision"], 1)

    def test_warning_only_annotations_do_not_block_approval(self):
        proposal = self.store.propose("transaction", row())
        annotated = self.store.annotate(proposal["id"], warnings=["Review this fictional source."])
        self.assertTrue(annotated["valid"])
        self.assertEqual(self.store.pending()[0]["warnings"], annotated["warnings"])
        self.store.approve(proposal["id"], 0)

    def test_invalid_annotations_are_atomic(self):
        proposal = self.store.propose("transaction", row())
        with self.assertRaises(FinanceError):
            self.store.annotate(proposal["id"], warnings=["Valid text"], questions=[None])
        self.assertEqual(self.store.pending()[0], proposal)


if __name__ == "__main__":
    unittest.main()
