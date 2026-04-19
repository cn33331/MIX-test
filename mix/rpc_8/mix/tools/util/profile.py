"""utility functions for profiling the code performance"""
import time
import cProfile
import pstats


def to_ms(time_in_second, count):
    """
    Returns the amount of time in ms for a single period of count.

    Args:
        time_in_second: total amount of time in seconds
        count = number of iterations completed within time_in_seconds
    """
    return (time_in_second / count) * 1000


def time_func(func, *args, count=1000):
    """
    Returns elapsed time of function.

    Takes the start time and end time for both process time and clock time.
    Then it returns both times as elapsed time.

    Args:
        func: This is the function being iterated through.
        *args: These are the arguments the function takes to iterate through.
        count: This is how many times the function is iterated through.
    """
    c = count
    start = time.perf_counter()
    startp = time.process_time()
    label = func.__name__
    while c > 0:
        func(*args)
        c -= 1
    endp = time.process_time()
    end = time.perf_counter()
    elapsed_time = to_ms(endp - startp, count)
    print('{0}:\n\tprocess time: {1} milliSecond\n\tclock time:{2} milliSecond'.format(
        label, elapsed_time, to_ms(end - start, count)))
    return elapsed_time


def print_mbps(byte_count, tms):
    mbps = int(byte_count/tms * 1000) / 1e6
    print('\t{0:.2f} mega bytes per second'.format(mbps))


def profile_func(func, *args, output_path):
    with cProfile.Profile() as pr:
        func(*args)

    stats = pstats.Stats(pr)
    stats.sort_stats(pstats.SortKey.TIME)
    stats.dump_stats(filename=output_path)
