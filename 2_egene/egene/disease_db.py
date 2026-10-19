"""Versioned HPO/HGNC disease association index; original resources stay intact."""
from __future__ import annotations

import argparse
from collections import Counter
import csv
import fcntl
import json
from pathlib import Path
import re
import sqlite3
import sys
import urllib.request

from .common import ROOT, checksum, now, write_json

DB_SCHEMA = "1.0"
QUOTED = re.compile(r'"((?:\\.|[^"\\])*)"')


def quoted(text: str) -> str | None:
    match = QUOTED.search(text)
    if not match:
        return None
    try:
        return json.loads('"' + match[1] + '"')
    except json.JSONDecodeError:
        return re.sub(r"\\(.)", r"\1", match[1])


def obo_terms(path: Path):
    term = None
    with path.open() as handle:
        for raw in handle:
            line = raw.rstrip("\n")
            if line.startswith("["):
                if term and term.get("id", "").startswith("HP:"):
                    yield term
                term = {"parents": [], "alt_ids": [], "names": [], "obsolete": False} if line == "[Term]" else None
            elif term is not None:
                if line.startswith("id: "):
                    term["id"] = line[4:]
                elif line.startswith("name: "):
                    term["name"] = line[6:]
                    term["names"].append(line[6:])
                elif line.startswith("is_a: HP:"):
                    term["parents"].append(line[6:].split()[0])
                elif line.startswith("alt_id: HP:"):
                    term["alt_ids"].append(line[8:])
                elif line == "is_obsolete: true":
                    term["obsolete"] = True
                elif line.startswith("replaced_by: HP:"):
                    term.setdefault("replacements", []).append(line[13:].split()[0])
                elif line.startswith("synonym: ") and " EXACT " in line:
                    name = quoted(line)
                    if name:
                        term["names"].append(name)
                elif line.startswith("property_value: ") and any(
                    value in line.split(" ", 2)[1] for value in ("label", "hasExactSynonym")
                ):
                    name = quoted(line)
                    if name:
                        term["names"].append(name)
        if term and term.get("id", "").startswith("HP:"):
            yield term


def table_rows(path: Path, required: set[str]):
    with path.open(newline="") as handle:
        reader = csv.DictReader((line for line in handle if not line.startswith("#")), delimiter="\t")
        if not reader.fieldnames or not required <= set(reader.fieldnames):
            raise ValueError(f"疾病资源表头不完整: {path.name}")
        for number, row in enumerate(reader, 2):
            if None in row or any(value is None for value in row.values()):
                raise ValueError(f"疾病资源列数异常: {path.name}:{number}")
            yield number, row


def disease_id(value: str) -> str:
    # MIM is a naming synonym, not a merge across distinct disease databases.
    return "OMIM:" + value[4:] if value.startswith("MIM:") else value


def build_index(directory: Path, target: Path) -> dict:
    temporary = target.with_suffix(".building.sqlite")
    if temporary.exists():
        temporary.unlink()
    db = sqlite3.connect(temporary)
    counts = Counter()
    try:
        db.executescript("""
            CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE terms (id TEXT PRIMARY KEY, data TEXT NOT NULL);
            CREATE TABLE diseases (id TEXT PRIMARY KEY, name TEXT NOT NULL);
            CREATE TABLE genes (symbol TEXT PRIMARY KEY, gene_id TEXT, hgnc_id TEXT);
            CREATE TABLE aliases (alias TEXT, symbol TEXT, kind TEXT, PRIMARY KEY(alias,symbol,kind));
            CREATE TABLE gene_disease (gene_id TEXT, symbol TEXT, disease_id TEXT, association_type TEXT,
                source TEXT, PRIMARY KEY(gene_id,symbol,disease_id,association_type,source));
            CREATE TABLE annotations (disease_id TEXT, hpo_id TEXT, negated INTEGER, aspect TEXT,
                frequency TEXT, reference TEXT, evidence TEXT, onset TEXT, sex TEXT, modifier TEXT,
                biocuration TEXT, line_number INTEGER);
        """)
        valid_terms = set()
        for term in obo_terms(directory / "hp-international.obo"):
            if not term.get("name"):
                raise ValueError(f"HPO 条目缺少名称: {term['id']}")
            db.execute("INSERT INTO terms VALUES (?,?)", (term["id"], json.dumps(term, ensure_ascii=False)))
            valid_terms.add(term["id"])
            counts["hpo_terms"] += 1
        for _, row in table_rows(directory / "hgnc_complete_set.tsv", {"symbol", "status", "entrez_id", "hgnc_id", "alias_symbol", "prev_symbol"}):
            if row["status"] != "Approved":
                continue
            symbol = row["symbol"]
            db.execute("INSERT INTO genes VALUES (?,?,?)", (symbol, row["entrez_id"], row["hgnc_id"]))
            for key in ("alias_symbol", "prev_symbol"):
                for alias in filter(None, row[key].split("|")):
                    db.execute("INSERT OR IGNORE INTO aliases VALUES (?,?,?)", (alias, symbol, key))
            counts["hgnc_genes"] += 1
        for _, row in table_rows(directory / "genes_to_disease.txt", {"ncbi_gene_id", "gene_symbol", "association_type", "disease_id", "source"}):
            identifier = disease_id(row["disease_id"])
            if row["association_type"] not in {"MENDELIAN", "POLYGENIC", "UNKNOWN"}:
                raise ValueError("HPO 出现未支持的基因—疾病关联类型")
            db.execute("INSERT OR IGNORE INTO diseases VALUES (?,?)", (identifier, identifier))
            db.execute("INSERT OR IGNORE INTO gene_disease VALUES (?,?,?,?,?)", (
                row["ncbi_gene_id"].removeprefix("NCBIGene:"), row["gene_symbol"], identifier,
                row["association_type"], row["source"]))
        for number, row in table_rows(directory / "phenotype.hpoa", {"database_id", "disease_name", "qualifier", "hpo_id", "aspect", "reference", "evidence", "frequency", "onset", "sex", "modifier", "biocuration"}):
            identifier = disease_id(row["database_id"])
            db.execute("INSERT INTO diseases VALUES (?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name", (identifier, row["disease_name"]))
            if row["hpo_id"] not in valid_terms:
                raise ValueError(f"疾病注释引用 HPO 中不存在的条目: {row['hpo_id']}")
            negated = row["qualifier"].strip().upper() == "NOT"
            db.execute("INSERT INTO annotations VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", (
                identifier, row["hpo_id"], int(negated), row["aspect"], row["frequency"],
                row["reference"], row["evidence"], row["onset"], row["sex"], row["modifier"], row["biocuration"], number))
            counts["annotations"] += 1
        db.executescript("""
            CREATE INDEX gene_disease_gene ON gene_disease(gene_id);
            CREATE INDEX gene_disease_symbol ON gene_disease(symbol);
            CREATE INDEX annotation_disease ON annotations(disease_id);
            CREATE INDEX annotation_aspect ON annotations(aspect,negated);
        """)
        for name, table in (("diseases", "diseases"), ("gene_disease_associations", "gene_disease"), ("gene_aliases", "aliases")):
            counts[name] = db.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
        if not counts["hpo_terms"] or not counts["gene_disease_associations"] or not counts["annotations"]:
            raise ValueError("疾病数据库为空")
        db.execute("INSERT INTO metadata VALUES ('schema_version',?)", (DB_SCHEMA,))
        db.execute("INSERT INTO metadata VALUES ('counts',?)", (json.dumps(dict(counts)),))
        db.commit()
        if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("疾病索引完整性检查失败")
    finally:
        db.close()
    temporary.replace(target)
    return dict(counts)


def verify_resource(path: Path, spec: dict) -> None:
    if path.stat().st_size != spec["bytes"]:
        raise ValueError(f"疾病资源体积不符: {path.name}")
    for algorithm in ("sha256", "md5"):
        if spec.get(algorithm) and checksum(path, algorithm) != spec[algorithm]:
            raise ValueError(f"疾病资源校验失败 ({algorithm}): {path.name}")


def setup(directory: Path, lock_path: Path) -> dict:
    lock = json.loads(lock_path.read_text())
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / ".setup.lock").open("w") as mutex:
        try:
            fcntl.flock(mutex, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ValueError("疾病数据安装正在运行") from error
        sources = {}
        for spec in lock["resources"]:
            path = directory / spec["name"]
            if not path.is_file():
                print(f"下载 {path.name} ({spec['bytes']:,} bytes)", flush=True)
                part = path.with_suffix(path.suffix + ".part")
                request = urllib.request.Request(spec["url"], headers={"User-Agent": "e-Gene disease-data/1.0"})
                with urllib.request.urlopen(request, timeout=60) as response, part.open("wb") as output:
                    while block := response.read(1024 * 1024):
                        output.write(block)
                verify_resource(part, spec)
                part.replace(path)
            verify_resource(path, spec)
            sources[spec["name"]] = {**spec, "path": spec["name"], "sha256": checksum(path)}
        target = directory / "disease.sqlite"
        existing = directory / "disease_database_manifest.json"
        if existing.is_file():
            installed = json.loads(existing.read_text())
            if (installed.get("sources") == sources and target.is_file() and
                    installed["database"]["sha256"] == checksum(target)):
                print(f"疾病数据库已就绪：{target}", flush=True)
                return installed
        print("建立 HPO / HGNC 疾病索引", flush=True)
        counts = build_index(directory, target)
        manifest = {"schema_version": DB_SCHEMA, "status": "complete", "built_at": now(),
                    "hpo_release": lock["hpo_release"], "hgnc_release": lock["hgnc_release"],
                    "source_lock_sha256": checksum(lock_path), "sources": sources, "counts": counts,
                    "database": {"path": target.name, "bytes": target.stat().st_size, "sha256": checksum(target)},
                    "attribution": "This analysis uses the Human Phenotype Ontology and HGNC; see source versions and licenses.",
                    "association_scope": "HPO gene-disease mappings with source-specific OMIM/ORPHA IDs; not ClinGen clinical-validity or mechanism curation."}
        write_json(existing, manifest)
        print(f"疾病数据库完成：{counts}", flush=True)
        return manifest


class DiseaseDatabase:
    def __init__(self, manifest_path: Path):
        self.manifest_path = manifest_path.resolve(strict=True)
        self.manifest = json.loads(self.manifest_path.read_text())
        if self.manifest.get("schema_version") != DB_SCHEMA or self.manifest.get("status") != "complete":
            raise ValueError("疾病数据库清单不符合契约")
        spec = self.manifest["database"]
        path = (self.manifest_path.parent / spec["path"]).resolve(strict=True)
        if path.stat().st_size != spec["bytes"] or checksum(path) != spec["sha256"]:
            raise ValueError("疾病数据库校验失败")
        self.connection = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
        self.connection.row_factory = sqlite3.Row
        if self.connection.execute("SELECT value FROM metadata WHERE key='schema_version'").fetchone()[0] != DB_SCHEMA:
            self.close()
            raise ValueError("疾病索引版本不一致")
        self.terms = {row[0]: json.loads(row[1]) for row in self.connection.execute("SELECT id,data FROM terms")}
        self.genes = {row["symbol"]: dict(row) for row in self.connection.execute("SELECT * FROM genes")}
        self.aliases = {}
        for row in self.connection.execute("SELECT alias,symbol FROM aliases"):
            self.aliases.setdefault(row[0], set()).add(row[1])

    def resolve_gene(self, symbol: str) -> dict:
        if symbol in self.genes:
            return {"status": "approved_symbol", **self.genes[symbol]}
        candidates = self.aliases.get(symbol, set())
        if len(candidates) == 1:
            return {"status": "unambiguous_alias", **self.genes[next(iter(candidates))]}
        if candidates:
            return {"status": "ambiguous_alias", "symbol": None, "gene_id": None, "candidates": sorted(candidates)}
        # Retain direct HPO symbols (including some mitochondrial symbols).
        rows = self.connection.execute("SELECT DISTINCT gene_id FROM gene_disease WHERE symbol=?", (symbol,)).fetchall()
        if len(rows) == 1:
            return {"status": "hpo_symbol", "symbol": symbol, "gene_id": rows[0][0]}
        return {"status": "unmapped_gene", "symbol": None, "gene_id": None}

    def associations(self, gene: dict) -> list[dict]:
        if not gene.get("symbol"):
            return []
        rows = self.connection.execute("""SELECT g.*,d.name disease_name FROM gene_disease g
            JOIN diseases d ON g.disease_id=d.id WHERE g.gene_id=? OR g.symbol=? ORDER BY g.disease_id,g.source""",
            (gene["gene_id"], gene["symbol"]))
        return [dict(row) for row in rows]

    def annotations(self, identifier: str) -> list[dict]:
        return [dict(row) for row in self.connection.execute("SELECT * FROM annotations WHERE disease_id=? ORDER BY line_number", (identifier,))]

    def close(self):
        self.connection.close()


def setup_main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--outdir", type=Path, default=ROOT / "data/disease")
    parser.add_argument("--lock", type=Path, default=ROOT / "config/disease_sources.lock.json")
    args = parser.parse_args(argv)
    try:
        setup(args.outdir.expanduser().absolute(), args.lock.expanduser().resolve(strict=True))
    except (OSError, ValueError, KeyError, sqlite3.Error) as error:
        print(f"疾病数据准备失败：{error}", file=sys.stderr)
        return 2
    return 0
