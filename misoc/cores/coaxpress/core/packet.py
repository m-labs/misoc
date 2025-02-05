from migen import *

from misoc.cores.coaxpress.common import char_width, KCode, word_layout, word_width
from misoc.interconnect.stream import Endpoint

class Packet_Wrapper(Module):
    def __init__(self):
        self.sink = Endpoint(word_layout)
        self.source = Endpoint(word_layout)

        # # #

        self.submodules.fsm = fsm = FSM(reset_state="IDLE")
        
        fsm.act("IDLE",
            self.sink.ack.eq(1),
            If(self.sink.stb,
                self.sink.ack.eq(0),
                NextState("INSERT_HEADER"),
            )
        )

        fsm.act("INSERT_HEADER",
            self.sink.ack.eq(0),
            self.source.stb.eq(1),
            self.source.data.eq(Replicate(KCode["pak_start"], 4)),
            self.source.k.eq(Replicate(1, 4)),
            If(self.source.ack, NextState("COPY")),
        )

        fsm.act("COPY",
            self.sink.connect(self.source),
            self.source.eop.eq(0),
            If(self.sink.stb & self.sink.eop & self.source.ack,
                NextState("INSERT_FOOTER"),
            ),
        )

        fsm.act("INSERT_FOOTER",
            self.sink.ack.eq(0),
            self.source.stb.eq(1),
            self.source.data.eq(Replicate(KCode["pak_end"], 4)),
            self.source.k.eq(Replicate(1, 4)),
            self.source.eop.eq(1),
            If(self.source.ack, NextState("IDLE")),
        )


@FullMemoryWE()
class Command_Test_Packet_Writer(Module):
    def __init__(self, buffer_depth):
        self.word_len = Signal(log2_int(buffer_depth))
        self.stb = Signal()
        self.stb_testseq = Signal()

        self.busy = Signal()

        # # #
        
        self.specials.mem = mem = Memory(word_width, buffer_depth)
        self.specials.mem_port = mem_port = mem.get_port()
        self.source = Endpoint(word_layout)

        # increment addr in the same cycle the moment addr_inc is high
        # as memory takes one cycle to shift to the correct addr
        addr_next = Signal(log2_int(buffer_depth))
        addr = Signal.like(addr_next)
        addr_rst = Signal()
        addr_inc = Signal()
        self.sync += addr.eq(addr_next),

        self.comb += [
            addr_next.eq(addr),
            If(addr_rst,
                addr_next.eq(addr_next.reset),
            ).Elif(addr_inc,
                addr_next.eq(addr + 1),
            ),
            mem_port.adr.eq(addr_next),
        ]

        self.submodules.fsm = fsm = FSM(reset_state="IDLE")
        self.comb += self.busy.eq(~fsm.ongoing("IDLE"))

        cnt = Signal(max=0xFFF)
        fsm.act("IDLE",
            addr_rst.eq(1),
            If(self.stb, NextState("TRANSMIT")),
            If(self.stb_testseq, 
                NextValue(cnt, cnt.reset),
                NextState("WRITE_TEST_PACKET_TYPE"),
            )
        )

        fsm.act("TRANSMIT",
            self.source.stb.eq(1),
            self.source.data.eq(mem_port.dat_r),
            If(self.source.ack,
                addr_inc.eq(1),
            ),
            If(addr_next == self.word_len,
                self.source.eop.eq(1),
                NextState("IDLE")
            )
        )

        fsm.act("WRITE_TEST_PACKET_TYPE",
            self.source.stb.eq(1),
            self.source.data.eq(Replicate(C(0x04, char_width), 4)),
            self.source.k.eq(Replicate(0, 4)),
            If(self.source.ack,NextState("WRITE_TEST_COUNTER"))
        )

        fsm.act("WRITE_TEST_COUNTER",
            self.source.stb.eq(1),
            self.source.data[:8].eq(cnt[:8]),
            self.source.data[8:16].eq(cnt[:8]+1),
            self.source.data[16:24].eq(cnt[:8]+2),
            self.source.data[24:].eq(cnt[:8]+3),
            self.source.k.eq(Cat(0, 0, 0, 0)),
            If(self.source.ack,
                If(cnt == 0xFFC,
                    self.source.eop.eq(1),
                    NextState("IDLE")
                ).Else(
                    NextValue(cnt, cnt + 4),
                )
               
            )
        )
