from migen import *

from misoc.interconnect.csr import *
from misoc.cores.liteeth_mini.common import *
from misoc.cores.liteeth_mini.mac.core import LiteEthMACCore
from misoc.cores.liteeth_mini.mac.wishbone import LiteEthMACWishboneInterface


class LiteEthMAC(Module, AutoCSR):
    def __init__(self, phy, dw,
                 interface="wishbone",
                 endianness="big",
                 with_preamble_crc=True,
                 nrxslots=2,
                 ntxslots=2):
        self.submodules.core = LiteEthMACCore(phy, dw, endianness, with_preamble_crc)
        self.csrs = []
        if interface == "wishbone":
            self.rx_slots = CSRConstant(nrxslots)
            self.tx_slots = CSRConstant(ntxslots)
            self.slot_size = CSRConstant(2**bits_for(eth_mtu))

            self.submodules.interface = LiteEthMACWishboneInterface(dw, nrxslots, ntxslots)
            self.comb += [
                self.interface.source.connect(self.core.sink),
                self.core.source.connect(self.interface.sink)
            ]
            self.ev, self.bus = self.interface.sram.ev, self.interface.bus
            self.csrs = self.interface.get_csrs() + self.core.get_csrs()
        else:
            raise NotImplementedError

    def get_csrs(self):
        return self.csrs
