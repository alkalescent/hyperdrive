from hyperdrive.Algotrader import HyperDrive
from hyperdrive.Utils import SwissArmyKnife

knife = SwissArmyKnife()
drive = HyperDrive()
drive = knife.use_dev(drive)


class TestHyperDrive:
    def test_init(self):
        assert type(drive).__name__ == "HyperDrive"
