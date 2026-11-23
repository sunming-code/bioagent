"""Build a portable, frontend-only Pages ZIP from explicitly selected public assets."""
import argparse
import base64
from collections import Counter
import csv
import hashlib
import json
from pathlib import Path
import re
from zipfile import ZIP_DEFLATED, ZipFile

from egene_pipeline.gdgpt_graph import render_graph
from egene_pipeline.gdgpt_report import render_plain, render_professional
from . import catalog


HERE = Path(__file__).resolve().parent
EXAMPLE_HASHES = {'report.json': '66e156f0d2ef01c468efbc8c656960b4d8b8ffd5835c832912f608b92d218ac7',
                  'gdgpt_input.json': 'cac450bdeb904eb60b8789c25a08da8b4b0b0bce24aa0e23d845386bc67ff4c8'}


def assets():
    files = {name: (HERE / 'public_demo' / name).read_bytes() for name in ('index.html', 'demo.js', 'demo.css')}
    files['studio.css'] = (HERE / 'static/studio.css').read_bytes()
    for name, digest in EXAMPLE_HASHES.items():
        data = (HERE / 'static/example' / name).read_bytes()
        if hashlib.sha256(data).hexdigest() != digest or json.loads(data)['sample_id'] != 'SYNTHETIC':
            raise ValueError('Public release requires the reviewed synthetic fixture: ' + name)
        files['reports/' + name] = data
    record = json.loads(files['reports/report.json'])
    graph = render_graph(record)
    for name, text in [('report.html', render_professional(record)), ('report_plain.html', render_plain(record)), ('report_graph.html', graph)]:
        files['reports/' + name] = text.encode()
    counts = Counter((row['SUPERPOP'], row['SUBPOP']) for row in catalog.dataset('panel'))
    hpo = [[row[key] for key in ('HPO', 'English', 'aliases')] for row in catalog.dataset('hpo')]
    with (HERE / 'references/igsr_frequency.tsv').open() as handle:
        frequencies = [[row[key] for key in ('CHROM', 'POS', 'REF', 'ALT', 'AF', 'AF_EUR', 'AF_EAS', 'AF_AFR', 'AF_AMR', 'AF_SAS')] for row in csv.DictReader(handle, delimiter='\t')]
    with (catalog.ROOT / catalog.EDGES).open() as handle:
        edges = sorted({tuple(row[key] for key in ('source_name', 'source_id', 'target_name', 'target_type', 'display_relation', 'source')) for row in csv.DictReader(handle)
                        if row['source_name'] in ('BRCA1', 'F5') and row['source_type'] == 'Gene'
                        and row['target_type'] in ('Disease', 'Pathway') and row['source'] == 'NCBI'})
    public = {'panel': [[group, population, count] for (group, population), count in sorted(counts.items())],
              'hpo': hpo, 'af': frequencies, 'edges': edges}
    files['reference.js'] = ('window.BioAgentReference=' + json.dumps(public, ensure_ascii=False, separators=(',', ':')).replace('<', '\\u003c') + ';\n').encode()
    scripts = re.findall(r'<script>(.*?)</script>', graph, re.S)
    hashes = ' '.join("'sha256-" + base64.b64encode(hashlib.sha256(script.encode()).digest()).decode() + "'" for script in scripts)
    files['_headers'] = ("/*\n  X-Content-Type-Options: nosniff\n  Referrer-Policy: no-referrer\n  Content-Security-Policy: "
                         f"default-src 'none'; script-src 'self' {hashes}; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
                         "connect-src 'none'; form-action 'none'; base-uri 'none'; frame-ancestors 'none'\n").encode()
    return files


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('zip_path', type=Path)
    options = parser.parse_args()
    files = assets()
    with ZipFile(options.zip_path, 'w', compression=ZIP_DEFLATED) as archive:
        for name, content in sorted(files.items()):
            archive.writestr(name, content)
    print(options.zip_path.resolve())


if __name__ == '__main__':
    main()
