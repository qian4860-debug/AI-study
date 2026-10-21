"""Match user-exported WoS RIS/tagged text to this collection, preserving evidence."""
from pathlib import Path
import argparse
import difflib
import hashlib
import json
import re
from collect import ROOT, load, norm, save


def parse(text):
    records, current, last = [], {}, None
    is_ris = bool(re.search(r'^TY\s+- ', text, re.M))
    for line in text.splitlines():
        match = re.match(r'^([A-Z0-9]{2})\s+-\s?(.*)$', line) if is_ris else re.match(r'^([A-Z0-9]{2})\s(.*)$', line)
        if line.strip() == 'ER' or (match and match[1] == 'ER'):
            if current:
                records.append(current)
            current, last = {}, None
        elif match:
            last = match[1]
            current[last] = (current.get(last, '') + ' ' + match[2]).strip()
        elif last and line.startswith(' '):
            current[last] += ' ' + line.strip()
    if current.get('TI'):
        records.append(current)
    result = []
    for row in records:
        if not row.get('TI'):
            continue
        doi = re.sub(r'^https?://(?:dx\.)?doi.org/', '', row.get('DO', row.get('DI', '')), flags=re.I).strip().lower()
        accession = row.get('UT', row.get('AN', ''))
        result.append(dict(title=row['TI'], doi=doi, wos_ut=accession if 'WOS:' in accession.upper() else '',
                           source=row.get('DB', ''), year=row.get('PY', '')))
    return result


def match_records(exported, catalog):
    matches, pending = [], []
    for row in exported:
        if not row['wos_ut']:
            pending.append(dict(**row, reason='No WoS accession identifier; not accepted as WoS verification'))
            continue
        exact = [r for r in catalog if row['doi'] and row['doi'] == r.get('doi', '').lower()]
        if not exact:
            exact = [r for r in catalog if difflib.SequenceMatcher(None, norm(row['title']), norm(r['title'])).ratio() >= .94]
        if len(exact) == 1:
            matches.append(dict(id=exact[0]['id'], **row))
        else:
            pending.append(dict(**row, reason='No unique collection match'))
    return matches, pending


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('export_file', type=Path)
    args = parser.parse_args()
    blob = args.export_file.read_bytes()
    for encoding in ['utf-8-sig', 'utf-16', 'gb18030']:
        try:
            text = blob.decode(encoding)
            break
        except UnicodeError:
            continue
    else:
        raise ValueError('unsupported export text encoding')
    records = parse(text)
    if not records:
        raise ValueError('No RIS/WoS tagged records found; export Full Record as plain text or RIS')
    matches, pending = match_records(records, load(ROOT / 'catalog.json')['records'])
    # Produce evidence for review; never silently overwrite the initial access log.
    save(ROOT / 'wos_export_matches.json', dict(export_sha256=hashlib.sha256(blob).hexdigest(),
          imported_records=len(records), matches=matches, pending=pending,
          note='Export evidence only; original smart-search access remained blocked. Update collection statuses after reviewing matches.'))
    print('WoS export matches', len(matches), 'pending', len(pending))
