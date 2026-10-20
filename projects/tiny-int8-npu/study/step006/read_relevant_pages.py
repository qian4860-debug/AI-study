from pathlib import Path
import json,logging
from pypdf import PdfReader
logging.getLogger('pypdf').setLevel(logging.ERROR)
root=Path(__file__).resolve().parent/'research'
catalog={r['id']:r for r in json.loads((root/'catalog.json').read_text(encoding='utf-8'))}
selected={
 'ai_compiler':[45,46,306,307,308,309,310,311,312],
 'tvm':[87,88,89,133,134,138,139,140],
 'llvm':[178,185,186,295,296],
 'gpu':[13,14],
 'cs217_roofline':[4,5,6,9,11,12,18],
 'cs217_eyeriss':[21,23,24,25,26,100],
 'cs231n_4':[82,83,84,85,86,87,88,89,90,91,92,93,94],
 'cs231n_8':[41,121],
 'cs231n_6':[24,35,49,88],
}
for key,pages in selected.items():
    reader=PdfReader(catalog[key]['path'])
    records=[dict(pdf_page=i,text=reader.pages[i-1].extract_text() or '') for i in pages]
    (root/f'{key}_selected.json').write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf-8')
    print(key,[(r['pdf_page'],len(r['text'])) for r in records],flush=True)
