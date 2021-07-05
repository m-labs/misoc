from migen import *
from migen.genlib.cdc import PulseSynchronizer

from misoc.interconnect.csr import AutoCSR, CSRStorage, CSR

class ICAP(Module, AutoCSR):
    def __init__(self, clk_divide_ratio='2'):
        self.iprog = CSR()

        ###

        ICAP_WIDTH = "X32"
        iprog_command_seq_i = [
            0xFFFFFFFF, # 0: Dummy Word
            0x000000BB, # 1: Bust Width Sync Word
            0x11220044, # 2: Bus Width Detect Pattern
            0xFFFFFFFF, # 3: Dummy Word
            0x5599AA66, # 4: Sync Word
            0x04000000, # 5: Type 1 NO OP 
            0x0C400080, # 6: Write WBSTAR 
            0x00000000, # 7: WBSTAR 
            0x0C000180, # 8: Write CMD 
            0x000000F0, # 9: Write IPROG 
            0x04000000, # 10: Type 1 NO OP  
            ]

        o = Signal(32)      # 32-bit output: Configuration data output bus
        clk = Signal()      # 1-bit input: Clock Input
        csib = Signal()     # 1-bit input: Active-Low ICAP Enable
        i = Signal(32)      # 32-bit input: Configuration data input bus
        rdwrb = Signal()    # 1-bit input: Read/Write (1/0) Select input
        
        self.clock_domains.icap = ClockDomain(reset_less=True)

        # BUFR primitive module
        self.specials += Instance("BUFR", name="BUFR_inst",
            p_BUFR_DIVIDE = clk_divide_ratio,

            o_O = self.icap.clk,
            i_CE = 1,
            i_CLR = 1,
            i_I = ClockSignal()
            )
        
        self.submodules += PulseSynchronizer("sys", "icap")

        # rising edge detection
        edge = Signal(2)
        self.sync.icap += [
            edge[1].eq(edge[0]),
            edge[0].eq(self.iprog.re)
        ]

        fsm = FSM()
        self.submodules += fsm
        fsm.act(0,
            NextValue(rdwrb, 1),
            NextValue(csib, 1),
            If(edge == 0b01,
                NextState(1)
            )
        )
        fsm.act(1,
            NextValue(rdwrb, 0),
            NextValue(csib, 1),
            NextState(2)
        )
        fsm.act(2,
            NextValue(rdwrb, 0),
            NextValue(csib, 0),
            NextValue(i, iprog_command_seq_i[0]),
            NextState(3)
        )
        fsm.act(3,
            NextValue(rdwrb, 0),
            NextValue(csib, 0),
            NextValue(i, iprog_command_seq_i[1]),
            NextState(4)
        )
        fsm.act(4,
            NextValue(rdwrb, 0),
            NextValue(csib, 0),
            NextValue(i, iprog_command_seq_i[2]),
            NextState(5)
        )
        fsm.act(5,
            NextValue(rdwrb, 0),
            NextValue(csib, 0),
            NextValue(i, iprog_command_seq_i[3]),
            NextState(6)
        )
        fsm.act(6,
            NextValue(rdwrb, 0),
            NextValue(csib, 0),
            NextValue(i, iprog_command_seq_i[4]),
            NextState(7)
        )
        fsm.act(7,
            NextValue(rdwrb, 0),
            NextValue(csib, 0),
            NextValue(i, iprog_command_seq_i[5]),
            NextState(8)
        )
        fsm.act(8,
            NextValue(rdwrb, 0),
            NextValue(csib, 0),
            NextValue(i, iprog_command_seq_i[6]),
            NextState(9)
        )
        fsm.act(9,
            NextValue(rdwrb, 0),
            NextValue(csib, 0),
            NextValue(i, iprog_command_seq_i[7]),
            NextState(10)
        )
        fsm.act(10,
            NextValue(rdwrb, 0),
            NextValue(csib, 0),
            NextValue(i, iprog_command_seq_i[8]),
            NextState(11)
        )
        fsm.act(11,
            NextValue(rdwrb, 0),
            NextValue(csib, 0),
            NextValue(i, iprog_command_seq_i[9]),
            NextState(12)
        )
        fsm.act(12,
            NextValue(rdwrb, 0),
            NextValue(csib, 0),
            NextValue(i, iprog_command_seq_i[10]),
            NextState(13)
        )
        fsm.act(13,
            NextValue(rdwrb, 0),
            NextValue(csib, 0),
            NextState(14)
        )
        fsm.act(14,
            NextValue(rdwrb, 0),
            NextValue(csib, 0),
            NextState(0)
        )

        # ICAPE2 primitive module
        self.specials += Instance("ICAPE2", name="ICAPE2_inst",
            p_ICAP_WIDTH = ICAP_WIDTH,

            o_O = o,
            i_CLK = ClockSignal("icap"),
            i_CSIB = csib,
            i_I = i,
            i_RDWRB = rdwrb
            )
