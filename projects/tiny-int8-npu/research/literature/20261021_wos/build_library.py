"""Build offline bibliography and register the collection without copying PDFs to Git."""
from pathlib import Path
import csv
import hashlib
import html
import json
import re
from collect import ROOT, LIBRARY, load, save, inspect_pdf

EXISTING = Path('C:/Users/11725/Documents/ChatGPT/设计规范/reference_library')
CATEGORY = dict(systems='系统与架构', circuits='电路与FPGA', deployment='编译与部署', quantization='量化算法', imu='IMU识别', gyro='陀螺算法')
USES = dict(survey='系统框架：计算、存储、数据移动与精度', eyeriss='同资源约束下比较数据流与输入/权重复用',
            eyeriss2='网络形状、互连与阵列利用率', roofline='计算/访存瓶颈；区分技术报告与期刊版本',
            dsp='DSP打包符号修正；区分精确模式与近似Overpacking', finn='二值网络流式硬件，不直接等同INT8',
            finnr='量化网络资源与性能设计空间', hls4ml='模型到HLS、位宽与低延迟实现',
            tvm='图优化、算子调度和硬件后端', jacob='整数尺度、偏置、重定标与舍入', hawq='后续混合精度选择依据',
            mcunet='模型/执行引擎协同与片内内存约束', har='第010步数据来源与受试者划分',
            denoise='陀螺去噪、姿态损失和独立轨迹评估', huang='时序补偿网络与静态MLP任务差异',
            temp='传统多项式/BP温度补偿基线', kalman='自适应滤波补偿基线与物理假设',
            transformer='关注在线输入可获得性及online/卷期年份差异', codesign='量化、QONNX与FPGA/ASIC生成',
            dpvsa='2026双精度DSP打包线索；全文未取得时仅保留书目')
ACCESS = dict(downloaded_fulltext='新下载公开PDF', existing_local_fulltext='已有本地全文',
              metadata_only_fulltext_not_obtained='仅书目，全文未取得')


def exports(records):
    bib, ris = [], []
    for r in records:
        authors = r.get('authors', [])
        fields = dict(title=r['title'], year=str(r['year']), url=r.get('source_url') or
                      ('https://doi.org/' + r['doi'] if r.get('doi') else 'https://arxiv.org/abs/' + r['arxiv'] if r.get('arxiv') else r['pdf_urls'][0]))
        if authors:
            fields['author'] = ' and '.join(authors)
        if r.get('doi'):
            fields['doi'] = r['doi']
        if r.get('venue'):
            fields['journal'] = r['venue']
        if r.get('arxiv'):
            fields.update(eprint=r['arxiv'], archivePrefix='arXiv')
        fields['note'] = 'WoS indexing unverified; PDF/metadata status recorded separately; not full-paper reviewed'
        bib.append('@misc{' + r['id'].replace('-', '') + ',\n' + ',\n'.join(f'  {k} = {{{v}}}' for k, v in fields.items()) + '\n}')
        entry = ['TY  - GEN', 'ID  - ' + r['id'], 'TI  - ' + r['title'], 'PY  - ' + str(r['year'])]
        entry += ['AU  - ' + a for a in authors]
        if r.get('doi'):
            entry.append('DO  - ' + r['doi'])
        entry += ['UR  - ' + fields['url'], 'N1  - WoS unverified; ' + ACCESS[r['access_status']], 'ER  - ']
        ris.append('\n'.join(entry))
    return '\n\n'.join(bib) + '\n', '\n\n'.join(ris) + '\n'


def page(records):
    cards = []
    for r in records:
        urls = [u for u in [r.get('source_url'), 'https://doi.org/' + r['doi'] if r.get('doi') else None,
                            'https://arxiv.org/abs/' + r['arxiv'] if r.get('arxiv') else None] if u]
        links = ' '.join(f'<a href="{html.escape(u, quote=True)}" target="_blank" rel="noopener">来源{i+1}</a>' for i, u in enumerate(urls))
        if r.get('pdf'):
            p = Path(r['pdf']['path'])
            links += f' <a href="{html.escape(p.as_uri(), quote=True)}">打开本地PDF（{r["pdf"]["pages"]}页）</a>'
        text = ' '.join([r['title'], CATEGORY[r['category']], r.get('doi', ''), ' '.join(r.get('authors', []))])
        cards.append(f'''<article data-search="{html.escape(text.lower(), quote=True)}" data-category="{r['category']}">
<h2>{r['id']} · {html.escape(r['title'])}</h2><p>{r['year']} · {CATEGORY[r['category']]} · {ACCESS[r['access_status']]}</p>
<p>{html.escape('; '.join(r.get('authors', [])) or '作者元数据待补充')}<br>{html.escape(r.get('venue', ''))}</p>
<p>项目阅读问题：{html.escape(USES[r['slug']])}</p><p>WoS：未核验；阅读：仅文件/首页题名检查，未精读全文。</p>
<p>{links}</p></article>''')
    options = ''.join(f'<option value="{k}">{v}</option>' for k, v in CATEGORY.items())
    return '''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>AI Study文献专题</title><style>body{font:16px/1.7 "Microsoft YaHei",sans-serif;max-width:1150px;margin:30px auto;padding:0 20px;color:#162133}h1{font-size:28px}h2{font-size:19px}article{border-top:1px solid #ccd5df;padding:18px 0}input,select{font:inherit;padding:9px;margin:6px 6px 6px 0}a{color:#1858a6;margin-right:12px}.notice{background:#fff4d8;padding:16px}header{position:sticky;top:0;background:white;padding:10px 0}</style>
<h1>AI Study：系统、电路、算法与IMU文献</h1><p class="notice">Web of Science访问返回403，本页为按关键词整理的公开来源候选，不是WoS检索导出。全文取得、版本身份、WoS核验和精读状态分别记录。</p>
<header><input id="q" size="36" placeholder="搜索题名、作者、DOI"><select id="c"><option value="">全部方向</option>''' + options + '''</select><span id="count"></span></header>''' + '\n'.join(cards) + '''
<script>const q=document.querySelector('#q'),c=document.querySelector('#c');function show(){let n=0;document.querySelectorAll('article').forEach(a=>{const yes=(!c.value||a.dataset.category===c.value)&&a.dataset.search.includes(q.value.toLowerCase());a.hidden=!yes;if(yes)n++});document.querySelector('#count').textContent=`显示 ${n} 条`}q.oninput=c.onchange=show;show()</script></html>'''


def integrate(records):
    current_path = EXISTING / 'catalog_current.json'
    main_index = EXISTING / 'index.html'
    current = load(current_path)
    old = [r for r in current if not r.get('id', '').startswith('AI-20261021-')]
    additions = []
    for i, r in enumerate(records):
        urls = list(dict.fromkeys([u for u in [
            'https://doi.org/' + r['doi'] if r.get('doi') else None,
            'https://arxiv.org/abs/' + r['arxiv'] if r.get('arxiv') else None,
            r.get('source_url'), r.get('download_url')] if u]))
        additions.append(dict(id=r['id'], origin='AI_study_keyword_primary_source_search', line=i+1,
            section='AI Study文献专题', category='AI Study｜' + CATEGORY[r['category']], kind='paper',
            title_as_listed=r['title'], canonical_title=r['title'], listed_author_or_poster='',
            verified_author='; '.join(r.get('authors', [])) or '待补充', url_as_listed=urls[0] if urls else '',
            identity_status=r['metadata_status'], access_status=ACCESS[r['access_status']], verified_urls=urls,
            local_candidates=[dict(path=r['pdf']['path'], status='PDF文件/首页题名核对；未精读')] if r.get('pdf') else [],
            notes=['WoS未核验，未取得WoS检索导出。', USES[r['slug']], '版本：' + r.get('version', '全文未取得')],
            reviewed_on='2026-10-21', doi=r.get('doi', ''), wos_status=r['wos_status']))
    combined = old + additions
    text = main_index.read_text(encoding='utf-8-sig')
    assert re.search(r'const rows=.*?;const q=', text, flags=re.S), 'existing index schema changed'
    before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in [current_path, main_index]}
    text = re.sub(r'const rows=.*?;const q=', lambda _: 'const rows=' + json.dumps(combined, ensure_ascii=False) + ';const q=', text, count=1, flags=re.S)
    text = re.sub(r'<h1>.*?</h1>', '<h1>收藏与AI Study参考资料库</h1>', text, count=1, flags=re.S)
    text = re.sub(r'<p>.*?</p>', f'<p>{len(combined)}条来源记录（既有{len(old)}条，AI Study新增{len(additions)}条）。身份核实、全文取得、WoS核验和精读状态分别记录。</p>', text, count=1, flags=re.S)
    link = '<p id="ai-study-collection"><a href="ai_study_20261021/index.html">打开AI Study专题：分类、全文与检索状态</a></p>'
    if 'id="ai-study-collection"' not in text:
        text = text.replace('<header>', link + '<header>', 1)
    save(current_path, combined)
    main_index.write_text(text, encoding='utf-8', newline='\n')
    collection = EXISTING / 'ai_study_20261021'
    collection.mkdir(exist_ok=True)
    (collection / 'index.html').write_text(page(records), encoding='utf-8', newline='\n')
    save(collection / 'catalog.json', load(ROOT / 'catalog.json'))
    readme = EXISTING / 'README.md'
    description = readme.read_text(encoding='utf-8-sig')
    if '## AI Study文献专题（2026-10-21）' not in description:
        description += '\n\n## AI Study文献专题（2026-10-21）\n\n本次保留原285条记录，另收录20条AI Study候选，统一入口index.html与catalog_current.json当前合计305条。原catalog.json与catalog.csv历史快照不改写。新专题见ai_study_20261021/index.html，PDF保存在D:/学习资料/资料/AI_Study_文献库/20261021。WoS入口403，尚未取得WoS站内结果；公开来源候选、全文取得与阅读状态分开记录。\n'
        readme.write_text(description, encoding='utf-8', newline='\n')
    assert load(current_path)[:len(old)] == old
    return dict(prior_records=len(old), added=len(additions), total=len(combined), prior_file_sha256=before,
                index=main_index.as_posix(), collection=(collection / 'index.html').as_posix())


def main():
    catalog = load(ROOT / 'catalog.json')
    records = catalog['records']
    assert len({r['id'] for r in records}) == len(records)
    for r in records:
        if r.get('pdf'):
            checked = inspect_pdf(Path(r['pdf']['path']), r)
            assert checked['sha256'] == r['pdf']['sha256']
    bib, ris = exports(records)
    for folder in [ROOT, LIBRARY]:
        folder.mkdir(parents=True, exist_ok=True)
        (folder / 'references.bib').write_text(bib, encoding='utf-8', newline='\n')
        (folder / 'references.ris').write_text(ris, encoding='utf-8', newline='\n')
        (folder / 'index.html').write_text(page(records), encoding='utf-8', newline='\n')
        with (folder / 'catalog.csv').open('w', encoding='utf-8-sig', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=['id', 'category', 'title', 'year', 'doi', 'access_status', 'wos_status', 'pdf_path'])
            writer.writeheader()
            for r in records:
                writer.writerow({**{k: r.get(k, '') for k in writer.fieldnames if k != 'pdf_path'}, 'pdf_path': r.get('pdf', {}).get('path', '')})
    integration = integrate(records)
    save(ROOT / 'library_registration.json', integration)
    skill = Path('C:/Users/11725/.codex/skills/ic-reference-library/references')
    catalog_path = skill / 'catalog.json'
    sources = load(catalog_path)
    name = 'AI Study系统、电路、算法与IMU文献专题'
    sources = [r for r in sources if r.get('name') != name]
    sources.append(dict(category='AI处理器与GPU架构', name=name, path=LIBRARY.as_posix(), exists=True, type='folder',
                        index=(LIBRARY / 'index.html').as_posix(), wos_status='未核验；smart-search访问403'))
    save(catalog_path, sources)
    md = skill / 'catalog.md'
    text = md.read_text(encoding='utf-8-sig')
    if '## AI Study文献专题（2026-10-21）' not in text:
        text += '\n\n## AI Study文献专题（2026-10-21）\n\n- ' + LIBRARY.as_posix() + '；index.html、catalog.json和RIS/BibTeX。按关键词公开检索，WoS入口403，未取得WoS站内结果；下载/已有全文、书目和阅读状态分别记录。已接入现有reference_library主索引。\n'
        md.write_text(text, encoding='utf-8', newline='\n')
    summary = load(ROOT / 'collection_result.json')
    summary.update(registration=integration, pdf_sha256={r['id']: r['pdf']['sha256'] for r in records if r.get('pdf')})
    save(ROOT / 'collection_result.json', summary)
    print('PASS registered collection', integration['total'], 'total records')


if __name__ == '__main__':
    main()
