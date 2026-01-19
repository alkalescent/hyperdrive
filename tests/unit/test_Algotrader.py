import sys
sys.path.append('hyperdrive')
from Algotrader import HyperDrive  # noqa autopep8
from Utils import SwissArmyKnife  # noqa autopep8

knife = SwissArmyKnife()
drive = HyperDrive()
drive = knife.use_dev(drive)


class TestHyperDrive:
    def test_init(self):
        assert type(drive).__name__ == 'HyperDrive'
