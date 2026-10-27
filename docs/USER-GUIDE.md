# Your first ten minutes

1. Start the app and choose a reporting period in Settings. Review and approve the setup proposal. Unknown dates can remain blank; an unrestricted dashboard then shows all recorded dates.
2. Try the fictional demo. Open Review and approve it only if you want demonstration entries in this new data folder. For a completely separate trial, extract a second fresh copy of the app before using the demo.
3. Open Transactions. Enter a fictional expense dated `2026-01-06`, description `Fictional groceries`, amount `-42.50`, account `Demo checking`, classification `expense`, category `Groceries`. Review before approval. No real account number is needed.
4. Open Plans & debts. Add a Groceries spending plan of `300.00` with explicit start/end dates. Budgets apply to their own dates. A debt balance needs its statement's as-of date. Blank debt balances stay unknown.
5. In Add information, choose `examples/fictional-transactions.csv`. Preview it; choose whether to preserve a copy. Preparing rows only creates a proposal. Fix any blank classification to a choice you can support, or use `unclassified` until you know more.
6. Check sources, signed amounts, dates and possible duplicates in Review. An invalid draft cannot be approved. Edit it into a new proposal. Approving one proposal changes the revision, so other older proposals must be reviewed again.
7. In Files & exports, export an XLSX snapshot. The exported workbook is a new file; imported workbooks and their formulas remain untouched. Summary figures are fixed snapshot values, not a spreadsheet calculation engine.

## Pasting notes

Use this template locally:

```text
Reporting dates:
Goal:
Account label (no full account number needed):
Date / description / money in or out / amount / category if known:
Source document and page, sheet, or row:
Questions or uncertain items:
Possible duplicates:
Budget category / planned amount / start / end:
Debt label / reported balance / as-of date / minimum payment / due date:
```

Optional AI receives only the notes you submit and the imported documents you explicitly select. There is no automatic analysis of the library or background sending of drafts. AI proposes transaction rows and follow-up questions. Enter plans and debt facts through their dedicated forms. Check every AI quotation against the original; provenance text from a model is not proof of correctness.

## Documents

Identical bytes are detected as duplicates. Different files with the same name are preserved as successive versions. A ZIP is an archive to preview: select members individually, then decide which to import. Nothing in a ZIP runs as a program. Document status describes parser accessibility, not your professional review or completeness.

Text PDF previews can be incomplete or scrambled. Scans need local OCR/manual notes; password-protected files are refused. Workbook formulas are shown as formulas and never executed or replaced. Formula amounts cannot be directly saved as numeric transactions. Enter an independently confirmed value if needed, with a source note.

## Correcting a saved entry

Use the transaction's Edit control, review the replacement, and approve it. The transaction keeps its ID and prior revisions remain available in backups. Deletion also requires review/approval and retains historical snapshots. Do not manually edit JSON files while the app is running.

## Reports

The overview separates income/expense results from other movements. It does not infer opening balances, net worth or debt balances from activity. Categories compare budgets to approved expense-classified records in each budget period. The XLSX/CSV register includes all recorded transactions; the report summary uses the configured reporting period. For a printable copy, export HTML, open it locally, then Print → Save as PDF. Review long descriptions and page breaks in the browser's print preview.

Very large totals that exceed spreadsheet numeric precision appear as exact text in XLSX exports, with an explanation on the Summary sheet. Ordinary amounts remain numeric. Keep the original snapshot if you convert those text totals for calculations in another application.
