from migen import *
from migen.genlib.resetsync import AsyncResetSynchronizer

from misoc.interconnect.csr import *
from misoc.interconnect import stream
from misoc.cores.liteeth_mini.common import *


def converter_description(dw):
    return [("data", dw)]


class LiteEthPHYMIITX(Module):
    def __init__(self, pads):
        self.sink = sink = stream.Endpoint(eth_phy_description(8))

        # # #

        if hasattr(pads, "tx_er"):
            self.sync += pads.tx_er.eq(0)
        converter = stream.Converter(converter_description(8),
                              converter_description(4))
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
        self.source = source = stream.Endpoint(eth_phy_description(8))

        # # #

        converter = stream.Converter(converter_description(4),
                              converter_description(8))
        converter = ResetInserter()(converter)
        self.submodules += converter

        self.sync += [
            converter.reset.eq(~pads.dv),
            converter.sink.stb.eq(1),
            converter.sink.data.eq(pads.rx_data)
        ]
        self.comb += [
            converter.sink.eop.eq(~pads.dv)
        ]
        self.comb += converter.source.connect(source)


class LiteEthPHYMIICRG(Module, AutoCSR):
    def __init__(self, clock_pads, pads):
        self._reset = CSRStorage()

        # # #

        if hasattr(clock_pads, "phy"):
            self.sync.base50 += clock_pads.phy.eq(~clock_pads.phy)

        self.clock_domains.cd_eth_rx = ClockDomain()
        self.clock_domains.cd_eth_tx = ClockDomain()
        self.comb += self.cd_eth_rx.clk.eq(clock_pads.rx)
        self.comb += self.cd_eth_tx.clk.eq(clock_pads.tx)

        reset = self._reset.storage
        self.comb += pads.rst_n.eq(~reset)
        self.specials += [
            AsyncResetSynchronizer(self.cd_eth_tx, reset),
            AsyncResetSynchronizer(self.cd_eth_rx, reset),
        ]


class LiteEthPHYMII(Module, AutoCSR):
    def __init__(self, clock_pads, pads):
        self.dw = 8
        self.submodules.crg = LiteEthPHYMIICRG(clock_pads, pads)
        self.submodules.tx =  ClockDomainsRenamer("eth_tx")(LiteEthPHYMIITX(pads))
        self.submodules.rx = ClockDomainsRenamer("eth_tx")(LiteEthPHYMIIRX(pads))
        self.sink, self.source = self.tx.sink, self.rx.source
