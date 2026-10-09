# Task KG Neo4j Schema (PrimeKG Task-driven)

更新时间：2026-03-13  
适用数据流：`kg.csv` -> `create3.py` -> `task_kg_output/*.csv` -> `import_magis_to_neo4j.py`

## 1) 节点标签（Node Labels）

固定 5 类：
- `:Gene`
- `:Disease`
- `:Pathway`
- `:Phenotype`
- `:Drug`

## 2) 节点属性（Node Properties）

每个节点统一属性：
- `id`（主键，格式示例：`Gene:1234`）
- `name`
- `type`（与标签一致）
- `normalized_name`
- `aliases`（`|` 分隔）
- `source`（`|` 分隔）
- `description`

说明：`create3.py` 里已将 PrimeKG 原始类型映射到标准标签，不再使用通用 `Entity`。

## 3) 关系类型（Relationship Types）

当前导入后实际存在：
- `ASSOCIATED_WITH`
- `INVOLVED_IN`
- `HAS_PHENOTYPE`
- `TREATS`
- `CONTRAINDICATED_FOR`
- `OFF_LABEL_FOR`
- `TARGETS`
- `METABOLIZED_BY`
- `TRANSPORTED_BY`
- `CARRIED_BY`

关系类型来源：`task_kg_edges.csv` 的 `relation_group`，在导入时标准化为大写下划线。

## 4) 关系属性（Relationship Properties）

每条关系保留：
- `relation_raw`
- `display_relation`
- `relation_group`
- `source`
- `weight`
- `source_type`
- `target_type`

说明：满足“保留原始 PrimeKG relation/display_relation + 规范化关系语义”的双轨要求。

## 5) 约束与索引（已在库中）

### 唯一约束
- `(:Gene {id})` UNIQUE
- `(:Disease {id})` UNIQUE
- `(:Pathway {id})` UNIQUE
- `(:Phenotype {id})` UNIQUE
- `(:Drug {id})` UNIQUE

### 索引
- 每个标签都有：`name`、`normalized_name` RANGE 索引
- 默认还会有 Neo4j 的 lookup 索引（NODE/RELATIONSHIP）

## 6) 当前实例快照（本次导入）

导入命令执行成功后统计：
- 节点总数：`10133`
- 关系总数：`87838`
- 节点分布：
  - Drug: `4730`
  - Gene: `3582`
  - Disease: `20`
  - Phenotype: `76`
  - Pathway: `1725`
- 关系分布（节选）：
  - ASSOCIATED_WITH: `30854`
  - INVOLVED_IN: `24724`
  - TARGETS: `18392`
  - METABOLIZED_BY: `8150`

## 7) 复现命令

### 7.1 构建任务子图
```bash
python create3.py --input kg.csv --output-dir task_kg_output --top-k-diseases 20 --min-genes 30 --min-pathways 30
```

### 7.2 导入 Neo4j（建议使用 .venv 解释器）
```bash
.venv\Scripts\python.exe import_magis_to_neo4j.py --input-dir task_kg_output --uri bolt://localhost:7687 --user neo4j --password <your_password> --clear --batch-size 1000
```

## 8) 推荐给协作者的验收查询

```cypher
// 1) 标签检查
MATCH (n) RETURN labels(n) AS labels, count(*) AS cnt ORDER BY cnt DESC;

// 2) Disease -> Gene
MATCH (d:Disease)-[r:ASSOCIATED_WITH]-(g:Gene)
RETURN d.name, count(DISTINCT g) AS gene_cnt
ORDER BY gene_cnt DESC LIMIT 20;

// 3) Gene -> Pathway
MATCH (g:Gene)-[r:INVOLVED_IN]-(p:Pathway)
RETURN g.name, count(DISTINCT p) AS pathway_cnt
ORDER BY pathway_cnt DESC LIMIT 20;

// 4) Disease -> Gene -> Pathway bridge
MATCH (d:Disease)-[:ASSOCIATED_WITH]-(g:Gene)-[:INVOLVED_IN]-(p:Pathway)
RETURN d.name, count(DISTINCT g) AS genes, count(DISTINCT p) AS pathways
ORDER BY pathways DESC LIMIT 20;
```
