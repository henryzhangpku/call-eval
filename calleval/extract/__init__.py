"""Extractor backends behind one interface.

An extractor turns transcripts into `CallExtraction`s: typed fields plus
evidence spans. It never produces a score.
"""

from __future__ import annotations

from typing import Protocol

from calleval.schema import CallExtraction, Transcript


class Extractor(Protocol):
    backend: str
    model_id: str
    question_version: str

    def extract_calls(self, transcripts: list[Transcript]) -> list[CallExtraction]:
        ...


def make_extractor(backend: str, **kw) -> Extractor:
    if backend == "offline":
        from calleval.extract.offline import RuleExtractor
        return RuleExtractor()
    if backend == "jev":
        from calleval.extract.jev import JevExtractor
        return JevExtractor(**kw)
    raise ValueError(f"unknown backend {backend!r}")
