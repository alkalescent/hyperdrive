"""Multiprocessing example demonstrating shared counter with locks."""

from multiprocessing import Process, Value

counter = Value("i", 0)
num = 1000


def fx1() -> None:
    """Increment shared counter with lock protection."""
    for _ in range(num):
        with counter.get_lock():
            counter.value += 1


def fx2() -> None:
    """Increment shared counter with lock protection."""
    for _ in range(num):
        with counter.get_lock():
            counter.value += 1


if __name__ == "__main__":
    p1 = Process(target=fx1)
    p2 = Process(target=fx2)
    p1.start()
    p2.start()
    p1.join()
    p2.join()

assert counter.value == num * 2
