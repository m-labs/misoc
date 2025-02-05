from migen import *

from misoc.cores.coaxpress.common import char_layout, char_width, KCode, word_layout, word_layout_dchar
from misoc.interconnect.stream import Endpoint

class Trigger_Inserter(Module):
    def __init__(self):
        self.stb = Signal()
        self.delay = Signal(char_width) 
        self.linktrig_mode = Signal()

        # # #

        self.sink = Endpoint(char_layout)
        self.source = Endpoint(char_layout)

        # Table 15 & 16 (CXP-001-2021)
        # Send [K28.2, K28.4, K28.4] or [K28.4, K28.2, K28.2] and 3x delay as trigger packet 
        trig_packet = [Signal(char_width), Signal(char_width), Signal(char_width), self.delay, self.delay, self.delay]
        trig_packet_k = [1, 1, 1, 0, 0, 0]
        self.comb += [
            If(self.linktrig_mode,
                trig_packet[0].eq(KCode["trig_indic_28_4"]),
                trig_packet[1].eq(KCode["trig_indic_28_2"]),
                trig_packet[2].eq(KCode["trig_indic_28_2"]),
            ).Else(
                trig_packet[0].eq(KCode["trig_indic_28_2"]),
                trig_packet[1].eq(KCode["trig_indic_28_4"]),
                trig_packet[2].eq(KCode["trig_indic_28_4"]),
            ),
        ]
        
        self.submodules.fsm = fsm = FSM(reset_state="COPY")
        
        cnt = Signal(max=6)
        fsm.act("COPY",
            NextValue(cnt, cnt.reset),
            self.sink.connect(self.source),
            If(self.stb, NextState("WRITE_TRIG"))
        )

        fsm.act("WRITE_TRIG",
            self.sink.ack.eq(0),
            self.source.stb.eq(1),
            self.source.data.eq(Array(trig_packet)[cnt]),
            self.source.k.eq(Array(trig_packet_k)[cnt]),
            If(self.source.ack,
                If(cnt == 5,
                    NextState("COPY"),
                ).Else(
                    NextValue(cnt, cnt + 1),
                )
            )
        )

class Trigger_ACK_Inserter(Module):
    def __init__(self):
        self.stb = Signal()

        # # #

        # Section 9.3.2 (CXP-001-2021)
        # Send 4x K28.6 and 4x 0x01 as trigger packet ack
        self.submodules.fsm = fsm = FSM(reset_state="COPY")
        
        self.sink = Endpoint(word_layout)
        self.source = Endpoint(word_layout)
        fsm.act("COPY",
            self.sink.connect(self.source),
            If(self.stb, NextState("WRITE_ACK0"))
        )

        fsm.act("WRITE_ACK0",
            self.sink.ack.eq(0),
            self.source.stb.eq(1),
            self.source.data.eq(Replicate(KCode["io_ack"], 4)),
            self.source.k.eq(Replicate(1, 4)),
            If(self.source.ack, NextState("WRITE_ACK1")),
        )

        fsm.act("WRITE_ACK1",
            self.sink.ack.eq(0),
            self.source.stb.eq(1),
            self.source.data.eq(Replicate(C(0x01, char_width), 4)),
            self.source.k.eq(Replicate(0, 4)),
            If(self.source.ack, NextState("COPY")),
        )

class Trigger_Reader(Module):
    def __init__(self):
        self.sink = Endpoint(word_layout_dchar)
        self.source = Endpoint(word_layout_dchar)

        self.trig = Signal()
        self.delay = Signal(char_width)
        self.linktrigger_n = Signal(char_width)

        # # #

        self.submodules.fsm = fsm = FSM(reset_state="COPY")

        fsm.act("COPY",
            If((self.sink.stb & (self.sink.dchar == KCode["trig_indic_28_2"]) & (self.sink.dchar_k == 1)),
                # discard K28,2
                self.sink.ack.eq(1),
                NextState("READ_DELAY")
            ).Else(
                self.sink.connect(self.source),
            )
        )

        fsm.act("READ_DELAY",
            self.sink.ack.eq(1),
            If(self.sink.stb,
                NextValue(self.delay, self.sink.dchar),
                NextState("READ_LINKTRIGGER"),
            )
        )

        fsm.act("READ_LINKTRIGGER",
            self.sink.ack.eq(1),
            If(self.sink.stb,
                NextValue(self.linktrigger_n, self.sink.dchar),
                self.trig.eq(1),
                NextState("COPY"),
            )
        )

class Trigger_ACK_Reader(Module):
    def __init__(self):
        self.sink = Endpoint(word_layout_dchar)
        self.source = Endpoint(word_layout_dchar)

        self.ack = Signal()

        # # #

        self.submodules.fsm = fsm = FSM(reset_state="COPY")

        fsm.act("COPY",
            If((self.sink.stb & (self.sink.dchar == KCode["io_ack"]) & (self.sink.dchar_k == 1)),
                # discard K28,6
                self.sink.ack.eq(1),
                NextState("READ_ACK")
            ).Else(
                self.sink.connect(self.source),
            )
        )

        fsm.act("READ_ACK",
            self.sink.ack.eq(1),
            If(self.sink.stb,
                NextState("COPY"),
                # discard the word after K28,6
                If((self.sink.dchar == 0x01) & (self.sink.dchar_k == 0),
                    self.ack.eq(1),
                )
            )
        )
