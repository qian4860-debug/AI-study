"""Read-only source inspection; run with the bundled Python/pypdf runtime."""
from pathlib import Path
import json,hashlib
from pypdf import PdfReader
ROOT=Path(__file__).resolve().parent
OUT=ROOT/'research';OUT.mkdir(exist_ok=True)
BASE=Path('C:/Users/11725/Desktop/学习资料')
sources={
 'gpu':BASE/'a805/L333/GPU设计基础.pdf',
 'ai_compiler':BASE/'AI编译器开发指南/芯科技前沿技术丛书  AI编译器开发指南-- isbn13 9787111716747.pdf',
 'llvm':BASE/'LLVM编译器原理与实践/芯科技前沿技术丛书  LLVM编译器原理与实践-- isbn13 9787111763543.pdf',
 'tvm':BASE/'TVM编译器原理与实践/芯科技前沿技术丛书  TVM编译器原理与实践-- isbn13 9787111739128.pdf',
 'cs217_matrix':BASE/'stanford/cs217/CS217_Stanford_Lec3_MatrixComp_Ardavan.pdf',
 'cs217_roofline':BASE/'stanford/cs217/CS217_Stanford_Lec6_2_Roofline_TPU_Kunle.pdf',
 'cs217_mlp':BASE/'stanford/cs217/CS217_Stanford_Lec7_MLP-CNN_Ardavan.pdf',
 'cs217_eyeriss':BASE/'stanford/cs217/CS217_Stanford_Lec8_Eyeriss_Yu-Hsin.pdf',
 'cs231n_4':BASE/'stanford/cs231n/cs231n_2017_lecture4.pdf',
 'cs231n_6':BASE/'stanford/cs231n/cs231n_2017_lecture6.pdf',
 'cs231n_8':BASE/'stanford/cs231n/cs231n_2017_lecture8.pdf',
}
catalog=[]
for key,path in sources.items():
    reader=PdfReader(path)
    count=len(reader.pages)
    indices=range(count) if key.startswith('cs') else range(min(32,count))
    records=[]
    for i in indices:
        records.append({'pdf_page':i+1,'text':reader.pages[i].extract_text() or ''})
    (OUT/f'{key}.json').write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf-8')
    catalog.append(dict(id=key,path=str(path),pages=count,inspected_pages=len(records),
                        extracted_characters=sum(len(r['text']) for r in records),sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    print(key,count,catalog[-1]['extracted_characters'],flush=True)
(OUT/'catalog.json').write_text(json.dumps(catalog,ensure_ascii=False,indent=2),encoding='utf-8')
