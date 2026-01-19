import sys
import pytest
from datetime import datetime
sys.path.append('hyperdrive')
from Workflow import Flow  # noqa autopep8

flow = Flow()
now = datetime.utcnow()


class TestWorkFlow:
    def test_get_workflow_start_time(self):
        assert flow.get_workflow_start_time('dividends') == datetime(
            now.year, now.month, 1, 12)
        with pytest.raises(AttributeError):
            assert flow.get_workflow_start_time('build')

    def test_is_workflow_running(self):
        assert not flow.is_workflow_running('unrate')
