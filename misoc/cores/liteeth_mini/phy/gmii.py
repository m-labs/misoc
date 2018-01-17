from migen import *
from migen.genlib.io import DDROutput
from migen.genlib.resetsync import AsyncResetSynchronizer

from misoc.interconnect.csr import *
from misoc.interconnect import stream
from misoc.cores.liteeth_mini.common import *


class LiteEthPHYGMIITX(Module):
    def __init__(self, pads):
        self.sink = sink = stream.Endpoint(eth_phy_layout(8))

        # # #

        if hasattr(pads, "tx_er"):
            self.sync += pads.tx_er.eq(0)
        self.sync += [
            pads.tx_en.eq(sink.stb),
            pads.tx_data.eq(sink.data),
            sink.ack.eq(1)
        ]


class LiteEthPHYGMIIRX(Module):
    def __init__(self, pads):
        self.source = source = stream.Endpoint(eth_phy_layout(8))

        # # #

        rx_dv_d = Signal()
        self.sync += [
            rx_dv_d.eq(pads.rx_dv),
            source.stb.eq(pads.rx_dv),
            source.data.eq(pads.rx_data)
        ]
        self.comb += source.eop.eq(~pads.rx_dv & rx_dv_d)


class LiteEthPHYGMIICRG(Module, AutoCSR):
    def __init__(self, clock_pads, pads, mii_mode=0):
        self._reset = CSRStorage()

        # # #

        self.clock_domains.cd_eth_rx = ClockDomain()
        self.clock_domains.cd_eth_tx = ClockDomain()

        # RX : Let the synthesis tool insert the appropriate clock buffer
        self.comb += self.cd_eth_rx.clk.eq(clock_pads.rx)

        # TX : GMII: Drive clock_pads.gtx, clock_pads.tx unused
        #      MII: Use PHY clock_pads.tx as eth_tx_clk, do not drive clock_pads.gtx
        self.specials += DDROutput(1, mii_mode, clock_pads.gtx, ClockSignal("eth_tx"))
        # XXX Xilinx specific, replace BUFGMUX with a generic clock buffer?
        self.specials += Instance("BUFGMUX",
                                  i_I0=self.cd_eth_rx.clk,
                                  i_I1=clock_pads.tx,
                                  i_S=mii_mode,
                                  o_O=self.cd_eth_tx.clk)

        reset = self._reset.storage
        self.comb += pads.rst_n.eq(~reset)
        self.specials += [
            AsyncResetSynchronizer(self.cd_eth_tx, reset),
            AsyncResetSynchronizer(self.cd_eth_rx, reset),
        ]


class LiteEthPHYGMII(Module, AutoCSR):
    def __init__(self, clock_pads, pads):
        self.submodules.crg = LiteEthPHYGMIICRG(clock_pads, pads)
        self.submodules.tx = ClockDomainsRenamer("eth_tx")(LiteEthPHYGMIITX(pads))
        self.submodules.rx = ClockDomainsRenamer("eth_rx")(LiteEthPHYGMIIRX(pads))
        self.sink, self.source = self.tx.sink, self.rx.source
