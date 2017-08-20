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

        rx_ctl = Signal()
        rx_data = Signal(8)

        q0 = Signal()
        self.specials += DDRInput(pads.rx_ctl, q0, rx_ctl, ClockSignal("eth_rx"))
        for i in range(4):
            self.specials += DDRInput(pads.rx_data[i], rx_data[4+i], rx_data[i],
                                      ClockSignal("eth_rx"))

        rx_ctl_d = Signal()
        self.sync.eth_rx += rx_ctl_d.eq(rx_ctl)
        eop = Signal()
        self.comb += eop.eq(~rx_ctl & rx_ctl_d)

        self.sync.eth_rx += [
            source.stb.eq(rx_ctl),
            source.data.eq(rx_data)
        ]
        self.comb += source.eop.eq(eop)


class LiteEthPHYRGMIICRG(Module, AutoCSR):
    def __init__(self, clock_pads, pads):
        self._reset = CSRStorage()

        # # #

        self.clock_domains.cd_eth_rx = ClockDomain()
        self.clock_domains.cd_eth_tx = ClockDomain()

        self.specials += [
            Instance("BUFG", i_I=clock_pads.rx, o_O=self.cd_eth_rx.clk),
            DDROutput(1, 0, clock_pads.tx, ClockSignal("eth_tx"))
        ]
        self.comb += self.cd_eth_tx.clk.eq(self.cd_eth_rx.clk)

        reset = self._reset.storage
        if hasattr(pads, "rst_n"):
            self.comb += pads.rst_n.eq(~reset)
        self.specials += [
            AsyncResetSynchronizer(self.cd_eth_tx, reset),
            AsyncResetSynchronizer(self.cd_eth_rx, reset),
        ]


class LiteEthPHYRGMII(Module, AutoCSR):
    def __init__(self, clock_pads, pads):
        self.dw = 8
        self.submodules.crg = LiteEthPHYRGMIICRG(clock_pads, pads)
        self.submodules.tx = LiteEthPHYRGMIITX(pads)
        self.submodules.rx = LiteEthPHYRGMIIRX(pads)
        self.sink, self.source = self.tx.sink, self.rx.source
