from migen import *

from misoc.cores.coaxpress.common import char_width, KCode, word_layout 
from misoc.interconnect.stream import Endpoint

class IdleWordInserter(Module):
    def __init__(self):
        # Section 9.2.5 (CXP-001-2021)
        # Send K28.5, K28.1, K28.1, D21.5  as idle word
        self.submodules.fsm = fsm = FSM(reset_state="WRITE_IDLE")
        
        self.sink = Endpoint(word_layout)
        self.source = Endpoint(word_layout)

        # Section 9.2.5.1 (CXP-001-2021)
        # IDLE should be transmitter every 10000 words
        cnt = Signal(max=10000, reset=9999)
        
        fsm.act("WRITE_IDLE",
            self.source.stb.eq(1),
            self.source.data.eq(Cat(KCode["idle_comma"], KCode["idle_alignment"], KCode["idle_alignment"], C(0xB5, char_width))),
            self.source.k.eq(Cat(1, 1, 1, 0)),

            self.sink.ack.eq(1),
            If(self.sink.stb,
                self.sink.ack.eq(0),
                If(self.source.ack,
                    NextValue(cnt, cnt.reset),
                    NextState("COPY"),
                )
            ),
        )

        fsm.act("COPY",
            self.sink.connect(self.source),
            # increment when uphas data and got ack
            If(self.sink.stb & self.source.ack, NextValue(cnt, cnt - 1)),
            If((( (~self.sink.stb) | (self.sink.eop) | (cnt == 0) ) & self.source.ack), NextState("WRITE_IDLE"))
        )

