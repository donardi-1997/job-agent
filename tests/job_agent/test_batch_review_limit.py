import pytest
from pydantic import ValidationError

from job_agent.computrabajo.batch import BatchApplyRequest


def test_batch_review_budget_defaults_to_100_and_allows_up_to_200() -> None:
	request = BatchApplyRequest()
	assert request.max_results == 100
	assert BatchApplyRequest(max_results=200).max_results == 200

	with pytest.raises(ValidationError):
		BatchApplyRequest(max_results=201)
