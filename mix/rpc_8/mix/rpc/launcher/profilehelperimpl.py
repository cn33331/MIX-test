from mix.driver.core.bus.busbase import I2CBus
from typing import List, Dict
import importlib
import ast

from .profilehelper import ProfileHelper, InstRef, ServiceObjects
from .profilehelper import GenericServiceConfig, ICIServiceConfig
from .instregistry import InstRegistry

from ..proxy.proxyfactory import ProxyFactory
from .coredriverproxy import I2CProxy, GPIOProxy, IOExpanderProxy, I2CMuxProxy
from .symboltable import Symbol, Scope, GlobalScope
from mix.tools.util.misc import is_valid_ip_addr, klass_from_class_name
from mix.tools.util.misc import is_running_on_zynq
from mix.tools.util.logfactory import create_null_logger
from mix.driver.core.bus.busbase import I2CMux
from mix.driver.core.ic.io_expander import IOExpander
from mix.driver.modulebase.mixmoduledriver import MIXModuleDriver
from mix.driver.core.bus.i2c import I2C
from mix.driver.core.bus.gpiobase import GPIO as GPIOBase
from mix.driver.core.bus.gpio import GPIO


class InstFactory(object):
    '''
    factory objects to make the instruments for a server
    '''
    '''
    There are many small methods in this class, not becaue the call
    tree is complicated, but because I am using method names in lieu of
    comments
    '''

    def __init__(self, scope, profile_helper):
        self.scope = scope
        self.objects = {}
        self.p_helper = profile_helper
        self.proxy_factories = {}
        self.logger = profile_helper.logger.getChild('factory')

    def make_inst(self, symbol):
        service_server_name = self.to_service_server_combined_name(self.scope.name, symbol.name)
        if val := self.objects.get(service_server_name):
            return val

        service = self.inst_from_cfg(symbol.definition)
        self.objects[service_server_name] = service
        return service

    def get_klass_no_init(self, symbol):
        val = None
        if isinstance(symbol.definition, GenericServiceConfig):
            val = self.klass_from_path(symbol.definition.class_name)
        elif isinstance(symbol.definition, ICIServiceConfig):
            for comp_str in symbol.definition.allowed_list:
                val = self.klass_from_ici(comp_str)
                if val: return val
        else:
            raise Exception("Invalid symbol definition")
        return val

    def inst_from_cfg(self, cfg):
        if isinstance(cfg, GenericServiceConfig):
            return self.make_generic_inst(cfg)
        else:
            return self.make_ici_inst(cfg)

    def make_generic_inst(self, cfg):
        assert isinstance(cfg, GenericServiceConfig)
        klass = self.klass_from_path(cfg.class_name)

        # Ensure if we are defining a driver by 'class' name, it is not loading an ICI 
        # driver with compatible support.
        compatible = getattr(klass, 'compatible', None)
        if compatible and len(compatible) > 0:
            raise ValueError(f"hwconfig defined {cfg.class_name} via 'class'",\
                                " but driver defines ICI 'compatible' listing.  "\
                                "Update the hwprofile to use 'allowed' listing instead.")

        kw_args = self.get_args(cfg.kw_args)
        return klass(**kw_args)

    def klass_from_path(self, class_str):
        parts = class_str.split('.', 1)
        if len(parts) == 1:
            return klass_from_class_name(parts[0])
        else:
            full_name = self.p_helper.look_up_full_name(parts[0])
            return klass_from_class_name(f'{full_name}.{parts[1]}')

    def klass_from_ici(self, comp_str):
        if result := self.p_helper.registry[comp_str]:
            module_path, class_name = result
            klass = getattr(importlib.import_module(
                module_path), class_name)
            assert issubclass(klass, MIXModuleDriver)
            return klass

    def make_ici_inst(self, cfg):
        assert isinstance(cfg, ICIServiceConfig)
        kw_args = self.get_args(cfg.kw_args)
        for comp_str in cfg.allowed_list:
            klass = self.klass_from_ici(comp_str)
            if klass:
                # try to instantiate, and match against, EEPROM data
                inst = klass(**kw_args)
                if self.match_comp_str(inst, cfg.allowed_list):
                    if self.check_inst_condition(inst):
                        return inst
        return None

    def check_inst_condition(self, inst):
        '''
        Checks the condition of the module, and throws an exception if condition  is not new (0) or repaired (1)
        '''
        try:
            c = inst.read_module_condition()
        except NotImplementedError as e:  # EEPROM maps v2 and v3 do not support condition, assume the module is OK
            self.logger.info(f'{str(e)}')
            return True
        if c in [0,1]:
            return True
        else:
            self.logger.error(f'Module condition of "{c}" is invalid. Contact module manufacturer or MIX support for guidance')
            return False

    def match_comp_str(self, service, allowed_list):
        d_comp_str = None
        try:
            d_comp_str = service.read_module_compatible()
        except Exception:
            self.logger.exception(f'error happpened when trying to read comp string '
                                  f'with driver {type(service)}')
        self.logger.info(f'comp string from device is {d_comp_str}; '
                         f'expect one of {service.compatible}; '
                         f'service class is {type(service)}')

        if d_comp_str in service.compatible:
            if d_comp_str in allowed_list:
                return True
        return False

    def parse_value(self, arg_value):
        '''parse arg_value from profile into live objects'''
        var = arg_value
        if isinstance(arg_value, GenericServiceConfig):
            var = self.make_generic_inst(arg_value)
        elif isinstance(arg_value, list):
            var = [self.parse_value(v) for v in arg_value]
        elif isinstance(arg_value, InstRef):
            var = self.resolve_var(arg_value)
        '''
        else:
            raise ValueError(f"{arg_value} is not one of GenericService, List or Variable")
        '''
        return var

    def get_args(self, kw_args):
        '''
        get the arguments for a ctor
        '''
        for name, val in kw_args.items():
            kw_args[name] = self.parse_value(val)
        return kw_args


    def to_service_server_combined_name(self, server_name, service_name):
        return server_name+'-'+service_name

    def log_resolve_var_failure(self, service_name : str, server_name):

        possible_matches = self.scope.find_servers_with_service(service_name)
        server_st = server_name if server_name else self.scope.name
        mix_conf_string = '@'+ server_name+'.'+service_name if server_name else '@'+ service_name
        msg_to_user = f'''No match found for service {service_name} in server {server_st}.
The instrument belonging to external server must be referenced using @server_name.service_name.'''
        if not possible_matches:
            msg_to_user+= ' No matches found for the service.\n'
        else:
            msg_to_user+= f' Try replacing {mix_conf_string} with one of the possible matche(s): '
            for idx, server_match in enumerate(possible_matches):
                msg_to_user+= '@'+server_match+'.'+service_name
                if(idx < len(possible_matches) -1):
                    msg_to_user+= ', '
                else:
                    msg_to_user+= '.\n'

        self.logger.info(msg_to_user)

    def resolve_var(self, inst_ref):
        assert isinstance(inst_ref, InstRef)

        full_inst_name = ''
        if not inst_ref.server:
            full_inst_name = self.to_service_server_combined_name(server_name = self.scope.name, service_name = inst_ref.inst_name)
        else:
            full_inst_name = self.to_service_server_combined_name(server_name = inst_ref.server, service_name = inst_ref.inst_name)

        var = self.objects.get(full_inst_name)
        if var is None:
            var_symbol = self.scope.resolve(inst_ref.inst_name, inst_ref.server)
            if var_symbol is None:
                self.log_resolve_var_failure(inst_ref.inst_name, inst_ref.server)
                raise ValueError(f"{inst_ref.inst_name} has not been defined")
            if var_symbol.scope.name == self.scope.name:
                var = self.make_inst(var_symbol)
            else:
                rpc_server_name = var_symbol.scope.name
                pf = self.proxy_factories.get(rpc_server_name)
                if pf is None:
                    server_cfg = self.p_helper.get_app_server_settings(
                        rpc_server_name)
                    pf = ProxyFactory.DefaultFactory(server_cfg.url, f'{self.scope.name}_proxy')
                    self.proxy_factories[rpc_server_name] = pf
                var = pf.get_proxy(inst_ref.inst_name)
                if isinstance(var_symbol.definition, GenericServiceConfig):
                    klass = self.klass_from_path(
                        var_symbol.definition.class_name)
                    if issubclass(klass, IOExpander):
                        var = IOExpanderProxy(var)
                    elif issubclass(klass, I2CMux):
                        var = I2CMuxProxy(var)
                    elif issubclass(klass, I2CBus):
                        var = I2CProxy(var)
                    elif issubclass(klass, GPIOBase):
                        var = GPIOProxy(var)

            # so we don't resolve the same instrument again
            self.objects[full_inst_name] = var

        if inst_ref.channel >= 0:
            return var[inst_ref.channel]
        else:
            return var


class DefaultProfileHelper(ProfileHelper):

    def __init__(self, profile, profile_loc):
        self.profile = profile
        self.version = profile.version
        self.registry = InstRegistry(profile.module_search_paths, profile_loc)
        self.app_server_list = [*profile.app_servers]
        self.logger = create_null_logger()
        self.make_sym_table()


    def get_xavier_ip(self):
        xavier_cfg = self.profile.manager.services['xavier']
        if pins_cfg := xavier_cfg.get('ip_pins'):
            ip_offset = 0

            pins = pins_cfg["pins"]
            if exp_class_name := pins_cfg.get('expander_class'):
                factory = InstFactory(None, self)
                expander_klass = factory.klass_from_path(exp_class_name)
                i2c_dev = pins_cfg['i2c_dev']
                dev_addr = pins_cfg['expander_i2c_addr']

            if is_running_on_zynq():
                if exp_class_name:
                    i2c_bus = I2C(i2c_dev)
                    expander = expander_klass(i2c_bus, dev_addr)
                    pin_values = [expander[pin].value for pin in pins]
                else:# if expander is not connected, there must be a direct GPIO connection 
                    pin_values = [ GPIO(pin).get_val() for pin in pins]
            else:
                # dummy value if not running on real xavier
                pin_values = [1, 1, 0]

            for i, b in enumerate(pin_values):
                ip_offset += b << i  # pins are LSB first

            first_three, last = xavier_cfg['base_ip'].rsplit('.', 1)
            ip = f"{first_three}.{ast.literal_eval('0x' + last) + ip_offset:x}"
            assert is_valid_ip_addr(ip)
            return ip
        else:  # if nothing in the hardware profile, we will go to the software side
            return xavier_cfg['default_ip']

    def get_file_system_settings(self):
        return self.profile.manager.services.get('file_system')

    def get_manager_settings(self):
        return self.profile.manager

    def get_app_server_list(self) -> List:
        return self.app_server_list

    def get_app_server_settings(self, server_name) -> Dict:
        config = self.profile.app_servers[server_name]
        return config

    def look_up_full_name(self, short_name):
        '''
        look up the full module path name. The mapping is deifned
        in sw_profile['namespaces']
        '''
        if len(self.profile.namespaces) > 0:
            if full_name := self.profile.namespaces.get(short_name):
                return full_name
        return short_name

    def make_sym_table(self):
        gs = GlobalScope()
        self.scopes = {}
        for server_name, server_cfg in self.profile.app_servers.items():
            s = Scope(server_name, parent=gs)
            for inst_name, inst_def in server_cfg.services.items():
                s.define(Symbol(inst_name, inst_def))
            gs.add_child(s)
            self.scopes[server_name] = s

    def get_services_for_server(self, server_name: str):
        services = {}
        scope = self.scopes[server_name]
        factory = InstFactory(scope, self)
        for name, symbol in scope.symbols.items():
            self.logger.info(f'making inst {name}')
            try:
                service = factory.make_inst(symbol)
                if not name.startswith('__'):
                    two_step = None
                    cfg = symbol.definition
                    if isinstance(cfg, ICIServiceConfig):
                        self.resolve_power_gpio(cfg, factory)
                        two_step = cfg.two_step
                    services[name] = ServiceObjects(service, two_step)
            except Exception as e:
                self.logger.exception(f'could  not make instrument {name} - {e}')
        return services, factory

    def resolve_power_gpio(self, ici_cfg, factory):
        power_cfg = ici_cfg.two_step.power_ctrl
        io_value = power_cfg.io
        power_gpio_pin = None
        if isinstance(io_value, InstRef):
            power_gpio_pin = factory.resolve_var(io_value)

        if isinstance(io_value, GenericServiceConfig):
            power_gpio_pin = factory.make_genric_inst(io_value)

        power_cfg.io = power_gpio_pin

    def dumps(self, name=''):
        if len(name) > 0:
            if name in self.profile.ap_server_list:
                return str(self.profile.app_servers[name])
            else:
                if attr := getattr(self, self.profile, name):
                    return str(attr)
                else:
                    return f"unkonwn attribute {name} in profile"
        else:
            return str(self.profile)
