from migen import *
from migen.genlib.misc import timeline

from misoc.interconnect import wishbone
from misoc.interconnect.csr import AutoCSR, CSRStorage, CSRStatus

IDCODE = 0x03631093 # 7a100t
ICAP_WIDTH = "X32"
FILE_NAME = "NONE"
iprog_command_seq_i = [
            0xFFFFFFFF, # Dummy Word
            0x5599AA66, # Sync Word
            0x04000000, # Type 1 NO OP 
            0x0C400080, # Write WBSTAR 
            0x00000000, # WBSTAR 
            0x0C000180, # Write CMD 
            0x000000F0, # Write IPROG 
            0x04000000, # Type 1 NO OP  
        ]

class ICAP(Module, AutoCSR):
    def __init__(self):
        self.trigger = CSRStorage()

        ###

        O = Signal(32)      # 32-bit output: Configuration data output bus
        CLK = Signal()      # 1-bit input: Clock Input
        CSIB = Signal()     # 1-bit input: Active-Low ICAP Enable
        I = Signal(32)      # 32-bit input: Configuration data input bus
        RDWRB = Signal()    # 1-bit input: Read/Write Select input
        state = Signal(4)   # state machine register

        # clock generation
        div = 4
        counter = Signal(max=div)
        self.sync += [
            If(counter == div//2 - 1,
                CLK.eq(1)
            ),
            If(counter == div - 1,
                counter.eq(0),
                CLK.eq(0)
            ).Else(
                counter.eq(counter + 1),
            ),
        ]

        self.clock_domains.icap = ClockDomain(reset_less=True)
        self.comb += ClockSignal("icap").eq(CLK)

        # rising edge detection
        edge = Signal(2)
        self.sync.icap += [
            edge[1].eq(edge[0]),
            edge[0].eq(self.trigger.storage)
        ]

        cases = {
            # idle_ICAP
            0x00:       [
                    RDWRB.eq(1),
                    CSIB.eq(1),
                    If(edge == 0b01,
                        state.eq(0x01)
                    )
            ],
            # Assert RDWRB
            0x01:       [
                    RDWRB.eq(0),
                    CSIB.eq(1),
                    state.eq(0x02)
            ],
            # Assert CSIB and send dummy
            0x02:       [
                    RDWRB.eq(0),
                    CSIB.eq(0),
                    I.eq(iprog_command_seq_i[0]),
                    state.eq(0x0c)
            ],
            # Send sync word
            0x03:       [
                    RDWRB.eq(0),
                    CSIB.eq(0),
                    I.eq(iprog_command_seq_i[1]),
                    state.eq(0x04)
            ],
            # Send NO OP
            0x04:       [
                    RDWRB.eq(0),
                    CSIB.eq(0),
                    I.eq(iprog_command_seq_i[2]),
                    state.eq(0x05)
            ],
            # Send Write WBSTAR
            0x05:       [
                    RDWRB.eq(0),
                    CSIB.eq(0),
                    I.eq(iprog_command_seq_i[3]),
                    state.eq(0x06)
            ],
            # Send WBSTAR
            0x06:       [
                    RDWRB.eq(0),
                    CSIB.eq(0),
                    I.eq(iprog_command_seq_i[4]),
                    state.eq(0x07)
            ],
            # Send Write CMD
            0x07:       [
                    RDWRB.eq(0),
                    CSIB.eq(0),
                    I.eq(iprog_command_seq_i[5]),
                    state.eq(0x08)
            ],
            # Send IPROG CMD
            0x08:       [
                    RDWRB.eq(0),
                    CSIB.eq(0),
                    I.eq(iprog_command_seq_i[6]),
                    state.eq(0x09)
            ],
            # Send NO OP
            0x09:       [
                    RDWRB.eq(0),
                    CSIB.eq(0),
                    I.eq(iprog_command_seq_i[7]),
                    state.eq(0x0a)
            ],
            # Deassert CSIB
            0x0a:       [
                    RDWRB.eq(0),
                    CSIB.eq(1),
                    state.eq(0x0b)
            ],
            # Deassert RDWRB
            0x0b:       [
                    RDWRB.eq(1),
                    CSIB.eq(1),
                    state.eq(0x00)
            ],
            # write Bus Width Sync Word
            0x0c:       [
                    RDWRB.eq(0),
                    CSIB.eq(0),
                    I.eq(0x000000BB),
                    state.eq(0x0d)
            ],
            # write Bus Width Detect pattern
            0x0d:       [
                    RDWRB.eq(0),
                    CSIB.eq(0),
                    I.eq(0x11220044),
                    state.eq(0x0e)
            ],
            # Write dummy   
            0x0e:       [
                    RDWRB.eq(0),
                    CSIB.eq(0),
                    I.eq(0xFFFFFFFF),
                    state.eq(0x03)
            ],
            "default":  [
                    RDWRB.eq(1),
                    CSIB.eq(1),
                    state.eq(0x00)
                ]
        }
        self.sync.icap += Case(state, cases)
        
        # ICAPE2 primitive module
        self.specials += Instance("ICAPE2", name="ICAPE2_inst",
            p_DEVICE_ID = IDCODE,
            p_ICAP_WIDTH = ICAP_WIDTH,
            p_SIM_CFG_FILE_NAME = FILE_NAME,

            o_O = O,
            i_CLK = ClockSignal("icap"),
            i_CSIB = CSIB,
            i_I = I,
            i_RDWRB = RDWRB
            )
        


