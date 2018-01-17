from migen import *
from migen.genlib.fsm import *
from migen.genlib.misc import chooser
from migen.genlib.record import Record

from misoc.interconnect import stream
from misoc.cores.liteeth_mini.common import eth_phy_layout, eth_preamble


class LiteEthMACPreambleInserter(Module):
    """Preamble inserter

    Inserts preamble at the beginning of each packet.

    Attributes
    ----------
    sink : in
        Packet octets.
    source : out
        Preamble, SFD, and packet octets.
    """
    def __init__(self):
        self.sink = sink = stream.Endpoint(eth_phy_layout(8))
        self.source = source = stream.Endpoint(eth_phy_layout(8))

        # # #

        preamble = Signal(64, reset=eth_preamble)
        cnt = Signal(max=8)
        clr_cnt = Signal()
        inc_cnt = Signal()

        self.sync += \
            If(clr_cnt,
                cnt.eq(0)
            ).Elif(inc_cnt,
                cnt.eq(cnt+1)
            )

        fsm = FSM(reset_state="IDLE")
        self.submodules += fsm
        fsm.act("IDLE",
            sink.ack.eq(1),
            clr_cnt.eq(1),
            If(sink.stb,
                sink.ack.eq(0),
                NextState("INSERT"),
            )
        )
        fsm.act("INSERT",
            source.stb.eq(1),
            chooser(preamble, cnt, source.data),
            If(cnt == 7,
                If(source.ack, NextState("COPY"))
            ).Else(
                inc_cnt.eq(source.ack)
            )
        )

        self.comb += [
            source.data.eq(sink.data),
            source.last_be.eq(sink.last_be)
        ]
        fsm.act("COPY",
            sink.connect(source, omit={"data", "last_be"}),

            If(sink.stb & sink.eop & source.ack,
                NextState("IDLE"),
            )
        )


class LiteEthMACPreambleChecker(Module):
    """Preamble detector

    Detects preamble at the beginning of each packet.

    Attributes
    ----------
    sink : in
        Bits input.
    source : out
        Packet octets starting immediately after SFD.
    error : out
        Pulses every time a preamble error is detected.
    """
    def __init__(self):
        self.sink = sink = stream.Endpoint(eth_phy_layout(8))
        self.source = source = stream.Endpoint(eth_phy_layout(8))

        self.error = Signal()

        # # #

        fsm = FSM(reset_state="IDLE")
        self.submodules += fsm

        fsm.act("IDLE",
            sink.ack.eq(1),
            If(sink.stb & ~sink.eop & (sink.data == eth_preamble >> 56),
                NextState("COPY")
            ),
            If(sink.stb & sink.eop, self.error.eq(1))
        )
        self.comb += [
            source.data.eq(sink.data),
            source.last_be.eq(sink.last_be)
        ]
        fsm.act("COPY",
            sink.connect(source, omit={"data", "last_be"}),
            If(source.stb & source.eop & source.ack,
                NextState("IDLE"),
            )
        )
