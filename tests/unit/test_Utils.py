"""Tests for the Utils module."""

import os

import pytest

from hyperdrive import Constants as C
from hyperdrive.Utils import SwissArmyKnife

knife = SwissArmyKnife()


class Example:
    """Example class for testing attribute manipulation."""

    def __init__(self) -> None:
        """Initialize example with default attributes."""
        self.var = "old"
        self.bucket_name = "random"


ex = Example()


class TestSwissArmyKnife:
    """Tests for the SwissArmyKnife utility class."""

    def test_replace_attr(self) -> None:
        """Test replacing and adding attributes on objects."""
        assert ex.var == "old"
        knife.replace_attr(ex, "var", "new")
        assert ex.var == "new"
        knife.replace_attr(ex, "absent", "present")
        with pytest.raises(AttributeError):
            _ = ex.absent

    def test_use_dev(self) -> None:
        """Test switching to dev bucket configuration."""
        assert ex.bucket_name == "random"
        if not C.CI:
            dev_ex = knife.use_dev(ex)
            assert dev_ex.bucket_name == os.environ["S3_DEV_BUCKET"]
