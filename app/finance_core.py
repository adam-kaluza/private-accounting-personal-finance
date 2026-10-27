"""Explicitly approved local personal-finance records, using only the stdlib.

Provenance: exact-decimal validation, date/sign checks, duplicate signatures and
immutable-revision patterns were adapted from the explicitly permitted pure
finance.py and ledger.py modules of private_accounting_v2. This module does not
import those modules, read their workspace, or discover any external data.

Construction is lazy. Proposals exist only in memory; only approve() writes an
approved revision. Historical revision bytes are never modified. Computed cash
activity is not an account balance, a debt balance, or a net-worth estimate.
"""
from __future__ import annotations

import copy
from datetime import date
from decimal import Decimal
import json
import os
from pathlib import Path
import re
import stat
import threading
import uuid


class FinanceError(ValueError):
    """Validation/storage failure with a fixed message and no sensitive paths."""


CLASSIFICATIONS = ("income", "expense", "transfer", "loan", "refund", "unclassified")
DEFAULT_SETUP = {"goals": "", "start_date": None, "end_date": None, "currency": "USD"}
MAX_TRANSACTIONS = 50000
MAX_BATCH = 10000
MAX_PLANS = 10000
MAX_PENDING = 200
MAX_JSON_BYTES = 32 * 1024 * 1024
MAX_JSON_DEPTH = 32
_AMOUNT = re.compile(r"[+-]?(?:0|[1-9][0-9]*)(?:\.[0-9]{1,2})?\Z")
_REVISION = re.compile(r"rev-[0-9]{8}-[0-9a-f]{32}\.json\Z")
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f\ud800-\udfff\ufffe\uffff]")
_KINDS = {"transaction", "transactions", "setup", "budget", "debt", "delete_transaction"}
_REGISTRY_LOCK = threading.RLock()
_REGISTRY: dict[str, tuple[threading.RLock, dict]] = {}


def _require(condition, message="The financial record is invalid."):
    if not condition:
        raise FinanceError(message)


def _text(value, limit=1000, required=False):
    _require(type(value) is str, "Enter text for this field.")
    value = value.strip()
    _require(len(value) <= limit and not _CONTROL.search(value),
             "Text is too long or contains unsupported characters.")
    _require(not required or bool(value), "A required text field is missing.")
    return value


def _date(value, optional=False):
    if value is None and optional:
        return None
    _require(type(value) is str and bool(re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value)),
             "Enter an explicit date in YYYY-MM-DD format; unknown optional dates must be null.")
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        raise FinanceError("The calendar date is invalid.") from None
    _require(1900 <= parsed.year <= 2200, "The date is outside the supported range.")
    return value


def _money(value, optional=False, signed=True):
    if value is None and optional:
        return None
    if type(value) is int:
        value = str(value)
    _require(type(value) is str, "Enter an exact decimal amount; floating-point amounts are not accepted.")
    value = value.strip()
    _require(len(value) <= 18 and bool(_AMOUNT.fullmatch(value)),
             "Use a plain decimal amount with at most two decimal places.")
    amount = Decimal(value)
    _require(abs(amount) <= Decimal("999999999999.99") and (signed or amount >= 0),
             "The amount is outside the supported range; budgets and debt amounts must be nonnegative.")
    return format(Decimal(0) if amount == 0 else amount, ".2f")


def _period(start, end):
    start, end = _date(start, True), _date(end, True)
    _require(not (start and end) or start <= end, "The period must start on or before its end date.")
    return start, end


def _fields(raw, allowed, required=()):
    _require(type(raw) is dict and set(raw) <= set(allowed), "Choose only supported fields for this record.")
    for field in required:
        _require(field in raw, "A required field is missing: " + field + ".")


def _transaction(raw):
    _fields(raw, ("date", "description", "amount", "account", "classification", "category", "source"),
            ("date", "description", "amount", "account"))
    result = {"date": _date(raw["date"]), "description": _text(raw["description"], 1000, True),
              "amount": _money(raw["amount"]), "account": _text(raw["account"], 120, True),
              "classification": raw.get("classification", "unclassified"),
              "category": _text(raw.get("category", "Uncategorized"), 160, True),
              "source": _text(raw.get("source", ""), 1200)}
    _require(result["classification"] in CLASSIFICATIONS, "Choose a supported transaction classification.")
    amount = Decimal(result["amount"])
    _require(result["classification"] != "income" or amount >= 0, "Income amounts must be nonnegative.")
    _require(result["classification"] != "expense" or amount <= 0, "Expense amounts must be nonpositive.")
    return result


def _setup(raw, previous=None):
    _fields(raw, DEFAULT_SETUP)
    result = copy.deepcopy(DEFAULT_SETUP if previous is None else previous)
    result.update(raw)
    result["goals"] = _text(result["goals"], 4000)
    result["start_date"], result["end_date"] = _period(result["start_date"], result["end_date"])
    _require(result["currency"] == "USD", "This release supports USD records only.")
    return result


def _budget(raw):
    _fields(raw, ("category", "amount", "start_date", "end_date"), ("category",))
    start, end = _period(raw.get("start_date"), raw.get("end_date"))
    return {"category": _text(raw["category"], 160, True),
            "amount": _money(raw.get("amount"), optional=True, signed=False),
            "start_date": start, "end_date": end}


def _debt(raw):
    _fields(raw, ("label", "balance", "as_of", "minimum_payment", "due_date", "source"), ("label",))
    result = {"label": _text(raw["label"], 160, True),
              "balance": _money(raw.get("balance"), optional=True, signed=False),
              "as_of": _date(raw.get("as_of"), True),
              "minimum_payment": _money(raw.get("minimum_payment"), optional=True, signed=False),
              "due_date": _date(raw.get("due_date"), True), "source": _text(raw.get("source", ""), 1200)}
    _require(result["balance"] is None or result["as_of"] is not None,
             "A reported debt balance needs an explicit as-of date.")
    return result


def _valid_id(value):
    _require(type(value) is str and bool(re.fullmatch(r"[0-9a-f]{32}", value)), "The record identifier is invalid.")
    return value


def _signature(row):
    return (row["date"], row["amount"], row["account"].casefold(),
            " ".join(row["description"].casefold().split()))


def _empty():
    return {"schema_version": 1, "revision": 0, "transactions": [], "budgets": [], "debts": [],
            "setup": copy.deepcopy(DEFAULT_SETUP), "documents": []}


def _local(path):
    _require(not str(path).startswith(("\\\\", "//")), "Only local filesystem roots are supported.")
    for component in (path, *path.parents):
        try:
            info = component.lstat()
        except FileNotFoundError:
            continue
        _require(not stat.S_ISLNK(info.st_mode) and not (getattr(info, "st_file_attributes", 0) & 0x400),
                 "Linked or redirected filesystem paths are not supported.")
        _require(not stat.S_ISREG(info.st_mode) or info.st_nlink == 1,
                 "Hard-linked storage files are not supported.")


def _json_object(pairs):
    result = {}
    for key, value in pairs:
        _require(key not in result, "Duplicate JSON fields are not supported.")
        result[key] = value
    return result


def _bad_constant(_):
    raise FinanceError("Nonfinite JSON numbers are not supported.")


def _read(path):
    _local(path)
    with path.open("rb") as stream:
        content = stream.read(MAX_JSON_BYTES + 1)
    _require(len(content) <= MAX_JSON_BYTES, "Saved records exceed the supported size.")
    value = json.loads(content.decode("utf-8"), object_pairs_hook=_json_object, parse_constant=_bad_constant)
    _require(type(value) is dict)
    return value


def _encoded(value):
    # Bound nesting before deepcopy or JSON encoding can recurse through an
    # arbitrary proposal. This also terminates cyclic container input safely.
    pending = [(value, 0)]
    while pending:
        item, depth = pending.pop()
        _require(depth <= MAX_JSON_DEPTH, "The record exceeds the supported JSON nesting depth.")
        if isinstance(item, dict):
            pending.extend((child, depth + 1) for child in item.values() if isinstance(child, (dict, list, tuple)))
        elif isinstance(item, (list, tuple)):
            pending.extend((child, depth + 1) for child in item if isinstance(child, (dict, list, tuple)))
    try:
        data = json.dumps(value, ensure_ascii=True, allow_nan=False, separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError, RecursionError):
        raise FinanceError("The proposal must contain ordinary finite JSON values.") from None
    _require(len(data) <= MAX_JSON_BYTES, "The record exceeds the supported size.")
    return data


def _validate_state(value):
    _require(type(value) is dict and set(value) == set(_empty()) and type(value["schema_version"]) is int
             and value["schema_version"] == 1 and type(value["revision"]) is int
             and 1 <= value["revision"] <= 99999999)
    _require(value["setup"] == _setup(value["setup"]) and set(value["setup"]) == set(DEFAULT_SETUP))
    # Document ownership/indexing is maintained by the import service, not inferred from finance rows.
    _require(value["documents"] == [], "Unsupported document records in saved finance state.")
    seen_ids = set()
    for collection, validator, limit in (("transactions", _transaction, MAX_TRANSACTIONS),
                                         ("budgets", _budget, MAX_PLANS), ("debts", _debt, MAX_PLANS)):
        rows = value[collection]
        _require(type(rows) is list and len(rows) <= limit)
        keys = set()
        for row in rows:
            _require(type(row) is dict and "id" in row)
            identifier = _valid_id(row["id"])
            _require(identifier not in seen_ids)
            seen_ids.add(identifier)
            raw = {k: v for k, v in row.items() if k != "id"}
            _require(validator(raw) == raw, "Saved record fields are not canonical.")
            if collection == "budgets":
                key = (row["category"].casefold(), row["start_date"], row["end_date"])
            elif collection == "debts":
                key = row["label"].casefold()
            else:
                continue
            _require(key not in keys, "Saved planning records contain duplicate keys.")
            keys.add(key)


class Store:
    """A single-process store; the loopback server must own one process per root.

    Every instance referring to the same lexical root shares a reentrant lock and
    proposal registry. The approval token is the approved revision number. A
    different approved revision requires a fresh proposal and a fresh review.
    """

    def __init__(self, root):
        self.root = Path(os.path.abspath(os.fspath(root)))
        key = os.path.normcase(str(self.root))
        with _REGISTRY_LOCK:
            self._lock, self._pending = _REGISTRY.setdefault(key, (threading.RLock(), {}))

    def _load(self):
        try:
            _local(self.root)
            pointer_path = self.root / "current.json"
            _local(pointer_path)
            if not pointer_path.exists():
                return _empty()
            pointer = _read(pointer_path)
            _require(set(pointer) == {"schema_version", "revision", "file"}
                     and type(pointer["schema_version"]) is int and pointer["schema_version"] == 1
                     and type(pointer["revision"]) is int and 1 <= pointer["revision"] <= 99999999
                     and type(pointer["file"]) is str and bool(_REVISION.fullmatch(pointer["file"])))
            result = _read(self.root / "revisions" / pointer["file"])
            _validate_state(result)
            _require(result["revision"] == pointer["revision"], "The saved revision pointer is inconsistent.")
            return result
        except FinanceError:
            raise
        except Exception:
            raise FinanceError("Saved finance records could not be loaded safely.") from None

    def state(self):
        with self._lock:
            return copy.deepcopy(self._load())

    def export_state(self):
        """Return approved records only; caller chooses how to save the export."""
        return self.state()

    def pending(self):
        with self._lock:
            return copy.deepcopy(list(self._pending.values()))

    def _prepare(self, kind, raw, state):
        warnings, questions, before = [], [], None
        data = copy.deepcopy(raw)
        if kind == "transactions":
            _require(type(raw) is list and 1 <= len(raw) <= MAX_BATCH,
                     "Supply a nonempty transaction list within the batch limit.")
            data = []
            for index, row in enumerate(raw, 1):
                try:
                    data.append(_transaction(row))
                except FinanceError as exc:
                    questions.append("Row " + str(index) + ": " + str(exc))
                    data.append(copy.deepcopy(row))
        else:
            try:
                if kind == "transaction":
                    _require(type(raw) is dict, "Supply a transaction object.")
                    if "id" in raw:
                        identifier = _valid_id(raw["id"])
                        before = next((r for r in state["transactions"] if r["id"] == identifier), None)
                        _require(before is not None, "The transaction to update was not found.")
                        data = dict(_transaction({k: v for k, v in raw.items() if k != "id"}), id=identifier)
                        warnings.append("Approval replaces this transaction; its identifier and prior revisions are preserved.")
                    else:
                        data = _transaction(raw)
                elif kind == "setup":
                    data, before = _setup(raw, state["setup"]), state["setup"]
                elif kind == "budget":
                    data = _budget(raw)
                    before = next((r for r in state["budgets"] if r["category"].casefold() == data["category"].casefold()
                                   and r["start_date"] == data["start_date"] and r["end_date"] == data["end_date"]), None)
                    if data["amount"] is None or not data["start_date"] or not data["end_date"]:
                        warnings.append("The budget amount or complete period is unknown; variance will remain unknown.")
                elif kind == "debt":
                    data = _debt(raw)
                    before = next((r for r in state["debts"] if r["label"].casefold() == data["label"].casefold()), None)
                    if data["balance"] is None:
                        warnings.append("The debt balance is unknown; no balance will be inferred from transactions.")
                elif kind == "delete_transaction":
                    _fields(raw, ("id",), ("id",))
                    _valid_id(raw["id"])
                    before = next((r for r in state["transactions"] if r["id"] == raw["id"]), None)
                    _require(before is not None, "The transaction to delete was not found.")
                    warnings.append("Approval removes this transaction from the current state; prior revisions remain intact.")
            except FinanceError as exc:
                questions.append(str(exc))
        duplicate_count = 0
        if not questions and kind in ("transaction", "transactions"):
            rows = [data] if kind == "transaction" else data
            replaced_id = before["id"] if kind == "transaction" and before is not None else None
            _require(len(state["transactions"]) + len(rows) - bool(replaced_id) <= MAX_TRANSACTIONS,
                     "The transaction limit was reached.")
            seen = {_signature(row) for row in state["transactions"] if row["id"] != replaced_id}
            for row in rows:
                signature = _signature(row)
                if signature in seen:
                    duplicate_count += 1
                seen.add(signature)
            if duplicate_count:
                warnings.append("Possible duplicate transactions need explicit duplicate acknowledgement before approval.")
            if any(row["classification"] == "unclassified" for row in rows):
                warnings.append("Unclassified transactions remain separate from income and expenses.")
        if before is not None and kind in ("budget", "debt"):
            warnings.append("Approval replaces the matching planning record in the current state; prior revisions remain intact.")
        return data, warnings, questions, copy.deepcopy(before), duplicate_count

    def propose(self, kind, data):
        _require(type(kind) is str and kind in _KINDS, "Choose a supported proposal kind.")
        _encoded(data)
        with self._lock:
            _require(len(self._pending) < MAX_PENDING, "Reject unused proposals before creating more.")
            state = self._load()
            normalized, warnings, questions, before, duplicates = self._prepare(kind, data, state)
            result = {"id": uuid.uuid4().hex, "kind": kind, "base_revision": state["revision"],
                      "data": normalized, "warnings": warnings, "questions": questions,
                      "valid": not questions, "duplicate_count": duplicates, "before": before}
            self._pending[result["id"]] = copy.deepcopy(result)
            return copy.deepcopy(result)

    def reject(self, identifier):
        with self._lock:
            _valid_id(identifier)
            _require(identifier in self._pending, "The proposal was not found or has already been resolved.")
            del self._pending[identifier]
            return {"id": identifier, "status": "rejected"}

    def annotate(self, identifier, warnings=(), questions=()):
        """Attach review context to the real pending proposal, never to disk.

        Questions prevent approval. Resolve them by creating and reviewing a
        fresh edited proposal; callers cannot silently clear existing questions.
        """
        _valid_id(identifier)
        additions = {}
        for field, values in (("warnings", warnings), ("questions", questions)):
            _require(type(values) in (list, tuple) and len(values) <= 100,
                     "Supply at most 100 review messages of each type.")
            additions[field] = [_text(value, 2000, True) for value in values]
        with self._lock:
            _require(identifier in self._pending, "The proposal was not found or has already been resolved.")
            proposal = self._pending[identifier]
            updated = copy.deepcopy(proposal)
            for field, values in additions.items():
                updated[field] = list(dict.fromkeys(updated[field] + values))
                _require(len(updated[field]) <= 200, "The proposal already has too many review messages.")
            updated["valid"] = not updated["questions"]
            self._pending[identifier] = updated
            return copy.deepcopy(updated)

    def _save(self, state):
        _validate_state(state)
        encoded = _encoded(state)
        temporary = None
        try:
            _local(self.root)
            self.root.mkdir(parents=True, exist_ok=True)
            directory = self.root / "revisions"
            _local(directory)
            directory.mkdir(exist_ok=True)
            name = "rev-" + str(state["revision"]).zfill(8) + "-" + uuid.uuid4().hex + ".json"
            revision_path = directory / name
            _local(revision_path)
            with revision_path.open("xb") as stream:
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            pointer = {"schema_version": 1, "revision": state["revision"], "file": name}
            temporary = self.root / (".pointer-" + uuid.uuid4().hex + ".tmp")
            _local(temporary)
            with temporary.open("xb") as stream:
                stream.write(_encoded(pointer))
                stream.flush()
                os.fsync(stream.fileno())
            _local(self.root / "current.json")
            os.replace(temporary, self.root / "current.json")
            temporary = None
        except FinanceError:
            raise
        except OSError:
            raise FinanceError("The approved revision could not be saved; check the local storage location.") from None
        finally:
            if temporary is not None:
                try:
                    _local(temporary)
                    temporary.unlink(missing_ok=True)
                except (OSError, FinanceError):
                    pass

    def approve(self, identifier, revision, allow_duplicates=False):
        _valid_id(identifier)
        _require(type(revision) is int and revision >= 0, "Supply the reviewed revision number.")
        _require(type(allow_duplicates) is bool, "Duplicate acknowledgement must be true or false.")
        with self._lock:
            proposal = self._pending.get(identifier)
            _require(proposal is not None, "The proposal was not found or has already been resolved.")
            state = self._load()
            _require(revision == state["revision"] == proposal["base_revision"],
                     "This proposal is stale. Create and review a fresh proposal before approval.")
            _require(not proposal["questions"],
                     "The proposal has unresolved review questions. Edit it and create a fresh proposal.")
            data, _, questions, before, duplicates = self._prepare(proposal["kind"], proposal["data"], state)
            _require(not questions, "The proposal has unresolved validation questions. Edit it and create a fresh proposal.")
            _require(not duplicates or allow_duplicates, "Explicitly acknowledge possible duplicates before approval.")
            kind = proposal["kind"]
            if kind in ("transaction", "transactions"):
                rows = [data] if kind == "transaction" else data
                if kind == "transaction" and before is not None:
                    state["transactions"][state["transactions"].index(before)] = dict(data)
                else:
                    state["transactions"].extend(dict(row, id=uuid.uuid4().hex) for row in rows)
            elif kind == "setup":
                state["setup"] = data
            elif kind in ("budget", "debt"):
                collection = state["budgets" if kind == "budget" else "debts"]
                _require(before is not None or len(collection) < MAX_PLANS, "The planning record limit was reached.")
                record = dict(data, id=before["id"] if before else uuid.uuid4().hex)
                if before is None:
                    collection.append(record)
                else:
                    collection[collection.index(before)] = record
            elif kind == "delete_transaction":
                state["transactions"] = [r for r in state["transactions"] if r["id"] != data["id"]]
            state["revision"] += 1
            _require(state["revision"] <= 99999999, "The revision limit was reached.")
            self._save(state)
            del self._pending[identifier]
            return copy.deepcopy(state)

    def demo(self):
        """Prepare clearly fictional examples without writing approved records."""
        sample = [
            ("2026-01-02", "Fictional monthly pay", "3200.00", "income", "Pay"),
            ("2026-01-03", "Fictional rent", "-1100.00", "expense", "Housing"),
            ("2026-01-05", "Fictional grocery trip", "-78.35", "expense", "Groceries"),
            ("2026-01-07", "Fictional savings transfer", "-250.00", "transfer", "Savings"),
            ("2026-01-08", "Fictional returned purchase", "24.00", "refund", "Shopping"),
            ("2026-01-10", "Fictional loan proceeds", "500.00", "loan", "Loan"),
            ("2026-01-11", "Fictional item needing review", "-12.00", "unclassified", "Uncategorized"),
        ]
        return self.propose("transactions", [
            {"date": day, "description": description, "amount": amount, "account": "Fictional checking",
             "classification": kind, "category": category, "source": "Fictional demo; not real financial records"}
            for day, description, amount, kind, category in sample])

    def overview(self, start="", end=""):
        with self._lock:
            state = self._load()
            start = state["setup"]["start_date"] if start in ("", None) else _date(start)
            end = state["setup"]["end_date"] if end in ("", None) else _date(end)
            start, end = _period(start, end)
            rows = [r for r in state["transactions"] if (not start or r["date"] >= start)
                    and (not end or r["date"] <= end)]
            total = {key: Decimal(0) for key in CLASSIFICATIONS}
            categories, accounts = {}, {}
            signatures = {}
            for row in rows:
                amount = Decimal(row["amount"])
                total[row["classification"]] += amount
                signature = _signature(row)
                signatures[signature] = signatures.get(signature, 0) + 1
                account = accounts.setdefault(row["account"], Decimal(0))
                accounts[row["account"]] = account + amount
                if row["classification"] in ("income", "expense"):
                    item = categories.setdefault(row["category"], {"income": Decimal(0), "expenses": Decimal(0)})
                    item["income" if row["classification"] == "income" else "expenses"] += (
                        amount if row["classification"] == "income" else -amount)
            f = lambda value: format(value, ".2f")
            budgets = []
            for budget in state["budgets"]:
                item = copy.deepcopy(budget)
                complete = budget["amount"] is not None and budget["start_date"] and budget["end_date"]
                item.update(actual=None, remaining=None, variance=None, status="unknown")
                if complete:
                    actual = -sum((Decimal(r["amount"]) for r in state["transactions"]
                                   if r["classification"] == "expense" and r["category"].casefold() == budget["category"].casefold()
                                   and budget["start_date"] <= r["date"] <= budget["end_date"]), Decimal(0))
                    amount = Decimal(budget["amount"])
                    item.update(actual=f(actual), remaining=f(amount - actual), variance=f(actual - amount),
                                status="active" if (start, end) == (budget["start_date"], budget["end_date"]) else "other_period")
                budgets.append(item)
            return {"revision": state["revision"], "start_date": start, "end_date": end,
                    "currency": state["setup"]["currency"], "transaction_count": len(rows),
                    "totals": {"income": f(total["income"]), "expenses": f(-total["expense"]),
                               "net_income_expenses": f(total["income"] + total["expense"]),
                               "transfers": f(total["transfer"]), "loans": f(total["loan"]),
                               "refunds": f(total["refund"]), "unclassified": f(total["unclassified"]),
                               "net_cash_flow": f(sum(total.values(), Decimal(0)))},
                    "categories": [{"category": category, **{key: f(value) for key, value in amounts.items()}}
                                   for category, amounts in sorted(categories.items())],
                    "accounts": [{"account": account, "net_cash_flow": f(amount), "balance": None}
                                 for account, amount in sorted(accounts.items())],
                    "budgets": budgets, "debts": copy.deepcopy(state["debts"]),
                    "unknowns": {"account_balances": True, "net_worth": True,
                                 "debt_balances": sum(r["balance"] is None for r in state["debts"])},
                    "review": {"unclassified_count": sum(r["classification"] == "unclassified" for r in rows),
                               "duplicate_count": sum(count for count in signatures.values() if count > 1)},
                    "warnings": ["Totals describe recorded transaction activity; opening balances and completeness are not known.",
                                 "Refunds, transfers, loans and unclassified records are separate from income and expenses."]}
