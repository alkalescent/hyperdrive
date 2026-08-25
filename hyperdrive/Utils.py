"""Utility classes for object manipulation and dev environment configuration."""

import os
from typing import Any, TypeVar

from . import Constants as C

T = TypeVar("T")


class SwissArmyKnife:
    """Multi-purpose utility class for object manipulation.

    Provides methods for recursively replacing object attributes
    and configuring objects for development environments.
    """

    def replace_attr(self, obj: T, find_key: str, replace_val: Any) -> T:
        """Recursively replace an attribute value in an object.

        Searches for the specified attribute on the object and its nested
        attributes, replacing all occurrences with the new value.

        Args:
            obj: The object to modify.
            find_key: The attribute name to search for.
            replace_val: The new value to set.

        Returns:
            The modified object with replaced attribute values.
        """
        try:
            getattr(obj, find_key)
            setattr(obj, find_key, replace_val)
            return obj
        except AttributeError:
            attrs = [
                attr
                for attr in dir(obj)
                if not (attr.startswith("__") and attr.endswith("__"))
            ]
            for key in attrs:
                try:
                    setattr(
                        obj,
                        key,
                        self.replace_attr(getattr(obj, key), find_key, replace_val),
                    )
                except AttributeError:
                    # This happens for read-only attributes
                    # like capitalize attr for a str obj
                    pass
            return obj

    def use_dev(self, obj: T) -> T:
        """Configure an object to use the development S3 bucket.

        Replaces the bucket_name attribute with the dev bucket when not in CI.

        Args:
            obj: The object to configure for development.

        Returns:
            The object configured with dev bucket name (or unchanged in CI).
        """
        # or simply make DevStore class that has s3 dev bucket name
        dev_obj = obj
        if not C.CI:
            dev_bucket = os.environ["S3_DEV_BUCKET"]
            dev_obj = self.replace_attr(obj, "bucket_name", dev_bucket)
        return dev_obj
