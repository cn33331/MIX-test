from .server import RPCServer
from ..transports.pingtransport import ZMQPingClientTransport
from ..util import constants
from .powercontroller import PowerController, POWER_CTRL_SERVICE


class RPCAppServer(RPCServer):
    '''
    an RPC server that's an application server, meaning:
    1. it has a power controller
    2. it sends out heart beat pings
    '''

    def __init__(self, protocol, transport, identity, config=None):
        super().__init__(protocol, transport, identity, config)

        # only app server needs a power controller
        self.pwr_ctrl = PowerController()
        self.pwr_ctrl.logger = self.logger.getChild('power_control')
        self.register(POWER_CTRL_SERVICE, self.pwr_ctrl)

    def setup_heart_beat(self):
        self.ping_transport = ZMQPingClientTransport()
        self.ping_transport.connect(constants.MAN_SERVER_PING_EP)

    def register(self, name, service, two_step=None):
        worker = super().register(name, service)
        if worker is not None:
            self.pwr_ctrl.register(name, worker, two_step)
        return worker

    def heart_beat_action(self):
        self.logger.info(f'.......{self._identity} sending ping........')
        self.ping_transport.ping(self._identity, self.transport.end_point, self.session_id)

    def clean_up(self):
        # this function is called after the server has asked the worker_man to stop all the
        # services. So the services already had a chance to call their reset function
        # the manager server doesn't have the power contorl service
        pwr_ctrl = self.get_service(POWER_CTRL_SERVICE)
        for wmworker in self.worker_man.workers.values():
            pwr_ctrl.power_off(wmworker.worker.id)

        self.ping_transport.shut_down()
