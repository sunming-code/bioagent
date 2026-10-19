import argparse
import json
from pathlib import Path


def load_jsonl(path: Path):
    rows = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def main():
    parser = argparse.ArgumentParser(description="根据 gold 文件生成 prediction 模板。")
    parser.add_argument("--gold", required=True, help="gold JSONL 路径")
    parser.add_argument("--out", required=True, help="输出 prediction JSONL 路径")
    args = parser.parse_args()

    gold_rows = load_jsonl(Path(args.gold))
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with out_path.open("w", encoding="utf-8") as f:
        for row in gold_rows:
            pred = {
                "id": row["id"],
                "answer_text": "",
                "predicted_genes": [],
                "predicted_pathways": [],
                "predicted_phenotypes": [],
                "predicted_drugs": [],
                "predicted_relations": [],
                "bridge_found": False,
                "mechanism_completeness": None,
                "graph_faithfulness": None,
                "utility_score": None,
                "tool_calls": [],
                "notes": ""
            }
            f.write(json.dumps(pred, ensure_ascii=False) + "\n")

    print(f"已生成 prediction 模板: {out_path}")


if __name__ == "__main__":
    main()
