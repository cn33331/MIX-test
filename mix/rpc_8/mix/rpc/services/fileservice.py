from mix.rpc.services.streamer import DataStream
from mix.tools.util.logfactory import LogMasterMixin
from mix.rpc.services.streamservice import StreamService

import os.path
import glob
import tarfile
import uuid
import subprocess
import select


class FileService(LogMasterMixin):
    rpc_public_api = ['allow_list', 'ls', 'cd', 'pwd']
    rpc_data_path_open = ['open_file', 'open_archive', 'tail']

    class FileServiceException(Exception):
        def __init__(self, desc=None):
            self._desc = desc

        def __str__(self):
            return self._desc

    class InvalidPath(FileServiceException):
        """
        Thrown in case invalid path is given (e.g. not part of allow_list)
        """

    class PathNotFound(FileServiceException):
        """
        File not found since operation required file to be present (e.g. open_file('r',...)
        """

    class InvalidMode(FileServiceException):
        """
        Unknown mode specified (e.g. only 'r' or 'w' are supported for open_file)
        """

    class InvalidArgument(FileServiceException):
        """
        Argument provided is not supported
        """

    class FileStreamer(DataStream):

        def __init__(self, file, delete_file=False):
            super().__init__('c')
            self._file = file
            self._delete_file = delete_file

        def read(self, size, timeout=None) -> bytes:
            if self._file.readable() is False:
                raise FileService.InvalidMode('read not supported')

            return self._file.read(size)

        def write(self, data: bytes):
            if self._file.writable() is False:
                raise FileService.InvalidMode('write not supported')

            self._file.write(bytes(data))

        def flush(self):
            self._file.flush()

        def drain(self):
            pass

        def close(self):
            self._file.close()
            if self._delete_file and os.path.exists(self._file.name):
                os.remove(os.path.relpath(self._file.name))

    class TailStreamer(StreamService):
        def __init__(self, file):
            super().__init__()
            self._file = file

            (self._pipe_r, self._pipe_w) = os.pipe()
            self._sp = subprocess.Popen('tail -F {}'.format(self._file.name),
                                        shell=True,
                                        stdout=self._pipe_w,
                                        stderr=self._pipe_w)

        def __del__(self):
            os.close(self._pipe_r)
            os.close(self._pipe_w)
            self._sp.terminate()
            self._file.close()

        def streaming_read(self, size, timeout):
            readable, _, _ = select.select([self._pipe_r], [], [], timeout)
            if readable:
                return os.read(self._pipe_r, size)
            return []

        def open_stream(self, *args, **kwargs):
            return super().open_stream('c', *args, **kwargs)


    def __init__(self, allow_list):
        super().__init__()
        self._allow_list = [self._normalize_path(e) for e in allow_list]
        # switch to working directory, first in the list
        if len(allow_list) == 0:
            raise FileService.InvalidArgument("No allow_list elements defined")
        self._cwd = None
        self.cd(allow_list[0])
        self._tailServices = dict()

    def _normalize_path(self, path):
        if len(path) == 0:
            return None
        # expand in case user path
        if path[0] == '~':
            path = os.path.expanduser(path)
        # always use full path
        return os.path.realpath(path)

    def _in_allow_list(self, path):
        return len([entry for entry in self._allow_list if path.startswith(entry)]) != 0

    def _run_command(self, cmd, args):
        return subprocess.run(' '.join([cmd, args if args else '']), capture_output=True, text=True, shell=True).stdout

    def open_file(self, mode, file_path) -> DataStream:
        """
        Open file in as DataStream object.
        :param mode: 'r' or 'w'
        :param file_path: relative or absolute path based on current working directory (cwd)
        :return: DataStream object
        """
        file_path = self._normalize_path(file_path)

        self.logger.debug('opening file stream for ' + mode + ' with path ' + str(file_path))

        if not self._in_allow_list(file_path):
            raise FileService.InvalidPath(file_path)

        if mode == 'r':
            if not os.path.exists(file_path):
                raise FileService.PathNotFound(file_path)

            f = open(file_path, 'rb')
            return FileService.FileStreamer(f)
        elif mode == 'w':
            # Figure out if path or actual filename
            f = open(file_path, 'wb')
            return FileService.FileStreamer(f)

        raise FileService.InvalidMode('Unknown mode: r or w are supported')

    def tail(self, file_path, read_timeout=100):
        """
        Open file in tail -F mode as DataStream object
        :param read_timeout: Wait for 'read_timeout' in ms for data to arrive
        :param file_path: Relative or absolute path based on cwd.
        :return: DataStream object
        """
        file_path = self._normalize_path(file_path)

        self.logger.debug('opening tail stream for with path ' + str(file_path))
        if not os.path.exists(file_path):
            raise FileService.PathNotFound(file_path)

        f = open(file_path, 'r')

        # clean-up
        for k in list(self._tailServices):
            if len(self._tailServices[k].streams) == 0:
                del self._tailServices[k]

        # tailServices map keeps track of already running tail client. It is conceivable that
        # same FILE has been opened for identical purpose.
        if file_path not in self._tailServices:
            self._tailServices[file_path] = FileService.TailStreamer(f)

        return self._tailServices[file_path].open_stream(read_timeout)

    def open_archive(self, file_path):
        """
        Create new archive based on glob based argument
        :param file_path: Files/Directories to include e.g. '*.log' based on cwd
        :return: DataStream object
        """
        file_path = self._normalize_path(file_path)
        self.logger.debug('opening archive stream for  with path ' + str(file_path))

        # create tmp tar file, write-only, gzip compression
        tmp_path = self._normalize_path(str(uuid.uuid4()))
        with tarfile.open(tmp_path, 'w:gz') as tf:
            # archive open, add all files found
            for file in glob.iglob(file_path, recursive=True):
                rel_path = os.path.relpath(file, self._cwd)
                tf.add(rel_path)

        f = open(tmp_path, 'rb')
        # Open streamer, but ensure tmp file is marked 'delete'
        return FileService.FileStreamer(f, True)

    def cd(self, path):
        """
        Change current working directory (cwd). Note, new path must be in allow_list
        :param path: Absolute or relative path based on cwd
        :return: New path
        """
        path = self._normalize_path(path)
        if path is None:
            raise FileService.PathNotFound(path)

        if self._in_allow_list(path):
            if not os.path.exists(path):
                raise FileService.PathNotFound(path)

            os.chdir(path)
            self._cwd = os.getcwd()
        else:
            raise FileService.InvalidPath(path)

        return self._cwd

    def ls(self, arg=None):
        """
        Pass-through ls command to shell.
        :param arg: All ls based options are supported e.g. '-l'
        :return: Output of ls command
        """
        return self._run_command('ls', arg)

    def allow_list(self):
        """
        Retrieve allow_list of accessible directories
        :return: List of directories
        """
        return self._allow_list

    def pwd(self):
        """
        Retrieve current working directory. At start-up cwd is first item in allow_list
        :return: Current working directory (cwd)
        """
        return self._cwd
