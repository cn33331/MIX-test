from mix.driver.core.bus.busbase import I2CMux, I2CBus
from mix.driver.core.ic.io_expander import IOExpander
from mix.driver.core.bus.gpiobase import GPIO

class I2CProxy(I2CBus):
    def __init__(self, proxy):
        self.proxy = proxy

    def acquire(self):
        self.proxy.acquire()

    def release(self):
        self.proxy.release()

    def read(self, addr, data_len):
        return self.proxy.read(addr, data_len)

    def write(self, addr, data):
        self.proxy.write(addr, data)

    def write_and_read(self, addr, wr_data, rd_len):
        return self.proxy.write_and_read(addr, wr_data, rd_len)

    def close(self):
        self.proxy.close()


class GPIOProxy(GPIO):

    def __init__(self, proxy):
        self.proxy = proxy

    def acquire(self):
        self.proxy.acquire()

    def release(self):
        self.proxy.release()

    def get_val(self):
        return self.proxy.get_val()

    def set_val(self, level):
        self.proxy.set_val(level)

    def get_dir(self):
        return self.proxy.get_dir()

    def set_dir(self, pin_dir):
        self.proxy.set_dir(pin_dir)

    def get_inverted(self):
        return self.proxy.get_inverted()

    def set_inverted(self, new_inverted):
        self.proxy.set_inverted(new_inverted)


class IOExpanderProxy(IOExpander):

    class ExpanderGPIOProxy(GPIO):
        def __init__(self, pin_no, expander_proxy):
            self.expander = expander_proxy
            super().__init__(pin_no)

        def get_val(self):
            return self.expander.get_pin_val(self.pin_id)

        def set_val(self, new_val):
            self.expander.set_pin_val(self.pin_id, new_val)

        def get_inverted(self):
            return self.expander.is_pin_inverted(self.pin_id)

        def set_inverted(self):
            raise NotImplementedError()

        def get_dir(self):
            return self.expander.get_pin_dir(self.pin_id)

        def set_dir(self, new_dir):
            return self.expander.set_pin_dir(self.pin_id, new_dir)

    def __init__(self, proxy):
        self.resources = {}
        self.proxy = proxy

    def create_resource(self, item_id):
        return self.ExpanderGPIOProxy(item_id, self.proxy)

    def set_pin_val(self, pin, value):
        self.proxy.set_pin_val(pin, value)

    def get_pin_val(self, pin):
        return self.proxy.get_pin_val(pin)

    def get_pin_dir(self, pin):
        return self.proxy.get_pin_dir(pin)

    def set_pin_dir(self, pin, direction):
        self.proxy.set_pin_dir(pin, direction)

    def is_pin_inverted(self, pin):
        return self.proxy.is_pin_inverted(pin)

    # the following methods are used by IC driver 
    # implementation only, and not proxied, however since IOExpander
    # defines this as abstract, a impl. must be provided

    def read_input(self, port_no):
        pass

    def read_output(self, port_no):
        pass

    def write_output(self, port_no, val):
        pass

    def read_dir(self, port_no):
        pass
    
    def write_dir(self, port_no, val):
        pass

    def read_inverted(self, port_no):
        pass

    def write_inverted(self, port_no, val):
        pass

class I2CMuxProxy(I2CMux):

    class I2CBusProxy(I2CBus):
        def __init__(self, channel, mux_proxy):
            self.mux = mux_proxy
            self.channel = channel

        def acquire(self):
            self.mux.acquire_channel(self.channel)

        def release(self):
            self.mux.release_channel(self.channel)

        def read(self, addr, data_len):
            return self.mux.read_channel(self.channel, addr, data_len)

        def write(self, addr, data):
            self.mux.write_channel(self.channel, addr, data)

        def write_and_read(self, addr, wr_data, rd_len):
            return self.mux.write_and_read_channel(self.channel, addr, wr_data, rd_len)

        def close():
            pass

    def __init__(self, proxy):
        super().__init__()
        self.proxy = proxy

    def create_resource(self, item_id):
        return self.I2CBusProxy(item_id, self.proxy)

    def acquire_channel(self, channel):
        self.proxy.acquire_channel(channel)

    def release_channel(self, channel):
        return self.proxy.release_channel(channel)

    def read_channel(self, channel, addr, data_len):
        return self.proxy.read_channel(channel, addr, data_len)

    def write_channel(self, channel, addr, data):
        self.proxy.write_channel(channel, addr, data)

    def write_and_read_channel(self, channel, addr, wr_data, rd_len):
        return self.proxy.write_and_read_channel(channel, addr, wr_data, rd_len)
