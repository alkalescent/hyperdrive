import os
import sys
import pytest
sys.path.append('hyperdrive')
from Utils import SwissArmyKnife  # noqa autopep8
import Constants as C  # noqa autopep8


knife = SwissArmyKnife()


class Example:
    def __init__(self):
        self.var = 'old'
        self.bucket_name = 'random'


ex = Example()


class TestSwissArmyKnife:
    def test_replace_attr(self):
        assert ex.var == 'old'
        knife.replace_attr(ex, 'var', 'new')
        assert ex.var == 'new'
        knife.replace_attr(ex, 'absent', 'present')
        with pytest.raises(AttributeError):
            getattr(ex, 'absent')

    def test_use_dev(self):
        assert ex.bucket_name == 'random'
        if not C.CI:
            dev_ex = knife.use_dev(ex)
            assert dev_ex.bucket_name == os.environ['S3_DEV_BUCKET']
