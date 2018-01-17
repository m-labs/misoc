from migen import *
from migen.genlib.resetsync import AsyncResetSynchronizer

from misoc.interconnect.csr import *
from misoc.interconnect import stream
from misoc.cores.liteeth_mini.common import *


class LiteEthPHYMIITX(Module):
    def __init__(self, pads):
        self.sink = sink = stream.Endpoint(eth_phy_layout(8))

        # # #

        if hasattr(pads, "tx_er"):
            self.sync += pads.tx_er.eq(0)
        converter = stream.Converter(8, 4)
        self.submodules += converter
        self.comb += [
            converter.sink.stb.eq(sink.stb),
            converter.sink.data.eq(sink.data),
            sink.ack.eq(converter.sink.ack),
            converter.source.ack.eq(1)
        ]
        self.sync += [
            pads.tx_en.eq(converter.source.stb),
            pads.tx_data.eq(converter.source.data)
        ]


class LiteEthPHYMIIRX(Module):
    def __init__(self, pads):
        self.source = source = stream.Endpoint(eth_phy_layout(8))

        # # #

        converter = stream.Converter(4, 8)
        converter = ResetInserter()(converter)
        self.submodules += converter

        self.sync += [
            converter.reset.eq(~pads.rx_dv),
            converter.sink.stb.eq(1),
            converter.sink.data.eq(pads.rx_data)
        ]
        self.comb += [
            converter.sink.eop.eq(~pads.rx_dv)
        ]
        self.comb += converter.source.connect(source)


class LiteEthPHYMIICRG(Module, AutoCSR):
    def __init__(self, clock_pads, pads):
        self._reset = CSRStorage()

        # # #

        self.clock_domains.cd_eth_rx = ClockDomain()
        self.clock_domains.cd_eth_tx = ClockDomain()
        self.specials += [
            Instance("BUFG", i_I=clock_pads.rx, o_O=self.cd_eth_rx.clk),
            Instance("BUFG", i_I=clock_pads.tx, o_O=self.cd_eth_tx.clk)
        ]

        reset = self._reset.storage
        if hasattr(pads, "rst_n"):
            self.comb += pads.rst_n.eq(~reset)
        self.specials += [
            AsyncResetSynchronizer(self.cd_eth_tx, reset),
            AsyncResetSynchronizer(self.cd_eth_rx, reset),
        ]


class LiteEthPHYMII(Module, AutoCSR):
    def __init__(self, clock_pads, pads):
        self.submodules.crg = LiteEthPHYMIICRG(clock_pads, pads)
        self.submodules.tx =  ClockDomainsRenamer("eth_tx")(LiteEthPHYMIITX(pads))
        self.submodules.rx = ClockDomainsRenamer("eth_tx")(LiteEthPHYMIIRX(pads))
        self.sink, self.source = self.tx.sink, self.rx.source
