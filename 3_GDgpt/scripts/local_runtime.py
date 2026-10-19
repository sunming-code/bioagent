"""Manage only this project's local Neo4j and Streamlit processes."""
import argparse
import json
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / ".runtime"
sys.path.insert(0, str(ROOT))
from utils import load_config


def port_open(port):
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1):
            return True
    except OSError:
        return False


def neo4j_command(action):
    env = os.environ.copy()
    env["JAVA_HOME"] = str(RUNTIME / "java")
    subprocess.run([str(RUNTIME / "neo4j/bin/neo4j"), action], env=env, cwd=ROOT, check=True,
                   start_new_session=True)


def owned_web_pid():
    try:
        pid = int((RUNTIME / "streamlit.pid").read_text())
        cmd = Path(f"/proc/{pid}/cmdline").read_bytes()
        return pid if b"streamlit" in cmd and str(ROOT / "app.py").encode() in cmd else None
    except (OSError, ValueError):
        return None


def stop_web():
    pid = owned_web_pid()
    if pid:
        os.kill(pid, signal.SIGTERM)
        deadline = time.monotonic() + 15
        while owned_web_pid():
            if time.monotonic() > deadline:
                raise RuntimeError("Streamlit did not stop within 15 seconds")
            time.sleep(0.1)
    (RUNTIME / "streamlit.pid").unlink(missing_ok=True)


def start():
    if not port_open(7687):
        neo4j_command("start")
    deadline = time.monotonic() + 60
    while not port_open(7687):
        if time.monotonic() > deadline:
            raise RuntimeError("Neo4j did not become ready; inspect .runtime/neo4j/logs/")
        time.sleep(1)
    subprocess.run([sys.executable, str(ROOT / "scripts/import_local_kg.py")], cwd=ROOT, check=True)
    if port_open(8501) and not owned_web_pid():
        raise RuntimeError("Port 8501 is occupied by another process")
    if not owned_web_pid():
        (RUNTIME / "logs").mkdir(parents=True, exist_ok=True)
        with (RUNTIME / "logs/streamlit.log").open("ab") as log:
            proc = subprocess.Popen(
                [sys.executable, "-m", "streamlit", "run", str(ROOT / "app.py"),
                 "--server.address", "127.0.0.1", "--server.port", "8501",
                 "--server.headless", "true", "--browser.gatherUsageStats", "false"],
                cwd=ROOT, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                start_new_session=True,
            )
        (RUNTIME / "streamlit.pid").write_text(str(proc.pid))
    deadline = time.monotonic() + 60
    while not port_open(8501):
        if not owned_web_pid() or time.monotonic() > deadline:
            raise RuntimeError("Streamlit did not start; inspect .runtime/logs/streamlit.log")
        time.sleep(1)
    print("Web: http://127.0.0.1:8501", flush=True)


def check():
    from neo4j import GraphDatabase
    from tools import Neo4jKGTool
    cfg = load_config()
    expected = json.loads((ROOT / "kg_build/task_kg_output/task_kg_summary.json").read_text())
    with GraphDatabase.driver(cfg["neo4j_uri"], auth=(cfg["neo4j_user"], cfg["neo4j_password"])) as driver:
        driver.verify_connectivity()
        with driver.session(database=cfg["neo4j_database"] or "neo4j") as session:
            n = session.run("MATCH (n) RETURN count(n) AS n").single()["n"]
            e = session.run("MATCH ()-[r]->() RETURN count(r) AS n").single()["n"]
    if (n, e) != (expected["node_count"], expected["edge_count"]):
        raise RuntimeError(f"Unexpected graph counts: {n}/{e}")
    print(f"PASS Neo4j: {n} nodes / {e} edges")
    conf = {k: cfg["neo4j_" + k] for k in ("uri", "user", "password", "database")}
    tool = Neo4jKGTool(conf)
    try:
        for query in (
            {"intent": "GeneToDisease", "gene": "TP53", "k": 3},
            {"intent": "DiseaseGenePathwayBridge", "disease": "breast carcinoma", "k": 3},
        ):
            result = tool.run_structured(json.dumps(query))
            if result.get("error") or not result.get("records"):
                raise RuntimeError(f"KG query failed: {query['intent']}")
            print(f"PASS {query['intent']}: {len(result['records'])} records")
    finally:
        if tool._driver:
            tool._driver.close()
    # Ignore shell proxy settings for local health probes.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open("http://127.0.0.1:8501/_stcore/health", timeout=5) as response:
        if response.read().strip() != b"ok":
            raise RuntimeError("Streamlit health response was not OK")
    print("PASS Streamlit health")
    if cfg.get("embedding_provider") == "local":
        from knowledge_base import DualKnowledgeBase
        kb = DualKnowledgeBase()
        kb.init_embeddings(cfg["api_key"], cfg["base_url"], provider="local",
                           model=cfg.get("embedding_model"))
        if not kb.initialized or not kb.embeddings.embed_query("乳腺癌 BRCA1"):
            raise RuntimeError("Local embeddings are unavailable")
        print("PASS local embedding model")
    print("LLM credentials: " + ("configured (use smoke to verify)" if cfg.get("api_key") else "missing"))


def smoke():
    from agents import MDTAgents
    from workflow import create_workflow, is_placeholder_final_answer
    from evaluation.run_batch_eval_template import run_one_question
    cfg = load_config()
    if not cfg.get("api_key"):
        raise RuntimeError("Configure API Key in the Web sidebar or GDGPT_API_KEY first")
    conf = {k: cfg["neo4j_" + k] for k in ("uri", "user", "password", "database")}
    agents = MDTAgents(cfg["api_key"], cfg["base_url"], cfg["text_model"], True, neo4j_conf=conf)
    # This is a deployment check, separate from six-round research experiments.
    question = "Using only the Task KG, list up to three pathways containing TP53 and cite the exact edge types. Do not make treatment recommendations. Each specialist should respond in at most 100 words and the final answer in at most 150 words."
    print(f"Running deployment workflow with model {cfg['text_model']} (max_rounds=1)", flush=True)
    started = time.monotonic()
    compiled = create_workflow(agents)

    class ProgressWorkflow:
        def stream(self, state):
            for event in compiled.stream(state):
                for stage, data in event.items():
                    print(f"Completed: {stage} ({data.get('stage_elapsed_seconds', 0):.2f}s)", flush=True)
                yield event

    result = run_one_question(ProgressWorkflow(), agents, question, max_rounds=1)
    result.update(id="local-runtime-smoke", question=question, model=cfg["text_model"], max_rounds=1,
                  generation_temperature=agents.llm.temperature,
                  reviewer_temperature=agents.critic_llm.temperature,
                  embedding_provider=cfg.get("embedding_provider", "openai"),
                  embedding_model=cfg.get("embedding_model"),
                  elapsed_seconds=round(time.monotonic()-started, 2))
    answer = result.get("answer_text", "")
    if is_placeholder_final_answer(answer) or len(answer.split()) < 20:
        raise RuntimeError("Workflow returned an empty or placeholder answer")
    runs = [run for call in result["tool_calls"] if isinstance(call.get("result"), dict)
            for run in call["result"].get("runs", [])]
    if not any(r.get("records") for r in runs):
        raise RuntimeError("Workflow returned no structured KG evidence")
    if any(run.get("error") for run in runs):
        raise RuntimeError("A KG tool reported an error during the deployment check")
    if any(not timing["ok"] for timing in result.get("execution_timings", [])):
        raise RuntimeError("A model request or specialist failed during the deployment check")
    path = ROOT / "evaluation/results/local_runtime_parallel_smoke.jsonl"
    path.write_text(json.dumps(result, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"PASS real workflow: {len(answer)} characters, {result['elapsed_seconds']} seconds")
    print(f"Result: {path}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("start", "stop", "restart-web", "status", "check", "smoke"), nargs="?", default="status")
    args = parser.parse_args()
    os.chdir(ROOT)
    if args.action == "start":
        start()
        check()
    elif args.action == "stop":
        stop_web()
        neo4j_command("stop")
    elif args.action == "restart-web":
        stop_web()
        start()
        check()
    elif args.action == "status":
        for label, port in (("Neo4j HTTP", 7474), ("Neo4j Bolt", 7687), ("Streamlit", 8501)):
            print(f"{label}: {'UP' if port_open(port) else 'DOWN'} (127.0.0.1:{port})")
    elif args.action == "check":
        check()
    else:
        smoke()


if __name__ == "__main__":
    main()
