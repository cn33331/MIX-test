from collections import namedtuple
import sys
import os
import textwrap
import shutil

from .consoleerror import ConsoleCmdError


class MiniArgParser(object):
    '''
    A simple argument parser for the management console prompt
    '''

    Argument = namedtuple(
        'Argument', 'name, arg_type, optional, default, help_msg')

    class ReturnedArgs(object):
        pass

    def __init__(self, name, msg=''):
        self.r_args = []  # require arguments
        self.o_args = []  # optional arguments
        self.cmd_name = name
        self.msg = msg

    def print_args_help(self, args):
        for arg in args:
            sys.stdout.write('   ')
            sys.stdout.write('{0:<12}'.format(arg.name))
            sys.stdout.write('{0:<10}'.format(
                str(arg.default.__class__.__name__)))
            sys.stdout.write(os.linesep)
            wrapper = textwrap.TextWrapper()
            indent_str = ' ' * 18
            wrapper.initial_indent = indent_str
            wrapper.subsequent_indent = indent_str
            wrapper.width = shutil.get_terminal_size().columns
            output = wrapper.wrap(arg.help_msg)
            for line in output:
                sys.stdout.write(line + os.linesep)

    def print_help(self, online_help=False):
        sys.stdout.write(os.linesep)
        if online_help:
            '''
            this is called because someone issued the help command, not becasuea an error was thrown
            '''
            if len(self.msg.strip()) > 0:
                sys.stdout.write(self.msg)
                sys.stdout.write(os.linesep)
                sys.stdout.write(os.linesep)

        sys.stdout.write('usage: {0} '.format(self.cmd_name))
        for arg in self.r_args:
            sys.stdout.write(
                '\u001b[4m{0}\u001b[0m '.format(arg.name))  # underline
        for arg in self.o_args:
            sys.stdout.write('[{0}] '.format(arg.name))

        sys.stdout.write(os.linesep)
        sys.stdout.write(os.linesep)
        if len(self.r_args) > 0:
            sys.stdout.write('required arguments: ' + os.linesep)
            self.print_args_help(self.r_args)

        if len(self.o_args) > 0:
            sys.stdout.write('optional arguments: ' + os.linesep)
            self.print_args_help(self.o_args)

    def add_argument(self, name, optional=False, arg_type=str, default='', help_msg=''):
        assert isinstance(default, arg_type)
        if optional:
            self.o_args.append(self.Argument(name=name,
                                             optional=optional,
                                             arg_type=arg_type,
                                             default=default,
                                             help_msg=help_msg)
                               )
        else:
            self.r_args.append(self.Argument(name=name,
                                             optional=optional,
                                             arg_type=arg_type,
                                             default=default,
                                             help_msg=help_msg)
                               )

    def parse(self, args):
        if isinstance(args, str):
            if len(args.strip()) == 0:
                args = []
            else:
                args = args.split(' ')

        self.args = self.r_args + self.o_args
        count = len(self.args)
        acount = len(args)
        r = self.ReturnedArgs()

        try:
            if acount > count:
                raise ValueError(
                    'too many arguments {0}'.format(' '.join(args)))

            for i in range(count):
                name = self.args[i].name
                if i < acount:
                    try:
                        arg_type = self.args[i].arg_type
                        val = arg_type(args[i])
                        setattr(r, name, val)
                    except Exception as e:
                        raise TypeError(
                            "error converting {0} to type {1}".format(args[i], arg_type)) from e
                else:
                    if not self.args[i].optional:
                        raise ValueError(
                            'argument {0} is not optional'.format(name))
                    setattr(r, name, self.args[i].default)
        except Exception as exc:
            sys.stdout.write(os.linesep)
            sys.stdout.write('!!!ERROR!!!: {0}'.format(str(exc)))
            sys.stdout.write(os.linesep)
            self.print_help()
            raise ConsoleCmdError() from exc
        else:
            return r
