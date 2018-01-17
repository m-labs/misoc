import math

from migen import *

from misoc.interconnect import stream
from misoc.cores.liteeth_mini.common import eth_phy_layout


class LiteEthMACPaddingInserter(Module):
    def __init__(self, padding):
        self.sink = sink = stream.Endpoint(eth_phy_layout(8))
        self.source = source = stream.Endpoint(eth_phy_layout(8))

        # # #

        counter = Signal(16, reset=1)
        counter_done = Signal()
        counter_reset = Signal()
        counter_ce = Signal()
        self.sync += \
            If(counter_reset,
                counter.eq(0)
            ).Elif(counter_ce,
                counter.eq(counter + 1)
            )
        self.comb += counter_done.eq(counter >= padding-1)

        self.submodules.fsm = fsm = FSM(reset_state="IDLE")
        fsm.act("IDLE",
            sink.connect(source),
            If(source.stb & source.ack,
                counter_ce.eq(1),
                If(sink.eop,
                    If(~counter_done,
                        source.eop.eq(0),
                        NextState("PADDING")
                    ).Else(
                        counter_reset.eq(1)
                    )
                )
            )
        )
        fsm.act("PADDING",
            source.stb.eq(1),
            source.eop.eq(counter_done),
            source.data.eq(0),
            If(source.stb & source.ack,
                counter_ce.eq(1),
                If(counter_done,
                    counter_reset.eq(1),
                    NextState("IDLE")
                )
            )
        )


class LiteEthMACPaddingChecker(Module):
    def __init__(self, packet_min_length):
        self.sink = sink = stream.Endpoint(eth_phy_layout(8))
        self.source = source = stream.Endpoint(eth_phy_layout(8))

        # # #

        # TODO: see if we should drop the packet when
        # payload size < minimum ethernet payload size
        self.comb += sink.connect(source)

