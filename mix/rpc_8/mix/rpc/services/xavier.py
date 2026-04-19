from mix.tools.util.logfactory import create_null_logger
from mix.driver.modulebase.mixcomponent import MIXComponent
from hashlib import sha1


class XINFO_FIELD():

    def __init__(self, offset, length):
        self._offset = offset
        self._length = length

    @property
    def offset(self):
        return self._offset

    @property
    def length(self):
        return self._length


# See rdar://72450811
XINFO_TABLE = {
    1: {
        'format': XINFO_FIELD(0x00, 1),
        'checksum': XINFO_FIELD(0x01, 20),
        'sn': XINFO_FIELD(0x15, 16),
        'reserved': XINFO_FIELD(0x25, 1),
        'mac': XINFO_FIELD(0x26, 6),
        'ers': XINFO_FIELD(0x2c, 1),
        'config': XINFO_FIELD(0x2D, 3)
    },
    2: {
        'format': XINFO_FIELD(0x00, 1),
        'checksum': XINFO_FIELD(0x01, 20),
        'sn': XINFO_FIELD(0x15, 17),
        'mac': XINFO_FIELD(0x26, 6),
        'ers': XINFO_FIELD(0x2c, 1),
        'config': XINFO_FIELD(0x2D, 3)
    }
}


class Xavier(MIXComponent):
    '''
    xavier represents the xavier board, including both the zynq soc
    and the linux environment. However, it's important xaiver itself does
    not rely on the driver pakcage. It should get its zynq object from
    its client
    '''

    rpc_public_api = ["get_system_time",
                      "set_system_time",
                      "read_serial_number",
                      "read_protected_blob",
                      "get_mac_address"]

    def __init__(self, zynq, os_helper):
        self.logger = create_null_logger()
        self.zynq = zynq
        self.os_helper = os_helper
        self._xinfo = None

    def set_ip(self, ip_addr):
        self.os_helper.ip = ip_addr

    def get_ip(self):
        return self.os_helper.ip

    def set_system_time(self, timestamp):
        '''
        Set the system time based on given timestamp.

        Args:
            timestamp: float/int, should be seconds from 1970/1/1.

        Returns:
            Current system time after it has been updated.
        '''
        self.os_helper.time = timestamp
        return self.os_helper.time

    def get_system_time(self):
        '''
        Return the system time in seconds since the epoch as a floating point number.
        '''
        return self.os_helper.time

    def read_nvmem(self, addr, count):
        dev = "/dev/mtd3"   # See rdar://73229031
        with open(dev, 'rb') as mtd:
            mtd.seek(addr, 0)
            data = mtd.read(count)
        return bytearray(data)

    def verify_xinfo(self):
        if self._xinfo is None:
            raise RuntimeError("Xavier info was not initialized")

        if len(self._xinfo) != 256:
            raise SystemError("Xavier info block lenght is incorrect ({})". format(len(self._xinfo)))

        format = self._xinfo[0]
        if format not in XINFO_TABLE.keys():
            raise SystemError("Xavier info format unknown ({})".format(format))

        sha1_start_offset = XINFO_TABLE[format]['checksum'].offset
        sha1_end_offset = XINFO_TABLE[format]['checksum'].offset + XINFO_TABLE[format]['checksum'].length
        sha_current = self._xinfo[sha1_start_offset:sha1_end_offset]
        sha_current = ''.join('{:02x}'.format(x) for x in sha_current)

        table_length = 0
        for field in XINFO_TABLE[format].values():
            table_length += field.length

        # Copy table
        tmp = bytearray(self._xinfo[:table_length])

        # Zero sha area
        tmp[sha1_start_offset:sha1_end_offset] = bytearray(sha1_end_offset - sha1_start_offset)

        # Compute actual sha
        sha_actual = sha1(tmp).hexdigest()
        if sha_current != sha_actual:
            raise SystemError("Invalid checksum.  exp({}) cal({})".format(sha_current, sha_actual))

        return None

    def read_serial_number(self) -> str:
        '''
        Read and return the Xavier's serial number.
        '''

        self.read_protected_blob()

        format = self._xinfo[0]

        if format in XINFO_TABLE.keys():
            start_offset = XINFO_TABLE[format]['sn'].offset
            end_offset = XINFO_TABLE[format]['sn'].offset + XINFO_TABLE[format]['sn'].length
            return self._xinfo[start_offset:end_offset].decode()
        else:
            raise SystemError("Table version {} is not known".format(format))

    def read_protected_blob(self) -> list:
        '''
        Read and return the Xavier's protected blob.

        The protected blob's checksum is verified.  If invalid, an exception is raised.
        '''

        if self._xinfo is None:
            self._xinfo = self.read_nvmem(0, 256)

        self.verify_xinfo()

        return list(self._xinfo)

    def get_mac_address(self) -> str:
        '''
        Read and return the Xavier's ethernet mac address.
        '''
        return self.os_helper.mac_address
