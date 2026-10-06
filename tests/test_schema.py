import dataclasses

import pytest

from calleval.extract.offline import RuleExtractor
from calleval.pipeline import load_calls
from calleval.quality import check
from calleval.schema import SchemaError, Span, validate_call, validate_intent


@pytest.fixture(scope="module")
def sample():
    tr = next(t for t in load_calls() if check(t).passed)
    return tr, RuleExtractor().extract(tr)


def test_valid_extraction_passes(sample):
    tr, ex = sample
    validate_call(ex, tr)


@pytest.mark.parametrize("field,value", [("resolved", "maybe"), ("repeats", -1), ("transfers", 1.5),
                                         ("callback", "yes"), ("confidence", 1.7), ("intent", "weather")])
def test_bad_field_rejected(sample, field, value):
    tr, ex = sample
    bad = dataclasses.replace(ex.intents[0], **{field: value})
    with pytest.raises(SchemaError):
        validate_intent(bad, tr)


def test_count_without_evidence_rejected(sample):
    tr, ex = sample
    bad = dataclasses.replace(ex.intents[0], transfers=2, transfer_spans=[])
    with pytest.raises(SchemaError):
        validate_intent(bad, tr)


def test_resolution_needs_evidence(sample):
    tr, ex = sample
    with pytest.raises(SchemaError):
        validate_intent(dataclasses.replace(ex.intents[0], resolved_spans=[]), tr)


def test_span_must_quote_real_text(sample):
    tr, ex = sample
    fake = Span(turn=0, start=0, end=5, text="hello")
    with pytest.raises(SchemaError):
        validate_intent(dataclasses.replace(ex.intents[0], resolved_spans=[fake]), tr)


def test_duplicate_intent_rejected(sample):
    tr, ex = sample
    with pytest.raises(SchemaError):
        validate_call(dataclasses.replace(ex, intents=ex.intents + ex.intents[:1]), tr)
