"""
This is a client side log collection utility.
"""
from mix.rpc.proxy.proxyfactory import ProxyFactory
from mix.rpc.util import constants
from mix.tools.util.logfactory import LogMasterMixin
import os
import tempfile
import shutil
import subprocess
import threading
import tarfile
import hashlib
import time
from datetime import datetime
import argparse

print_log_time = True


class LogCollector(LogMasterMixin):

    def __init__(self, proxyfactory, logger=None):
        """
        If its set to none it creates a logger but if
        it is passed a logger it assumes it is a logger instance.


        Args:
            proxyfactory: Client proxy factory.
            logger: Starts the logger.
        """
        super().__init__()
        self.identity = "client_log_collector"
        if logger is None:
            self.setup_logger(self.identity)
        else:
            self.logger = logger
        self.pf = proxyfactory
        self.collector = self.pf.get_proxy(constants.LOG_COLLECTOR_NAME)
        self.fs = self.pf.get_proxy('file_system')

    def __del__(self):
        """
        Stops the logger and deletes it.
        """
        self.stop_logger()

    def collect_mix_log(self, destination):
        """
        Returns location of the mix log archive.
        """
        return self._collect_client_and_xavier(self.collector.create_mix_log_archive, destination)

    def collect_debug_log(self, destination):
        """
        Returns location of the debug log archive.
        """
        return self._collect_client_and_xavier(self.collector.create_debug_log_archive, destination)

    def _collect_client_and_xavier(self, xavier_collection_api, destination):
        with tempfile.TemporaryDirectory() as tmpdir:
            xavier_archive_path = os.path.join(tmpdir, "xavier")
            client_archive_path = os.path.join(tmpdir, "client")

            th_xavier = threading.Thread(target=self._collect_xavier, args=[xavier_collection_api, xavier_archive_path])
            th_xavier.start()

            th_client = threading.Thread(target=self._collect_client, args=[client_archive_path])
            th_client.start()

            th_xavier.join()
            th_client.join()

            output_as_archive = False

            output = os.path.join(destination, "mix_log_"+datetime.now().strftime("%Y%m%d_%H%M%S"))
            if output_as_archive:
                output += ".tgz"
                # Create a combined xavier and client archive, and place it in 'destination'
                t1 = time.time()
                with tarfile.open(output, "w:gz") as t:
                    t.add(tmpdir, arcname=os.path.basename(output[:-4]))
                t2 = time.time()
                if print_log_time:
                    print("tar final took {}s".format(t2 - t1))
            else:
                shutil.move(tmpdir, output)

            return output

    def _collect_client(self, destination):
        t1 = time.time()

        oslog_file = os.path.join(destination, "mix.log")
        client_var_tmp_mix = os.path.join(destination, "var/tmp/mix")

        # Collect oslog
        os.makedirs(os.path.dirname(oslog_file), exist_ok=True)
        ta1 = time.time()
        cmd = "log show --predicate 'subsystem contains \"com.apple.hwte.mix\"' --info --debug > " + oslog_file
        subprocess.run(cmd, capture_output=True, text=True, shell=True)
        ta2 = time.time()
        if print_log_time:
            print("client log:  'log show' took {}s".format(ta2 - ta1))

        # Collect local /var/tmp/mix log
        tb1 = time.time()
        shutil.copytree('/var/tmp/mix', client_var_tmp_mix)
        tb2 = time.time()
        if print_log_time:
            print("client log:  log copy took {}s".format(tb2 - tb1))

        t2 = time.time()
        if print_log_time:
            print("client log: total {}s".format(t2 - t1))

    def _collect_xavier(self, collection_api, destination):
        """
        Request Xavier to collect a set of logs.  The log set to collect is
        based on the predefined 'profile'.
        """
        t1 = time.time()

        os.makedirs(destination, exist_ok=True)

        self.logger.info("Collecting...")
        # Ask Server to perform collection return the resulted filepath and md5
        # If something's wrong, an exception is raised.
        ta1 = time.time()
        xavier_log_archive = collection_api()
        ta2 = time.time()
        if print_log_time:
            print("xavier log:  gather {}s".format(ta2 - ta1))
        self.logger.info("Collection finished.")

        # print("self.collector.collect result:", xavier_log_archive)

        destination_archive = os.path.join(destination, os.path.basename(xavier_log_archive['name']))
        self.logger.info("Retriving archive as {}...".format(destination_archive))
        dlen = 0
        tb1 = time.time()
        with self.fs.open_file('r', xavier_log_archive['name']) as archive_ds:
            with open(destination_archive, 'wb') as archive_local:
                while True:
                    data = archive_ds.read(1024 * 1024)
                    if len(data) == 0:
                        break
                    archive_local.write(bytes(data))
                    dlen += len(data)
        tb2 = time.time()
        if print_log_time:  print("xavier log:  download {}s".format(tb2 - tb1))
        self.logger.info("Retrival finished.  {} bytes took {}s".format(dlen, tb2-tb1))

        # Calculate SHA256
        self.logger.info("Verifying...")
        self.logger.info("  original sha256: {}".format(xavier_log_archive['sha256']))
        sha = hashlib.sha256()
        with open(destination_archive, "rb") as f:
            for chunk in iter(lambda: f.read(1024*8), b""):
                sha.update(chunk)
        sha256 = sha.hexdigest()
        self.logger.info("  received archive sha256: {}".format(sha256))
        if sha256 == xavier_log_archive['sha256']:
            self.logger.info("  sha256 matched.")
        else:
            self.logger.error("  sha256 mismatched!")
            raise SystemError("Archive collection errored")

        # Cleanup Xavier
        self.collector.remove_archive(xavier_log_archive['name'])

        # Unarchive
        tc1 = time.time()
        with tarfile.open(destination_archive) as t:
            t.extractall(destination)
        os.remove(destination_archive)
        tc2 = time.time()
        if print_log_time:
            print("xavier log:  unarchive took {}s".format(tc2 - tc1))

        t2 = time.time()
        if print_log_time:
            print("xavier log: total {}s".format(t2 - t1))
        return destination

    def collect_file(self, file_path, destination):
        """
        Request collection to a specific file.  The file must be in the
        'allow_list' area.
        """

        # This is basically a whitelisted scp.

        if not os.path.isdir(destination):
            raise OSError(2, "Directory doesn't exist or it's not a directory", destination)

        destination_file = os.path.join(destination, os.path.basename(file_path))
        self.logger.info("Retriving file {}...".format(os.path.basename(file_path)))
        with self.fs.open_file('r', file_path) as ds:
            with open(destination_file, 'wb') as local_fh:
                while True:
                    data = ds.read(1024 * 1024)
                    if len(data) == 0:
                        break
                    local_fh.write(bytes(data))
        self.logger.info("Retrival finished.")

        return destination_file


if __name__ == '__main__':
    usage = '''
            To collect a log archive based on collection profile:
                %(prog)s -s <server_ip>:<management_port> -p <profile> -i <site_identity>

                EX: %(prog)s -s 169.254.1.32:50000 -p app -i dut0
                EX: %(prog)s -s 169.254.1.32:50000 -p debug

            To collect a single file:
                %(prog)s -s <server_ip>:<management_port> -f <filepath>

                EX: %(prog)s -s 169.254.1.32:50000 -f '~/somefile.txt'
            '''
    parser = argparse.ArgumentParser(usage=usage)
    parser.add_argument('-s', '--server',
                        help='Lynx Managemenet Server endpoint.  Ex: "169.254.1.32:50000"',
                        default='169.254.1.32:50000')

    parser.add_argument('-p', '--profile',
                        help='Log collection profile.  "mix" or "debug"',
                        nargs='?',
                        default='mix')

    parser.add_argument('-f', '--file',
                        help='Retrieve a single file located in the given file path',
                        nargs='?',
                        default='')

    args = parser.parse_args()
    server = args.server
    profile = args.profile
    file_to_collect = args.file

    proxyfactory = ProxyFactory.DefaultFactory("tcp://"+server, "mserver")
    lc = LogCollector(proxyfactory)

    if file_to_collect is not None and len(file_to_collect) > 0:
        result = lc.collect_file(file_to_collect, ".")
    elif profile == 'mix':
        result = lc.collect_mix_log(".")
    elif profile == 'debug':
        result = lc.collect_debug_log(".")
    else:
        print("Error - invalid argument.  See -h for help.")
        exit(-1)

    print("Log collected as:", result)
