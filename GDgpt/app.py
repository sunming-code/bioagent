import streamlit as st
import json
from agents import MDTAgents
from workflow import create_workflow
from utils import load_config, save_config
from knowledge_base import kb_system

"""
GDgpt 前端页面：收集生物医学机制问题、可选标准答案和运行配置。
启动多智能体工作流，并展示 Task KG 证据、角色分析过程和最终推理结果。
"""

#Updated Page Config & Title
st.set_page_config(page_title="GDgpt - 多智能体生物医学知识推理系统", layout="wide", page_icon="🧬")

st.markdown("""
<style>
    .role-badge { background-color: #e8f4f8; padding: 4px 8px; border-radius: 4px; font-weight: bold; color: #0066cc; font-size: 0.9em;}
    .cot-box { border: 2px dashed #6f42c1; padding: 15px; border-radius: 10px; margin-top: 10px; background-color: #f3f0ff; }
    .retrieval-box { font-size: 0.85em; color: #555; border-left: 3px solid #6c757d; padding-left: 10px; margin-bottom: 5px; background: #fafafa; padding: 5px;}
    .tool-box { font-size: 0.85em; color: #2e7d32; border-left: 3px solid #2e7d32; padding-left: 10px; margin-bottom: 5px; background: #f1f8e9; padding: 5px;}
    .kg-box { font-size: 0.9em; color: #37474f; border-left: 3px solid #1565c0; padding-left: 10px; margin-bottom: 8px; background: #eef5ff; padding: 8px;}
    .context-label { font-weight: bold; color: #495057; font-size: 0.9em; }
    .saved-badge { color: green; font-weight: bold; }
    .not-saved-badge { color: #dc3545; font-weight: bold; }
</style>
""", unsafe_allow_html=True)

if "config" not in st.session_state:
    st.session_state.config = load_config()

#Sidebar
with st.sidebar:
    st.title("🧬 GDgpt")
    st.caption("多智能体生物医学知识推理系统")

    with st.expander("⚙️ 系统配置", expanded=False):
        with st.form("config_form"):
            api_key = st.text_input("API Key", value=st.session_state.config.get("api_key", ""), type="password")
            base_url = st.text_input("Base URL", value=st.session_state.config.get("base_url",
                                                                                   "https://dashscope.aliyuncs.com/compatible-mode/v1"))
            text_model = st.text_input("Text Model ID", value=st.session_state.config.get("text_model", "qwen-plus"))
            enable_tools = st.checkbox("启用外部检索 / PubMed / Neo4j KG",
                                       value=st.session_state.config.get("enable_tools", True))

            st.divider()
            st.markdown("#### Neo4j (Bolt)")
            neo4j_uri = st.text_input("Neo4j URI", value=st.session_state.config.get("neo4j_uri", ""),
                                      placeholder="neo4j://localhost:7687")
            neo4j_user = st.text_input("Neo4j Username", value=st.session_state.config.get("neo4j_user", ""))
            neo4j_password = st.text_input("Neo4j Password", value=st.session_state.config.get("neo4j_password", ""),
                                           type="password")
            neo4j_database = st.text_input("Neo4j Database（可选）",
                                           value=st.session_state.config.get("neo4j_database", ""),
                                           placeholder="neo4j")
            if st.form_submit_button("保存配置"):
                new_conf = {
                    "api_key": api_key,
                    "base_url": base_url,
                    "text_model": text_model,
                    "enable_tools": enable_tools,
                    "neo4j_uri": neo4j_uri,
                    "neo4j_user": neo4j_user,
                    "neo4j_password": neo4j_password,
                    "neo4j_database": neo4j_database
                }
                save_config(new_conf)
                st.session_state.config = new_conf
                st.success("配置已保存。")

    if st.session_state.config.get("enable_tools") and not st.session_state.config.get("neo4j_uri"):
        st.warning("Neo4j URI 为空。请填写并保存后再使用 Neo4j_KG。")

    max_rounds = st.slider("最大推理轮数", 3, 15, 6)

    st.divider()
    st.subheader("🧠 推理过程记录")
    context_container = st.container()

#Main Interface
st.title("GDgpt - 多智能体生物医学知识推理系统")
st.caption("结合 Neo4j Task KG、外部检索与多角色智能体，对基因、疾病、通路、表型和药物相关问题进行结构化推理。")
st.markdown("---")

col1, col2 = st.columns([1, 1.5])

with col1:
    st.subheader("生物医学问题输入")
    case_input = st.text_area("问题描述", height=200, placeholder="请输入基因、疾病、通路、表型或药物相关的机制分析问题...")

    st.markdown("### 🎓 评测模式（可选）")
    ground_truth = st.text_input("标准答案（可选）")

    start_btn = st.button("🚀 开始知识推理", type="primary")


#UI Handler
def safe_json_load(text):
    try:
        return json.loads(text)
    except Exception:
        return None


def render_kg_run(container, run):
    label = run.get("label") or run.get("tool", "未知工具")
    intent = run.get("intent", "-")
    records = run.get("records", [])
    text = run.get("text", "")
    display_labels = {
        "disease": "疾病",
        "gene": "基因",
        "pathway": "通路",
        "phenotype": "表型",
        "drug": "药物",
        "genes": "相关基因",
        "gene_count": "基因数量",
        "relation": "关系",
        "disease_relation": "疾病关系",
        "phenotype_relation": "表型关系",
        "disease_gene_relations": "疾病-基因关系",
        "gene_pathway_relations": "基因-通路关系",
        "drug_gene_relations": "药物-基因关系",
        "gene_disease_relations": "基因-疾病关系",
        "source": "来源",
        "disease_sources": "疾病证据来源",
        "pathway_sources": "通路证据来源",
        "weight": "权重",
        "disease_gene_weight": "疾病-基因权重",
        "gene_pathway_weight": "基因-通路权重",
        "drug_gene_weight": "药物-基因权重",
        "gene_disease_weight": "基因-疾病权重",
    }

    with container.expander(f"KG 查询：{label}（{intent}）", expanded=False):
        stats_cols = st.columns(4)
        stats_cols[0].metric("记录数", len(records))
        stats_cols[1].metric("基因命中", sum(1 for rec in records if rec.get("gene")))
        stats_cols[2].metric("通路命中", sum(1 for rec in records if rec.get("pathway")))
        stats_cols[3].metric(
            "表型/药物",
            sum(1 for rec in records if rec.get("phenotype")) + sum(1 for rec in records if rec.get("drug"))
        )

        if records:
            for rec in records[:5]:
                pairs = []
                for key in [
                    "disease", "gene", "pathway", "phenotype", "drug", "genes",
                    "gene_count", "relation", "disease_relation", "phenotype_relation",
                    "disease_gene_relations", "gene_pathway_relations",
                    "drug_gene_relations", "gene_disease_relations",
                    "source", "disease_sources", "pathway_sources",
                    "weight", "disease_gene_weight", "gene_pathway_weight",
                    "drug_gene_weight", "gene_disease_weight"
                ]:
                    if key in rec and rec[key] not in (None, "", []):
                        value = rec[key]
                        if isinstance(value, list):
                            value = ", ".join(map(str, value))
                        pairs.append(f"**{display_labels.get(key, key)}**: {value}")
                st.markdown(f"<div class='kg-box'>{'<br>'.join(pairs)}</div>", unsafe_allow_html=True)
        else:
            st.markdown(f"<div class='tool-box'>{text}</div>", unsafe_allow_html=True)


class UIHandler:
    def __init__(self, container):
        self.root_container = container
        self.current_role = None
        self.role_expander = None
        self.text_placeholder = None
        self.full_text = ""

    def _ensure_expander(self, role):
        if role != self.current_role:
            self.current_role = role
            self.full_text = ""
            self.role_expander = self.root_container.expander(f"🗣️ {role} 正在分析...", expanded=True)
            self.text_placeholder = self.role_expander.empty()

    def on_token(self, role, token):
        self._ensure_expander(role)
        self.full_text += token
        self.text_placeholder.markdown(self.full_text + "▌")

    def finish_turn(self):
        if self.text_placeholder:
            self.text_placeholder.markdown(self.full_text)

    def on_tool_output(self, role, query, result):
        self._ensure_expander(role)
        with self.role_expander:
            with st.expander(f"🛠️ 工具调用：{query}", expanded=False):
                parsed = safe_json_load(result)
                if isinstance(parsed, dict) and isinstance(parsed.get("runs"), list):
                    for run in parsed["runs"]:
                        render_kg_run(st, run)
                else:
                    st.markdown(f"<div class='tool-box'>{result}</div>", unsafe_allow_html=True)


# Execution
if start_btn:
    cfg = st.session_state.config
    if not cfg.get("api_key"): st.stop()

    neo4j_conf = {
        "uri": cfg.get("neo4j_uri", ""),
        "user": cfg.get("neo4j_user", ""),
        "password": cfg.get("neo4j_password", ""),
        "database": cfg.get("neo4j_database", "")
    }
    agents = MDTAgents(cfg["api_key"], cfg["base_url"], cfg["text_model"], cfg["enable_tools"], neo4j_conf=neo4j_conf)
    app = create_workflow(agents)

    with col2:
        st.subheader("多智能体推理过程")
        status_log = st.status("正在初始化工作流...", expanded=True)
        chat_box = st.container()

        ui = UIHandler(chat_box)
        agents.set_stream_callback(ui.on_token)
        agents.set_tool_callback(ui.on_tool_output)

        if hasattr(agents.tools, "get_tool_status"):
            tool_status = agents.tools.get_tool_status()
            neo4j_status = tool_status.get("Neo4j_KG", {"ok": "false", "message": "未知状态"})
            if neo4j_status.get("ok") == "true":
                status_log.write("✅ Neo4j_KG 连接成功。")
            else:
                status_log.write(f"⚠️ Neo4j_KG 暂不可用：{neo4j_status.get('message')}")
                chat_box.warning(f"Neo4j_KG 暂不可用：{neo4j_status.get('message')}")
        else:
            status_log.write("⚠️ 当前进程无法检查工具状态，请重启 Streamlit 后再试。")
            chat_box.warning("当前进程无法检查工具状态，请重启 Streamlit 后再试。")

        state = {
            "case_info": case_input, "ground_truth": ground_truth,
            "selected_roles": [], "triage_reason": "", "current_round": 1, "max_rounds": max_rounds,
            "context_bullets": [], "final_answer": "", "is_converged": False,
            "kb_context_text": "", "kb_context_docs": [],
            "kg_prefetch_text": "", "kg_prefetch_runs": [], "kg_prefetch_plan": {}
        }

        try:
            for event in app.stream(state):

                if "triage" in event:
                    data = event["triage"]
                    status_log.write(f"✅ 角色分工完成。")

                    docs = data.get('kb_context_docs', [])
                    if docs:
                        with chat_box.expander(f"📚 长期经验检索（{len(docs)} 条匹配）", expanded=False):
                            for doc in docs:
                                source = doc.metadata.get("source_kb", "Unknown")
                                st.markdown(
                                    f"<div class='retrieval-box'><b>来源：</b> {source}<br>{doc.page_content}</div>",
                                    unsafe_allow_html=True)
                    else:
                        chat_box.caption("ℹ️ 未找到相关的长期经验记录。")

                    chat_box.info(f"**📋 角色分工依据：** {data['triage_reason']}")
                    chat_box.success(f"**已选择分析角色：** {', '.join(data['selected_roles'])}")
                    chat_box.markdown("---")

                if "kg_prefetch" in event:
                    data = event["kg_prefetch"]
                    status_log.write("✅ Task KG 证据预取完成。")
                    chat_box.info("已在多角色分析前加载共享 Task KG 证据。")
                    with chat_box.expander("🧭 共享 Task KG 证据预取", expanded=False):
                        plan = data.get("kg_prefetch_plan", {})
                        if plan:
                            st.caption("共享查询计划")
                            st.code(json.dumps(plan, indent=2, ensure_ascii=False), language="json")
                        runs = data.get("kg_prefetch_runs", [])
                        if runs:
                            for run in runs:
                                render_kg_run(st, run)
                        else:
                            st.markdown(
                                f"<div class='tool-box'>{data.get('kg_prefetch_text', '暂无共享 KG 证据。')}</div>",
                                unsafe_allow_html=True
                            )

                if "consultation_layer" in event:
                    ui.finish_turn()
                    data = event["consultation_layer"]
                    rnd = data["current_round"]
                    status_log.update(label=f"第 {rnd} 轮：多角色推理中...", state="running")

                    # --- Update Sidebar with 6-Part Context ---
                    latest_bullet = data["context_bullets"][-1]
                    with context_container:
                        with st.expander(f"📝 第 {rnd} 轮推理摘要", expanded=False):
                            try:
                                ctx_data = json.loads(latest_bullet)
                                # 6-Part Display
                                st.markdown(
                                    f"<span class='context-label'>一致性：</span> {ctx_data.get('Consistency', '-')}",
                                    unsafe_allow_html=True)
                                st.markdown(
                                    f"<span class='context-label'>冲突点：</span> {ctx_data.get('Conflict', '-')}",
                                    unsafe_allow_html=True)
                                st.markdown(
                                    f"<span class='context-label'>独立见解：</span> {ctx_data.get('Independence', '-')}",
                                    unsafe_allow_html=True)
                                st.markdown(
                                    f"<span class='context-label'>综合推理：</span> {ctx_data.get('Integration', '-')}",
                                    unsafe_allow_html=True)
                                st.markdown(
                                    f"<span class='context-label'>工具使用：</span> {ctx_data.get('Tools_Usage', '-')}",
                                    unsafe_allow_html=True)
                                st.markdown(
                                    f"<span class='context-label'>长期经验：</span> {ctx_data.get('Long_Term_Experience', '-')}",
                                    unsafe_allow_html=True)
                            except:
                                st.text(latest_bullet)

                if "safety_layer" in event:
                    data = event["safety_layer"]
                    if data["is_converged"]:
                        status_log.update(label="✅ 推理已收敛", state="complete", expanded=False)
                        st.balloons()
                        st.markdown("### 🏁 最终知识推理结论")
                        st.success(data["final_answer"])

                        # Training Logic
                        if ground_truth:
                            st.markdown("---")
                            st.markdown("### 🧪 结果评测与经验沉淀")
                            with st.spinner("正在评测结果并保存经验..."):
                                result = agents.cot_reviewer(case_input, data["final_answer"], ground_truth)

                                st.markdown(f"<div class='cot-box'>", unsafe_allow_html=True)

                                if result.get("is_correct"):
                                    st.markdown("#### ✅ 结果正确")
                                    summary_s4 = result.get("summary_s4", "暂无摘要。")
                                    st.write(f"**最终推理摘要：** {summary_s4}")

                                    # Formulate Record for CorrectKB
                                    record = {
                                        "Question": case_input,
                                        "Answer": data["final_answer"],
                                        "Summary of S4_final": summary_s4
                                    }
                                    kb_system.save_correct_experience(record)

                                    st.markdown("---")
                                    st.markdown(f"<span class='saved-badge'>✅ 已保存到：CorrectKB</span>",
                                                unsafe_allow_html=True)
                                    st.markdown(
                                        f"<span class='not-saved-badge'>❌ 未保存到：ChainKB（原因：结果正确）</span>",
                                        unsafe_allow_html=True)

                                else:
                                    st.markdown("#### ❌ 结果不正确")
                                    st.write(f"**错误反思：** {result.get('error_reflection', '-')}")

                                    # Formulate Record for ChainKB
                                    record = {
                                        "Question": case_input,
                                        "Correct Answer": ground_truth,
                                        "Initial Hypothesis": result.get("initial_hypothesis", "-"),
                                        "Analysis Process": result.get("analysis_process", "-"),
                                        "Final Conclusion": result.get("final_conclusion", "-"),
                                        "Error Reflection": result.get("error_reflection", "-")
                                    }
                                    kb_system.save_reflection_experience(record)

                                    st.markdown("---")
                                    st.markdown(f"<span class='saved-badge'>✅ 已保存到：ChainKB</span>",
                                                unsafe_allow_html=True)
                                    st.markdown(
                                        f"<span class='not-saved-badge'>❌ 未保存到：CorrectKB（原因：结果不正确）</span>",
                                        unsafe_allow_html=True)

                                st.markdown("</div>", unsafe_allow_html=True)
                    else:
                        chat_box.warning("⚠️ 当前结论尚未收敛，继续下一轮推理。")

        except Exception as e:
            st.error(f"运行出错：{e}")
