# Trap list: data problems found, with evidence (Raymond's version)

Draft, 3 Nov 2026. Starts from the team draft's 19 problems (checkpoint file, section 3), **independently re-checked** where I could run the query myself, plus problems the draft doesn't list.

Legend: **✅ verified** = I reproduced the evidence myself; **↺ from draft** = taken from the team draft, not yet re-checked; **➕ new** = not in the team draft.

## A. Problems in the structured data

| # | Problem | Evidence | Impact | Planned handling | Status |
|---|---|---|---|---|---|
| 1 | **Two severity scales in one column, never converted** | Before 1 Jul 2025: 48 rows, avg 3.96, counts 1→5 = 2/4/6/18/18. From 1 Jul 2025: 37 rows, avg 2.30, counts 1→5 = 9/15/8/3/2. `severity = 1` returns 11 rows; only 4 are truly worst. "Severity 4–5" naively returns 41; correctly normalised it's 11 | **Critical.** The auditor will test this | `severity_as_logged` + `severity_scale` + `severity_5_worst` (= 6 − logged before 1 Jul 2025). Tools query only `severity_5_worst`. KC to confirm the mapping | ✅ verified |
| 2 | **Two timestamp formats in the sensor CSV** | First rows: `2026-01-01T00:00:00+08:00` and `1767196800000` for the **same instant** (00:00 SGT). 26,788 epoch rows (matches draft) | High: wrong ordering, joins, day/night split | Store `epoch_ms` (UTC) + `sampled_at` (SGT); raw string kept in raw table | ✅ verified |
| 3 | **Two temperature units** | Same first reading: CNC-03 `141.4,F` (= 60.8 °C), CMP-01 `112.2,F` (= 44.6 °C) next to CNC-01 `39.4,C`. Draft: 15,806 °F rows (15%), not "half" as the GM's email says | High: false overheating | `temp_c` only in clean table; raw value + unit kept | ✅ verified (examples); share ↺ from draft |
| 4 | Sensor gaps | ~2% single missed 12-minute readings per machine, longest 36 min | Medium | Mark gaps (`qc_flag`), never interpolate | ↺ from draft |
| 5 | Sensors on only 5 of 12 machines | CNC-01/02/03, CMP-01, PMP-T01 | High for condition questions on the other 7 | Agent abstains | ↺ from draft |
| 6 | Spares "ALL" is ambiguous | HYD-32 (VG32) listed for ALL, but nameplates show three different lubricants | High: wrong oil advice | Keep "ALL" unexpanded; flag; ask KC | ↺ from draft |
| 7 | Spares free text, mixed units | Lead times like "2-3 weeks (Germany)", costs like "$38/spool", sizes in mm and inches; 3 parts below minimum | Medium | Parse to numeric columns, keep raw | ↺ from draft |
| 13 | **Open work orders frozen at the data end** | 22 OPEN + 12 AWAITING PARTS; all data ends 30 Jun 2026 (work orders 2024-01-01 to 2026-06-30) | Medium: "what's open now?" would be 4 months stale | Every answer says "as of 30 Jun 2026" | ✅ verified |
| 17 | **Late reporting** | 35 of 85 incidents (41%) "found during audit"; 25 same day, 25 next day | Context for the auditor (late reporting is itself an audit finding) | Report as logged; offer as an insight | ✅ verified |
| 11 | Possible duplicate person | Two codes, same name, trade and shift | Medium (PDPA, per-person counts) | Flag, don't merge; ask KC | ↺ from draft |
| 12 | Near-miss with lost days | 4 "near miss" incidents have lost days > 0 | Medium | Flag | ↺ from draft |
| 14 | Fault text not machine-specific | 13 descriptions across all machines; 69 "compressor overheat" orders on non-compressors | Medium | Never infer failure mode from description | ↺ from draft |
| 16 | Incident IDs not in date order | 41 consecutive pairs go backwards | Low | Never sort by ID | ↺ from draft |
| 19 | `emp_code` declared non-unique | Draft: "not unique in source", count unknown. My check printed no repeated codes | Medium: joins on emp_code | **Pending:** `SELECT COUNT(*), COUNT(DISTINCT emp_code), SUM(emp_code IS NULL) FROM employees;` If 32/32/0, declare it unique and make the links real foreign keys | ✅ partly (pending one query) |
| ➕ 20 | **No foreign keys in the dump** | `SHOW CREATE TABLE` for all 4 tables: primary keys only, no `FOREIGN KEY` clauses | Medium: nothing stops orphans in future loads (today: 0 orphans per draft) | Add FKs in the clean schema where codes are unique; orphan check on every run | ✅ verified |

## B. Problems in the images and documents

| # | Problem | Evidence | Impact | Planned handling | Status |
|---|---|---|---|---|---|
| 8 | **Nameplate fields implausible for the machine** | `nameplate_BLAST-01.jpg`: capacity "450 A @ 60%" is a welding-machine duty rating, not a blasting chamber's | Medium | `semantic_ok = false`; don't answer capacity from plates | ✅ seen on BLAST-01 |
| ➕ 21 | **Lubricant on BLAST-01 nameplate looks copied from a machine tool** | Same plate: "Shell Tonna S3 M68", a slideway oil for machine-tool guideways, plus "GREASE INTERVAL 1000 h", on a blasting chamber with make "CUSTOM", model "SG-Fab". 7,929 kg for a 15 kW unit is also odd | Medium: the oil question for BLAST-01 could be answered confidently but wrongly | Flag `semantic_ok = false` for lubricant too; answer with a caveat; ask KC | ➕ new |
| ➕ 22 | **Incident description doesn't fit the machine** | `IR-2024-900.jpg`: "weld flash burn" logged at LTH-01 (a manual lathe, "workshop bay") | Medium: per-machine incident counts may blame the wrong machine | Store as logged; flag description/machine mismatch; don't re-assign | ➕ new |
| ➕ 23 | **Ambiguous date format on paper forms** | `IR-2024-900.jpg`: "01/07/2024" (1 Jul or 7 Jan?). The database stores a real `date`, so compare with it to decide | Low–medium: wrong date → wrong scale for severity | Parse forms as DD/MM (Singapore convention), confirm against the DB row; flag disagreements | ➕ new |
| 9 | 5-Why documents missing | 12 of 30 forms say attached / "see attached"; none in the package (e.g. `IR-2024-900.jpg`: "see attached") | Medium for the audit | Agent says they're absent | ✅ seen on IR-2024-900; count ↺ |
| 10 | 5-Why field inconsistent | 9 forms say "N/A near miss"; 7 aren't near misses | Medium | Store raw, don't infer root cause | ↺ from draft |
| 15 | SOP cites an event the database lacks | SOP-CRANE-02 mentions an Aug 2025 sling near-miss; no such incident | Low–medium | Show as a source conflict | ↺ from draft |
| 18 | Form coverage and legibility | 30 of 85 incidents scanned; one severity digit unreadable | Low | Confidence per field, `needs_review` | ↺ from draft |
| ➕ 24 | **Three names for the same company** | "Jurong Marine Services" (course brief), "Jurong Marine & Engineering Pte Ltd" (CLIENT_BRIEF, form header), "JME" (nameplate asset tag) | Low: affects search and the pitch, not the data | Use the legal name; treat the others as aliases | ➕ new |
| ➕ 25 | **Asset tag pattern breaks once** | 11 tags follow `ABC-NN`; `PMP-T01` has a letter in the number | Low: a regex like `[A-Z]+-\d+` would miss it | Match machine ids against the `machines` table, never by pattern | ➕ new |
| ➕ 26 | **Character encoding glitch in the GM email** | A symbol (likely an em dash) shows as a box in VS Code | Low: broken quotes in citations | Read all text files as UTF-8 with replacement; log any replaced characters | ➕ new (to confirm by opening the file) |
| ➕ 27 | **GM's email overstates the °F share** | Email: "half the temperature in Fahrenheit". Data: 15% | Low, but worth saying politely to the client | Correct with evidence in the data quality report | ↺ draft finding, framed as a client correction |

## C. Handling lessons (not client traps, worth one line in the report)

- **Opening the sensor CSV in Excel and saving it destroys the epoch timestamps** (they become `1.7672E+12`, 5 significant digits). It happened to my copy on 1 Nov. Restored from the original download, SHA-256 `05C18527…BC6BD023`. Team rule: don't save the CSV in Excel; check copies against the hash.
- **The client data stays out of git.** All evidence above is counts, codes and file names, with no names or row dumps.

## D. Questions this list raises for KC

1. Confirm the severity mapping (old 1 = new 5, i.e. `6 − logged`) and the exact cutover date (1 Jul 2025).
2. What does "ALL" mean in the spares list, given three different lubricants on the nameplates?
3. Is the BLAST-01 nameplate (capacity, lubricant, weight) correct, or was it made from a template?
4. Was the IR-2024-900 weld flash burn really at LTH-01?
5. Where are the 5-Why documents the forms refer to?
6. Are the two employee codes with the same name one person?
