"""Concurrency invariants: barriers, ordering, blindness, UI and real local KG."""
import json
import sys
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from agents import MDTAgents
from parallel_execution import consult_specialists
from tools import MedicalTools, Neo4jKGTool
from utils import load_config
from workflow import create_workflow

ROLES = ["GeneCurator", "PathwayBiologist", "EvidenceReviewer", "HypothesisIntegrator"]


class FakeAgents(MDTAgents):
    def __init__(self, workers=4):
        super().__init__("test-key", "http://127.0.0.1:1/v1", "test-model",
                         enable_tools=False, max_parallel_experts=workers)
        self.barrier = threading.Barrier(workers)
        self.completed = []
        self.contexts = []
        self.lock = threading.Lock()

    def primary_care_doctor(self, case_info):
        return {"selected_roles": ROLES, "reasoning": "test"}

    def specialist_consult(self, role, case_info, residual_context, round_num=1):
        self.barrier.wait(timeout=3)
        with self.lock:
            self.contexts.append((round_num, residual_context))
        time.sleep(0.01 * (4 - ROLES.index(role)))
        if self.tool_callback:
            self.tool_callback(role, "query", json.dumps({"runs": []}))
        for token in (role, ":done"):
            if self.stream_callback:
                self.stream_callback(role, token)
        with self.lock:
            self.completed.append((round_num, role))
        return role + ":done"

    def lead_physician_synthesis(self, dialogues, round_num):
        assert all((round_num, role) in self.completed for role in ROLES)
        assert dialogues == [f"**{role}**: {role}:done" for role in ROLES]
        return "substantive-summary-round-" + str(round_num)

    def safety_reviewer(self, bullet, round_num):
        if round_num == 1:
            return "STATUS: DIVERGED\nFINAL_ANSWER: Continuing analysis"
        return "STATUS: CONVERGED\nFINAL_ANSWER: substantive final report"


class ParallelChecks(unittest.TestCase):
    def test_experts_overlap_callbacks_stay_on_caller_and_order_is_stable(self):
        agents = FakeAgents()
        caller = threading.get_ident()
        texts = {role: "" for role in ROLES}
        def token(role, text):
            self.assertEqual(threading.get_ident(), caller)
            texts[role] += text
        def tool(*args):
            self.assertEqual(threading.get_ident(), caller)
        agents.set_stream_callback(token)
        agents.set_tool_callback(tool)
        result = consult_specialists(agents, ROLES, "case", "identical previous context", 1)
        self.assertEqual(result, [f"**{r}**: {r}:done" for r in ROLES])
        self.assertEqual(texts, {r: r + ":done" for r in ROLES})
        self.assertEqual(len(set(c for _, c in agents.contexts)), 1)
        self.assertEqual(agents.completed[0][1], ROLES[-1])
        self.assertIs(agents.stream_callback, token)
        self.assertIs(agents.tool_callback, tool)

    def test_worker_limit_is_enforced(self):
        agents = FakeAgents(workers=2)
        active, maximum = 0, 0
        lock = threading.Lock()
        def work(role, *args):
            nonlocal active, maximum
            with lock:
                active += 1
                maximum = max(maximum, active)
            agents.barrier.wait(timeout=3)
            time.sleep(0.02)
            with lock:
                active -= 1
            return role
        agents.specialist_consult = work
        consult_specialists(agents, ROLES, "case", "context", 1)
        self.assertEqual(maximum, 2)

    def test_exception_restores_callbacks_and_does_not_drop_other_workers(self):
        agents = FakeAgents()
        original = lambda *args: None
        agents.stream_callback = original
        def work(role, *args):
            agents.barrier.wait(timeout=3)
            if role == ROLES[0]:
                raise RuntimeError("expected worker failure")
            agents.completed.append(role)
            return role
        agents.specialist_consult = work
        with self.assertRaisesRegex(RuntimeError, "expected worker failure"):
            consult_specialists(agents, ROLES, "case", "context", 1)
        self.assertIs(agents.stream_callback, original)
        self.assertEqual(set(agents.completed), set(ROLES[1:]))

    def test_two_round_workflow_preserves_blindness_and_synthesis_barrier(self):
        agents = FakeAgents()
        state = dict(case_info="case", ground_truth="SECRET_GOLD", current_round=1,
                     max_rounds=2, context_bullets=[], selected_roles=[], is_converged=False)
        with patch("workflow.kb_system.init_embeddings"), patch(
            "workflow.kb_system.retrieve_context_details", return_value={"text": "prior", "docs": []}
        ):
            events = list(create_workflow(agents).stream(state))
        self.assertEqual(events[-1]["safety_layer"]["final_answer"], "substantive final report")
        for rnd in (1, 2):
            contexts = [ctx for n, ctx in agents.contexts if n == rnd]
            self.assertEqual(len(contexts), 4)
            self.assertEqual(len(set(contexts)), 1)
            self.assertNotIn("SECRET_GOLD", contexts[0])
            self.assertEqual("substantive-summary-round-1" in contexts[0], rnd == 2)
        self.assertTrue(all("stage_elapsed_seconds" in update for event in events for update in event.values()))

    def test_batch_evidence_keeps_round_then_role_order(self):
        from evaluation.run_batch_eval_template import run_one_question
        agents = FakeAgents()
        with patch("workflow.kb_system.init_embeddings"), patch(
            "workflow.kb_system.retrieve_context_details", return_value={"text": "prior", "docs": []}
        ):
            result = run_one_question(create_workflow(agents), agents, "case", max_rounds=2)
        self.assertEqual([call["role"] for call in result["tool_calls"]], ROLES * 2)

    def test_questions_sharing_an_agent_do_not_replace_each_others_callbacks(self):
        from evaluation.run_batch_eval_template import run_one_question
        agents = FakeAgents()
        app = create_workflow(agents)
        with patch("workflow.kb_system.init_embeddings"), patch(
            "workflow.kb_system.retrieve_context_details", return_value={"text": "prior", "docs": []}
        ):
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(run_one_question, app, agents, f"case-{i}", 1) for i in range(2)]
                results = [future.result(timeout=10) for future in futures]
        for result in results:
            self.assertEqual([call["role"] for call in result["tool_calls"]], ROLES)
            self.assertEqual(len([t for t in result["execution_timings"] if t["stage"] == "specialist.total"]), 4)

    def test_triage_and_experience_retrieval_overlap(self):
        agents = FakeAgents()
        barrier = threading.Barrier(2)
        def triage(case):
            barrier.wait(timeout=3)
            return {"selected_roles": ROLES, "reasoning": "test"}
        def retrieve(case):
            barrier.wait(timeout=3)
            return {"text": "prior", "docs": []}
        agents.primary_care_doctor = triage
        state = dict(case_info="case", ground_truth="", current_round=1,
                     max_rounds=1, context_bullets=[], selected_roles=[], is_converged=False)
        with patch("workflow.kb_system.init_embeddings"), patch(
            "workflow.kb_system.retrieve_context_details", side_effect=retrieve
        ):
            events = list(create_workflow(agents).stream(state))
        self.assertTrue(events[-1]["safety_layer"]["is_converged"])

    def test_adaptive_classification_overlaps_triage(self):
        agents = FakeAgents()
        agents.adaptive_routing = True
        barrier = threading.Barrier(2)
        def triage(case):
            barrier.wait(timeout=3)
            return {"selected_roles": ROLES, "reasoning": "test"}
        def complexity(case):
            barrier.wait(timeout=3)
            return "moderate"
        agents.primary_care_doctor, agents.assess_complexity = triage, complexity
        with patch("workflow.kb_system.init_embeddings"), patch(
            "workflow.kb_system.retrieve_context_details", return_value={"text": "prior", "docs": []}
        ):
            stream = create_workflow(agents).stream(dict(case_info="case", max_rounds=6, context_bullets=[]))
            first = next(stream)["triage"]
            stream.close()
        self.assertEqual(first["selected_roles"], ROLES[:3])
        self.assertEqual(first["max_rounds"], 1)

    def test_shared_experience_model_initializes_once(self):
        from knowledge_base import DualKnowledgeBase
        kb, calls = DualKnowledgeBase(), []
        barrier = threading.Barrier(8)
        def construct(**kwargs):
            calls.append(1)
            time.sleep(.02)
            return object()
        def init(_):
            barrier.wait(timeout=3)
            kb.init_embeddings("test-key", "http://127.0.0.1:1/v1")
        with patch("knowledge_base.OpenAIEmbeddings", side_effect=construct), patch.object(kb, "_load_stores"):
            with ThreadPoolExecutor(max_workers=8) as pool:
                list(pool.map(init, range(8)))
        self.assertTrue(kb.initialized)
        self.assertEqual(len(calls), 1)

    def test_independent_kg_plan_queries_overlap_and_preserve_order_and_errors(self):
        tools = MedicalTools(enable=False, max_parallel_queries=3)
        tools.enable, tools.tools = True, [object()]
        tools._tool_by_name["Neo4j_KG"] = object()
        barrier = threading.Barrier(3)
        class KG:
            def run_structured(self, text):
                row = json.loads(text)
                barrier.wait(timeout=3)
                time.sleep((3-row["index"]) * .01)
                return {"text": str(row["index"]), "records": [], **({"error": "bad query"} if row["index"] == 1 else {})}
        tools.neo4j_kg = KG()
        rows = tools.execute_plan(json.dumps({"queries": [{"tool": "Neo4j_KG", "index": i} for i in range(3)]}))["runs"]
        self.assertEqual([row["text"] for row in rows], ["0", "1", "2"])
        self.assertEqual(rows[1]["error"], "bad query")
        self.assertTrue(all("elapsed_seconds" in row for row in rows))

    def test_live_kg_initialization_and_errors_are_isolated(self):
        cfg = load_config()
        if not cfg.get("neo4j_uri"):
            self.skipTest("No configured Neo4j")
        from neo4j import GraphDatabase
        kg = Neo4jKGTool({k: cfg["neo4j_"+k] for k in ("uri", "user", "password", "database")})
        original = GraphDatabase.driver
        starts = threading.Barrier(8)
        creates = []
        def factory(*args, **kwargs):
            creates.append(1)
            time.sleep(.02)
            return original(*args, **kwargs)
        def work(index):
            starts.wait(timeout=3)
            # A per-thread diagnostic must never leak to another query.
            kg.last_error = str(index)
            starts.wait(timeout=3)
            self.assertEqual(kg.last_error, str(index))
            result = kg.run_structured(json.dumps({"intent": "GeneToPathway", "gene": "TP53", "k": 3}))
            self.assertFalse(result.get("error"))
            self.assertTrue(result["records"])
        try:
            with patch.object(GraphDatabase, "driver", side_effect=factory):
                with ThreadPoolExecutor(max_workers=8) as pool:
                    list(pool.map(work, range(8)))
            self.assertEqual(len(creates), 1)
        finally:
            if kg._driver:
                kg._driver.close()

    def test_streamlit_parallel_role_outputs_are_separate(self):
        from streamlit.testing.v1 import AppTest
        agents = FakeAgents()
        # Exercise the actual workflow and callback queue through the Web button.
        # Two rounds exercise UI buffers and cursor cleanup across boundaries.
        with patch("agents.MDTAgents", return_value=agents), patch("workflow.kb_system.init_embeddings"), patch(
            "workflow.kb_system.retrieve_context_details", return_value={"text": "prior", "docs": []}
        ):
            page = AppTest.from_file(str(ROOT / "app.py"), default_timeout=20).run()
            next(b for b in page.button if "开始知识推理" in b.label).click().run()
        self.assertFalse(page.exception, [e.message for e in page.exception])
        for role in ROLES:
            panels = [panel for panel in page.expander if panel.label == f"🗣️ {role} 正在分析..."]
            self.assertEqual(len(panels), 2)
            for panel in panels:
                text = "\n".join(block.value for block in panel.markdown)
                self.assertIn(role + ":done", text)
                self.assertNotIn("▌", text)
                for other in ROLES:
                    if other != role:
                        self.assertNotIn(other + ":done", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
