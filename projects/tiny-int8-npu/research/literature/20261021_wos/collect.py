"""Download public author/publisher PDFs; never label web candidates as WoS hits."""
from pathlib import Path
import argparse
import concurrent.futures
import difflib
import hashlib
import html
import json
import re
import threading
import time
import unicodedata
import urllib.parse
import urllib.request
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parent
LIBRARY = Path('D:/学习资料/资料/AI_Study_文献库/20261021')
LOCK = threading.Lock()
ARXIV_LAST = 0.
UA = 'AI-Study-Literature/1.0 (personal scholarly reference collection)'


def save(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')


def load(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def norm(text):
    return ''.join(c.lower() for c in unicodedata.normalize('NFKD', text) if c.isalnum())


def get(url, binary=False):
    global ARXIV_LAST
    if urllib.parse.urlsplit(url).hostname in ['arxiv.org', 'export.arxiv.org']:
        with LOCK:
            time.sleep(max(0., 3.1 - (time.monotonic() - ARXIV_LAST)))
            ARXIV_LAST = time.monotonic()
    req = urllib.request.Request(url, headers={'User-Agent': UA})
    with urllib.request.urlopen(req, timeout=30) as response:
        body = response.read(40 * 1024 * 1024 + 1)
        if len(body) > 40 * 1024 * 1024:
            raise ValueError('file exceeds 40MiB collection limit')
        return body if binary else body.decode('utf-8', errors='replace')


def metadata(seed):
    result = dict(title=seed['title'], year=seed['year'], doi=seed['doi'], authors=[], venue='',
                  metadata_status='seed identity; publisher metadata pending', metadata_sources=[])
    errors = []
    candidates = []
    if seed['doi']:
        try:
            url = 'https://api.crossref.org/works/' + urllib.parse.quote(seed['doi'], safe='')
            candidates = [(url, json.loads(get(url))['message'])]
        except Exception as exc:
            errors.append(str(exc))
    if not candidates and seed['slug'] not in ['tvm', 'mcunet', 'har']:
        try:
            url = 'https://api.crossref.org/works?' + urllib.parse.urlencode({'query.title': seed['title'], 'rows': 3})
            candidates = [(url, item) for item in json.loads(get(url))['message']['items']]
        except Exception as exc:
            errors.append(str(exc))
    for url, record in candidates:
        parts = [record.get('title', [''])[0]] + record.get('subtitle', [])
        title = html.unescape(re.sub(r'<[^>]+>', '', ': '.join(parts)))
        title = re.sub(r'\s+', ' ', title).strip()
        score = difflib.SequenceMatcher(None, norm(seed['title']), norm(title)).ratio()
        if score < .88:
            errors.append('rejected title mismatch: ' + title)
            continue
        result.update(title=title, doi=record['DOI'], authors=[
            ' '.join([a.get('given', ''), a.get('family', '')]).strip() or a.get('name', '')
            for a in record.get('author', [])], venue=record.get('container-title', [''])[0],
            metadata_status='DOI/title matched Crossref publisher deposit', metadata_sources=[url],
            publication_dates={k: record[k].get('date-parts') for k in ['published', 'published-print', 'published-online', 'issued'] if k in record},
            metadata_title_similarity=round(score, 4))
        date = record.get('published', record.get('issued', {})).get('date-parts', [[seed['year']]])
        result['year'] = date[0][0]
        break
    if not result['authors'] and seed['arxiv']:
        try:
            url = 'https://arxiv.org/abs/' + seed['arxiv']
            page = get(url)
            metas = re.findall(r'<meta\s+[^>]*name=["\']([^"\']+)["\'][^>]*content=["\']([^"\']*)', page, re.I)
            authors = [html.unescape(v) for k, v in metas if k == 'citation_author']
            titles = [html.unescape(v) for k, v in metas if k == 'citation_title']
            if titles and difflib.SequenceMatcher(None, norm(seed['title']), norm(titles[0])).ratio() >= .88:
                result.update(authors=authors, metadata_status='arXiv author metadata/title matched', metadata_sources=[url])
        except Exception as exc:
            errors.append(str(exc))
    if seed['slug'] == 'tvm' and not result['authors']:
        result.update(authors=['Tianqi Chen', 'Thierry Moreau', 'Ziheng Jiang', 'Lianmin Zheng', 'Eddie Yan',
                               'Haichen Shen', 'Meghan Cowan', 'Leyuan Wang', 'Yuwei Hu', 'Luis Ceze',
                               'Carlos Guestrin', 'Arvind Krishnamurthy'], venue='13th USENIX OSDI',
                      metadata_status='USENIX official BibTeX checked',
                      metadata_sources=['https://www.usenix.org/conference/osdi18/presentation/chen'])
    if seed['slug'] == 'har' and not result['authors']:
        result.update(authors=['Davide Anguita', 'Alessandro Ghio', 'Luca Oneto', 'Xavier Parra', 'Jorge L. Reyes-Ortiz'],
                      venue='ESANN 2013', metadata_status='ESANN official paper title/author entry',
                      metadata_sources=seed['pdf_urls'])
    result['metadata_notes'] = errors
    return result


def inspect_pdf(path, seed):
    blob = path.read_bytes()
    if not blob.startswith(b'%PDF-'):
        raise ValueError('not a PDF; possible HTML/login page')
    pdf = PdfReader(path)
    if not len(pdf.pages):
        raise ValueError('empty PDF')
    title_text = norm(pdf.pages[0].extract_text() or '')
    expected = norm(seed['title'])
    exact = expected in title_text
    if not exact:
        words = re.findall(r'[a-z]{4,}', seed['title'].lower())
        score = sum(norm(w) in title_text for w in set(words)) / max(1, len(set(words)))
    else:
        score = 1.
    if score < .75:
        raise ValueError('PDF title identity needs manual review, score=' + str(score))
    return dict(path=path.as_posix(), sha256=hashlib.sha256(blob).hexdigest(), pages=len(pdf.pages),
                bytes=len(blob), title_check='normalized exact title' if exact else 'title words; version wording may differ',
                title_check_score=round(score, 4), reading_status='file integrity and first-page title checked; full paper not reviewed')


def collect(seed):
    item = dict(seed)
    item.update(metadata(seed))
    item.update(wos_status='not_verified; smart-search HTTP403; no WoS export imported',
                discovery='keyword-guided primary-source web search; NOT a WoS search hit', attempts=[])
    if seed.get('local_pdf') and Path(seed['local_pdf']).exists():
        try:
            item['pdf'] = inspect_pdf(Path(seed['local_pdf']), seed)
            item['access_status'] = 'existing_local_fulltext'
            item['version'] = 'existing local article; original acquisition route not revalidated'
            print('LOCAL', seed['slug'], item['pdf']['pages'], flush=True)
            return item
        except Exception as exc:
            item['attempts'].append(dict(local_path=seed['local_pdf'], error=str(exc)))
    dest = LIBRARY / 'pdf' / f"{seed['id']}_{seed['slug']}.pdf"
    if dest.exists():
        try:
            item['pdf'] = inspect_pdf(dest, seed)
            item['access_status'] = 'downloaded_fulltext'
            item['version'] = 'cached public PDF; see previous run/source URL'
            prior_file = ROOT / 'catalog.json'
            if prior_file.exists():
                prior = next((r for r in load(prior_file)['records'] if r['id'] == seed['id']), None)
                if prior and prior.get('pdf', {}).get('sha256') == item['pdf']['sha256']:
                    for key in ['download_url', 'version', 'attempts']:
                        if key in prior:
                            item[key] = prior[key]
            return item
        except Exception:
            pass
    for url in dict.fromkeys(seed['pdf_urls']):
        try:
            blob = get(url, binary=True)
            if not blob.startswith(b'%PDF-'):
                raise ValueError('not PDF; rejected response')
            dest.parent.mkdir(parents=True, exist_ok=True)
            temporary = dest.with_suffix('.part')
            temporary.write_bytes(blob)
            check = inspect_pdf(temporary, seed)
            temporary.replace(dest)
            check['path'] = dest.as_posix()
            item.update(pdf=check, access_status='downloaded_fulltext', download_url=url,
                        version='author preprint' if 'arxiv.org' in url else 'public publisher/author-hosted PDF; see source/version')
            item['attempts'].append(dict(url=url, result='PDF verified'))
            print('DOWNLOADED', seed['slug'], check['pages'], flush=True)
            return item
        except Exception as exc:
            item['attempts'].append(dict(url=url, error=str(exc)))
    item['access_status'] = 'metadata_only_fulltext_not_obtained'
    print('METADATA ONLY', seed['slug'], flush=True)
    return item


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--retry-missing', action='store_true')
    args = parser.parse_args()
    seeds = load(ROOT / 'seeds.json')
    previous = {r['id']: r for r in load(ROOT / 'catalog.json')['records']} if args.retry_missing else {}
    pending = [s for s in seeds if not previous.get(s['id'], {}).get('pdf')]
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        fresh = {r['id']: r for r in pool.map(collect, pending)}
    records = [fresh.get(s['id']) or previous[s['id']] for s in seeds]
    for seed, record in zip(seeds, records):
        if args.retry_missing and seed['slug'] in ['finn', 'finnr']:
            record.update(metadata(seed))
    for record in records:
        if not record.get('doi') and not record.get('arxiv') and record['slug'] != 'har':
            record['metadata_status'] += '; DOI not resolved'
    results = dict(date='2026-10-21', wos_url='https://www.webofscience.com/wos/woscc/smart-search',
                   wos_access=dict(status='blocked', http_status=403, wos_result_count=None,
                                   explanation='No available node_repl/browser automation runtime; no authenticated WoS results obtained'),
                   records=records)
    save(ROOT / 'catalog.json', results)
    save(LIBRARY / 'catalog.json', results)
    summary = {status: sum(r['access_status'] == status for r in records) for status in
               ['downloaded_fulltext', 'existing_local_fulltext', 'metadata_only_fulltext_not_obtained']}
    save(ROOT / 'collection_result.json', dict(status='PARTIAL_WOS_ACCESS_BLOCKED', counts=summary,
                                              total=len(records), library=LIBRARY.as_posix()))
    print('COLLECTED', summary)


if __name__ == '__main__':
    main()
