from migen import *
from migen.genlib.cdc import PulseSynchronizer

from misoc.interconnect.csr import AutoCSR, CSR

class ICAP(Module, AutoCSR):
    def __init__(self, version, clk_divide_ratio="2"):
        """
        ICAP module.

        Use this module to issue the IPROG command and restart the gateware.
        Both E2 and E3 are supported by selecting the right version.
        """
        self.iprog = CSR()

        ###

        iprog_command_seq_i = [
            0xFFFFFFFF, # 0: Dummy Word
            0x000000BB, # 1: Bus Width Sync Word
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
        iprog_command_seq = Array(Constant(a) for a in iprog_command_seq_i)

        csib = Signal()     # 1-bit input: Active-Low ICAP Enable
        i = Signal(32)      # 32-bit input: Configuration data input bus
        rdwrb = Signal()    # 1-bit input: Read/Write (1/0) Select input

        counter = Signal(max=11)

        self.clock_domains.icap = ClockDomain()

        if version == "E2":
            # BUFR primitive module
            self.specials += Instance("BUFR", name="BUFR_inst",
                p_BUFR_DIVIDE = clk_divide_ratio,

                o_O = self.icap.clk,
                i_CE = 1,
                i_CLR = 1,
                i_I = ClockSignal()
            )
        elif version == "E3":
            # BUFGCE_DIV primitive module
            self.specials += Instance("BUFGCE_DIV", name="BUFGCE_DIV_inst",
                p_BUFGCE_DIVIDE = int(clk_divide_ratio),

                o_O = self.icap.clk,
                i_CE = 1,
                i_CLR = 1,
                i_I = ClockSignal()
            )

        self.submodules += PulseSynchronizer("sys", "icap")

        fsm = FSM(reset_state="idle")
        self.submodules += ClockDomainsRenamer("icap")(fsm)
        fsm.act("idle",
            rdwrb.eq(1),
            csib.eq(1),
            # NextValue(rdwrb, 1),
            # NextValue(csib, 1),
            If(self.iprog.re,
                NextState("assert_write")
            )
        )
        fsm.act("assert_write",
            rdwrb.eq(0),
            csib.eq(1),
            # NextValue(rdwrb, 0),
            # NextValue(csib, 1),
            NextState("command")
        )
        fsm.act("command",
            rdwrb.eq(0),
            csib.eq(0),
            # NextValue(rdwrb, 0),
            # NextValue(csib, 0),
            NextValue(i, iprog_command_seq[counter]),
            # i.eq(iprog_command_seq[counter]),
            NextValue(counter, counter+1),
            # counter.eq(counter+1),
            If(counter == 10,
                NextState("deactivate")
            ).Else(
                NextState("command")
            )
        )
        fsm.act("deactivate",
            rdwrb.eq(0),
            csib.eq(1),
            # NextValue(rdwrb, 0),
            # NextValue(csib, 1),
            NextState("idle")
        )

        if version == "E2":
            # ICAPE2 primitive module
            self.specials += Instance("ICAPE2", name="ICAPE2_inst",
                p_ICAP_WIDTH = "X32",

                i_CLK = ClockSignal("icap"),
                i_CSIB = csib,
                i_I = i,
                i_RDWRB = rdwrb
            )
        elif version == "E3":
            # ICAPE3 primitive module
            self.specials += Instance("ICAPE3", name="ICAPE3_inst",
                i_CLK = ClockSignal("icap"),
                i_CSIB = csib,
                i_I = i,
                i_RDWRB = rdwrb
            )
