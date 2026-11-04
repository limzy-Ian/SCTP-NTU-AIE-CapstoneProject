# Data audit: Raymond's verification (3 Nov 2026)

Run against the local MySQL load of `data/sql/jurongmarine_cmms.sql` (database `jurong_marine`). Counts only, no personal data.

## Row counts and date ranges

| Table | Rows | Date range | Matches team draft? |
|---|---|---|---|
| machines | 12 | – | ✅ 12 |
| employees | 32 | – | ✅ 32 |
| work_orders | 1,603 | 2024-01-01 to 2026-06-30 | ✅ 1,603, same range |
| safety_incidents | 85 | 2024-01-24 to 2026-06-18 | ✅ 85, same range |

## Work order status

| Status | Count |
|---|---|
| CLOSED | 1,569 |
| OPEN | 22 |
| AWAITING PARTS | 12 |
| **Total** | **1,603** ✅ |

Matches the draft's problem 13 (22 open + 12 awaiting parts). All data ends 30 Jun 2026, so open items must be reported "as of 30 Jun 2026".

## Incident reporting

| Reporting | Count | Share |
|---|---|---|
| found during audit | 35 | 41% |
| reported same day | 25 | 29% |
| reported next day | 25 | 29% |
| **Total** | **85** ✅ | |

Matches the draft's problem 17 (35 of 85, 41%). Only three clean values, so there are no spelling variants to fix.

## Severity: the scale trap, verified

The query split incidents by `incident_date < '2025-07-01'`, so **`old_scale = 1` means before 1 Jul 2025 (1 = worst)** and **`old_scale = 0` means from 1 Jul 2025 (5 = worst)**.

| Severity as logged | Before 1 Jul 2025 (1 = worst) | From 1 Jul 2025 (5 = worst) |
|---|---|---|
| 1 | 2 ← **worst** | 9 (mildest) |
| 2 | 4 | 15 |
| 3 | 6 | 8 |
| 4 | 18 | 3 |
| 5 | 18 (mildest) | 2 ← **worst** |
| **Rows** | **48** | **37** |
| Average | 3.96 | 2.30 |

**Checks against the draft:** 48 / 37 rows ✅. Averages 3.96 / 2.30 ✅. `severity = 1` returns 9 + 2 = **11** rows ✅. Truly worst-case = 2 (old scale, logged 1) + 2 (new scale, logged 5) = **4** ✅.

**What the pattern shows:** in both periods most incidents are minor. Before July 2025 they cluster at 4–5, after at 1–2. That mirror image is itself the evidence that the scale flipped. A naive query gets it badly wrong:

| Naive question | Naive answer | Correct answer (normalised to 5 = worst) |
|---|---|---|
| "How many severity-1 (worst) incidents?" | 11 | 4 |
| "How many severity 4–5 (serious) incidents?" | 18 + 18 + 3 + 2 = 41 | old 1–2 (2 + 4 = 6) + new 4–5 (3 + 2 = 5) = **11** |

Normalisation rule: `severity_5_worst = 6 − severity` for incidents before 1 Jul 2025, unchanged from that date. Still to confirm with KC.

## Files

| Source | Count | Matches team draft? | Notes |
|---|---|---|---|
| `logs/vibration_temp_2026H1.csv` | 106,385 lines = **106,384 rows** + header | ✅ | Columns: `timestamp, machine_id, vib_rms_mms, temp, temp_unit` |
| `images/nameplates/` | 12 | ✅ | |
| `images/incident_reports/` | 30 | ✅ | |
| `docs/sops/` | 4 files | ✅ | SOP-LOTO-01 706 B, SOP-CRANE-02 575 B, SOP-CONFINED-03 434 B, GM email 788 B. All under 1 KB |
| `tabular/critical_spares.xlsx` | not yet checked | draft: 1 sheet, 10 rows, 8 columns | |

### Sensor CSV first rows: two traps visible immediately

```
2026-01-01T00:00:00+08:00,CNC-01,1.78,39.4,C
2026-01-01T00:00:00+08:00,CNC-02,2.35,56.6,C
1767196800000,CNC-03,2.19,141.4,F
1767196800000,CMP-01,3.32,112.2,F
```

- **Two timestamp formats:** ISO with +08:00 (Singapore time) and epoch milliseconds (UTC). They describe the same instant: `1767196800000` = 2025-12-31 16:00 UTC = 2026-01-01 00:00 SGT, so the first four rows are one 00:00 reading from four machines.
- **Two temperature units:** 141.4 °F = 60.8 °C and 112.2 °F = 44.6 °C. After conversion they fall in the same range as the °C rows.
- **Resolved, not a client trap:** an earlier local copy showed epoch values as `1.7672E+12` (rounded to 5 digits). Cause: the CSV was opened and re-saved in Excel on 1 Nov (hash `AFBED42D…`). The original download is intact: SHA-256 `05C18527593E5D5DC4BD0B3D17B6EF8C67B7987B30D50EFA77BEBBE3BC6BD023`, 0 rounded values, so the copy was restored from it. **Team rule:** never open and save the CSV in Excel; check copies against this hash.

## Still to run

- **Problem 19 (repeated emp_codes):** the output didn't show up in the paste. If MySQL printed nothing, the result was empty, i.e. **no code repeats**. Confirm with a query that always prints:
  `SELECT COUNT(*) AS rows_, COUNT(DISTINCT emp_code) AS distinct_codes, SUM(emp_code IS NULL) AS empty_codes FROM employees;`
  If rows_ = distinct_codes = 32 and empty_codes = 0, `emp_code` is unique in practice, just not declared unique. That would correct the draft's "not unique in source".
- Spares xlsx: open in Excel (read only, don't save) and note sheets, rows and columns.
- Epoch precision check: done (see Files).
