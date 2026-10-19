"""Concurrent, same-round blind specialists with callbacks on the caller thread."""
from concurrent.futures import ThreadPoolExecutor
from queue import Empty, Queue
from time import perf_counter


def consult_specialists(agents, roles, case_info, residual_context, round_num):
    if not roles:
        return []
    events = Queue()
    callbacks = (agents.stream_callback, agents.tool_callback)
    agents.stream_callback = lambda *args: events.put((0, args))
    agents.tool_callback = lambda *args: events.put((1, args))

    def consult(role):
        started = perf_counter()
        ok = False
        try:
            events.put((0, (role, "")))
            result = agents.specialist_consult(role, case_info, residual_context, round_num)
            ok = not result.startswith("Error:")
            return f"**{role}**: {result}"
        finally:
            if hasattr(agents, "record_timing"):
                agents.record_timing("specialist.total", started, role=role, round_num=round_num, ok=ok)

    try:
        workers = min(len(roles), max(1, int(getattr(agents, "max_parallel_experts", 7))))
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="gdgpt-expert") as executor:
            futures = [executor.submit(consult, role) for role in roles]
            # Streamlit widgets and user callbacks must only run on this caller
            # thread. Drain every event before restoring callbacks or synthesizing.
            while True:
                try:
                    kind, args = events.get(timeout=0.03)
                except Empty:
                    if all(f.done() for f in futures) and events.empty():
                        break
                    continue
                if callbacks[kind]:
                    callbacks[kind](*args)
            # Completion order must not reorder the lead integrator's evidence.
            return [future.result() for future in futures]
    finally:
        agents.stream_callback, agents.tool_callback = callbacks
