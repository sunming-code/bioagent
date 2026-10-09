import pandas as pd

def extract_magis_subgraph():
    print("1. 正在读取 PrimeKG 完整数据 (kg.csv)...")
    # 假设你下载的文件在当前目录
    df = pd.read_csv('kg.csv', low_memory=False)
    
    print("PrimeKG 中包含的所有节点类型:", df['x_type'].unique())
    
    print("\n2. 开始抽取 MAGIS 核心子图...")
    # 定义我们的 5 大目标类型
    target_types = ['gene/protein', 'disease', 'pathway', 'phenotype', 'drug']
    
    # 核心过滤逻辑：只有当起点和终点都在这5个类型中时，我们才保留这条边
    mask = df['x_type'].isin(target_types) & df['y_type'].isin(target_types)
    subgraph_df = df[mask]
    
    print(f"抽取完成！\n原始全图边数: {len(df):,}\n过滤后子图边数: {len(subgraph_df):,}")
    
    print("\n3. 清洗并保存为 Neo4j 可直读的格式...")
    # 剔除用不到的 x_index, y_index, x_source, y_source，减小文件体积
    neo4j_df = subgraph_df[[
        'x_id', 'x_type', 'x_name', 
        'relation', 'display_relation', 
        'y_id', 'y_type', 'y_name'
    ]]
    
    # 保存结果
    output_file = 'magis_kg_edges.csv'
    neo4j_df.to_csv(output_file, index=False)
    print(f"✅ 子图已成功保存至 {output_file}！")

if __name__ == "__main__":
    extract_magis_subgraph()