from migen import *

from misoc.interconnect.csr import *


class Identifier(Module, AutoCSR):
    def __init__(self, ident):
        contents = list(ident.encode())
        l = len(contents)
        if l > 255:
            raise ValueError("Identifier string must be 255 characters or less")
        contents.insert(0, l)

        self.address = CSRStorage(8)
        self.data = CSRStatus(8)

        mem = Memory(8, len(contents), init=contents)
        port = mem.get_port()
        self.specials += mem, port
        self.comb += [
            port.adr.eq(self.address.storage),
            self.data.status.eq(port.dat_r)
        ]
