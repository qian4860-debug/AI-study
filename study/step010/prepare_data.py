"""UCI HAR: reproducible 18-column derivative; never execute downloaded code."""
from pathlib import Path
import argparse
import csv
import hashlib
import io
import json
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parent
PRIMARY_URL = 'https://archive.ics.uci.edu/static/public/240/human+activity+recognition+using+smartphones.zip'
URL = 'https://d396qusza40orc.cloudfront.net/getdata%2Fprojectfiles%2FUCI%20HAR%20Dataset.zip'
PAGE = 'https://archive.ics.uci.edu/dataset/240/human+activity+recognition+using+smartphones'
FEATURES = [f'{group}-{stat}()-{axis}' for group in ['tBodyAcc', 'tGravityAcc', 'tBodyGyro']
            for stat in ['mean', 'std'] for axis in 'XYZ']


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def save(path, value):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n', encoding='utf-8', newline='\n')


def read_rows(path):
    with Path(path).open(newline='', encoding='utf-8') as f:
        return list(csv.DictReader(f))


def check_data():
    p = load(ROOT / 'data/provenance.json')
    for name, expected in p['derivative_sha256'].items():
        if sha(ROOT / 'data' / name) != expected:
            raise ValueError('modified dataset derivative: ' + name)
    return p


def extract(archive):
    # Existing provenance pins the transport archive; an upstream change is rejected.
    prior = ROOT / 'data/provenance.json'
    outer_sha = sha(archive)
    if prior.exists() and load(prior)['archive_sha256'] != outer_sha:
        raise ValueError('pinned archive changed; investigate before replacing data')
    with zipfile.ZipFile(archive) as outer:
        if 'UCI HAR Dataset/features.txt' in outer.namelist():
            payload = Path(archive).read_bytes()
        else:
            inner_name = next(n for n in outer.namelist() if n.endswith('UCI HAR Dataset.zip'))
            payload = outer.read(inner_name)
    source_hashes = {}
    with zipfile.ZipFile(io.BytesIO(payload)) as inner:
        prefix = 'UCI HAR Dataset/'

        def get(name):
            blob = inner.read(prefix + name)
            source_hashes[name] = hashlib.sha256(blob).hexdigest()
            # Legacy README contains Latin-1 author/location characters.
            return blob.decode('latin-1')

        feature_text = get('features.txt')
        mapping = {line.split(maxsplit=1)[1]: int(line.split()[0]) - 1 for line in feature_text.splitlines()}
        columns = [mapping[n] for n in FEATURES]
        for n in ['README.txt', 'features_info.txt', 'activity_labels.txt', 'features.txt']:
            target = ROOT / 'data' / n
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(get(n), encoding='utf-8', newline='\n')
        counts = {}
        for split, expected in [('train', 7352), ('test', 2947)]:
            x = get(f'{split}/X_{split}.txt').splitlines()
            y = get(f'{split}/y_{split}.txt').split()
            subjects = get(f'{split}/subject_{split}.txt').split()
            assert len(x) == len(y) == len(subjects) == expected
            with (ROOT / f'data/{split}.csv').open('w', encoding='utf-8', newline='') as f:
                writer = csv.writer(f, lineterminator='\n')
                writer.writerow(['source_row', 'subject', 'label', *FEATURES])
                for i, (row, label, subject) in enumerate(zip(x, y, subjects)):
                    values = row.split()
                    assert len(values) == 561
                    writer.writerow([i, int(subject), int(label) - 1, *[values[j] for j in columns]])
            counts[split] = expected
    names = ['train.csv', 'test.csv', 'README.txt', 'features_info.txt', 'activity_labels.txt', 'features.txt']
    result = dict(dataset='UCI HAR', doi='10.24432/C54S4K', source_page=PAGE, download_url=URL,
                  primary_download_url=PRIMARY_URL, transport='Public Coursera course distribution, dated 2014-01-15',
                  byte_comparison_with_current_uci_archive=False,
                  current_uci_page_license='CC BY 4.0', license_url='https://creativecommons.org/licenses/by/4.0/',
                  archive_readme_terms='2012 README requires publication citation and prohibits commercial use',
                  project_use='local educational experiment; original README retained; no commercial permission inferred for this archive',
                  creators=['Jorge Reyes-Ortiz', 'Davide Anguita', 'Alessandro Ghio', 'Luca Oneto', 'Xavier Parra'],
                  archive_sha256=outer_sha, inner_zip_sha256=hashlib.sha256(payload).hexdigest(),
                  source_member_sha256=source_hashes, counts=counts,
                  feature_names=FEATURES, feature_indices_1based=[j + 1 for j in columns],
                  changes='18 named columns selected verbatim; labels 1..6 mapped to 0..5; source row/subject retained; Latin-1 docs converted to UTF-8',
                  derivative_sha256={n: sha(ROOT / 'data' / n) for n in names})
    save(prior, result)
    print('PASS UCI HAR extraction', counts, 'columns', [j + 1 for j in columns])


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--download', action='store_true')
    parser.add_argument('--archive', type=Path)
    args = parser.parse_args()
    archive = args.archive or ROOT / 'cache/uci_har_course.zip'
    if args.download:
        archive.parent.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(URL, archive)
    if args.archive or args.download:
        extract(archive)
    else:
        print('PASS dataset hashes', check_data()['counts'])
