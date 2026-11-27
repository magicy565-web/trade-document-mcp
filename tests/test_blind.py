import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "tools"))
from blind_evaluation import Case, evaluate


def test_blind_cohort_and_group_overlap():
    case = Case(
        case_id="example-1",
        company="fictional",
        template_family="A",
        source_group="G",
        region="US",
        source_type="synthetic",
        rights_record="synthetic-qa",
        split="blind",
        reviewers=["fixture-A", "fixture-B"],
        eligible=True,
        released=True,
        correct=True,
        first_pass=True,
        manual_clarification=False,
        format_rework=False,
        fields=10,
        field_errors=0,
        critical_fields=3,
        critical_errors=0,
    )
    report = evaluate([case])
    assert report["real"]["first_pass_rate"] is None
    assert report["synthetic"]["wilson_95"][0] < 1
    with pytest.raises(ValueError, match="shares"):
        evaluate([case, case.model_copy(update={"case_id": "train", "split": "train"})])
