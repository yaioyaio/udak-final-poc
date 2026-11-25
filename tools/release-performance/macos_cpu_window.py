"""Bounded aggregate CPU observation on the local macOS test host."""
import ctypes
from functools import lru_cache
import sys
from threading import Lock
import time


@lru_cache(maxsize=1)
def cpu_reader():
    if sys.platform != 'darwin':
        raise ValueError('MACOS_CPU_COUNTER_UNAVAILABLE')
    # <mach/host_info.h> HOST_CPU_LOAD_INFO, <mach/machine.h> CPU_STATE_IDLE.
    mach = ctypes.CDLL(None)
    mach.mach_host_self.argtypes = []
    mach.mach_host_self.restype = ctypes.c_uint32
    host = mach.mach_host_self()
    statistics = mach.host_statistics
    statistics.argtypes = (ctypes.c_uint32, ctypes.c_int, ctypes.POINTER(ctypes.c_uint32),
                           ctypes.POINTER(ctypes.c_uint32))
    statistics.restype = ctypes.c_int

    def read():
        ticks = (ctypes.c_uint32 * 4)()
        count = ctypes.c_uint32(len(ticks))
        if not host or statistics(host, 3, ticks, ctypes.byref(count)) != 0 or count.value != len(ticks):
            raise ValueError('MACOS_CPU_COUNTER_UNAVAILABLE')
        return tuple(ticks)

    return read


def sample(previous, current, interval_ns):
    delta = [b - a for a, b in zip(previous, current, strict=True)]
    if len(delta) != 4 or min(delta) < 0 or sum(delta) <= 0 or interval_ns <= 0:
        raise ValueError('INVALID_CPU_COUNTER')
    return {'interval_ns': interval_ns, 'total_ticks': sum(delta), 'idle_ticks': delta[2]}


def quiet(row, idle_permille, max_interval_ns):
    return (type(row['interval_ns']) is int and 0 < row['interval_ns'] <= max_interval_ns
            and type(row['idle_ticks']) is int and type(row['total_ticks']) is int
            and 0 <= row['idle_ticks'] <= row['total_ticks'] and row['total_ticks'] > 0
            and 1000 * row['idle_ticks'] >= idle_permille * row['total_ticks'])


class CpuWindow:
    """Coalesce samples from owned worker monitors into one host timeline."""

    def __init__(self, samples, idle_permille, reader, clock=time.monotonic_ns):
        self.samples = samples
        self.idle_permille = idle_permille
        self.reader = reader
        self.clock = clock
        self.lock = Lock()
        self.first_time = self.last_time = clock()
        self.last = reader()

    def observe(self):
        with self.lock:
            now = self.clock()
            interval = now - self.last_time
            if interval < 1_000_000_000:
                return
            current = self.reader()
            row = sample(self.last, current, interval)
            self.samples.append(row)
            self.last_time, self.last = now, current
            if not quiet(row, self.idle_permille, 3_000_000_000):
                raise ValueError('HOST_CPU_OVERLAP')

    def finish(self):
        self.observe()
        with self.lock:
            now = self.clock()
            return {'elapsed_ns': now - self.first_time, 'tail_ns': now - self.last_time}
