"""Check local PDF bytes, catalog exports and existing-library registration."""
from pathlib import Path
import hashlib
import re
import unittest
from collect import ROOT, LIBRARY, load
from import_wos import parse, match_records


class ImportTests(unittest.TestCase):
    def test_ris_identity(self):
        records = parse('TY  - JOUR\nTI  - Integer model\nDO  - https://doi.org/10.1234/TEST\nAN  - WOS:000123\nER  - \n')
        matches, pending = match_records(records, [dict(id='paper1', doi='10.1234/test', title='Integer model')])
        self.assertEqual(len(matches), 1)
        self.assertFalse(pending)

    def test_no_accession_is_not_wos(self):
        records = parse('TY  - JOUR\nTI  - Integer model\nDO  - 10.1234/test\nER  - \n')
        matches, pending = match_records(records, [dict(id='paper1', doi='10.1234/test', title='Integer model')])
        self.assertFalse(matches)
        self.assertEqual(len(pending), 1)

    def test_tagged_multiline_title(self):
        records = parse('FN Clarivate\nPT J\nTI Integer model\n   and hardware\nDI 10.1234/test\nUT WOS:000123\nER\nEF\n')
        self.assertEqual(records[0]['title'], 'Integer model and hardware')
        self.assertEqual(records[0]['wos_ut'], 'WOS:000123')


def check():
    catalog = load(ROOT / 'catalog.json')
    records = catalog['records']
    assert len(records) == len({r['id'] for r in records}) == 20
    assert catalog['wos_access']['http_status'] == 403
    assert catalog['wos_access']['wos_result_count'] is None
    for row in records:
        assert row['wos_status'].startswith('not_verified')
        if row.get('pdf'):
            p = Path(row['pdf']['path'])
            assert p.read_bytes().startswith(b'%PDF-')
            assert hashlib.sha256(p.read_bytes()).hexdigest() == row['pdf']['sha256'], row['id']
            assert row['pdf']['pages'] > 0
    assert len(re.findall(r'^TY  - ', (ROOT / 'references.ris').read_text(encoding='utf-8'), re.M)) == 20
    assert len(re.findall(r'^@misc\{', (ROOT / 'references.bib').read_text(encoding='utf-8'), re.M)) == 20
    registration = load(ROOT / 'library_registration.json')
    existing = Path(registration['index']).parent
    combined = load(existing / 'catalog_current.json')
    assert sum(r['id'].startswith('AI-20261021-') for r in combined) == 20
    assert len(combined) >= registration['total']  # Other collections may grow later.
    assert (LIBRARY / 'index.html').exists()
    print('PASS library/PDF hashes, 20 citation exports and main-index registration')


if __name__ == '__main__':
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(ImportTests))
    if not result.wasSuccessful():
        raise SystemExit(1)
    check()
