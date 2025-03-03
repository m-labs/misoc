from migen import *
from misoc.interconnect.stream import Endpoint
from misoc.cores.liteeth_mini.mac.crc import LiteEthMACCRCEngine
from misoc.cores.coaxpress.common import word_layout_dchar, word_width


@ResetInserter()
@CEInserter()
class CXPCRC32(Module):
    # Section 9.2.2.2 (CXP-001-2021)
    width = 32
    polynom = 0x04C11DB7
    seed = 2**width - 1
    check = 0x00000000

    def __init__(self, data_width):
        self.data = Signal(data_width)
        self.value = Signal(self.width)
        self.error = Signal()

        # # #

        self.submodules.engine = LiteEthMACCRCEngine(
            data_width, self.width, self.polynom
        )
        reg = Signal(self.width, reset=self.seed)
        self.sync += reg.eq(self.engine.next)
        self.comb += [
            self.engine.data.eq(self.data),
            self.engine.last.eq(reg),
            self.value.eq(reg[::-1]),
            self.error.eq(reg != self.check),
        ]


class CXPCRC32Checker(Module):
    def __init__(self):
        self.error = Signal()

        self.sink = Endpoint(word_layout_dchar)
        self.source = Endpoint(word_layout_dchar)

        # # #

        self.submodules.crc = crc = CXPCRC32(word_width)
        self.comb += crc.data.eq(self.sink.data)

        self.submodules.fsm = fsm = FSM(reset_state="INIT")
        fsm.act("INIT",
            crc.reset.eq(1),
            NextState("CHECKING"),
        )

        fsm.act("RESET",
            crc.reset.eq(1),
            self.error.eq(crc.error),
            NextState("CHECKING"),
        )

        fsm.act("CHECKING",
            If(self.sink.stb & self.sink.eop,
                # discard the crc
                self.sink.ack.eq(1),
                NextState("RESET"),
            ).Else(
                self.sink.connect(self.source),
            ),
            crc.ce.eq(self.sink.stb & self.source.ack),
        )
    
