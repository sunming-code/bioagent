from langchain_community.tools import DuckDuckGoSearchRun
from langchain_core.tools import Tool
import json
from typing import Any, Dict, Optional, List, Tuple

try:
    from langchain_community.tools import PubMedQueryRun
    from langchain_community.utilities import PubMedAPIWrapper
except ImportError:
    PubMedQueryRun = None
    PubMedAPIWrapper = None


class Neo4jKGTool:
    """
    Neo4j KG tool (Bolt) for the Task KG schema.

    Supported intents (JSON recommended):
    - GeneToDisease: {"intent":"GeneToDisease","gene":"TP53","k":10}
    - GeneToPathway: {"intent":"GeneToPathway","gene":"TP53","k":10}
    - DiseaseToGene: {"intent":"DiseaseToGene","disease":"breast cancer","k":10}
    - DiseaseToPathway: {"intent":"DiseaseToPathway","disease":"breast cancer","k":10}
    - DiseaseGenePathwayBridge: {"intent":"DiseaseGenePathwayBridge","disease":"breast cancer","k":10}
    - GenePhenotypeBridge: {"intent":"GenePhenotypeBridge","gene":"TP53","k":10}
    - DrugTargetDiseaseBridge: {"intent":"DrugTargetDiseaseBridge","drug":"tamoxifen","k":10}

    If the input is not valid JSON, it will be treated as a free-text term and
    run with a conservative default (GeneToDisease).
    """

    def __init__(self, neo4j_conf: Optional[Dict[str, Any]] = None):
        self.conf = neo4j_conf or {}
        self._driver = None
        self.last_error = ""
        # HTTP 模式：公司网络封锁 Bolt(7687) 时，走 Aura 的 HTTP Query API(443)。
        # 触发条件：uri 以 neo4j+s:// 或 https:// 开头，或 conf["http_mode"] 为真。
        self._http = None  # 惰性初始化的 HTTP 客户端配置

    def _use_http(self) -> bool:
        uri = (self.conf.get("uri") or "").strip().lower()
        if self.conf.get("http_mode"):
            return True
        # neo4j+s:// 是 Aura 加密连接；本地/自建 bolt:// 仍走原生驱动
        return uri.startswith("neo4j+s://") or uri.startswith("https://")

    def _ensure_http(self):
        """初始化 HTTP Query API 客户端配置（Aura, 走 443）。"""
        if self._http is not None:
            return
        import base64
        import ssl

        uri = (self.conf.get("uri") or "").strip()
        user = (self.conf.get("user") or "").strip()
        password = (self.conf.get("password") or "").strip()
        if not uri or not user or not password:
            raise RuntimeError("Neo4j is not configured (missing uri/user/password).")

        # 从 neo4j+s://host[:port] 提取 host
        host = uri.split("://", 1)[1].split("/", 1)[0].split(":", 1)[0].strip()
        database = (self.conf.get("database") or "").strip() or user
        self._http = {
            "endpoint": f"https://{host}/db/{database}/query/v2",
            "auth": base64.b64encode(f"{user}:{password}".encode()).decode(),
            "ctx": ssl.create_default_context(),
        }

    def _http_run(self, cypher: str, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """通过 Aura HTTP Query API 执行 Cypher，返回与 Bolt .data() 一致的 list[dict]。"""
        import json as _json
        import urllib.request
        import urllib.error

        self._ensure_http()
        body = {"statement": cypher}
        if params:
            body["parameters"] = params
        req = urllib.request.Request(
            self._http["endpoint"], data=_json.dumps(body).encode(), method="POST"
        )
        req.add_header("Authorization", f"Basic {self._http['auth']}")
        req.add_header("Content-Type", "application/json")
        req.add_header("Accept", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=60, context=self._http["ctx"]) as r:
                payload = _json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            detail = e.read()[:300].decode(errors="replace")
            raise RuntimeError(f"Aura HTTP API error {e.code}: {detail}")
        # Query API v2 返回 {"data": {"fields": [...], "values": [[...], ...]}}
        data = payload.get("data", {})
        fields = data.get("fields", [])
        values = data.get("values", [])
        return [dict(zip(fields, row)) for row in values]

    def _ensure_driver(self):
        if self._driver is not None:
            return
        try:
            from neo4j import GraphDatabase  # type: ignore
        except Exception as e:
            raise RuntimeError(
                "Neo4j driver not available. Please `pip install neo4j` in this environment."
            ) from e

        uri = (self.conf.get("uri") or "").strip()
        user = (self.conf.get("user") or "").strip()
        password = (self.conf.get("password") or "").strip()
        if not uri or not user or not password:
            raise RuntimeError("Neo4j is not configured (missing uri/user/password).")

        self._driver = GraphDatabase.driver(uri, auth=(user, password))

    @staticmethod
    def _relation_text(var_name: str = "r") -> str:
        return f"coalesce({var_name}.display_relation, type({var_name}))"

    def test_connection(self) -> Dict[str, str]:
        try:
            if self._use_http():
                self._http_run("RETURN 1 AS ok")
                return {"ok": "true", "message": "Neo4j (HTTP Query API) connection successful."}
            self._ensure_driver()
            database = (self.conf.get("database") or "").strip() or None
            with self._driver.session(database=database) as session:
                session.run("RETURN 1 AS ok").data()
            return {"ok": "true", "message": "Neo4j connection successful."}
        except Exception as e:
            self.last_error = str(e)
            return {"ok": "false", "message": str(e)}

    @staticmethod
    def _parse_input(query: str) -> Dict[str, Any]:
        q = (query or "").strip()
        if not q:
            return {"intent": "GeneToDisease", "gene": "", "k": 10}
        try:
            data = json.loads(q)
            if isinstance(data, dict):
                return data
        except Exception:
            pass
        # Fallback: treat as a gene symbol/name
        return {"intent": "GeneToDisease", "gene": q, "k": 10}

    @staticmethod
    def _normalize_intent(intent: Any) -> str:
        i = str(intent or "").strip()
        return i or "GeneToDisease"

    @staticmethod
    def _safe_k(k: Any, default: int = 10, max_k: int = 50) -> int:
        try:
            v = int(k)
            if v <= 0:
                return default
            return min(v, max_k)
        except Exception:
            return default

    @staticmethod
    def _normalize_lookup_value(value: str) -> str:
        return " ".join((value or "").strip().lower().split())

    @staticmethod
    def _cypher_match_entity(var_name: str, norm_param_name: str, raw_param_name: str) -> str:
        """实体匹配：精确匹配 name/normalized_name/id/aliases"""
        return (
            f"toLower(coalesce({var_name}.normalized_name, '')) = ${norm_param_name} OR "
            f"toLower(coalesce({var_name}.name, '')) = ${norm_param_name} OR "
            f"toLower(coalesce({var_name}.id, '')) = ${norm_param_name} OR "
            f"ANY(alias IN split(coalesce({var_name}.aliases, ''), '|') "
            f"WHERE toLower(trim(alias)) = ${norm_param_name})"
        )

    @classmethod
    def _entity_params(cls, key: str, value: str, k: int) -> Dict[str, Any]:
        return {
            key: value,
            f"{key}_norm": cls._normalize_lookup_value(value),
            "k": k
        }

    def _build_query(self, payload: Dict[str, Any]) -> Tuple[str, Dict[str, Any], str, List[str]]:
        intent = self._normalize_intent(payload.get("intent"))
        k = self._safe_k(payload.get("k", 10))

        if intent == "GeneToDisease":
            gene = str(payload.get("gene", "")).strip()
            cypher = f"""
            MATCH (g:Gene)-[r:ASSOCIATED_WITH]-(d:Disease)
            WHERE {self._cypher_match_entity('g', 'gene_norm', 'gene')}
            RETURN g.name AS gene, d.name AS disease, {self._relation_text()} AS relation,
                   coalesce(r.source, '') AS source, coalesce(r.weight, 0.0) AS weight
            ORDER BY weight DESC, disease ASC
            LIMIT $k
            """
            return cypher, self._entity_params("gene", gene, k), "Gene→Disease", ["gene", "disease", "relation", "source", "weight"]

        if intent == "GeneToPathway":
            gene = str(payload.get("gene", "")).strip()
            cypher = f"""
            MATCH (g:Gene)-[r:INVOLVED_IN]-(p:Pathway)
            WHERE {self._cypher_match_entity('g', 'gene_norm', 'gene')}
            RETURN g.name AS gene, p.name AS pathway, {self._relation_text()} AS relation,
                   coalesce(r.source, '') AS source, coalesce(r.weight, 0.0) AS weight
            ORDER BY weight DESC, pathway ASC
            LIMIT $k
            """
            return cypher, self._entity_params("gene", gene, k), "Gene→Pathway", ["gene", "pathway", "relation", "source", "weight"]

        if intent == "DiseaseToGene":
            # 排序改为"生物学度数"（query-time only，不写 KG）。
            #
            # 为什么不能再按 weight 排：ASSOCIATED_WITH 的 r.weight 在全库 30854 条边上
            # 都是**空字符串**（类型 STRING NOT NULL，不是 0 也不是 null），所以
            # coalesce(r.weight, 0.0) 返回 ''，ORDER BY 的主键恒定，退化成纯字母序。
            # 实测 521-1156 个邻居里只有 2/300 个 gold 基因落在字母序 top-8 内。
            #
            # bio_degree = 基因连到的**去重** Disease 数 + 它参与的**去重** Pathway 数，
            # 即"把药理边剔掉后的度数"。总 degree 不能用：它被药物边主导
            # （CYP3A4 的 1970 度里 1942 条连 Drug），排出来是药物代谢 hub 而非疾病基因。
            # 两项都必须去重计数：双向存边会让关系计数变成 2x，两项量纲对不上，
            # 排出来的就不是探针测过的那个量。
            # 检索侧探针（15 题）：R@5 0.0033 -> 0.0400，R@20 0.0167 -> 0.0933；
            # 只看金标可信的 6 题：R@5 0.0000 -> 0.1000，R@20 0.0000 -> 0.1833。
            # 两项已知代价，都是实测，不要在转述时抹掉：
            #   (1) 另外 9 题的金标是 "PrimeKG (no OT match)"（近乎任意取的邻居），
            #       那 9 题 R@5 从 0.0056 掉到 0.0000，是**变差**；
            #   (2) 排序偏向研究热度高的 hub 基因：15 题 top-8 两两重合度 0.577，
            #       15 份 top-8 合起来只有 24 个不同基因，疾病特异性不如字母序。
            # 复现脚本：evaluation/scripts/probe_gene_ranking_signals.py。
            # 完整数字与权衡见 FINDINGS.md。
            #
            # 同时去重：CSV 双向存边，无向 MATCH 会把每个 disease-gene 对匹配两次，
            # 修复前 LIMIT 8 只能拿到 4 个不同基因。按 g 聚合后 k 才是真的 k。
            # 输出列契约保持不变（disease/gene/relation/source/weight），只改顺序：
            # weight 仍原样透传，不被改写成 bio_degree —— 否则同名列在不同 intent 下
            # 含义不同，下游比较会出错。bio_degree 只活在 WITH 里，供 ORDER BY 用。
            disease = str(payload.get("disease", "")).strip()
            cypher = f"""
            MATCH (d:Disease)-[r:ASSOCIATED_WITH]-(g:Gene)
            WHERE {self._cypher_match_entity('d', 'disease_norm', 'disease')}
            WITH d, g, collect(r) AS rels
            WITH d, g, rels,
                 COUNT {{ MATCH (g)-[:ASSOCIATED_WITH]-(d2:Disease)
                          RETURN DISTINCT d2 }}
                 + COUNT {{ MATCH (g)-[:INVOLVED_IN]-(p2:Pathway)
                            RETURN DISTINCT p2 }} AS bio_degree
            ORDER BY bio_degree DESC, g.name ASC
            LIMIT $k
            WITH d, g, rels,
                 reduce(acc = [], src IN [x IN rels | coalesce(x.source, '')] |
                        CASE WHEN src = '' OR src IN acc THEN acc
                             ELSE acc + src END) AS sources
            RETURN d.name AS disease, g.name AS gene,
                   {self._relation_text('rels[0]')} AS relation,
                   reduce(out = '', s IN sources |
                          CASE WHEN out = '' THEN s
                               ELSE out + '|' + s END) AS source,
                   coalesce(rels[0].weight, 0.0) AS weight
            """
            return cypher, self._entity_params("disease", disease, k), "Disease→Gene", ["disease", "gene", "relation", "source", "weight"]

        if intent == "DiseaseToPathway":
            disease = str(payload.get("disease", "")).strip()
            cypher = f"""
            MATCH (d:Disease)-[r:ASSOCIATED_WITH|INVOLVED_IN]-(p:Pathway)
            WHERE {self._cypher_match_entity('d', 'disease_norm', 'disease')}
            RETURN d.name AS disease, p.name AS pathway, {self._relation_text()} AS relation,
                   coalesce(r.source, '') AS source, coalesce(r.weight, 0.0) AS weight
            ORDER BY weight DESC, pathway ASC
            LIMIT $k
            """
            return cypher, self._entity_params("disease", disease, k), "Disease→Pathway", ["disease", "pathway", "relation", "source", "weight"]

        if intent == "DiseaseToPhenotype":
            disease = str(payload.get("disease", "")).strip()
            cypher = f"""
            MATCH (d:Disease)-[r:HAS_PHENOTYPE]-(p:Phenotype)
            WHERE {self._cypher_match_entity('d', 'disease_norm', 'disease')}
            RETURN d.name AS disease, p.name AS phenotype, {self._relation_text()} AS relation,
                   coalesce(r.source, '') AS source, coalesce(r.weight, 0.0) AS weight
            ORDER BY weight DESC, phenotype ASC
            LIMIT $k
            """
            return cypher, self._entity_params("disease", disease, k), "Disease→Phenotype", ["disease", "phenotype", "relation", "source", "weight"]

        if intent == "DrugToDisease":
            drug = str(payload.get("drug", "")).strip()
            cypher = f"""
            MATCH (drug:Drug)-[r:TREATS|CONTRAINDICATED_FOR|OFF_LABEL_FOR]-(d:Disease)
            WHERE {self._cypher_match_entity('drug', 'drug_norm', 'drug')}
            RETURN drug.name AS drug, d.name AS disease, {self._relation_text()} AS relation,
                   coalesce(r.source, '') AS source, coalesce(r.weight, 0.0) AS weight
            ORDER BY weight DESC, disease ASC
            LIMIT $k
            """
            return cypher, self._entity_params("drug", drug, k), "Drug→Disease", ["drug", "disease", "relation", "source", "weight"]

        if intent == "DiseaseToDrug":
            disease = str(payload.get("disease", "")).strip()
            cypher = f"""
            MATCH (d:Disease)-[r:TREATS|CONTRAINDICATED_FOR|OFF_LABEL_FOR]-(drug:Drug)
            WHERE {self._cypher_match_entity('d', 'disease_norm', 'disease')}
            RETURN d.name AS disease, drug.name AS drug, {self._relation_text()} AS relation,
                   coalesce(r.source, '') AS source, coalesce(r.weight, 0.0) AS weight
            ORDER BY weight DESC, drug ASC
            LIMIT $k
            """
            return cypher, self._entity_params("disease", disease, k), "Disease→Drug", ["disease", "drug", "relation", "source", "weight"]

        if intent == "GeneToDrug":
            gene = str(payload.get("gene", "")).strip()
            cypher = f"""
            MATCH (g:Gene)-[r:TARGETS|METABOLIZED_BY|TRANSPORTED_BY|CARRIED_BY]-(drug:Drug)
            WHERE {self._cypher_match_entity('g', 'gene_norm', 'gene')}
            RETURN g.name AS gene, drug.name AS drug, {self._relation_text()} AS relation,
                   coalesce(r.source, '') AS source, coalesce(r.weight, 0.0) AS weight
            ORDER BY weight DESC, drug ASC
            LIMIT $k
            """
            return cypher, self._entity_params("gene", gene, k), "Gene→Drug", ["gene", "drug", "relation", "source", "weight"]

        if intent == "DiseaseGenePathwayBridge":
            disease = str(payload.get("disease", "")).strip()
            cypher = f"""
            MATCH (d:Disease)-[r1:ASSOCIATED_WITH]-(g:Gene)-[r2:INVOLVED_IN]-(p:Pathway)
            WHERE {self._cypher_match_entity('d', 'disease_norm', 'disease')}
            WITH d, p,
                 collect(DISTINCT g.name)[0..5] AS genes,
                 count(DISTINCT g) AS gene_count,
                 collect(DISTINCT {self._relation_text('r1')}) AS disease_gene_relations,
                 collect(DISTINCT {self._relation_text('r2')}) AS gene_pathway_relations,
                 collect(DISTINCT coalesce(r1.source, ''))[0..5] AS disease_sources,
                 collect(DISTINCT coalesce(r2.source, ''))[0..5] AS pathway_sources,
                 max(coalesce(r1.weight, 0.0)) AS disease_gene_weight,
                 max(coalesce(r2.weight, 0.0)) AS gene_pathway_weight
            RETURN d.name AS disease, p.name AS pathway, genes, gene_count,
                   disease_gene_relations, gene_pathway_relations, disease_sources, pathway_sources,
                   disease_gene_weight, gene_pathway_weight
            ORDER BY gene_count DESC, gene_pathway_weight DESC, pathway ASC
            LIMIT $k
            """
            return cypher, self._entity_params("disease", disease, k), "Disease→Gene→Pathway", ["disease", "pathway", "genes", "gene_count", "disease_gene_relations", "gene_pathway_relations", "disease_sources", "pathway_sources", "disease_gene_weight", "gene_pathway_weight"]

        if intent == "GenePhenotypeBridge":
            gene = str(payload.get("gene", "")).strip()
            cypher = f"""
            MATCH (g:Gene)-[r1:ASSOCIATED_WITH]-(d:Disease)-[r2:HAS_PHENOTYPE]-(p:Phenotype)
            WHERE {self._cypher_match_entity('g', 'gene_norm', 'gene')}
            WITH g, d, p,
                 {self._relation_text('r1')} AS disease_relation,
                 {self._relation_text('r2')} AS phenotype_relation,
                 coalesce(r1.source, '') AS disease_source,
                 coalesce(r2.source, '') AS phenotype_source,
                 coalesce(r1.weight, 0.0) AS disease_weight,
                 coalesce(r2.weight, 0.0) AS phenotype_weight
            RETURN g.name AS gene, d.name AS disease, p.name AS phenotype,
                   disease_relation, phenotype_relation,
                   disease_source, phenotype_source,
                   disease_weight, phenotype_weight
            ORDER BY disease_weight DESC, phenotype_weight DESC, phenotype ASC
            LIMIT $k
            """
            return cypher, self._entity_params("gene", gene, k), "Gene→Disease→Phenotype", ["gene", "disease", "phenotype", "disease_relation", "phenotype_relation", "disease_source", "phenotype_source", "disease_weight", "phenotype_weight"]

        if intent == "DrugTargetDiseaseBridge":
            drug = str(payload.get("drug", "")).strip()
            cypher = f"""
            MATCH (drug:Drug)-[r1:TARGETS|METABOLIZED_BY|TRANSPORTED_BY|CARRIED_BY]-(g:Gene)-[r2:ASSOCIATED_WITH]-(d:Disease)
            WHERE {self._cypher_match_entity('drug', 'drug_norm', 'drug')}
            WITH drug, d,
                 collect(DISTINCT g.name)[0..5] AS genes,
                 count(DISTINCT g) AS gene_count,
                 collect(DISTINCT {self._relation_text('r1')}) AS drug_gene_relations,
                 collect(DISTINCT {self._relation_text('r2')}) AS gene_disease_relations,
                 max(coalesce(r1.weight, 0.0)) AS drug_gene_weight,
                 max(coalesce(r2.weight, 0.0)) AS gene_disease_weight
            RETURN drug.name AS drug, d.name AS disease, genes, gene_count,
                   drug_gene_relations, gene_disease_relations,
                   drug_gene_weight, gene_disease_weight
            ORDER BY gene_count DESC, gene_disease_weight DESC, disease ASC
            LIMIT $k
            """
            return cypher, self._entity_params("drug", drug, k), "Drug→Gene→Disease", ["drug", "disease", "genes", "gene_count", "drug_gene_relations", "gene_disease_relations", "drug_gene_weight", "gene_disease_weight"]

        raise ValueError(f"Unsupported intent: {intent}")

    def run_structured(self, query: str) -> Dict[str, Any]:
        payload = self._parse_input(query)
        intent = self._normalize_intent(payload.get("intent"))
        k = self._safe_k(payload.get("k", 10))

        try:
            cypher, params, label, columns = self._build_query(payload)

            if self._use_http():
                # HTTP Query API 模式（Aura, 走 443，绕过被封的 Bolt 7687）
                records = self._http_run(cypher, params)
            else:
                self._ensure_driver()
                database = (self.conf.get("database") or "").strip() or None
                with self._driver.session(database=database) as session:
                    records = session.run(cypher, params).data()

            return {
                "tool": "Neo4j_KG",
                "intent": intent,
                "label": label,
                "k": k,
                "query_payload": payload,
                "columns": columns,
                "records": records,
                "text": self._format_structured_result(label, intent, k, records)
            }
        except Exception as e:
            self.last_error = str(e)
            return {
                "tool": "Neo4j_KG",
                "intent": intent,
                "label": intent,
                "k": k,
                "query_payload": payload,
                "columns": [],
                "records": [],
                "text": f"[Neo4j_KG] Error: {e}",
                "error": str(e)
            }

    @staticmethod
    def _format_record_value(key: str, value: Any) -> str:
        if isinstance(value, list):
            return f"{key}={', '.join(map(str, value))}"
        return f"{key}={value}"

    def _format_structured_result(self, label: str, intent: str, k: int, records: List[Dict[str, Any]]) -> str:
        if not records:
            return f"[Neo4j_KG] {label} (intent={intent}, k={k})\nNo matches."

        lines: List[str] = [f"[Neo4j_KG] {label} (intent={intent}, k={k})"]
        preview_keys = (
            "gene", "disease", "pathway", "phenotype", "drug", "genes", "gene_count",
            "relation", "disease_relation", "phenotype_relation", "drug_gene_relations",
            "gene_disease_relations", "disease_gene_relations", "gene_pathway_relations",
            "source", "disease_sources", "pathway_sources", "weight", "disease_gene_weight", "gene_pathway_weight",
            "drug_gene_weight", "gene_disease_weight"
        )
        for rec in records[:k]:
            parts = [
                self._format_record_value(key, rec[key])
                for key in preview_keys
                if key in rec and rec[key] not in (None, "", [])
            ]
            lines.append("- " + ", ".join(parts))
        return "\n".join(lines)

    def run(self, query: str) -> str:
        return self.run_structured(query)["text"]


class MedicalTools:
    def __init__(self, enable=True, neo4j_conf: Optional[Dict[str, Any]] = None):
        self.enable = enable
        self.tools = []
        self._tool_by_name: Dict[str, Tool] = {}

        if not enable:
            return

        # 1. Web Search
        try:
            self.search = DuckDuckGoSearchRun()
            t = Tool(
                name="Web_Search",
                func=self.search.run,
                description="Search the web for general background or recent information."
            )
            self.tools.append(t)
            self._tool_by_name[t.name] = t
        except Exception as e:
            print(f"Search tool init failed: {e}")

        # 2. PubMed
        if PubMedQueryRun:
            try:
                self.pubmed = PubMedQueryRun(api_wrapper=PubMedAPIWrapper())
                t = Tool(
                    name="PubMed",
                    func=self.pubmed.run,
                    description="Search for biomedical literature and academic papers."
                )
                self.tools.append(t)
                self._tool_by_name[t.name] = t
            except Exception as e:
                print(f"PubMed init failed: {e}")

        # 3. Neo4j Knowledge Graph (Gene-Disease-Pathway)
        try:
            self.neo4j_kg = Neo4jKGTool(neo4j_conf=neo4j_conf)
            t = Tool(
                name="Neo4j_KG",
                func=self.neo4j_kg.run,
                description="Query the Task KG in Neo4j. Supports single-hop and bridge intents for disease, gene, pathway, phenotype, and drug."
            )
            self.tools.append(t)
            self._tool_by_name[t.name] = t
        except Exception as e:
            # Don't fail the whole app if neo4j isn't installed/configured.
            print(f"Neo4j_KG init skipped: {e}")

    def _run_payload(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        tool_name = str(payload.get("tool", "")).strip()
        tool = self._tool_by_name.get(tool_name)
        if not tool:
            err = f"Unknown tool '{tool_name}'. Available: {', '.join(self._tool_by_name.keys())}"
            return {"tool": tool_name or "unknown", "text": err, "records": [], "error": err}

        if tool_name == "Neo4j_KG" and hasattr(self, "neo4j_kg"):
            return self.neo4j_kg.run_structured(json.dumps({k: v for k, v in payload.items() if k != "tool"}, ensure_ascii=False))

        tool_input = str(payload.get("query") or payload.get("q") or "")
        try:
            res = tool.run(tool_input)
            return {"tool": tool_name, "text": f"--- {tool.name} Result ---\n{res[:600]}...", "records": []}
        except Exception as e:
            return {"tool": tool_name, "text": f"Error running {tool.name}: {e}", "records": [], "error": str(e)}

    def execute_plan(self, query: str) -> Dict[str, Any]:
        if not self.enable or not self.tools:
            return {"text": "", "runs": []}

        q = (query or "").strip()
        try:
            payload = json.loads(q)
        except Exception:
            payload = None

        runs: List[Dict[str, Any]] = []

        if isinstance(payload, dict):
            if payload.get("queries") and isinstance(payload.get("queries"), list):
                for item in payload["queries"]:
                    if isinstance(item, dict):
                        runs.append(self._run_payload(item))
            elif payload.get("tool"):
                runs.append(self._run_payload(payload))

        if not runs:
            for tool in self.tools:
                try:
                    res = tool.run(query)
                    runs.append({
                        "tool": tool.name,
                        "text": f"--- {tool.name} Result ---\n{res[:600]}...",
                        "records": []
                    })
                except Exception as e:
                    runs.append({
                        "tool": tool.name,
                        "text": f"Error running {tool.name}: {e}",
                        "records": [],
                        "error": str(e)
                    })

        text_parts = [run["text"] for run in runs if run.get("text")]
        return {
            "text": "\n\n".join(text_parts),
            "runs": runs
        }

    def run_tools(self, query: str):
        """Execute tools and return combined string result"""
        return self.execute_plan(query)["text"]

    def get_tool_status(self) -> Dict[str, Dict[str, str]]:
        status: Dict[str, Dict[str, str]] = {}
        if not self.enable:
            status["tools"] = {"ok": "false", "message": "Tools are disabled."}
            return status

        status["Web_Search"] = {
            "ok": "true" if "Web_Search" in self._tool_by_name else "false",
            "message": "Ready." if "Web_Search" in self._tool_by_name else "ddgs package is missing."
        }
        status["PubMed"] = {
            "ok": "true" if "PubMed" in self._tool_by_name else "false",
            "message": "Ready." if "PubMed" in self._tool_by_name else "PubMed tool unavailable."
        }
        if hasattr(self, "neo4j_kg"):
            status["Neo4j_KG"] = self.neo4j_kg.test_connection()
        else:
            status["Neo4j_KG"] = {"ok": "false", "message": "Neo4j_KG tool was not initialized."}
        return status