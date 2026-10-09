# MAGIS Knowledge Graph Builder

将MAGIS演示数据导入到Neo4j知识图谱。

## 功能

- 从CSV文件读取节点和关系数据
- 自动创建Neo4j约束和索引
- 支持多种节点类型（Gene、Disease、Drug）
- 支持多种关系类型（disease_protein、drug_protein等）
- 批量导入优化性能

## 安装

项目使用uv管理依赖：

```bash
uv sync
```

## 使用

激活虚拟环境：

```bash
.venv\Scripts\activate
```

运行导入脚本：

```bash
python import_magis_to_neo4j.py
```

## 要求

- Neo4j 5.0+
- Python 3.9+
- neo4j Python驱动

## 数据文件

将CSV数据文件放在与脚本相同的目录中：
- `magis_demo_100_edges.csv` - 演示数据（100条边）
- `magis_kg_edges.csv` - 完整知识图谱

## 配置

编辑脚本中的Neo4j连接参数：

```python
NEO4J_URI = "bolt://localhost:7687"
NEO4J_USER = "neo4j"
NEO4J_PASSWORD = "password"
```
