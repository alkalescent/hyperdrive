"""Tests for the Algotrader module."""

from hyperdrive.Algotrader import HyperDrive
from hyperdrive.Utils import SwissArmyKnife

knife = SwissArmyKnife()
drive = HyperDrive()
drive = knife.use_dev(drive)


class TestHyperDrive:
    """Tests for the HyperDrive main class."""

    def test_init(self) -> None:
        """Test HyperDrive initialization."""
        assert type(drive).__name__ == "HyperDrive"
