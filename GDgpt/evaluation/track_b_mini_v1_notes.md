# Track B Mini v1 Notes

This file records what is currently included in `track_b_mini_v1.jsonl` and what is intentionally deferred.

## Current composition

- `4` items from `B3_self_mtb`
- `2` items from `B1_primekgqa_derived`
- `0` items from `B2_mtbbench_text`

## Why B2 is deferred for now

The public `MTBBench` question file inspected on 2026-05-13 contains `183` questions, and all `183` are yes/no longitudinal prognosis or recurrence prompts. That source is real and valuable, but it is not directly compatible with the current GDgpt metric pipeline, which expects fields such as:

- `gold_genes`
- `gold_actionable_genes`
- `gold_pathways`
- `gold_drugs`
- `expected_kg_edges`

Because of that mismatch, `MTBBench` is being tracked as a real external source candidate, but not yet injected into `track_b_mini_v1.jsonl`.

## Integrity rules for mini v1

- `B3_self_mtb` items are allowed, but must stay clearly labeled as `author_curated_public_case`.
- `B1_primekgqa_derived` items come from real external benchmark records, but are adapted into MTB-compatible prompts. They are not direct official PrimeKGQA benchmark questions and must never be described as such.
- Any future `B2_mtbbench_text` addition should either:
  - go into a separate task family and metric path, or
  - be transformed only with explicit documentation that it is a derived, not direct, benchmark item.

## Intended next step

Grow this mini set from `6` items to `10-15` items while preserving source honesty:

- add `2-4` more `B1_primekgqa_derived` items only if the source facts are clean enough
- add `2-4` more `B3_self_mtb` items for core oncology mechanisms and low-coverage honesty checks
- keep `MTBBench` in the source registry until a compatible evaluation path is defined
