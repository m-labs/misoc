from migen import *
from migen.genlib.fsm import *
from migen.genlib.misc import chooser
from migen.genlib.record import Record

from misoc.interconnect import stream
from misoc.cores.liteeth_mini.common import eth_phy_layout, eth_preamble


class LiteEthMACPreambleInserter(Module):
    def __init__(self, dw):
        self.sink = stream.Endpoint(eth_phy_layout(dw))
        self.source = stream.Endpoint(eth_phy_layout(dw))

        # # #

        preamble = Signal(64, reset=eth_preamble)
        cnt_max = (64//dw)-1
        cnt = Signal(max=cnt_max+1)
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
            self.sink.ack.eq(1),
            clr_cnt.eq(1),
            If(self.sink.stb,
                self.sink.ack.eq(0),
                NextState("INSERT"),
            )
        )
        fsm.act("INSERT",
            self.source.stb.eq(1),
            chooser(preamble, cnt, self.source.data),
            If(cnt == cnt_max,
                If(self.source.ack, NextState("COPY"))
            ).Else(
                inc_cnt.eq(self.source.ack)
            )
        )

        self.comb += [
            self.source.data.eq(self.sink.data),
            self.source.last_be.eq(self.sink.last_be)
        ]
        fsm.act("COPY",
            self.sink.connect(self.source, omit={"data", "last_be"}),

            If(self.sink.stb & self.sink.eop & self.source.ack,
                NextState("IDLE"),
            )
        )


class LiteEthMACPreambleChecker(Module):
    def __init__(self, dw):
        self.sink = stream.Endpoint(eth_phy_layout(dw))
        self.source = stream.Endpoint(eth_phy_layout(dw))

        # # #

        preamble = Signal(64, reset=eth_preamble)
        cnt_max = (64//dw) - 1
        cnt = Signal(max=cnt_max+1)
        clr_cnt = Signal()
        inc_cnt = Signal()

        self.sync += \
            If(clr_cnt,
                cnt.eq(0)
            ).Elif(inc_cnt,
                cnt.eq(cnt+1)
            )

        discard = Signal()
        clr_discard = Signal()
        set_discard = Signal()

        self.sync += \
            If(clr_discard,
                discard.eq(0)
            ).Elif(set_discard,
                discard.eq(1)
            )

        ref = Signal(dw)
        match = Signal()
        self.comb += [
            chooser(preamble, cnt, ref),
            match.eq(self.sink.data == ref)
        ]

        fsm = FSM(reset_state="IDLE")
        self.submodules += fsm

        fsm.act("IDLE",
            self.sink.ack.eq(1),
            clr_cnt.eq(1),
            clr_discard.eq(1),
            If(self.sink.stb,
                clr_cnt.eq(0),
                inc_cnt.eq(1),
                clr_discard.eq(0),
                set_discard.eq(~match),
                NextState("CHECK"),
            )
        )
        fsm.act("CHECK",
            self.sink.ack.eq(1),
            If(self.sink.stb,
                set_discard.eq(~match),
                If(cnt == cnt_max,
                    If(discard | (~match),
                        NextState("IDLE")
                    ).Else(
                        NextState("COPY")
                    )
                ).Else(
                    inc_cnt.eq(1)
                )
            )
        )
        self.comb += [
            self.source.data.eq(self.sink.data),
            self.source.last_be.eq(self.sink.last_be)
        ]
        fsm.act("COPY",
            self.sink.connect(self.source, omit={"data", "last_be"}),
            If(self.source.stb & self.source.eop & self.source.ack,
                NextState("IDLE"),
            )
        )
