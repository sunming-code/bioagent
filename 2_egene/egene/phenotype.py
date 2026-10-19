"""Auditable HPO resolution and semantic similarity, without invented symptoms."""
from __future__ import annotations

from collections import Counter, defaultdict
from functools import lru_cache
import math
import re
import unicodedata


def normalized_label(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


class Ontology:
    def __init__(self, terms: dict):
        self.terms = terms
        self.alternatives = {alt: identifier for identifier, term in terms.items() for alt in term["alt_ids"]}
        self.labels = defaultdict(set)
        for identifier, term in terms.items():
            if not term["obsolete"]:
                for name in term["names"]:
                    self.labels[normalized_label(name)].add(identifier)
        self._visiting = set()

    def canonical(self, identifier: str) -> str:
        identifier = self.alternatives.get(identifier, identifier)
        visited = set()
        while identifier in self.terms and self.terms[identifier]["obsolete"]:
            if identifier in visited:
                raise ValueError("HPO obsolete replacement cycle")
            visited.add(identifier)
            replacements = self.terms[identifier].get("replacements", [])
            if len(replacements) != 1:
                raise ValueError(f"HPO 条目已废弃且无法唯一替代: {identifier}")
            identifier = replacements[0]
        if identifier not in self.terms:
            raise ValueError(f"未知 HPO 标识: {identifier}")
        return identifier

    @lru_cache(maxsize=None)
    def ancestors(self, identifier: str) -> frozenset[str]:
        if identifier in self._visiting:
            raise ValueError("HPO is_a 层次存在循环")
        self._visiting.add(identifier)
        result = {identifier}
        try:
            for parent in self.terms[identifier]["parents"]:
                if parent in self.terms:
                    result.update(self.ancestors(parent))
        finally:
            self._visiting.remove(identifier)
        return frozenset(result)

    def phenotype(self, identifier: str) -> bool:
        return "HP:0000118" in self.ancestors(identifier)

    def describe(self, identifier: str) -> dict:
        return {"id": identifier, "label": self.terms[identifier]["name"]}


def resolve_case(case: dict, ontology: Ontology, aliases: dict) -> dict:
    positive, negative, entries, unresolved = set(), set(), [], []
    local_aliases = {normalized_label(name): ontology.canonical(identifier) for name, identifier in aliases.items()}
    for entry in case.get("phenotypes", []):
        method = "explicit_id"
        if "id" in entry:
            identifier = ontology.canonical(entry["id"])
        else:
            label = normalized_label(entry["label"])
            matches = ({local_aliases[label]} if label in local_aliases else ontology.labels.get(label, set()))
            if len(matches) != 1:
                unresolved.append({"input": entry, "reason": "ambiguous_label" if matches else "unrecognized_label", "candidates": sorted(matches)})
                continue
            identifier = next(iter(matches))
            method = "configured_alias" if label in local_aliases else "exact_ontology_label_or_synonym"
        if not ontology.phenotype(identifier):
            raise ValueError(f"病例表型必须属于 Phenotypic abnormality 分支: {identifier}")
        # Broad ontology roots carry no patient-specific information.
        if identifier == "HP:0000118":
            unresolved.append({"input": entry, "reason": "uninformative_phenotype_root", "candidates": []})
            continue
        target = positive if entry["observed"] else negative
        target.add(identifier)
        entries.append({"input": entry, "resolved": ontology.describe(identifier), "method": method})
    for present in positive:
        if any(absent in ontology.ancestors(present) for absent in negative):
            raise ValueError(f"病例同时肯定和否定同一表型或其上位概念: {present}")
    return {"sample_id": case["sample_id"], "sex": case.get("sex", "unknown"),
            "positive_hpo_ids": sorted(positive), "negative_hpo_ids": sorted(negative),
            "resolved_entries": entries, "unresolved_entries": unresolved,
            "status": ("partial" if unresolved else "resolved") if positive else "no_resolved_positive_phenotypes",
            "clinical_description": case.get("clinical_description", ""),
            "clinical_description_interpreted": False,
            "age_years": case.get("age_years"), "onset_age_years": case.get("onset_age_years"),
            "age_and_onset_usage": "retained_for_review; no unvalidated age cutoff or automatic exclusion"}


def frequency_fraction(value: str) -> float | None:
    value = value.strip()
    ranges = {"HP:0040280": 1.0, "HP:0040281": 0.895, "HP:0040282": 0.545,
              "HP:0040283": 0.17, "HP:0040284": 0.025, "HP:0040285": 0.0}
    if value in ranges:
        return ranges[value]
    try:
        if re.fullmatch(r"\d+/\d+", value):
            first, last = map(int, value.split("/"))
            return first / last if last and 0 <= first <= last else None
        if value.endswith("%"):
            fraction = float(value[:-1]) / 100
            return fraction if 0 <= fraction <= 1 else None
    except ValueError:
        pass
    return None


class PhenotypeScorer:
    def __init__(self, database, ontology: Ontology, negative_penalty: float = 0.25):
        self.ontology = ontology
        self.negative_penalty = negative_penalty
        profiles = defaultdict(set)
        for row in database.connection.execute("SELECT DISTINCT disease_id,hpo_id,frequency FROM annotations WHERE aspect='P' AND negated=0"):
            if frequency_fraction(row[2]) == 0:
                continue
            identifier = ontology.canonical(row[1])
            if ontology.phenotype(identifier):
                profiles[row[0]].add(identifier)
        counts = Counter()
        for terms in profiles.values():
            closure = set()
            for term in terms:
                closure.update(ontology.ancestors(term))
            counts.update(closure)
        total = len(profiles)
        self.ic = {identifier: -math.log((counts[identifier] + 1) / (total + 1)) for identifier in ontology.terms}
        self.corpus_diseases = total

    @lru_cache(maxsize=200000)
    def similarity(self, first: str, second: str) -> tuple[float, str]:
        shared = self.ontology.ancestors(first) & self.ontology.ancestors(second)
        if not shared:
            return 0.0, "HP:0000001"
        ancestor = min(shared, key=lambda identifier: (-self.ic[identifier], identifier))
        denominator = self.ic[first] + self.ic[second]
        score = 2 * self.ic[ancestor] / denominator if denominator > 0 else 0.0
        return min(1.0, max(0.0, score)), ancestor

    def score(self, resolved: dict, annotations: list[dict]) -> dict:
        positive, negative, disease_positive, disease_negative = resolved["positive_hpo_ids"], resolved["negative_hpo_ids"], {}, set()
        for annotation in annotations:
            if annotation["aspect"] != "P":
                continue
            identifier = self.ontology.canonical(annotation["hpo_id"])
            if not self.ontology.phenotype(identifier):
                continue
            fraction = frequency_fraction(annotation["frequency"])
            if annotation["negated"] or fraction == 0:
                disease_negative.add(identifier)
            else:
                disease_positive.setdefault(identifier, []).append(annotation)
        result = {"status": "not_evaluated_no_positive_phenotypes", "score": None, "positive_score": None,
                  "negative_conflict_fraction": None, "matches": [], "contradictions": [],
                  "method": "Lin symmetric best-match average; corpus IC; not a diagnostic probability"}
        if not positive:
            return result
        if not disease_positive:
            result["status"] = "not_evaluated_no_disease_phenotypes"
            return result
        forward = []
        for query in positive:
            target = min(disease_positive, key=lambda term: (-self.similarity(query, term)[0], term))
            score, mica = self.similarity(query, target)
            forward.append(score)
            result["matches"].append({"patient": self.ontology.describe(query), "disease": self.ontology.describe(target),
                                      "similarity": round(score, 6), "common_ancestor": self.ontology.describe(mica),
                                      "annotation_references": sorted({row["reference"] for row in disease_positive[target]})})
        backward = [max(self.similarity(query, term)[0] for query in positive) for term in disease_positive]
        positive_score = (sum(forward) / len(forward) + sum(backward) / len(backward)) / 2
        conflicts = []
        for absent in negative:
            implicated = [term for term in disease_positive if absent in self.ontology.ancestors(term)]
            if implicated:
                conflicts.append({"type": "patient_absent_disease_present", "patient": self.ontology.describe(absent),
                                  "disease_hpo_ids": sorted(implicated), "severity": max(
                                      (frequency_fraction(row["frequency"]) if frequency_fraction(row["frequency"]) is not None else 0.5)
                                      for term in implicated for row in disease_positive[term])})
        for query in positive:
            excluded = [term for term in disease_negative if term in self.ontology.ancestors(query)]
            if excluded:
                conflicts.append({"type": "patient_present_disease_excluded", "patient": self.ontology.describe(query),
                                  "disease_hpo_ids": sorted(excluded), "severity": 1.0})
        conflict_fraction = sum(row["severity"] for row in conflicts) / max(1, len(negative) + len(positive))
        result.update(status="evaluated", score=round(max(0.0, positive_score - self.negative_penalty * conflict_fraction), 6),
                      positive_score=round(positive_score, 6), negative_conflict_fraction=round(conflict_fraction, 6),
                      contradictions=conflicts)
        return result
