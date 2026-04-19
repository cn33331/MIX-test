from .MCONSWProfileVisitor import MCONSWProfileVisitor
from .MCONSWProfileLexer import MCONSWProfileLexer
from .MCONSWProfileParser import MCONSWProfileParser
from .MCONHWProfileVisitor import MCONHWProfileVisitor
from .MCONHWProfileLexer import MCONHWProfileLexer
from .MCONHWProfileParser import MCONHWProfileParser
from ..profilehelper import ServerProfile, Profile, ICIServiceConfig, GenericServiceConfig
from ..profilehelper import InstRef
from ..profileerrors import ProfileValueError, AntlrProfileParseError
from ..instregistry import InstRegistry
from ...server.icipowercontrol import TwoStepControl
from mix.tools.util.misc import is_valid_ip_addr

from antlr4 import FileStream, CommonTokenStream
from antlr4.error.ErrorListener import ErrorListener
from collections import OrderedDict
import pathlib
import ast  # ast.literal_eval is a safer alternative than eval to convert
# a string literal to a string


class VerboseListener(ErrorListener):

    def __init__(self):
        self.errors = []

    def syntaxError(self, recognizer, offendingSymbol, line, column, msg, e):
        stack = recognizer.getRuleInvocationStack()
        stack.reverse()
        err_str = f"line {line}:{column} {msg} \n      rule stack: {stack}"
        self.errors.append(err_str)


class SWPVisitor(MCONSWProfileVisitor):

    def __init__(self, profile, file_name):
        super().__init__()
        self.profile = profile
        self.file_name = file_name
        # use default in case profile doesn't specify
        self._set_module_search_paths(['mix/driver/'])

    def _set_module_search_paths(self, paths):
        # module search path has to be relative to MIXROOT
        def _convert_to_relative(path_str):
            if path_str[0] == '/': return pathlib.Path(path_str[1:])
            return pathlib.Path(path_str)

        self.profile.module_search_paths = [
            str(InstRegistry.get_mix_root() / _convert_to_relative(p)) for p in paths ] 

    def visitVersion(self, ctx: MCONSWProfileParser.VersionContext):
        self.profile.version = int(ctx.NUMBER().getText())

    def visitModule_search_paths(self, ctx: MCONSWProfileParser.Module_search_pathsContext):
        self._set_module_search_paths([ast.literal_eval(
            d.getText()) for d in ctx.array().children[1:-1:2]])

    def visitNamespaces(self, ctx: MCONSWProfileParser.NamespacesContext):
        for pair in ctx.pair():
            short_name = ast.literal_eval(pair.STRING().getText())
            path_name = ast.literal_eval(pair.value().getText())
            self.profile.namespaces[short_name] = path_name

    def visitUrl(self, ctx: MCONSWProfileParser.UrlContext):
        url_value = ast.literal_eval(ctx.STRING().getText())
        return url_value

    def visitConfig(self, ctx: MCONSWProfileParser.ConfigContext):
        ret = {}
        for pair in ctx.pair():
            name = ast.literal_eval(pair.STRING().getText())
            value = ast.literal_eval(pair.value().getText())
            ret[name] = value
        return ret

    def visitMan_server(self, ctx: MCONSWProfileParser.Man_serverContext):
        self.profile.manager.url = self.visitUrl(ctx.url())
        if config_ctx := ctx.config():
            self.profile.manager.config = self.visitConfig(config_ctx)
        services = OrderedDict()
        if xavier_ctx := ctx.xavier():
            services['xavier'] = self.visitXavier(xavier_ctx)
        if fs_ctx := ctx.file_system():
            services['file_system'] = self.visitFile_system(fs_ctx)
        self.profile.manager.services = services

    def visitApp_server(self, ctx: MCONSWProfileParser.App_serverContext):
        server_name = ast.literal_eval(ctx.STRING().getText())
        server_url = self.visitUrl(ctx.url())
        if config_ctx := ctx.config():
            server_config = self.visitConfig(config_ctx)
        else:
            server_config = {}
        self.profile.app_servers[server_name] = ServerProfile(server_url,
                                                              server_config)

    def get_and_check_ip(self, node):
        text = ast.literal_eval(node.getText())
        # if ip string is valid save ret['default_ip']
        if not is_valid_ip_addr(text):
            #check that file exists, if it does then read ip from it, if the read ip is not valid, then raise exception
            with open(text) as ip_file:
                ip_st = ip_file.readline()
                if is_valid_ip_addr(ip_st):
                    return ip_st
                raise ProfileValueError(f"in {self.file_name}, file {text} exists, but does not hold valid ip address", node)
        else:
            return text

    def visitXavier(self, ctx: MCONSWProfileParser.XavierContext):
        ret = {}
        # import pdb; pdb.set_trace()
        if ctx.default_ip() is None:
            ret['default_ip'] = '169.254.254.1'
        else:
            ret['default_ip'] = self.get_and_check_ip(
                ctx.default_ip().STRING())
        if ctx.base_ip():
            ret['base_ip'] = self.get_and_check_ip(ctx.base_ip().STRING())

        return ret

    def visitFile_system(self, ctx: MCONSWProfileParser.File_systemContext):
        ret = {}
        if allow_list_ctx := ctx.allow_list():
            allow_list_array = allow_list_ctx.array()
            ret['allow_list'] = [ast.literal_eval(
                d.getText()) for d in allow_list_array.children[1:-1:2]]
        return ret


class HWPVisitor(MCONHWProfileVisitor):

    def __init__(self, profile, file_name):
        super().__init__()
        self.profile = profile
        self.file_name = file_name

    def visitVersion(self, ctx: MCONHWProfileParser.VersionContext):
        token = ctx.NUMBER()
        version = int(token.getText())
        if version != self.profile.version:
            raise ValueError(f'version in hardware profile {version} does not match '
                             f'the version in software profile {self.profile.version}')

    # Visit a parse tree produced by MCONHWProfileParser#ip_pins.
    def visitIp_pins(self, ctx: MCONHWProfileParser.Ip_pinsContext):
        xavier = self.profile.manager.services['xavier']
        if 'base_ip' not in xavier:
            raise ProfileValueError("IP pins are configured in the hardware profile, "
                                    "but base_ip is not configured in the software profile")
        array_ctx = ctx.pins().array()
        ip_pins = {}
        if e_ctx := ctx.expander():
            ip_pins['expander_class'] = ast.literal_eval(e_ctx.STRING().getText())
            ip_pins['expander_i2c_addr'] = ast.literal_eval(
                e_ctx.NUMBER().getText())

            i2c_dev_ctx = ctx.ip_i2c_dev()
            ip_pins['i2c_dev'] = ast.literal_eval(i2c_dev_ctx.STRING().getText())

        ip_pins['pins'] = [ast.literal_eval(
            d.getText()) for d in array_ctx.children[1:-1:2]]
        ip_pins['pins'] = ast.literal_eval(ctx.pins().array().getText())
        xavier['ip_pins'] = ip_pins

    def visitApp_server_services(self, ctx: MCONHWProfileParser.App_server_servicesContext):
        name = ast.literal_eval(ctx.STRING().getText())
        if name not in self.profile.app_servers:
            raise ProfileValueError(f"in {self.file_name}: {name} is not a server defined in sw profile",
                                    ctx.STRING())
        self.current_app_server = name
        return self.visitChildren(ctx)

    # Visit a parse tree produced by MCONHWProfileParser#service.
    def visitService(self, ctx: MCONHWProfileParser.ServiceContext):
        app_server = self.profile.app_servers[self.current_app_server]
        name = ast.literal_eval(ctx.STRING().getText())
        if p_ctx := ctx.plain_obj():
            app_server.services[name] = self.visitPlain_obj(p_ctx)
        else:
            app_server.services[name] = self.visitIci_obj(ctx.ici_obj())

    # Visit a parse tree produced by MCONHWProfileParser#plain_obj.
    def visitPlain_obj(self, ctx: MCONHWProfileParser.Plain_objContext):
        class_name = ast.literal_eval(ctx.ctor().STRING().getText())
        args = {}
        args_count = ctx.getChildCount() - 2  # remove ctor and comma
        for i in range(args_count):
            if kw_ctx := ctx.kw_arg(i):
                name, value = self.visitKw_arg(kw_ctx)
                args[name] = value
        return GenericServiceConfig(class_name, args)

    def visitIci_obj(self, ctx: MCONHWProfileParser.Ici_objContext):
        as_ctx = ctx.allow_string().array()
        allowed_list = [ast.literal_eval(d.getText())
                        for d in as_ctx.children[1:-1:2]]

        # we get the default value if two_step is not configured
        two_step_ctrl = TwoStepControl()
        two_step_ctx = ctx.two_step()
        if len(two_step_ctx) > 1:
            service_name = ctx.parentCtx.STRING().getText()
            raise ProfileValueError(f'{service_name} has more than one two_step config block')
        if len(two_step_ctx) > 0:
            two_step_ctrl = self.visitTwo_step(two_step_ctx[0])

        args = {}
        args_count = ctx.getChildCount() - 4  # remove ctor and comma
        for i in range(args_count):
            if kw_ctx := ctx.kw_arg(i):
                name, value = self.visitKw_arg(kw_ctx)
                args[name] = value

        return ICIServiceConfig(allowed_list, two_step_ctrl, args)

    def visitTwo_step(self, ctx: MCONHWProfileParser.Two_stepContext):
        two_step_ctrl = TwoStepControl()
        ctx.ctrl = two_step_ctrl

        if ctx_pwr_ctrl := ctx.power_ctl():
            self.current_params = {}
            pwr_ctrl_args_cnt = ctx_pwr_ctrl.getChildCount() - 4
            for i in range(pwr_ctrl_args_cnt):
                if pctx := ctx_pwr_ctrl.power_ctrl_args(i):
                    pctx.accept(self)

            for name, value in self.current_params.items():
                setattr(two_step_ctrl.power_ctrl, name, value)

        self.current_params = {}
        life_cycle_calls_cnt = ctx.getChildCount() - 6
        for i in range(life_cycle_calls_cnt):
            if lcctx := ctx.ici_life_cycle_call(i):
                lcctx.accept(self)
        self.current_params = None
        return two_step_ctrl

    # Visit a parse tree produced by MCONHWProfileParser#pc_io.
    def visitPc_io(self, ctx: MCONHWProfileParser.Pc_ioContext):
        if ctx_str := ctx.STRING():
            io_var = ast.literal_eval(ctx_str.getText())
            io_var = self.replace_var(io_var)
            self.current_params['io'] = io_var
        else:
            self.current_params['io'] = self.visitPlain_obj(ctx.plain_obj())

    # Visit a parse tree produced by MCONHWProfileParser#pc_active_low.
    def visitPc_active_low(self, ctx: MCONHWProfileParser.Pc_active_lowContext):
        self.current_params['active_low'] = ast.literal_eval(ctx.getChild(2).getText())

    # Visit a parse tree produced by MCONHWProfileParser#pc_delay.
    def visitPc_delay(self, ctx: MCONHWProfileParser.Pc_delayContext):
        self.current_params['delay'] = ast.literal_eval(ctx.NUMBER().getText())

    # Visit a parse tree produced by MCONHWProfileParser#pc_timeout.
    def visitPc_timeout(self, ctx: MCONHWProfileParser.Pc_timeoutContext):
        self.current_params['timeout'] = ast.literal_eval(
            ctx.NUMBER().getText())

    # Visit a parse tree produced by MCONHWProfileParser#ici_life_cycle_call.
    def visitIci_life_cycle_call(self, ctx: MCONHWProfileParser.Ici_life_cycle_callContext):
        name = ast.literal_eval(ctx.ici_call_name().getChild(0).getText())
        self.current_params = {}

        call_args = getattr(ctx.parentCtx.ctrl, name)
        call_args_cnt = ctx.getChildCount() - 4
        for i in range(call_args_cnt):
            if ctx_call_arg := ctx.ici_call_arg(i):
                ctx_call_arg.accept(self)

        for name, value in self.current_params.items():
            setattr(call_args, name, value)

    def visitPc_args(self, ctx: MCONHWProfileParser.Pc_argsContext):
        self.current_params['args'] = ast.literal_eval(ctx.array().getText())

    def visitKw_arg(self, ctx: MCONHWProfileParser.Kw_argContext):
        arg_name = eval(ctx.STRING(0).getText())
        if ctx.STRING(1):
            arg_value = ast.literal_eval(ctx.STRING(1).getText())
            arg_value = self.replace_var(arg_value)
        elif ctx.NUMBER():
            arg_value = ast.literal_eval(ctx.NUMBER().getText())
        elif ctx.array():  # array only support legal python code or variable reference
            arg_value = ast.literal_eval(ctx.array().getText())
            for val in arg_value:
                if isinstance(val, str):
                    val = self.replace_var(val)
        elif ctx.boolean():
            txt = ctx.boolean().getText()
            arg_value = ast.literal_eval(txt)
        else:
            arg_value = self.visitPlain_obj(ctx.plain_obj())
        return arg_name, arg_value

    def replace_var(self, arg_str):
        if arg_str[0] == '@':
            return InstRef(arg_str[1:])
        else:
            return arg_str


class ProfileLoader(object):
    '''
    The object responsible for parsing the profile files and filling in the
    profile data structure with valid information. Note that in the constructor,
    the file paths are pathlib.Path objects, not str
    '''

    def __init__(self, swp_file: pathlib.Path, hwp_file: pathlib.Path):
        error_listener = VerboseListener()
        sw_input = FileStream(swp_file.as_posix())
        sw_lexer = MCONSWProfileLexer(sw_input)
        token_stream = CommonTokenStream(sw_lexer)
        sw_parser = MCONSWProfileParser(token_stream)
        sw_parser.addErrorListener(error_listener)
        sw_tree = sw_parser.sw_profile()
        if len(error_listener.errors) > 0:
            raise AntlrProfileParseError(error_listener)

        hw_input = FileStream(hwp_file.as_posix())
        hw_lexer = MCONHWProfileLexer(hw_input)
        token_stream = CommonTokenStream(hw_lexer)
        hw_parser = MCONHWProfileParser(token_stream)
        hw_parser.addErrorListener(error_listener)
        hw_tree = hw_parser.hw_profile()
        if len(error_listener.errors) > 0:
            raise AntlrProfileParseError(error_listener)

        self.profile = Profile()
        sw_visitor = SWPVisitor(self.profile, swp_file.name)
        hw_visitor = HWPVisitor(self.profile, hwp_file.name)
        sw_visitor.visit(sw_tree)
        hw_visitor.visit(hw_tree)
