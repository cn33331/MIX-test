from mix.tools.util.attrcontainer import AttrContainerMixin


class PowerControlParams(AttrContainerMixin):
    '''
    parameters for the power control of an ICI instrument
    '''
    __slots__ = ['io', 'active_low', 'delay', 'timeout']

    def __init__(self, io=None, active_low=False, delay=0, timeout=0.1):
        self.io = io
        self.active_low = active_low
        self.delay = delay
        self.timeout = timeout


class PowerCallArgs(AttrContainerMixin):
    '''
    Arguments for power event calls of ICI instruments
    '''
    __slots__ = ['args', 'delay', 'timeout']

    def __init__(self, delay=0, timeout=0.1, args=[]):
        self.timeout = timeout
        self.delay = delay
        self.args = args


class TwoStepControl(AttrContainerMixin):
    '''
    two step power on control informatoni for ICI
    compatible service
    '''
    __slots__ = ['power_ctrl', 'pre_power_on_init_args',
                 'post_power_on_init_args', 'pre_power_down_args']

    def __init__(self):
        self.power_ctrl = PowerControlParams()
        self.pre_power_on_init_args = PowerCallArgs()
        self.post_power_on_init_args = PowerCallArgs()
        self.pre_power_down_args = PowerCallArgs()
