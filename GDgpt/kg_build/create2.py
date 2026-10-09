import pandas as pd

def extract_mini_demo_subgraph():
    print("1. 正在读取 PrimeKG 完整数据 (kg.csv)...")
    # 假设你下载的文件在当前目录
    df = pd.read_csv('kg.csv', low_memory=False)
    
    print("\n2. 开始过滤 MAGIS 核心节点类型...")
    # 定义我们的 5 大目标类型
    target_types = ['gene/protein', 'disease', 'pathway', 'phenotype', 'drug']
    
    # 核心过滤逻辑：只有当起点和终点都在这5个类型中时，我们才保留这条边
    mask = df['x_type'].isin(target_types) & df['y_type'].isin(target_types)
    subgraph_df = df[mask]
    
    print("\n3. 制作包含 ~100 多条丰富边的 Demo 小数据集...")
    # 为了保证"丰富度"（即包含各种节点和关系），我们按 'display_relation' 分组
    # 每种关系随机抽取 15 条数据。PrimeKG 的核心关系大概有十几种
    # 这样抽样后不仅数据量小巧（100多条），导入 Neo4j 后还能看到各种不同颜色的节点和连线！
    mini_demo_df = subgraph_df.groupby('display_relation').apply(
        lambda x: x.sample(n=min(15, len(x)), random_state=42)
    ).reset_index(drop=True)
    
    print(f"抽取完成！Mini Demo 包含边数: {len(mini_demo_df)} 条")
    
    print("\n4. 清洗并保存为 Neo4j 可直读的格式...")
    # 剔除用不到的张量索引等无关列，减小文件体积
    neo4j_df = mini_demo_df[[
        'x_id', 'x_type', 'x_name', 
        'relation', 'display_relation', 
        'y_id', 'y_type', 'y_name'
    ]]
    
    # 保存结果
    output_file = 'magis_demo_100_edges.csv'
    neo4j_df.to_csv(output_file, index=False)
    print(f"✅ Demo 小数据集已成功保存至 {output_file}！您可以直接将其导入 Neo4j 测试了。")

if __name__ == "__main__":
    extract_mini_demo_subgraph()