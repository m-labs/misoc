from migen import *
from migen.genlib.resetsync import AsyncResetSynchronizer
from migen.genlib.io import DDROutput, DDRInput

from misoc.interconnect.csr import *
from misoc.interconnect import stream
from misoc.cores.liteeth_mini.common import *


class LiteEthPHYRGMIITX(Module):
    def __init__(self, pads):
        self.sink = sink = stream.Endpoint(eth_phy_layout(8))

        # # #

        self.specials += DDROutput(sink.stb, sink.stb, pads.tx_ctl, ClockSignal("eth_tx"))
        for i in range(4):
            self.specials += DDROutput(sink.data[i], sink.data[4+i], pads.tx_data[i],
                                       ClockSignal("eth_tx"))
        self.comb += sink.ack.eq(1)


class LiteEthPHYRGMIIRX(Module):
    def __init__(self, pads):
        self.source = source = stream.Endpoint(eth_phy_layout(8))

        # # #

        rx_ctl_u = Signal()
        rx_data_u = Signal(8)
        q0 = Signal()
        self.specials += DDRInput(pads.rx_ctl, rx_ctl_u, q0, ClockSignal("eth_rx"))
        for i in range(4):
            self.specials += DDRInput(pads.rx_data[i], rx_data_u[i], rx_data_u[4+i],
                                      ClockSignal("eth_rx"))
        # register to ease rx_ctl timing, e.g. on Sayma
        rx_ctl = Signal()
        rx_data = Signal(8)
        self.sync.eth_rx += [
            rx_ctl.eq(rx_ctl_u),
            rx_data.eq(rx_data_u)
        ]

        rx_ctl_d = Signal()
        self.sync.eth_rx += [
            rx_ctl_d.eq(rx_ctl),
            source.stb.eq(rx_ctl),
            source.data.eq(rx_data)
        ]
        self.comb += source.eop.eq(~rx_ctl & rx_ctl_d)


class LiteEthPHYRGMII(Module, AutoCSR):
    def __init__(self, pads):
        self.submodules.tx = LiteEthPHYRGMIITX(pads)
        self.submodules.rx = LiteEthPHYRGMIIRX(pads)
        self.sink, self.source = self.tx.sink, self.rx.source
