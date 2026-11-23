"""Install the upstream-pinned HPO gene/disease lookup table, without credentials."""
import hashlib
import json
from pathlib import Path
import urllib.request


def main():
    root = Path(__file__).resolve().parents[1] / '2_egene'
    target = root / 'data/disease/genes_to_disease.txt'
    lock = json.loads((root / 'config/disease_sources.lock.json').read_text())
    spec = next(item for item in lock['resources'] if item['name'] == target.name)
    if target.is_file() and hashlib.sha256(target.read_bytes()).hexdigest() == spec['sha256']:
        return
    with urllib.request.urlopen(spec['url'], timeout=25) as response:
        data = response.read(spec['bytes'] + 1)
    if len(data) != spec['bytes'] or hashlib.sha256(data).hexdigest() != spec['sha256']:
        raise ValueError('HPO reference does not match the upstream lock.')
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_suffix('.tmp')
    temp.write_bytes(data)
    temp.replace(target)


if __name__ == '__main__':
    main()
