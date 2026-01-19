import os

from . import Constants as C


class SwissArmyKnife:
    def replace_attr(self, obj, find_key, replace_val):
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

    def use_dev(self, obj):
        # or simply make DevStore class that has s3 dev bucket name
        dev_obj = obj
        if not C.CI:
            dev_bucket = os.environ["S3_DEV_BUCKET"]
            dev_obj = self.replace_attr(obj, "bucket_name", dev_bucket)
        return dev_obj
