import os
import subprocess
import re
import shutil
import time
import hashlib
from pathlib import Path

from mix.tools.util.logfactory import LogMasterMixin


class LogCollectionService(LogMasterMixin):
    '''
    LogCollectionService provide standard ways to gather logs and status from the system and
    create archive for it.

    However, this service does not perform file transfer.  FileService provides that function.
    '''

    rpc_public_api = ['create_mix_log_archive', 'create_debug_log_archive', 'remove_archive']

    def __init__(self, logger=None):
        super().__init__()
        self.identity = "log_collector"
        if logger is None:
            self.setup_logger(self.identity)
        else:
            self.logger = logger

        self.logger.info("created")

        # A registry of what this collected.  Only allow filessytem cleanup
        # on our colleced logs.
        self.collections = []

    def __del__(self):
        self.logger.info("destroy")
        self.stop_logger()

    def create_mix_log_archive(self):
        '''
        Collect logs using the 'mix' profile, which is only contains logs from the MIX subsystem.

        This profile is typically good for test station logging.

        MIX subsystem logs typically includes (but subject to change):
            /var/tmp/mix/*log
            /mix/version.json
            /mix/addon/config/*

        Returns:
            str: the filepath (locally on Xavier) of the archived created.
        '''
        return self.create_log_archive('mix')

    def create_debug_log_archive(self):
        '''
        Collect logs using the 'debug' profile, which is comprehensive and system wide.

        This profile is typically used when debugging issues along with MIX team.

        Returns:
            str: the filepath (locally on Xavier) of the archived created.
        '''
        return self.create_log_archive('debug')

    def create_log_archive(self, profile="mix", rotate_log=False):
        """
        Collect and create an archive for the server side's log.
        :param profile,             The type of collection to perform.
                                    Must be either 'mix' or 'debug'.
        :param rotate_log(bool),    Attempt to rotate log file with .log extensions
        TODO:  FIX ME   FIX ME   FIX ME

        :return: Absolute path to created archive.
        """

        print("Server side logcollectionservice.collect start")

        # Perform collection
        t1 = time.time()
        cmd = " ".join([os.path.join(os.path.dirname(os.path.abspath(__file__)), "logcollect.sh"), profile])
        result = subprocess.run(cmd, capture_output=True, text=True, shell=True)
        t2 = time.time()
        print("log archive process took {}s".format(t2 - t1))
        self.logger.info("log archive process too {}s".format(t2 - t1))

        self.logger.info(result.stdout)
        self.logger.error(result.stderr)
        if (result.returncode != 0):
            msg = "Log collection failed:" + result.stdout + "\n" + result.stdout
            self.logger.error(msg)
            raise SystemError(msg)

        # Archive available: /tmp/logcollect/logcollect_xxxx.tgz
        self.archive_filepath = re.search("Archive available: (.*)\n", result.stdout).group(1)

        # Calculate SHA256
        sha = hashlib.sha256()
        with open(self.archive_filepath, "rb") as f:
            for chunk in iter(lambda: f.read(1024 * 8), b""):
                sha.update(chunk)
        sha256 = sha.hexdigest()
        self.logger.info("log archive is {} (sha256={})".format(self.archive_filepath, sha256))

        result = {}
        # result['md5'] = md5
        result['sha256'] = sha256
        result['name'] = self.archive_filepath

        self.collections.append(result['name'])

        # Management space usage in '/tmp/logcollect'.
        self.manage_space(result['name'])

        return result

    def remove_archive(self, archive):
        """
        Remove archives that we've collected previously.

        This method will only delete archive that LogCollectionService knows about.  
        I.e. You can't leverage this to delete arbitrary files from the system.
        
        Args:
            archive: str, absolute path to archive file.
        """
        # Only remove items that we collected ourself.
        if archive in self.collections:
            self.logger.info("deleting " + archive)
            os.remove(archive)
            shutil.rmtree(archive[:-4])
        else:
            self.logger.error(
                "Cannot remove item '{}', not a collected archive".format(archive))
            raise SystemError("Cannot delete file that wasn't collected.")

    def manage_space(self, active_archive):
        """
        Limit '/tmp/logcollect' to x number of archives and size
        """
        MAX_ARCHIVES = 10
        MAX_SIZE = 1024 * 1024 * 100    # 100MB

        log_archive_dir = '/tmp/logcollect'
        items = sorted(Path(log_archive_dir).iterdir(), key=os.path.getmtime)

        # manage item count
        junks = items[:-MAX_ARCHIVES]
        for item in junks:
            if active_archive in str(item):
                continue
            self._remove_item(str(item))

        # manage size
        while self._dir_size(log_archive_dir) > MAX_SIZE:
            items = sorted(Path(log_archive_dir).iterdir(), key=os.path.getmtime)
            oldest = items[0]
            if str(oldest) in active_archive:
                break
            self._remove_item(str(oldest))

    def _dir_size(self, dir):
        return sum(f.stat().st_size for f in Path(dir).glob('**/*') if f.is_file())

    def _remove_item(self, path):
        self.logger.info("removing item: {}".format(path))
        if os.path.isdir(path):
            shutil.rmtree(path)
        else:
            os.remove(path)
