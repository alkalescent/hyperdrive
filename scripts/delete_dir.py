"""Delete specific symbol directories from S3 storage."""

from typing import Any

from hyperdrive.Storage import Store

store = Store()

bucket = store.get_bucket()

symbols = ["IAC", "OTIS", "VTRS"]


def chunks(lst: list[Any], size: int) -> list[list[Any]]:
    """Split a list into chunks of specified size.

    Args:
        lst: List to split.
        size: Maximum size of each chunk.

    Returns:
        List of sublists, each with at most 'size' elements.
    """
    size = max(1, size)
    return [lst[i: i + size] for i in range(0, len(lst), size)]


for symbol in symbols:
    keys = [
        obj.key
        for obj in bucket.objects.filter(Prefix=f"data/intraday/polygon/{symbol}/")
    ]
    keys = chunks(keys, 500)
    for key in keys:
        store.delete_objects(key)
