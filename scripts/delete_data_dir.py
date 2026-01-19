from hyperdrive.Storage import Store

store = Store()

bucket = store.get_bucket()


def chunks(lst, size):
    size = max(1, size)
    return [lst[i : i + size] for i in range(0, len(lst), size)]


keys = [obj.key for obj in bucket.objects.filter(Prefix="data\\")]
keys = chunks(keys, 500)
for key in keys:
    store.delete_objects(key)
