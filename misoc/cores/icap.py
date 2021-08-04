from migen import *
from migen.genlib.cdc import PulseSynchronizer

from misoc.interconnect.csr import AutoCSR, CSR

class ICAP(Module, AutoCSR):
    def __init__(self, fpga_family, clk_divide_ratio="2"):
        """
        ICAP module.

        Use this module to issue the IPROG command and restart the gateware.
        Both E2 and E3 are supported by selecting the right version.+
        
        Parameters
        ----------
        fpga_family : str
            FPGA family name, used to determine the version of primitive. 
            Supported family: ultrascale (metlino/sayma), 7series (kasli)

        clk_divide_ratio : str
            Optional. The divide ratio of the clock frequency from system clock.
        """
        self.iprog = CSR()

        ###
        if fpga_family not in {"ultrascale", "7series"}:
            raise ValueError("Not supported FPGA family")

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

        icap_csib = Signal()     # 1-bit input: Active-Low ICAP Enable
        icap_i = Signal(32)      # 32-bit input: Configuration data input bus
        icap_rdwrb = Signal()    # 1-bit input: Read/Write (1/0) Select input

        self.clock_domains.cd_icap = ClockDomain(reset_less=True)

        if fpga_family == "7series":
            # BUFR primitive module
            self.specials += Instance("BUFR",
                p_BUFR_DIVIDE = clk_divide_ratio,

                o_O = self.cd_icap.clk,
                i_CE = 1,
                i_CLR = 0,
                i_I = ClockSignal()
            )
        elif fpga_family == "ultrascale":
            # BUFGCE_DIV primitive module
            self.specials += Instance("BUFGCE_DIV",
                p_BUFGCE_DIVIDE = int(clk_divide_ratio),

                o_O = self.cd_icap.clk,
                i_CE = 1,
                i_CLR = 0,
                i_I = ClockSignal()
            )

        icap_iprog_re = PulseSynchronizer("sys", "icap")
        self.comb += icap_iprog_re.i.eq(self.iprog.re)
        self.submodules += icap_iprog_re

        counter = Signal(max=len(iprog_command_seq_i))
        fsm = FSM(reset_state="idle")
        self.submodules += ClockDomainsRenamer("icap")(fsm)
        fsm.act("idle",
            icap_rdwrb.eq(1),
            icap_csib.eq(1),
            If(icap_iprog_re.o,
                NextState("assert_write")
            )
        )
        fsm.act("assert_write",
            icap_rdwrb.eq(0),
            icap_csib.eq(1),
            NextState("command")
        )
        fsm.act("command",
            icap_rdwrb.eq(0),
            icap_csib.eq(0),
            icap_i.eq(iprog_command_seq[counter]),
            NextValue(counter, counter+1),
            If(counter == len(iprog_command_seq_i) - 1,
                NextState("deactivate")
            ).Else(
                NextState("command")
            )
        )
        fsm.act("deactivate",
            icap_rdwrb.eq(0),
            icap_csib.eq(1),
            NextState("idle")
        )

        if fpga_family == "7series":
            # ICAPE2 primitive module
            self.specials += Instance("ICAPE2",
                p_ICAP_WIDTH = "X32",

                i_CLK = ClockSignal("icap"),
                i_CSIB = icap_csib,
                i_I = icap_i,
                i_RDWRB = icap_rdwrb
            )
        elif fpga_family == "ultrascale":
            # ICAPE3 primitive module
            self.specials += Instance("ICAPE3",
                i_CLK = ClockSignal("icap"),
                i_CSIB = icap_csib,
                i_I = icap_i,
                i_RDWRB = icap_rdwrb
            )
