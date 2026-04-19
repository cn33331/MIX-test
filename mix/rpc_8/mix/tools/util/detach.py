
import os
import sys
import signal


def daemonize(stdin=None,
              stdout=None,
              stderr=None):
    """
    this function makes the process a daemon process. Based on recipe 12.14 of Python cookbook.
    https://learning.oreilly.com/library/view/
    python-cookbook-3rd/9781449357337/ch12.html#_launching_a_daemon_process_on_unix

    Example code for running a server in
    a daemon process with this function:

    try:
        daemonize(stdout='/tmp/daemon.log',
                  stderr='/tmp/daemon.log')
    except RuntimeError as e:
        print(e, file=sys.stderr)
        raise SystemExit(1)

    s = RPCAppServer.DefaultServer('tcp://127.0.0.1:12345', 'my_server')
    s.start()
    import time
    sys.stdout.write('Daemon started with pid {}\n'.format(os.getpid()))
    while s.serving:
        sys.stdout.write('Daemon Alive! {}\n'.format(time.ctime()))
        time.sleep(10)

    """

    # First fork (detaches from parent)
    try:
        if os.fork() > 0:
            raise SystemExit(0)
    except OSError:
        raise RuntimeError('fork #1 failed')

    os.chdir('/')
    os.umask(0)
    os.setsid()
    # Second fork (relinquish session leadership)
    try:
        if os.fork() > 0:
            raise SystemExit(0)
    except OSError:
        raise RuntimeError('fork #2 failed.')

    # Flush I/O buffers
    sys.stdout.flush()
    sys.stderr.flush()

    # Replace file descriptors for stdin, stdout, and stderr
    if stdin is not None:
        with open(stdin, 'rb', 0) as f:
            os.dup2(f.fileno(), sys.stdin.fileno())
    if stdout is not None:
        with open(stdout, 'ab', 0) as f:
            os.dup2(f.fileno(), sys.stdout.fileno())
    if stderr is not None:
        with open(stderr, 'ab', 0) as f:
            os.dup2(f.fileno(), sys.stderr.fileno())

    # Arrange to have the PID file removed on exit/signal
    # atexit.register(lambda: os.remove(pidfile))

    # Signal handler for termination (required)

    def sigterm_handler(signo, frame):
        raise SystemExit(1)

    signal.signal(signal.SIGTERM, sigterm_handler)


def detached_main():
    try:
        daemonize()
    except RuntimeError as e:
        print(e, file=sys.stderr)
        raise SystemExit(1)
    from mix.rpc.server.mserver import ManagementServer
    m_server = ManagementServer('tcp://127.0.0.1:50000', None)
    m_server.start()
    print('server started')
    import os
    return os.getpid()


if __name__ == '__main__':
    print('before calling detached')
    pid = detached_main()
    print("pid: {0}".format(pid))
