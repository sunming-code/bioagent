import argparse
import csv
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set, Tuple


TYPE_MAP = {
	"gene/protein": "Gene",
	"disease": "Disease",
	"pathway": "Pathway",
	"effect/phenotype": "Phenotype",
	"phenotype": "Phenotype",
	"drug": "Drug",
}

TARGET_LABELS = {"Gene", "Disease", "Pathway", "Phenotype", "Drug"}


def normalize_type(raw_type: str) -> Optional[str]:
	if not raw_type:
		return None
	return TYPE_MAP.get(raw_type.strip().lower())


def clean_text(value: str) -> str:
	if value is None:
		return ""
	value = str(value).strip()
	value = re.sub(r"\s+", " ", value)
	return value


def normalize_name(name: str, label: str) -> str:
	name = clean_text(name)
	if label == "Gene":
		return name.upper()
	return name.lower()


def norm_relation(display_relation: str, source_type: str, target_type: str) -> str:
	drel = clean_text(display_relation).lower()
	pair = (source_type, target_type)

	if set(pair) == {"Disease", "Gene"}:
		return "ASSOCIATED_WITH"
	if set(pair) == {"Gene", "Pathway"}:
		return "INVOLVED_IN"
	if set(pair) == {"Disease", "Pathway"}:
		return "ASSOCIATED_WITH_PATHWAY"
	if set(pair) == {"Disease", "Phenotype"}:
		if "absent" in drel:
			return "LACKS_PHENOTYPE"
		return "HAS_PHENOTYPE"
	if set(pair) == {"Drug", "Disease"}:
		if drel == "indication":
			return "TREATS"
		if drel == "off-label use":
			return "OFF_LABEL_FOR"
		if drel == "contraindication":
			return "CONTRAINDICATED_FOR"
		return "ASSOCIATED_WITH"
	if set(pair) == {"Drug", "Gene"}:
		if drel == "target":
			return "TARGETS"
		if drel == "enzyme":
			return "METABOLIZED_BY"
		if drel == "transporter":
			return "TRANSPORTED_BY"
		if drel == "carrier":
			return "CARRIED_BY"
		return "INTERACTS_WITH"
	return "RELATED_TO"


def edge_key(row: Dict[str, str], sx: str, sy: str) -> Tuple[str, str, str, str, str, str]:
	return (
		sx,
		clean_text(row["x_id"]),
		sy,
		clean_text(row["y_id"]),
		clean_text(row.get("relation", "")),
		clean_text(row.get("display_relation", "")),
	)


class TaskKGBuilder:
	def __init__(
		self,
		input_csv: Path,
		output_dir: Path,
		top_k_diseases: int,
		min_genes: int,
		min_pathways: int,
		focus_keywords: Optional[List[str]] = None,
		seed_disease_ids: Optional[Set[str]] = None,
		seed_disease_names: Optional[Set[str]] = None,
	):
		self.input_csv = input_csv
		self.output_dir = output_dir
		self.top_k_diseases = top_k_diseases
		self.min_genes = min_genes
		self.min_pathways = min_pathways
		self.focus_keywords = [k.lower() for k in (focus_keywords or []) if k.strip()]
		self.seed_disease_ids = {clean_text(x) for x in (seed_disease_ids or set())}
		self.seed_disease_names = {clean_text(x).lower() for x in (seed_disease_names or set())}

		self.disease_name: Dict[str, str] = {}
		self.gene_name: Dict[str, str] = {}
		self.pathway_name: Dict[str, str] = {}

		self.d2g: Dict[str, Set[str]] = defaultdict(set)
		self.g2p: Dict[str, Set[str]] = defaultdict(set)

	def first_pass_build_indices(self) -> None:
		with self.input_csv.open("r", encoding="utf-8", newline="") as f:
			reader = csv.DictReader(f)
			for row in reader:
				sx = normalize_type(row.get("x_type", ""))
				sy = normalize_type(row.get("y_type", ""))
				if sx not in TARGET_LABELS or sy not in TARGET_LABELS:
					continue

				xid = clean_text(row.get("x_id", ""))
				yid = clean_text(row.get("y_id", ""))
				xname = clean_text(row.get("x_name", ""))
				yname = clean_text(row.get("y_name", ""))

				if sx == "Disease":
					self.disease_name[xid] = xname
				if sy == "Disease":
					self.disease_name[yid] = yname
				if sx == "Gene":
					self.gene_name[xid] = xname
				if sy == "Gene":
					self.gene_name[yid] = yname
				if sx == "Pathway":
					self.pathway_name[xid] = xname
				if sy == "Pathway":
					self.pathway_name[yid] = yname

				if sx == "Disease" and sy == "Gene":
					self.d2g[xid].add(yid)
				elif sx == "Gene" and sy == "Disease":
					self.d2g[yid].add(xid)

				if sx == "Gene" and sy == "Pathway":
					self.g2p[xid].add(yid)
				elif sx == "Pathway" and sy == "Gene":
					self.g2p[yid].add(xid)

	def _keyword_match(self, disease_name: str) -> bool:
		if not self.focus_keywords:
			return True
		text = disease_name.lower()
		return any(k in text for k in self.focus_keywords)

	def select_seed_diseases(self) -> Set[str]:
		if self.seed_disease_ids:
			return {d for d in self.seed_disease_ids if d in self.d2g}

		if self.seed_disease_names:
			name_to_id = {v.lower(): k for k, v in self.disease_name.items()}
			selected = {name_to_id[n] for n in self.seed_disease_names if n in name_to_id}
			return {d for d in selected if d in self.d2g}

		candidates = []
		for disease_id, genes in self.d2g.items():
			if not genes:
				continue
			pathways = set()
			for gene_id in genes:
				pathways.update(self.g2p.get(gene_id, set()))

			gene_count = len(genes)
			pathway_count = len(pathways)
			if gene_count < self.min_genes or pathway_count < self.min_pathways:
				continue

			disease_nm = self.disease_name.get(disease_id, "")
			if not self._keyword_match(disease_nm):
				continue

			bridge_score = gene_count * pathway_count
			candidates.append((bridge_score, gene_count, pathway_count, disease_id))

		candidates.sort(reverse=True)
		return {x[3] for x in candidates[: self.top_k_diseases]}

	def build_task_subgraph(self, seed_diseases: Set[str]) -> Tuple[List[Dict[str, str]], Counter]:
		selected_genes: Set[str] = set()
		for d in seed_diseases:
			selected_genes.update(self.d2g.get(d, set()))

		selected_pathways: Set[str] = set()
		for g in selected_genes:
			selected_pathways.update(self.g2p.get(g, set()))

		edges: List[Dict[str, str]] = []
		edge_seen: Set[Tuple[str, str, str, str, str, str]] = set()
		relation_counter: Counter = Counter()

		with self.input_csv.open("r", encoding="utf-8", newline="") as f:
			reader = csv.DictReader(f)
			for row in reader:
				sx = normalize_type(row.get("x_type", ""))
				sy = normalize_type(row.get("y_type", ""))
				if sx not in TARGET_LABELS or sy not in TARGET_LABELS:
					continue

				xid = clean_text(row.get("x_id", ""))
				yid = clean_text(row.get("y_id", ""))

				keep = False
				pair = (sx, sy)
				pair_set = {sx, sy}

				if pair_set == {"Disease", "Gene"}:
					disease_id = xid if sx == "Disease" else yid
					keep = disease_id in seed_diseases
				elif pair_set == {"Gene", "Pathway"}:
					gene_id = xid if sx == "Gene" else yid
					keep = gene_id in selected_genes
				elif pair_set == {"Disease", "Pathway"}:
					disease_id = xid if sx == "Disease" else yid
					pathway_id = xid if sx == "Pathway" else yid
					keep = disease_id in seed_diseases and pathway_id in selected_pathways
				elif pair_set == {"Disease", "Phenotype"}:
					disease_id = xid if sx == "Disease" else yid
					keep = disease_id in seed_diseases
				elif pair_set == {"Drug", "Disease"}:
					disease_id = xid if sx == "Disease" else yid
					keep = disease_id in seed_diseases
				elif pair_set == {"Drug", "Gene"}:
					gene_id = xid if sx == "Gene" else yid
					keep = gene_id in selected_genes

				if not keep:
					continue

				key = edge_key(row, sx, sy)
				if key in edge_seen:
					continue
				edge_seen.add(key)

				relation_group = norm_relation(row.get("display_relation", ""), sx, sy)
				relation_counter[relation_group] += 1

				edges.append(
					{
						"source_id": f"{sx}:{xid}",
						"source_raw_id": xid,
						"source_name": clean_text(row.get("x_name", "")),
						"source_type": sx,
						"target_id": f"{sy}:{yid}",
						"target_raw_id": yid,
						"target_name": clean_text(row.get("y_name", "")),
						"target_type": sy,
						"relation_raw": clean_text(row.get("relation", "")),
						"display_relation": clean_text(row.get("display_relation", "")),
						"relation_group": relation_group,
						"source": clean_text(row.get("x_source", "")) or clean_text(row.get("y_source", "")),
						"weight": clean_text(row.get("weight", "")),
					}
				)

		return edges, relation_counter

	def build_nodes_from_edges(self, edges: Iterable[Dict[str, str]]) -> List[Dict[str, str]]:
		node_meta: Dict[str, Dict[str, str]] = {}
		aliases: Dict[str, Set[str]] = defaultdict(set)
		sources: Dict[str, Set[str]] = defaultdict(set)

		for e in edges:
			for side in ("source", "target"):
				nid = e[f"{side}_id"]
				nname = clean_text(e[f"{side}_name"])
				ntype = e[f"{side}_type"]
				if nid not in node_meta:
					node_meta[nid] = {
						"id": nid,
						"name": nname,
						"type": ntype,
						"normalized_name": normalize_name(nname, ntype),
						"description": "",
					}
				elif nname and nname != node_meta[nid]["name"]:
					aliases[nid].add(nname)

			if e.get("source"):
				sources[e["source_id"]].add(e["source"])
				sources[e["target_id"]].add(e["source"])

		result = []
		for nid, info in node_meta.items():
			item = dict(info)
			item["aliases"] = "|".join(sorted(aliases.get(nid, set())))
			item["source"] = "|".join(sorted(sources.get(nid, set())))
			result.append(item)

		return result

	def write_outputs(
		self,
		seed_diseases: Set[str],
		edges: List[Dict[str, str]],
		nodes: List[Dict[str, str]],
		relation_counter: Counter,
	) -> None:
		self.output_dir.mkdir(parents=True, exist_ok=True)

		edges_path = self.output_dir / "task_kg_edges.csv"
		nodes_path = self.output_dir / "task_kg_nodes.csv"
		seeds_path = self.output_dir / "selected_seed_diseases.csv"
		summary_path = self.output_dir / "task_kg_summary.json"

		edge_fields = [
			"source_id",
			"source_raw_id",
			"source_name",
			"source_type",
			"target_id",
			"target_raw_id",
			"target_name",
			"target_type",
			"relation_raw",
			"display_relation",
			"relation_group",
			"source",
			"weight",
		]
		node_fields = ["id", "name", "type", "normalized_name", "aliases", "source", "description"]

		with edges_path.open("w", encoding="utf-8", newline="") as f:
			writer = csv.DictWriter(f, fieldnames=edge_fields)
			writer.writeheader()
			writer.writerows(edges)

		with nodes_path.open("w", encoding="utf-8", newline="") as f:
			writer = csv.DictWriter(f, fieldnames=node_fields)
			writer.writeheader()
			writer.writerows(nodes)

		with seeds_path.open("w", encoding="utf-8", newline="") as f:
			writer = csv.DictWriter(f, fieldnames=["disease_id", "disease_name"])
			writer.writeheader()
			for disease_id in sorted(seed_diseases):
				writer.writerow({"disease_id": disease_id, "disease_name": self.disease_name.get(disease_id, "")})

		type_counter = Counter(n["type"] for n in nodes)
		summary = {
			"input_csv": str(self.input_csv),
			"seed_disease_count": len(seed_diseases),
			"node_count": len(nodes),
			"edge_count": len(edges),
			"nodes_by_type": dict(type_counter),
			"edges_by_relation_group": dict(relation_counter),
		}

		with summary_path.open("w", encoding="utf-8") as f:
			json.dump(summary, f, ensure_ascii=False, indent=2)

	def run(self) -> None:
		self.first_pass_build_indices()
		seed_diseases = self.select_seed_diseases()
		if not seed_diseases:
			raise RuntimeError("未选出 seed diseases，请降低 min_genes/min_pathways 或检查 seed 参数。")

		edges, relation_counter = self.build_task_subgraph(seed_diseases)
		nodes = self.build_nodes_from_edges(edges)
		self.write_outputs(seed_diseases, edges, nodes, relation_counter)


def parse_csv_set(value: str) -> Set[str]:
	if not value:
		return set()
	return {clean_text(x) for x in value.split(",") if clean_text(x)}


def parse_args() -> argparse.Namespace:
	parser = argparse.ArgumentParser(description="Build a task-driven PrimeKG subgraph for disease mechanism reasoning.")
	parser.add_argument("--input", default="kg.csv", help="PrimeKG raw CSV path")
	parser.add_argument("--output-dir", default="task_kg_output", help="Output folder for nodes/edges CSV")
	parser.add_argument("--top-k-diseases", type=int, default=50, help="Auto-select top K diseases by bridge score")
	parser.add_argument("--min-genes", type=int, default=20, help="Minimum disease-gene count for auto seed selection")
	parser.add_argument("--min-pathways", type=int, default=20, help="Minimum bridge pathways for auto seed selection")
	parser.add_argument(
		"--focus-keywords",
		default="",
		help="Comma-separated disease keywords for domain focus, e.g. cancer,schizophrenia,inflammatory",
	)
	parser.add_argument("--seed-disease-ids", default="", help="Comma-separated disease IDs for explicit seeds")
	parser.add_argument("--seed-disease-names", default="", help="Comma-separated disease names for explicit seeds")
	return parser.parse_args()


def main() -> None:
	args = parse_args()
	builder = TaskKGBuilder(
		input_csv=Path(args.input),
		output_dir=Path(args.output_dir),
		top_k_diseases=args.top_k_diseases,
		min_genes=args.min_genes,
		min_pathways=args.min_pathways,
		focus_keywords=[x.strip() for x in args.focus_keywords.split(",") if x.strip()],
		seed_disease_ids=parse_csv_set(args.seed_disease_ids),
		seed_disease_names=parse_csv_set(args.seed_disease_names),
	)
	builder.run()
	print(f"✅ 完成任务型图谱构建，输出目录: {args.output_dir}")


if __name__ == "__main__":
	main()
