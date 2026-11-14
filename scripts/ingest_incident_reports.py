#!/usr/bin/env python3
"""Jurong Marine WSH-F02 JPEG -> OCR review CSV/JSONL -> MySQL staging.

This is a NON-DESTRUCTIVE ingestion utility: it does not alter safety_incidents.
A human reviewer must approve extracted records before authoritative use.
"""
from __future__ import annotations

import argparse
import csv
from datetime import date, datetime
import hashlib
import json
import os
from pathlib import Path
import re
import sys

import cv2
import numpy as np
import pytesseract
from dotenv import load_dotenv

# ROI coordinates are fractions of the source image width/height. They match
# the WSH-F02 photo layout supplied with the Jurong Marine capstone.
ROI = {
    'report_no':       (0.37, 0.111, 0.82, 0.156),
    'incident_date':   (0.37, 0.153, 0.76, 0.203),
    'machine_location':(0.37, 0.201, 0.98, 0.252),
    'emp_code':        (0.37, 0.248, 0.74, 0.297),
    'description':     (0.37, 0.292, 0.995, 0.341),
    'severity_raw':    (0.385,0.338, 0.58, 0.398),
    'lost_days':       (0.38, 0.389, 0.63, 0.444),
    'reporting':       (0.38, 0.439, 0.97, 0.488),
    'immediate_action':(0.060,0.522, 0.992,0.579),
    'root_cause':      (0.414,0.578, 0.98, 0.631),
}

IMG_PATTERN = re.compile(r'^IR-(\d{4})-(\d+)\.(?:jpe?g|png)$', re.I)
REPORT_PATTERN = re.compile(r'IR\s*[-–—]\s*(\d{4})\s*[-–—]\s*(\d{3,6})', re.I)
ISO_FMT = '%Y-%m-%d'
DATE_CUTOFF_START = date(2025, 7, 1)
DATE_CUTOFF_END = date(2025, 8, 1)


def image_crop(img: np.ndarray, roi: tuple[float, float, float, float]) -> np.ndarray:
    h, w = img.shape[:2]
    x0, y0, x1, y1 = roi
    return img[int(y0*h):int(y1*h), int(x0*w):int(x1*w)]


def blue_text_mask(bgr: np.ndarray) -> np.ndarray:
    """Keep dark-blue handwritten/typed field entries and suppress black labels.

    Especially important for 2025 severity digits that overlap 'WSH matrix'.
    """
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    ink = cv2.inRange(hsv, (88, 35, 22), (145, 255, 255))
    return cv2.bitwise_not(ink)  # black foreground on white background


def label_black_mask(bgr: np.ndarray) -> np.ndarray:
    """Keep dark black printed text, suppress higher-saturation blue entries."""
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    # Black printed labels: low value and usually low saturation.
    black = cv2.inRange(hsv, (0, 0, 0), (179, 100, 150))
    return cv2.bitwise_not(black)


def run_ocr(gray: np.ndarray, *, psm: int = 7, whitelist: str = '') -> tuple[str, float]:
    if psm == 10:
        # Single-character OCR is unreliable when a tiny digit occupies only a
        # small corner of a wide ROI. Crop to the ink bounds and add padding.
        ys, xs = np.where(gray < 165)
        if len(xs):
            clipped = gray[max(0, int(ys.min())-3):int(ys.max())+4,
                           max(0, int(xs.min())-3):int(xs.max())+4]
            pad = max(12, clipped.shape[0] // 2)
            gray = cv2.copyMakeBorder(clipped, pad, pad, pad, pad,
                                      cv2.BORDER_CONSTANT, value=255)
    enlarged = cv2.resize(gray, None, fx=4 if psm == 10 else 3,
                          fy=4 if psm == 10 else 3, interpolation=cv2.INTER_CUBIC)
    config = f'--oem 3 --psm {psm}'
    if whitelist:
        config += f' -c tessedit_char_whitelist={whitelist}'
    data = pytesseract.image_to_data(
        enlarged, lang='eng', config=config,
        output_type=pytesseract.Output.DICT,
    )
    parts: list[str] = []
    confidences: list[tuple[float, int]] = []
    for i, token in enumerate(data['text']):
        token = token.strip()
        if not token:
            continue
        parts.append(token)
        try:
            conf = float(data['conf'][i])
        except (TypeError, ValueError):
            conf = -1
        if conf >= 0:
            confidences.append((conf, max(1, len(token))))
    if confidences:
        confidence = sum(c * weight for c, weight in confidences) / sum(w for _, w in confidences)
    else:
        confidence = 0.0
    return ' '.join(parts).strip(), round(confidence, 2)


def read_fields(image: np.ndarray, debug_dir: Path | None = None, stem: str = '', *, ocr_runner=None):
    ocr_runner = ocr_runner or run_ocr
    readings: dict[str, str] = {}
    confidence: dict[str, float] = {}
    for field, rect in ROI.items():
        crop = image_crop(image, rect)
        mask = blue_text_mask(crop) if field in ('severity_raw','immediate_action','root_cause') else cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        opts = {'psm': 10 if field in ('severity_raw', 'lost_days') else 7}
        if field in ('severity_raw', 'lost_days'):
            opts['whitelist'] = '0123456789'
        text, score = ocr_runner(mask, **opts)
        readings[field] = text
        confidence[field] = score
        if debug_dir:
            cv2.imwrite(str(debug_dir / f'{stem}_{field}.png'), mask)

    # The PRINTED label identifies which direction the scale runs. Crop to
    # left-hand printed portion so the overlapped blue severity digit does not
    # confuse the extraction. Do not infer the boundary date from incident ID.
    label_roi = (0.058, 0.332, 0.386, 0.391)
    label_img = label_black_mask(image_crop(image, label_roi))
    readings['severity_label'], confidence['severity_label'] = ocr_runner(label_img, psm=6)
    if debug_dir:
        cv2.imwrite(str(debug_dir / f'{stem}_severity_label.png'), label_img)
    return readings, confidence


def parse_date(s: str) -> date | None:
    m = re.search(r'\b(\d{1,2})\s*/\s*(\d{1,2})\s*/\s*(20\d\d)\b', s)
    if not m:
        return None
    try:
        return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    except ValueError:
        return None


def scale_from_label(label: str) -> str:
    # Number printed as 'Severity (1 = MOST SEVERE)' vs '(5 = MOST SEVERE)'.
    # Expected OCR is incomplete when overprinting occurs; if unreadable,
    # the July 2025 transition remains unresolved until manual approval.
    m = re.search(r'(?:Severity\s*\()?\s*([15])\s*[=:]\s*MOST\s*SEVERE', label, re.I)
    if not m:
        m = re.search(r'Severity\s*\(?\s*([15])\s*=', label, re.I)
    if not m:
        return 'UNKNOWN'
    return 'OLD_1_WORST' if m.group(1) == '1' else 'NEW_5_WORST'


def resolve_scale(incident_date: date | None, label: str) -> tuple[str, str, list[str]]:
    flags: list[str] = []
    form_scale = scale_from_label(label)
    if form_scale != 'UNKNOWN':
        if incident_date and incident_date < DATE_CUTOFF_START and form_scale != 'OLD_1_WORST':
            flags.append('SCALE_CONFLICT_PRE_JULY')
        if incident_date and incident_date >= DATE_CUTOFF_END and form_scale != 'NEW_5_WORST':
            flags.append('SCALE_CONFLICT_POST_JULY')
        return form_scale, 'FORM_LABEL', flags
    if incident_date is None:
        return 'UNKNOWN', 'UNDETERMINED', ['SEVERITY_SCALE_UNDETERMINED']
    if incident_date < DATE_CUTOFF_START:
        flags.append('SCALE_DATE_INFERRED_CHECK_FORM')
        return 'OLD_1_WORST', 'DATE_INFERRED', flags
    if incident_date >= DATE_CUTOFF_END:
        flags.append('SCALE_DATE_INFERRED_CHECK_FORM')
        return 'NEW_5_WORST', 'DATE_INFERRED', flags
    return 'UNKNOWN', 'UNDETERMINED', ['JULY_2025_SCALE_REQUIRES_FORM_REVIEW']


def normalize_severity(raw: int | None, scale: str) -> int | None:
    if raw is None or not 1 <= raw <= 5:
        return None
    if scale == 'OLD_1_WORST':
        return 6 - raw
    if scale == 'NEW_5_WORST':
        return raw
    return None


def extract_one(path: Path, debug_dir: Path | None = None, *, ocr_runner=None) -> dict:
    im = cv2.imread(str(path))
    if im is None:
        raise ValueError(f'Cannot open image: {path}')
    stem = path.stem
    readings, confidences = read_fields(im, debug_dir, stem, ocr_runner=ocr_runner)
    flags: list[str] = []
    file_match = IMG_PATTERN.match(path.name)
    filename_report = f'IR-{file_match.group(1)}-{file_match.group(2)}' if file_match else None
    raw_report = REPORT_PATTERN.search(readings['report_no'])
    ocr_report = f'IR-{raw_report.group(1)}-{int(raw_report.group(2))}' if raw_report else None
    if filename_report and ocr_report and filename_report != ocr_report:
        flags.append('REPORT_NO_FILENAME_IMAGE_MISMATCH')
    if not ocr_report:
        flags.append('REPORT_NO_OCR_FAILED_FILENAME_USED' if filename_report else 'REPORT_NO_MISSING')
    report_no = filename_report or ocr_report
    incident_id = int(report_no.split('-')[-1]) if report_no else None

    dt = parse_date(readings['incident_date'])
    if dt is None:
        flags.append('DATE_MISSING_OR_INVALID')
    if dt and report_no and str(dt.year) != report_no.split('-')[1]:
        flags.append('DATE_REPORT_YEAR_MISMATCH')

    location_raw = readings['machine_location'] or None
    machine_match = re.search(r'\b[A-Z]{2,8}(?:-[A-Z0-9]+)+\b', (location_raw or '').upper())
    machine_id = machine_match.group(0) if machine_match else None
    if machine_id:
        # Common OCR ambiguity in numeric part: CNC-O2 -> CNC-02.
        machine_id = re.sub(r'-O(?=\d)', '-0', machine_id)
    if machine_id is None:
        flags.append('MACHINE_ID_MISSING')
    employee_text = readings['emp_code'].upper().replace(' ', '')
    # EMP019 is commonly OCRed as EMPO19 (letter O versus zero).
    employee_text = re.sub(r'^EMPO', 'EMP0', employee_text)
    employee_match = re.search(r'EMP\s*[-:]?\s*(\d{3})', employee_text, re.I)
    emp_code = f'EMP{employee_match.group(1)}' if employee_match else None
    if emp_code is None:
        flags.append('EMPLOYEE_ID_MISSING')

    # Severity/ lost-days are cropped separately to avoid confusing the form's
    # scale instruction (1=worst or 5=worst) with the actual blue number.
    raw_digits = re.findall(r'[1-5]', readings['severity_raw'])
    severity_raw = int(raw_digits[0]) if len(raw_digits) == 1 else None
    if severity_raw is None:
        flags.append('SEVERITY_OCR_AMBIGUOUS')
    days_digits = re.findall(r'\d+', readings['lost_days'])
    lost_days = int(days_digits[0]) if len(days_digits) == 1 else None
    if lost_days is None or lost_days > 365:
        lost_days = None
        flags.append('LOST_DAYS_OCR_AMBIGUOUS')

    scale, scale_source, scale_flags = resolve_scale(dt, readings['severity_label'])
    flags.extend(scale_flags)
    description = readings['description'] or None
    reporting = readings['reporting'] or None
    immediate = readings['immediate_action'] or None
    root = readings['root_cause'] or None
    if not description:
        flags.append('DESCRIPTION_MISSING')
    if not reporting:
        flags.append('REPORTING_MISSING')
    if description and re.search(r'near\s+miss', description, re.I) and lost_days and lost_days > 0:
        flags.append('NEAR_MISS_WITH_LOST_WORK_DAYS_VERIFY')
    if root and re.search(r'n\s*/\s*a\s*near\s*miss', root, re.I):
        if not description or not re.search(r'near\s+miss', description, re.I):
            flags.append('ROOT_CAUSE_MARKED_NEAR_MISS_BUT_INJURY_REPORTED')
    if root and re.search(r'\b(?:see\s+attached|yes)\b', root, re.I):
        flags.append('ROOT_CAUSE_ATTACHMENT_EXISTENCE_UNVERIFIED')
    if not root or re.search(r'\bpending\b', root, re.I):
        flags.append('ROOT_CAUSE_NOT_COMPLETED')
    if reporting and re.search(r'found\s+during\s+audit', reporting, re.I):
        flags.append('REPORTING_DISCOVERED_DURING_AUDIT_VERIFY_NOTICE_DATE')

    important = ['report_no', 'incident_date', 'machine_location', 'emp_code',
                 'description', 'severity_raw', 'lost_days', 'reporting']
    nonzero = [confidences[k] for k in important if readings[k].strip()]
    mean_confidence = round(sum(nonzero) / len(nonzero), 2) if nonzero else 0.0
    if mean_confidence < 70:
        flags.append('OCR_CONFIDENCE_BELOW_70')

    # Source image bytes retained externally; SHA-256 makes the retained evidence
    # tamper-evident when compared to the database's captured image_hash.
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return {
        'report_no': report_no,
        'incident_id': incident_id,
        'incident_date': dt.isoformat() if dt else None,
        'machine_id': machine_id,
        'location_raw': location_raw,
        'emp_code': emp_code,
        'description': description,
        'severity_raw': severity_raw,
        'severity_scale': scale,
        'scale_source': scale_source,
        'severity_5_worst': normalize_severity(severity_raw, scale),
        'lost_days': lost_days,
        'reporting': reporting,
        'immediate_action': immediate,
        'root_cause_reference': root,
        'image_path': str(path.resolve()),
        'image_sha256': digest,
        'ocr_confidence': mean_confidence,
        'extraction_flags': sorted(set(flags)),
        'ocr_raw_json': {'readings': readings, 'field_confidence': confidences},
        'review_status': 'PENDING_REVIEW',
    }


CSV_FIELDS = [
    'report_no','incident_id','incident_date','machine_id','location_raw',
    'emp_code','description','severity_raw','severity_scale','scale_source',
    'severity_5_worst','lost_days','reporting','immediate_action',
    'root_cause_reference','image_path','image_sha256',
    'ocr_confidence','extraction_flags','review_status'
]


def write_outputs(records: list[dict], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    with (out_dir / 'incident_reports_ocr_preview.csv').open('w', newline='', encoding='utf-8-sig') as f:
        wr = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        wr.writeheader()
        for r in records:
            wr.writerow({k: ';'.join(r[k]) if k == 'extraction_flags' else r.get(k)
                         for k in CSV_FIELDS})
    with (out_dir / 'incident_reports_ocr_full.jsonl').open('w', encoding='utf-8') as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + '\n')
    with (out_dir / 'incident_reports_review_queue.csv').open('w', newline='', encoding='utf-8-sig') as f:
        wr = csv.DictWriter(f, fieldnames=['report_no','incident_date','severity_raw',
                                            'severity_scale','severity_5_worst',
                                            'ocr_confidence','extraction_flags','image_path'])
        wr.writeheader()
        for r in records:
            wr.writerow({k: ';'.join(r[k]) if k == 'extraction_flags' else r.get(k)
                         for k in wr.fieldnames})


def upload_mysql(records: list[dict]) -> tuple[int, int, list[str]]:
    # Imported only for --commit; dry run requires no database connection.
    import mysql.connector
    required = ('MYSQL_HOST','MYSQL_PORT','MYSQL_USER','MYSQL_PASSWORD','MYSQL_DATABASE')
    missing = [key for key in required if not os.getenv(key)]
    if missing:
        raise RuntimeError(f'Missing MySQL .env entries: {", ".join(missing)}')
    connection = mysql.connector.connect(
        host=os.environ['MYSQL_HOST'], port=int(os.environ['MYSQL_PORT']),
        user=os.environ['MYSQL_USER'], password=os.environ['MYSQL_PASSWORD'],
        database=os.environ['MYSQL_DATABASE'], connection_timeout=15,
    )
    insert_sql = '''
    INSERT INTO incident_report_ocr (
      report_no, incident_id, incident_date, machine_id, location_raw, emp_code,
      description, severity_raw, severity_scale, scale_source, severity_5_worst,
      lost_days, reporting, immediate_action, root_cause_reference,
      image_path, image_sha256, ocr_confidence, extraction_flags, ocr_raw_json,
      review_status
    ) VALUES (
      %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s
    )'''
    cols = ['report_no','incident_id','incident_date','machine_id','location_raw',
            'emp_code','description','severity_raw','severity_scale','scale_source',
            'severity_5_worst','lost_days','reporting','immediate_action',
            'root_cause_reference','image_path','image_sha256','ocr_confidence',
            'extraction_flags','ocr_raw_json','review_status']
    inserted = skipped = 0
    errors: list[str] = []
    try:
        cur = connection.cursor()
        schema_path = Path(__file__).resolve().parents[1] / 'sql' / 'incident_report_schema.sql'
        cur.execute(schema_path.read_text(encoding='utf-8'))
        for r in records:
            if not r['report_no']:
                errors.append(f'{r["image_path"]}: missing report_no')
                continue
            cur.execute('SELECT image_sha256 FROM incident_report_ocr WHERE report_no=%s',
                        (r['report_no'],))
            old = cur.fetchone()
            if old:
                if old[0] != r['image_sha256']:
                    errors.append(f'{r["report_no"]}: different photo hash; manual version review required')
                else:
                    skipped += 1
                continue
            values = [json.dumps(r[k], ensure_ascii=False) if k in ('extraction_flags','ocr_raw_json')
                      else r.get(k) for k in cols]
            cur.execute(insert_sql, values)
            inserted += 1
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
    return inserted, skipped, errors


def self_test() -> None:
    assert normalize_severity(1, 'OLD_1_WORST') == 5
    assert normalize_severity(2, 'OLD_1_WORST') == 4
    assert normalize_severity(4, 'OLD_1_WORST') == 2
    assert normalize_severity(5, 'NEW_5_WORST') == 5
    assert normalize_severity(2, 'NEW_5_WORST') == 2
    assert scale_from_label('Severity (1 = MOST SEVERE):') == 'OLD_1_WORST'
    assert scale_from_label('Severity (5 = MOST SEVERE, new WSH matrix):') == 'NEW_5_WORST'
    assert resolve_scale(date(2025,7,4), '')[0] == 'UNKNOWN'
    assert resolve_scale(date(2025,7,11), 'Severity (5 = MOST SEVERE)')[0] == 'NEW_5_WORST'
    assert parse_date('01/07/2024') == date(2024,7,1)
    print('All severity-cutover unit checks passed')


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--images-dir', type=Path, help='Folder of incident-report JPG/PNG photographs')
    ap.add_argument('--out-dir', type=Path, default=Path('data/processed/incident_reports'))
    ap.add_argument('--env-file', type=Path, default=Path('.env'))
    ap.add_argument('--tesseract-exe', default='', help='Windows path to tesseract.exe')
    ap.add_argument('--debug-crops', action='store_true', help='Save cropped field images for diagnosis')
    ap.add_argument('--commit', action='store_true', help='Write to MySQL staging table')
    ap.add_argument('--self-test', action='store_true')
    args = ap.parse_args()
    if args.self_test:
        self_test()
        return 0
    if not args.images_dir or not args.images_dir.is_dir():
        ap.error('--images-dir must be an existing directory')
    load_dotenv(args.env_file, override=False)
    if args.tesseract_exe:
        pytesseract.pytesseract.tesseract_cmd = args.tesseract_exe
    elif os.name == 'nt':
        candidate = Path(r'C:\Program Files\Tesseract-OCR\tesseract.exe')
        if candidate.exists():
            pytesseract.pytesseract.tesseract_cmd = str(candidate)
    try:
        print('Tesseract:', pytesseract.get_tesseract_version())
    except Exception as exc:
        raise RuntimeError('Tesseract not installed or executable path is incorrect') from exc
    paths = sorted([p for p in args.images_dir.iterdir() if p.suffix.lower() in ('.jpg','.jpeg','.png')])
    if not paths:
        ap.error('No JPEG/PNG files in images directory')
    args.out_dir.mkdir(parents=True, exist_ok=True)
    debug_dir = args.out_dir / 'debug_crops' if args.debug_crops else None
    if debug_dir:
        debug_dir.mkdir(parents=True, exist_ok=True)
    records: list[dict] = []
    failures: list[str] = []
    for p in paths:
        try:
            r = extract_one(p, debug_dir)
            records.append(r)
            print(f'{p.name}: {r["report_no"]} | {r["incident_date"]} | '
                  f'raw={r["severity_raw"]}, scale={r["severity_scale"]}, '
                  f'normalized={r["severity_5_worst"]} | flags={len(r["extraction_flags"])}')
        except Exception as exc:
            failures.append(f'{p.name}: {type(exc).__name__}: {exc}')
            print('EXTRACTION FAILURE:', failures[-1], file=sys.stderr)
    write_outputs(records, args.out_dir)
    if failures:
        (args.out_dir / 'incident_reports_failures.txt').write_text('\n'.join(failures)+'\n', encoding='utf-8')
    print(f'Extracted {len(records)} of {len(paths)} images; '
          f'preview/review files in {args.out_dir}')
    if args.commit:
        inserted, skipped, errors = upload_mysql(records)
        print(f'MySQL staging: inserted={inserted}, identical_skipped={skipped}, conflicts={len(errors)}')
        if errors:
            (args.out_dir / 'incident_reports_mysql_conflicts.txt').write_text(
                '\n'.join(errors)+'\n', encoding='utf-8')
            for error in errors:
                print('DB REVIEW REQUIRED:', error, file=sys.stderr)
        return 1 if errors or failures else 0
    print('DRY-RUN ONLY. Use --commit after checking preview/review files; the staging table is created automatically.')
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
