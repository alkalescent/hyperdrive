from hyperdrive.Storage import Store

store = Store()

bucket = store.get_bucket()

symbols = ["IAC", "OTIS", "VTRS"]


def chunks(lst, size):
    size = max(1, size)
    return [lst[i : i + size] for i in range(0, len(lst), size)]


for symbol in symbols:
    keys = [
        obj.key
        for obj in bucket.objects.filter(Prefix=f"data/intraday/polygon/{symbol}\\")
    ]
    keys = chunks(keys, 500)
    for key in keys:
        store.delete_objects(key)
