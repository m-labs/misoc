from migen import *

from misoc.cores.coaxpress.common import char_layout, char_width, KCode, word_layout, word_layout_dchar
from misoc.interconnect.stream import Endpoint

class TriggerInserter(Module):
    def __init__(self, clk_freq):
        self.stb = Signal()
        self.linktrig_mode = Signal(2)
        self.extra_linktrig = Signal()
        self.bitrate2x = Signal()

        # # #

        self.sink = Endpoint(char_layout)
        self.source = Endpoint(char_layout)

        # Fixed latency triggering - Section 9.3.1.1 (CXP-001-2021)
        # As trigger packet can only start transmitting in char boundary, the timing between a trigger event and the start of packet transmission can varies.
        # 
        # To minimize this jitter, a delay is encoded into the trigger packet following this formula:
        # delay + time between trigger event & char boundery = 1 char tranmission time (which is constant)
        # 
        # So the receiver can use the delay value to recreate the trigger event with low jitter and a fixed latency
        period_ns = int(1e9 / clk_freq)
        delay = Signal(max=240, reset=239)

        self.sync += [
            If(self.source.ack,
                # start of packet transmission (i.e char boundary)
                delay.eq(delay.reset),
            ).Else(
                If(self.bitrate2x,
                    # in 41.6 Mpbs, the ratio of delay : time (ns) = 1 : 1  
                    delay.eq(delay - (period_ns)),
                ).Else(
                    # in 20.83 Mpbs, the ratio of delay : time (ns) = 1 : 2  
                    delay.eq(delay - (period_ns // 2)),
                )
            ),
        ]


        # Table 15 & 16 (CXP-001-2021)
        # Send [K28.2, K28.4, K28.4] or [K28.4, K28.2, K28.2] and 3x delay as trigger packet 
        delay_r = Signal(char_width)
        trig_packet = [Signal(char_width), Signal(char_width), Signal(char_width), delay_r, delay_r, delay_r]
        trig_packet_k = [1, 1, 1, 0, 0, 0]
        self.sync += [
            If(self.stb,
                If(self.linktrig_mode[0],
                    trig_packet[0].eq(KCode["trig_indic_28_4"]),
                    trig_packet[1].eq(KCode["trig_indic_28_2"]),
                    trig_packet[2].eq(KCode["trig_indic_28_2"]),
                ).Else(
                    trig_packet[0].eq(KCode["trig_indic_28_2"]),
                    trig_packet[1].eq(KCode["trig_indic_28_4"]),
                    trig_packet[2].eq(KCode["trig_indic_28_4"]),
                ),
                If(self.extra_linktrig,
                    # the LSB of delay is repurposed to define extra linktrig_mode
                    # LSB = 0 when using LinkTrigger0 or LinkTrigger1
                    # LSB = 1 when using LinkTrigger2 or LinkTrigger3
                    delay_r.eq(self.linktrig_mode[1] | delay[1:])
                ).Else(
                    delay_r.eq(delay)
                )
            )
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

class TriggerACKInserter(Module):
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

class TriggerReader(Module):
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

class TriggerACKReader(Module):
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
