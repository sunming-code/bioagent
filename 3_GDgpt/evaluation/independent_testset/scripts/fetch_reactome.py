#!/usr/bin/env python3
"""
从 Reactome 获取基因-通路关联数据
用于构建独立于 PrimeKG 的测试集 Gold Standard
"""

import json
import requests
import time
from pathlib import Path
from typing import List, Dict, Any, Optional

# Reactome REST API endpoints
REACTOME_CONTENT_API = "https://reactome.org/ContentService"
REACTOME_ANALYSIS_API = "https://reactome.org/AnalysisService"

# 目标通路列表（选择重要的生物学通路）
TARGET_PATHWAYS = [
    # 细胞周期与增殖
    {"name": "Cell Cycle", "id": "R-HSA-1640170"},
    {"name": "Cell Cycle Checkpoints", "id": "R-HSA-69620"},
    {"name": "Mitotic G1-G1/S phases", "id": "R-HSA-453279"},
    
    # DNA 修复
    {"name": "DNA Repair", "id": "R-HSA-73894"},
    {"name": "DNA Double-Strand Break Repair", "id": "R-HSA-5693532"},
    {"name": "Base Excision Repair", "id": "R-HSA-73884"},
    
    # 细胞凋亡
    {"name": "Apoptosis", "id": "R-HSA-109581"},
    {"name": "Intrinsic Pathway for Apoptosis", "id": "R-HSA-109606"},
    {"name": "Extrinsic Pathway for Apoptosis", "id": "R-HSA-5357769"},
    
    # 信号转导
    {"name": "Signal Transduction", "id": "R-HSA-162582"},
    {"name": "Signaling by Receptor Tyrosine Kinases", "id": "R-HSA-9006934"},
    {"name": "PI3K/AKT Signaling in Cancer", "id": "R-HSA-2219528"},
    {"name": "MAPK family signaling cascades", "id": "R-HSA-5683057"},
    {"name": "Signaling by WNT", "id": "R-HSA-195721"},
    {"name": "Signaling by NOTCH", "id": "R-HSA-157118"},
    {"name": "Signaling by Hedgehog", "id": "R-HSA-5358351"},
    
    # 免疫系统
    {"name": "Immune System", "id": "R-HSA-168256"},
    {"name": "Adaptive Immune System", "id": "R-HSA-1280218"},
    {"name": "Innate Immune System", "id": "R-HSA-168249"},
    {"name": "Cytokine Signaling in Immune system", "id": "R-HSA-1280215"},
    {"name": "Interleukin-6 signaling", "id": "R-HSA-6783783"},
    
    # 代谢
    {"name": "Metabolism", "id": "R-HSA-1430728"},
    {"name": "Glucose metabolism", "id": "R-HSA-70326"},
    {"name": "Fatty acid metabolism", "id": "R-HSA-8978868"},
    {"name": "Cholesterol biosynthesis", "id": "R-HSA-191273"},
    
    # 基因表达调控
    {"name": "Gene expression (Transcription)", "id": "R-HSA-74160"},
    {"name": "Transcriptional regulation by TP53", "id": "R-HSA-3700989"},
    {"name": "Regulation of TP53 Activity", "id": "R-HSA-5633007"},
    
    # 蛋白质稳态
    {"name": "Autophagy", "id": "R-HSA-9612973"},
    {"name": "Protein ubiquitination", "id": "R-HSA-461399"},
    
    # 神经系统
    {"name": "Neuronal System", "id": "R-HSA-112316"},
    {"name": "Transmission across Chemical Synapses", "id": "R-HSA-112315"},
    
    # 血管生成
    {"name": "VEGF signaling", "id": "R-HSA-4420097"},
]


def get_pathway_info(pathway_id: str) -> Optional[Dict[str, Any]]:
    """
    获取通路的详细信息
    """
    url = f"{REACTOME_CONTENT_API}/data/pathway/{pathway_id}"
    
    try:
        response = requests.get(url, timeout=30)
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"  ❌ Failed to get pathway info: {e}")
        return None


def get_pathway_participants(pathway_id: str) -> Optional[List[Dict[str, Any]]]:
    """
    获取通路中的参与者（基因/蛋白）
    """
    url = f"{REACTOME_CONTENT_API}/data/participants/{pathway_id}"
    
    try:
        response = requests.get(url, timeout=30)
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"  ❌ Failed to get participants: {e}")
        return None


def get_pathway_genes(pathway_id: str) -> Optional[List[Dict[str, Any]]]:
    """
    获取通路中的基因列表（通过 contained events 和 physical entities）
    """
    # 方法1: 尝试获取 contained physical entities
    url = f"{REACTOME_CONTENT_API}/data/pathway/{pathway_id}/containedEvents"
    
    try:
        response = requests.get(url, timeout=30)
        if response.status_code != 200:
            # 方法2: 直接查询基因参与
            url2 = f"{REACTOME_CONTENT_API}/data/pathways/low/entity/{pathway_id}"
            response = requests.get(url2, timeout=30)
        
        if response.status_code == 404:
            return None
        
        return response.json() if response.status_code == 200 else None
    except requests.exceptions.RequestException as e:
        print(f"  ❌ Failed to get pathway genes: {e}")
        return None


def search_genes_in_pathway(pathway_id: str, pathway_name: str) -> Dict[str, Any]:
    """
    搜索通路中包含的基因
    使用多种 API 端点尝试获取最完整的基因列表
    """
    genes = set()
    gene_details = []
    
    # 尝试获取 participants
    participants = get_pathway_participants(pathway_id)
    if participants:
        for p in participants:
            if isinstance(p, dict):
                # 检查是否是蛋白/基因
                schema_class = p.get("schemaClass", "")
                if schema_class in ["EntityWithAccessionedSequence", "Protein", "Gene"]:
                    display_name = p.get("displayName", "")
                    # 提取基因符号（通常在方括号中或直接是名称）
                    if "[" in display_name:
                        gene_symbol = display_name.split("[")[0].strip()
                    else:
                        gene_symbol = display_name.split(" ")[0] if " " in display_name else display_name
                    
                    if gene_symbol and gene_symbol not in genes:
                        genes.add(gene_symbol)
                        gene_details.append({
                            "gene_symbol": gene_symbol,
                            "display_name": display_name,
                            "reactome_id": p.get("stId", ""),
                            "schema_class": schema_class
                        })
    
    # 尝试另一个端点获取更多信息
    try:
        url = f"{REACTOME_CONTENT_API}/data/pathway/{pathway_id}/referenceEntities"
        response = requests.get(url, timeout=30)
        if response.status_code == 200:
            ref_entities = response.json()
            for entity in ref_entities:
                if isinstance(entity, dict):
                    db_name = entity.get("databaseName", "")
                    if db_name in ["UniProt", "NCBI Gene"]:
                        gene_names = entity.get("geneName", [])
                        for gn in gene_names:
                            if gn and gn not in genes:
                                genes.add(gn)
                                gene_details.append({
                                    "gene_symbol": gn,
                                    "database": db_name,
                                    "identifier": entity.get("identifier", ""),
                                    "display_name": entity.get("displayName", "")
                                })
    except Exception as e:
        print(f"  ⚠️ Reference entities query failed: {e}")
    
    return {
        "pathway_id": pathway_id,
        "pathway_name": pathway_name,
        "gene_count": len(genes),
        "genes": list(genes),
        "gene_details": gene_details[:50],  # 限制详情数量
        "source": "Reactome",
        "query_time": time.strftime("%Y-%m-%d %H:%M:%S")
    }


def fetch_all_pathways(output_dir: Path):
    """
    获取所有目标通路的基因信息
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    
    print("=" * 60)
    print("📥 Fetching pathway-gene associations from Reactome...")
    print("=" * 60)
    
    pathway_data = []
    
    for i, pathway in enumerate(TARGET_PATHWAYS):
        print(f"[{i+1}/{len(TARGET_PATHWAYS)}] Querying: {pathway['name']}...")
        
        result = search_genes_in_pathway(pathway["id"], pathway["name"])
        if result and result["gene_count"] > 0:
            pathway_data.append(result)
            print(f"  ✓ Found {result['gene_count']} genes")
        else:
            print(f"  ⚠️ No genes found or query failed")
        
        time.sleep(0.3)  # 避免 API 限流
    
    # 保存数据
    output_file = output_dir / "reactome_pathway_genes.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(pathway_data, f, indent=2, ensure_ascii=False)
    print(f"\n✅ Saved {len(pathway_data)} pathway records to {output_file}")
    
    # 生成摘要
    summary = {
        "source": "Reactome",
        "fetch_time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "total_pathways": len(pathway_data),
        "pathways": [
            {
                "name": p["pathway_name"],
                "id": p["pathway_id"],
                "gene_count": p["gene_count"]
            }
            for p in pathway_data
        ],
        "total_unique_genes": len(set(g for p in pathway_data for g in p["genes"]))
    }
    
    summary_file = output_dir / "reactome_summary.json"
    with open(summary_file, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    print(f"📊 Summary saved to {summary_file}")
    
    return pathway_data


if __name__ == "__main__":
    # 设置输出目录
    script_dir = Path(__file__).parent.parent
    raw_data_dir = script_dir / "raw_data"
    
    print("🚀 Starting Reactome data fetch...")
    print(f"   Output directory: {raw_data_dir}")
    print()
    
    pathway_data = fetch_all_pathways(raw_data_dir)
    
    print("\n" + "=" * 60)
    print("✅ Reactome data fetch complete!")
    print("=" * 60)
    print(f"   Total pathways: {len(pathway_data)}")
    print(f"   Total genes: {sum(p['gene_count'] for p in pathway_data)}")
