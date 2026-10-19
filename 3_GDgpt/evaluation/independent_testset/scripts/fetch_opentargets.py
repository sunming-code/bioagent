#!/usr/bin/env python3
"""
从 Open Targets Platform 获取基因-疾病关联数据
用于构建独立于 PrimeKG 的测试集 Gold Standard
"""

import json
import requests
import time
from pathlib import Path
from typing import List, Dict, Any

# Open Targets GraphQL API endpoint
OPENTARGETS_API = "https://api.platform.opentargets.org/api/v4/graphql"

# 目标疾病列表（选择常见且可能在 PrimeKG 中也有的疾病）
TARGET_DISEASES = [
    # 癌症类
    {"name": "breast carcinoma", "efo_id": "EFO_0000305"},
    {"name": "lung cancer", "efo_id": "EFO_0001071"},
    {"name": "colorectal cancer", "efo_id": "EFO_0005842"},
    {"name": "prostate cancer", "efo_id": "EFO_0001663"},
    {"name": "hepatocellular carcinoma", "efo_id": "EFO_0000182"},
    {"name": "pancreatic cancer", "efo_id": "EFO_0002618"},
    {"name": "ovarian cancer", "efo_id": "EFO_0001075"},
    {"name": "melanoma", "efo_id": "EFO_0000756"},
    {"name": "leukemia", "efo_id": "EFO_0000565"},
    {"name": "glioblastoma", "efo_id": "EFO_0000519"},
    
    # 神经系统疾病
    {"name": "Alzheimer disease", "efo_id": "MONDO_0004975"},
    {"name": "Parkinson disease", "efo_id": "EFO_0002508"},
    {"name": "schizophrenia", "efo_id": "EFO_0000692"},
    {"name": "major depressive disorder", "efo_id": "EFO_0003761"},
    {"name": "epilepsy", "efo_id": "EFO_0000474"},
    
    # 心血管疾病
    {"name": "coronary artery disease", "efo_id": "EFO_0001645"},
    {"name": "heart failure", "efo_id": "EFO_0003144"},
    {"name": "hypertension", "efo_id": "EFO_0000537"},
    {"name": "atrial fibrillation", "efo_id": "EFO_0000275"},
    
    # 代谢疾病
    {"name": "type 2 diabetes mellitus", "efo_id": "EFO_0001360"},
    {"name": "obesity", "efo_id": "EFO_0001073"},
    
    # 自身免疫疾病
    {"name": "rheumatoid arthritis", "efo_id": "EFO_0000685"},
    {"name": "multiple sclerosis", "efo_id": "EFO_0003885"},
    {"name": "systemic lupus erythematosus", "efo_id": "EFO_0002690"},
    
    # 其他
    {"name": "asthma", "efo_id": "EFO_0000270"},
    {"name": "chronic kidney disease", "efo_id": "EFO_0003884"},
]

# 目标基因列表（用于 gene-centered 问题）
TARGET_GENES = [
    "TP53", "BRCA1", "BRCA2", "EGFR", "KRAS", "PIK3CA",
    "PTEN", "AKT1", "MTOR", "MYC", "RB1", "CDKN2A",
    "BRAF", "ALK", "RET", "MET", "HER2", "ERBB2",
    "JAK2", "FLT3", "BCL2", "MDM2", "STAT3", "SRC",
    "VEGFA", "TNF", "IL6", "APOE", "APP", "MAPT"
]


def query_disease_associations(efo_id: str, disease_name: str, min_score: float = 0.3) -> Dict[str, Any]:
    """
    查询某个疾病关联的基因
    
    Args:
        efo_id: 疾病的 EFO ID
        disease_name: 疾病名称
        min_score: 最小关联分数阈值
    
    Returns:
        包含疾病信息和关联基因的字典
    """
    query = """
    query diseaseAssociations($efoId: String!, $size: Int!) {
      disease(efoId: $efoId) {
        id
        name
        description
        associatedTargets(page: {size: $size, index: 0}) {
          count
          rows {
            target {
              id
              approvedSymbol
              approvedName
            }
            score
            datatypeScores {
              id
              score
            }
          }
        }
      }
    }
    """
    
    variables = {
        "efoId": efo_id,
        "size": 100  # 获取 top 100 关联基因
    }
    
    try:
        response = requests.post(
            OPENTARGETS_API,
            json={"query": query, "variables": variables},
            headers={"Content-Type": "application/json"},
            timeout=30
        )
        response.raise_for_status()
        data = response.json()
        
        if "errors" in data:
            print(f"  ⚠️ API Error for {disease_name}: {data['errors']}")
            return None
        
        disease_data = data.get("data", {}).get("disease")
        if not disease_data:
            print(f"  ⚠️ No data found for {disease_name} ({efo_id})")
            return None
        
        # 筛选高置信度关联
        associations = disease_data.get("associatedTargets", {}).get("rows", [])
        filtered_genes = []
        for assoc in associations:
            if assoc["score"] >= min_score:
                filtered_genes.append({
                    "gene_id": assoc["target"]["id"],
                    "gene_symbol": assoc["target"]["approvedSymbol"],
                    "gene_name": assoc["target"]["approvedName"],
                    "association_score": assoc["score"],
                    "datatype_scores": assoc.get("datatypeScores", [])
                })
        
        return {
            "disease_id": disease_data["id"],
            "disease_name": disease_data["name"],
            "disease_description": disease_data.get("description", ""),
            "total_associations": disease_data["associatedTargets"]["count"],
            "filtered_genes": filtered_genes,
            "filter_threshold": min_score,
            "source": "Open Targets Platform",
            "query_time": time.strftime("%Y-%m-%d %H:%M:%S")
        }
        
    except requests.exceptions.RequestException as e:
        print(f"  ❌ Request failed for {disease_name}: {e}")
        return None


def query_gene_diseases(gene_symbol: str, min_score: float = 0.3) -> Dict[str, Any]:
    """
    查询某个基因关联的疾病
    
    Args:
        gene_symbol: 基因符号
        min_score: 最小关联分数阈值
    
    Returns:
        包含基因信息和关联疾病的字典
    """
    # 首先通过基因符号查询 Ensembl ID
    search_query = """
    query searchTarget($queryString: String!) {
      search(queryString: $queryString, entityNames: ["target"], page: {size: 1, index: 0}) {
        hits {
          id
          name
          entity
        }
      }
    }
    """
    
    try:
        # 搜索基因
        response = requests.post(
            OPENTARGETS_API,
            json={"query": search_query, "variables": {"queryString": gene_symbol}},
            headers={"Content-Type": "application/json"},
            timeout=30
        )
        response.raise_for_status()
        search_data = response.json()
        
        hits = search_data.get("data", {}).get("search", {}).get("hits", [])
        if not hits:
            print(f"  ⚠️ Gene not found: {gene_symbol}")
            return None
        
        ensembl_id = hits[0]["id"]
        
        # 查询基因关联的疾病
        disease_query = """
        query targetAssociations($ensemblId: String!, $size: Int!) {
          target(ensemblId: $ensemblId) {
            id
            approvedSymbol
            approvedName
            associatedDiseases(page: {size: $size, index: 0}) {
              count
              rows {
                disease {
                  id
                  name
                }
                score
                datatypeScores {
                  id
                  score
                }
              }
            }
          }
        }
        """
        
        response = requests.post(
            OPENTARGETS_API,
            json={"query": disease_query, "variables": {"ensemblId": ensembl_id, "size": 50}},
            headers={"Content-Type": "application/json"},
            timeout=30
        )
        response.raise_for_status()
        data = response.json()
        
        if "errors" in data:
            print(f"  ⚠️ API Error for {gene_symbol}: {data['errors']}")
            return None
        
        target_data = data.get("data", {}).get("target")
        if not target_data:
            print(f"  ⚠️ No data found for {gene_symbol}")
            return None
        
        # 筛选高置信度关联
        associations = target_data.get("associatedDiseases", {}).get("rows", [])
        filtered_diseases = []
        for assoc in associations:
            if assoc["score"] >= min_score:
                filtered_diseases.append({
                    "disease_id": assoc["disease"]["id"],
                    "disease_name": assoc["disease"]["name"],
                    "association_score": assoc["score"],
                    "datatype_scores": assoc.get("datatypeScores", [])
                })
        
        return {
            "gene_id": target_data["id"],
            "gene_symbol": target_data["approvedSymbol"],
            "gene_name": target_data["approvedName"],
            "total_associations": target_data["associatedDiseases"]["count"],
            "filtered_diseases": filtered_diseases,
            "filter_threshold": min_score,
            "source": "Open Targets Platform",
            "query_time": time.strftime("%Y-%m-%d %H:%M:%S")
        }
        
    except requests.exceptions.RequestException as e:
        print(f"  ❌ Request failed for {gene_symbol}: {e}")
        return None


def fetch_all_data(output_dir: Path):
    """
    获取所有 Open Targets 数据
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # 1. 获取疾病-基因关联（用于 disease-centered 问题）
    print("=" * 60)
    print("📥 Fetching disease-gene associations from Open Targets...")
    print("=" * 60)
    
    disease_associations = []
    for i, disease in enumerate(TARGET_DISEASES):
        print(f"[{i+1}/{len(TARGET_DISEASES)}] Querying: {disease['name']}...")
        result = query_disease_associations(disease["efo_id"], disease["name"])
        if result:
            disease_associations.append(result)
            print(f"  ✓ Found {len(result['filtered_genes'])} high-confidence genes")
        time.sleep(0.5)  # 避免 API 限流
    
    # 保存疾病关联数据
    disease_output = output_dir / "opentargets_disease_associations.json"
    with open(disease_output, "w", encoding="utf-8") as f:
        json.dump(disease_associations, f, indent=2, ensure_ascii=False)
    print(f"\n✅ Saved {len(disease_associations)} disease records to {disease_output}")
    
    # 2. 获取基因-疾病关联（用于 gene-centered 问题）
    print("\n" + "=" * 60)
    print("📥 Fetching gene-disease associations from Open Targets...")
    print("=" * 60)
    
    gene_associations = []
    for i, gene in enumerate(TARGET_GENES):
        print(f"[{i+1}/{len(TARGET_GENES)}] Querying: {gene}...")
        result = query_gene_diseases(gene)
        if result:
            gene_associations.append(result)
            print(f"  ✓ Found {len(result['filtered_diseases'])} high-confidence diseases")
        time.sleep(0.5)
    
    # 保存基因关联数据
    gene_output = output_dir / "opentargets_gene_associations.json"
    with open(gene_output, "w", encoding="utf-8") as f:
        json.dump(gene_associations, f, indent=2, ensure_ascii=False)
    print(f"\n✅ Saved {len(gene_associations)} gene records to {gene_output}")
    
    # 3. 生成摘要统计
    summary = {
        "source": "Open Targets Platform",
        "fetch_time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "disease_centered": {
            "total_diseases": len(disease_associations),
            "diseases": [d["disease_name"] for d in disease_associations],
            "total_gene_associations": sum(len(d["filtered_genes"]) for d in disease_associations)
        },
        "gene_centered": {
            "total_genes": len(gene_associations),
            "genes": [g["gene_symbol"] for g in gene_associations],
            "total_disease_associations": sum(len(g["filtered_diseases"]) for g in gene_associations)
        }
    }
    
    summary_output = output_dir / "opentargets_summary.json"
    with open(summary_output, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    print(f"\n📊 Summary saved to {summary_output}")
    
    return disease_associations, gene_associations


if __name__ == "__main__":
    # 设置输出目录
    script_dir = Path(__file__).parent.parent
    raw_data_dir = script_dir / "raw_data"
    
    print("🚀 Starting Open Targets data fetch...")
    print(f"   Output directory: {raw_data_dir}")
    print()
    
    disease_data, gene_data = fetch_all_data(raw_data_dir)
    
    print("\n" + "=" * 60)
    print("✅ Open Targets data fetch complete!")
    print("=" * 60)
    print(f"   Disease-centered: {len(disease_data)} diseases")
    print(f"   Gene-centered: {len(gene_data)} genes")
