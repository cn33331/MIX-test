from ..util import constants

from .icipowercontrol import TwoStepControl
from .worker import PowerState
from mix.tools.util.logfactory import create_null_logger
from mix.driver.core.bus.gpiobase import DPinLevel
from mix.driver.core.bus.gpiobase import PinDir

from collections import namedtuple
import time

POWER_CTRL_SERVICE = constants.POWER_CTRL_NAME

WorkerPowerControl = namedtuple(
    'WorkerPowerControl', ['worker', 'two_step'])


class PowerController(object):
    '''
    this is the service that controls the power states of all services registered
    on a RPCAppServer
    '''

    rpc_public_api = ['power_on', 'power_off']

    def __init__(self):
        self.workers = {}
        self.logger = create_null_logger()

    def register(self, service_name, worker, two_step):
        _two_step = None
        if self.is_ici_compatible(worker.service):
            _two_step = two_step or TwoStepControl()
        self.workers[service_name] = WorkerPowerControl(worker, _two_step)
        self.init_power_state(worker, _two_step)

    def is_ici_compatible(self, service):
        # ideally I should test for isinstance(MIXModuleDriver)
        # but I didn't want to bring in the explicit dependency
        if hasattr(service, "pre_power_on_init") and \
           hasattr(service, "post_power_on_init") and \
           hasattr(service, "pre_power_down"):
            return True
        else:
            return False

    def init_power_state(self, worker, two_step):
        worker.power_state = PowerState.StandBy
        service = worker.service
        if two_step:
            if two_step.power_ctrl.io is None:
                # system does not support power control even though
                # the instrument is 2 step compatible
                pargs = two_step.pre_power_on_init_args
                service.pre_power_on_init(pargs.timeout, *pargs.args)
                time.sleep(pargs.delay)
                pargs = two_step.post_power_on_init_args
                service.post_power_on_init(pargs.timeout, *pargs.args)
                time.sleep(pargs.delay)
                worker.power_state = PowerState.Ready
        else:
            worker.power_state = PowerState.Ready

    def _handle_no_change(self, two_step):
        if two_step:
            if two_step.power_ctrl.io:
                return constants.ICI_POWER_OK
            else:
                return constants.ICI_NO_POWER_CONTROL
        else:
            return constants.ICI_NOT_COMPATIBLE

    def power_on(self, service_name):
        if service_name not in self.workers:
            raise KeyError(f"Service not found {service_name}")

        worker = self.workers[service_name].worker
        two_step = self.workers[service_name].two_step
        ret = constants.ICI_NOT_COMPATIBLE

        if worker.power_state == PowerState.Ready:
            return self._handle_no_change(two_step)

        if two_step:
            self.logger.info(f'powering on {service_name}')
            timeout = two_step.pre_power_on_init_args.timeout
            pargs = two_step.pre_power_on_init_args.args
            delay = two_step.pre_power_on_init_args.delay
            worker.service.pre_power_on_init(timeout, *pargs)
            time.sleep(delay)
            ret = constants.ICI_NO_POWER_CONTROL

            if pin := two_step.power_ctrl.io:
                if two_step.power_ctrl.active_low:
                    pin.value = DPinLevel.Low
                else:
                    pin.value = DPinLevel.High
                pin.dir = PinDir.OUTPUT
                time.sleep(two_step.power_ctrl.delay)
                ret = constants.ICI_POWER_OK

            timeout = two_step.post_power_on_init_args.timeout
            pargs = two_step.post_power_on_init_args.args
            delay = two_step.post_power_on_init_args.delay
            worker.service.post_power_on_init(timeout, *pargs)
            time.sleep(delay)
            # if this is nto an ICI compatible service, the power state
            # is always ready and never needs to be changed.
            worker.power_state = PowerState.Ready

        return ret

    def power_off(self, service_name):
        if service_name not in self.workers:
            raise KeyError(f"Service not found {service_name}")

        worker = self.workers[service_name].worker
        two_step = self.workers[service_name].two_step

        if worker.power_state == PowerState.StandBy:
            return self._handle_no_change(two_step)

        ret = constants.ICI_NOT_COMPATIBLE
        if two_step:
            self.logger.info(f'powering off {service_name}')
            timeout = two_step.pre_power_down_args.timeout
            pargs = two_step.pre_power_down_args.args
            delay = two_step.pre_power_down_args.delay
            worker.service.pre_power_down(timeout, *pargs)
            time.sleep(delay)
            ret = constants.ICI_NO_POWER_CONTROL

            if pin := two_step.power_ctrl.io:
                if two_step.power_ctrl.active_low:
                    pin.value = DPinLevel.High
                else:
                    pin.value = DPinLevel.Low
                time.sleep(two_step.power_ctrl.delay)
                ret = constants.ICI_POWER_OK

            worker.power_state = PowerState.StandBy
        return ret
