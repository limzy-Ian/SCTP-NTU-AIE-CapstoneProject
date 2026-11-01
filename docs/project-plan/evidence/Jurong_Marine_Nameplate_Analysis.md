# Jurong Marine — Equipment Nameplate Analysis

**Analysis Done By Ian Lim Using Chatgpt with the 12 JPGs as comparison** 
**Analysis date:** 1 November 2026  
**Source:** 12 supplied equipment nameplate photographs  
**Purpose:** Asset-master data audit, preventive maintenance planning, and CMMS capstone documentation

> **Data integrity note:** Values below are transcribed from the supplied nameplate images. Suspected inconsistencies are *flagged for verification* rather than silently corrected. A nameplate grease interval does not by itself establish that a maintenance task is overdue.

## 1. Executive Summary

All **12 equipment nameplates** were reviewed for identifiers, technical specifications, manufacturing dates, lubricant information, and stated maintenance intervals. The most significant finding is that several **capacity descriptions appear inconsistent with the associated equipment type**, suggesting possible cross-record contamination, incorrect label mapping, or erroneous original data.

The nameplates provide a useful starting point for a CMMS asset register, but they do not provide operating-hour readings, completed maintenance records, or inspection evidence. Accordingly, the dataset supports **maintenance interval configuration**, not a defensible overdue-maintenance determination.

## 2. Equipment Inventory

| Asset tag | Manufacturer / model | Mfg. date | Power (kW) | Weight (kg) | Grease interval (h) |
|---|---|---|---:|---:|---:|
| CNC-01 | MAZAK QT-250 | 10/2018 | 22 | 9,257 | 500 |
| CNC-02 | MAZAK QT-350 | 02/2020 | 30 | 3,680 | 1,000 |
| CNC-03 | DMG Mori DMU-50 | 08/2022 | 15 | 8,092 | 500 |
| CRN-01 | KONECRANES CXT | 02/2016 | 7.5 | 6,085 | 2,000 |
| CRN-02 | DEMAG DC-Com | 03/2019 | 18.5 | 1,620 | 500 |
| LTH-01 | COLCHESTER Triumph | 04/2009 | 30 | 2,559 | 500 |
| MILL-01 | BRIDGEPORT GX-1000 | 06/2015 | 7.5 | 5,311 | 500 |
| PMP-T01 | KSB Etanorm | 06/2020 | 7.5 | 3,194 | 2,000 |
| WELD-01 | LINCOLN R450 | 05/2019 | 18.5 | 4,908 | 2,000 |
| WELD-02 | MILLER XMT-350 | 05/2017 | 22 | 3,529 | 2,000 |
| BLAST-01 | CUSTOM SG-Fab | 03/2014 | 15 | 7,929 | 1,000 |
| CMP-01 | ATLAS Copco GA30 | 11/2021 | 15 | 3,588 | 500 |

### Inventory statistics

| Metric | Result |
|---|---:|
| Equipment records | **12** |
| Sum of stated electrical power | **208.5 kW** |
| Sum of stated equipment weights | **59,752 kg** |
| Average equipment age (as of Nov 2026) | **Approximately 9 years** |
| Oldest listed asset | **LTH-01** (04/2009) |
| Newest listed asset | **CNC-03** (08/2022) |
| Capacity/specification mismatches to investigate first | **6 assets** |

*The total power is the sum of nameplate ratings, not measured or coincident electrical demand. The total weight is a sum of nameplate values, not a verified lifting plan.*

## 3. Data-Quality Findings and Trap List

### 3.1 High-priority capacity and specification mismatches

| Asset | Original nameplate value | Why it needs investigation | Recommended verification |
|---|---|---|---|
| **CRN-01** — KONECRANES crane | `CAPACITY 450 A @ 60%` | Amperage and duty cycle resemble a welding output specification rather than a crane's rated lifting capacity. | Review crane plate, load test / inspection records, and OEM documentation for safe working load. |
| **PMP-T01** — KSB pump | `CAPACITY 450 A @ 60%` | Welding-type current rating is not a typical pump capacity. | Confirm design flow rate, head, pump curve, and motor data from OEM documentation. |
| **WELD-01** — LINCOLN welding equipment | `CAPACITY 2000 kg` | Mass/lifting capacity appears inappropriate for a welding power source's output rating. | Confirm output current, voltage, and duty cycle on the OEM specification sheet. |
| **WELD-02** — MILLER welding equipment | `CAPACITY 30 kW FAD 88 cfm` | FAD (free air delivery) normally describes compressor airflow, not welding capacity. | Compare model and serial number against OEM welding specifications. |
| **BLAST-01** — CUSTOM blasting equipment | `CAPACITY 450 A @ 60%` | Welding-type rating appears inconsistent with blasting equipment. | Check equipment documentation for the intended capacity measure. |
| **CMP-01** — ATLAS compressor | `POWER 15 kW`; `CAPACITY 30 kW FAD 88 cfm` | Two different kW values occur on the same plate; it is unclear whether the capacity line incorrectly includes a power rating. | Verify installed motor rating and FAD against the OEM technical sheet. |

**Interpretation:** The repeated `450 A @ 60%` entry on unrelated equipment types is a strong **data-validation signal**. It does **not** prove which original document or process introduced the problem. Preserve the exact photographed value until it is checked against trusted records.

### 3.2 Additional electrical-rating checks

These are secondary review candidates, not confirmed errors:

| Asset | Nameplate values | Reason for manual review |
|---|---|---|
| **MILL-01** | 7.5 kW, FLA 56 A, 3PH 380–440 V | The listed full-load amperage appears high for a 7.5 kW three-phase motor under typical conditions. Confirm whether the values describe the whole machine or a particular motor/circuit. |
| **CNC-01** | 22 kW, FLA 23 A, 3PH 415 V | The stated current appears low relative to the stated power if both describe the same three-phase input. Confirm rating definitions and electrical documentation. |

Do **not** automatically rewrite any amperage or power value. Electrical ratings can refer to different components or machine-wide inputs; measurements, motor data, and manufacturer manuals are needed.

### 3.3 Suggested trap-list schema

Record each issue with the fields `asset_tag`, `source_file`, `field_name`, `raw_value`, `expected_format_or_range`, `issue_description`, `severity`, `verification_source`, `resolution_status`, `reviewer`, and `reviewed_at`.

Use statuses such as **Open**, **Under review**, **Verified as correct**, and **Corrected with evidence**. Retain both the raw source value and any validated value for auditability.

## 4. Preventive Maintenance Analysis

### 4.1 Grease intervals

| Stated interval | Equipment count | Share |
|---|---:|---:|
| 500 operating hours | 6 | 50.0% |
| 1,000 operating hours | 2 | 16.7% |
| 2,000 operating hours | 4 | 33.3% |
| **Total** | **12** | **100%** |

Assets with a **500-hour** grease interval: **CNC-01, CNC-03, CRN-02, LTH-01, MILL-01, CMP-01**. These have the shortest stated interval and should be configured for more frequent meter-based preventive maintenance.

### 4.2 Lubricant descriptions

| Nameplate lubricant | Equipment count |
|---|---:|
| ISO VG32 | 5 |
| ISO VG68 | 4 |
| Shell Tonna S3 M68 | 3 |
| **Total** | **12** |

**Important distinction:** The plates specify *lubricant* and *grease interval* as separate fields. ISO VG32 / ISO VG68 are viscosity grades, and Shell Tonna S3 M68 is an oil product name. Do not assume these describe the actual **grease** required at each lubrication point; verify lubrication charts or equipment manuals.

### 4.3 Can overdue maintenance be determined?

**No.** The photographs show intervals but do not show current operating hours or the operating hours at the last completed service.

For example, a machine with a **500-hour interval** last serviced at **4,000 operating hours** would next be due at **4,500 operating hours**.

A meter-based CMMS schedule needs at least:

- Asset identifier and service task
- Maintenance interval in operating hours
- Meter reading at most recent completed service
- Current meter reading and timestamp
- Service completion and work-order history

Suggested calculation:

```text
next_due_hours = last_service_meter_hours + interval_hours
hours_remaining = next_due_hours - current_meter_hours
overdue = hours_remaining < 0
```

This calculation assumes reliable, monotonically increasing hour-meter readings and appropriately handled resets or meter replacements.

## 5. Equipment Age and Reliability Considerations

**LTH-01**, manufactured in April 2009, is approximately **17 years and 7 months** old as of November 2026. Other comparatively older assets include **BLAST-01 (2014)**, **MILL-01 (2015)**, and **CRN-01 (2016)**.

Their ages justify reviewing maintenance records, inspection findings, part availability, and failure history. **Age alone is not proof of poor reliability** and should not be used as the sole basis for replacement or risk ranking.

## 6. Recommended CMMS Data Model

The supplied records provide the basis for four related entities:

| Entity | Suggested fields | Why it is needed |
|---|---|---|
| **Asset Master** | `asset_id`, `asset_tag`, `manufacturer`, `model`, `serial_number`, `mfg_date`, `asset_category`, validated technical attributes | Authoritative equipment identity and characteristics |
| **Maintenance Schedule** | `schedule_id`, `asset_id`, `task_name`, `interval_hours`, `lubricant_requirement`, `next_due_hours`, `status` | Meter-based preventive maintenance planning |
| **Maintenance History** | `work_order_id`, `asset_id`, `schedule_id`, `technician`, `completed_at`, `meter_hours`, `work_performed`, `completion_status` | Evidence of work performed and due-date calculations |
| **Data Quality Issues** | `issue_id`, `asset_id`, `source_file`, `field_name`, `raw_value`, `issue_description`, `severity`, `status`, `verification_evidence` | Traceable validation, investigation, and correction |

### Suggested data-handling rules

1. **Retain raw input unchanged.** Store transcribed source values and the source photograph reference in a raw/staging layer.
2. **Use normalized typed fields.** Store dates as dates, power as numeric kW, weight as numeric kg, and operating-hour intervals as integers.
3. **Do not force unrelated capacity units into one numeric column.** Crane lifting capacity, pump flow/head, welding current/duty cycle, and compressor FAD require distinct measurement types and units.
4. **Separate verified from unverified values.** Support `raw_value`, `validated_value`, validation status, evidence, and reviewer.
5. **Use stable keys.** Give each asset an internal `asset_id`; enforce uniqueness on `asset_tag` as appropriate and review duplicates before import.

## 7. Capstone Week 1 Deliverable Mapping

| Week 1 deliverable | Contribution from this analysis | Remaining work |
|---|---|---|
| **Data audit** | 12 nameplate images reviewed; fields extracted, grouped, and compared | Audit **all other files** in `data/`, with counts and file-level evidence |
| **ER diagram of cleaned schema** | Four proposed entities and suggested fields | Draw the finalized Mermaid ER diagram in `docs/` after reconciling with existing SQL data |
| **Trap list with evidence** | Six priority mismatches plus two secondary checks, each tied to an asset and observed values | Cross-reference photographs and other source records; track resolutions |
| **Architecture proposal** | Raw/staging → validation → CMMS asset master → maintenance scheduling | Produce the complete Mermaid architecture diagram in `docs/` |
| **Everyone committed at least once** | No evidence from nameplates | Verify Git commit history for every team member |

## 8. Recommendations and Next Steps

**Immediate priority:** Investigate mismatched capacity specifications, especially values repeated across unrelated asset types, before using these records to plan crane lifts, pump sizing, welding operations, or compressor capacity.

**Next:** Load the transcribed nameplate records into a **raw/staging table**; create validated typed asset records only after resolving—or explicitly marking—questionable values. Build preventive maintenance schedules from the stated intervals but defer overdue alerts until accurate meter readings and historical work orders exist.

**For the capstone:** Include this report in `docs/` as a supporting asset audit; add image references and a resolution tracker to the data-quality trap list. Use manufacturer manuals and physical inspection evidence to close identified anomalies.

---

### Limitations

- The analysis is limited to the **12 photographs provided**; it is not a complete audit of the project's entire `data/` directory.
- Suspected mismatches are **flags for human verification**, not established corrections or findings of equipment non-compliance.
- The photographs do not establish operating condition, legal inspection status, service history, or equipment availability.
- No due-maintenance or safe-operating determination should be made solely from this report.
