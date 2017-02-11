import os

from migen import *

from misoc.interconnect import wishbone


class MOR1KX(Module):
    def __init__(self, platform, **kwargs):
        self.ibus = i = wishbone.Interface()
        self.dbus = d = wishbone.Interface()
        self.interrupt = Signal(32)

        ###

        defaults = dict(
            FEATURE_INSTRUCTIONCACHE="ENABLED",
            OPTION_ICACHE_BLOCK_WIDTH=4,
            OPTION_ICACHE_SET_WIDTH=8,
            OPTION_ICACHE_WAYS=1,
            OPTION_ICACHE_LIMIT_WIDTH=31,
            FEATURE_DATACACHE="ENABLED",
            OPTION_DCACHE_BLOCK_WIDTH=4,
            OPTION_DCACHE_SET_WIDTH=8,
            OPTION_DCACHE_WAYS=1,
            OPTION_DCACHE_LIMIT_WIDTH=31,
            FEATURE_TIMER="NONE",
            OPTION_PIC_TRIGGER="LEVEL",
            FEATURE_SYSCALL="NONE",
            FEATURE_TRAP="NONE",
            FEATURE_RANGE="NONE",
            FEATURE_OVERFLOW="NONE",
            FEATURE_ADDC="ENABLED",
            FEATURE_CMOV="ENABLED",
            FEATURE_FFL1="ENABLED",
            OPTION_CPU0="CAPPUCCINO",
            IBUS_WB_TYPE="B3_REGISTERED_FEEDBACK",
            DBUS_WB_TYPE="B3_REGISTERED_FEEDBACK",
        )
        defaults.update(kwargs)
        parameters = {"p_{}".format(k): v for k, v in defaults.items()}

        i_adr_o = Signal(32)
        d_adr_o = Signal(32)
        self.specials += Instance("mor1kx",
                                  i_clk=ClockSignal(),
                                  i_rst=ResetSignal(),

                                  i_irq_i=self.interrupt,

                                  o_iwbm_adr_o=i_adr_o,
                                  o_iwbm_dat_o=i.dat_w,
                                  o_iwbm_sel_o=i.sel,
                                  o_iwbm_cyc_o=i.cyc,
                                  o_iwbm_stb_o=i.stb,
                                  o_iwbm_we_o=i.we,
                                  o_iwbm_cti_o=i.cti,
                                  o_iwbm_bte_o=i.bte,
                                  i_iwbm_dat_i=i.dat_r,
                                  i_iwbm_ack_i=i.ack,
                                  i_iwbm_err_i=i.err,
                                  i_iwbm_rty_i=0,

                                  o_dwbm_adr_o=d_adr_o,
                                  o_dwbm_dat_o=d.dat_w,
                                  o_dwbm_sel_o=d.sel,
                                  o_dwbm_cyc_o=d.cyc,
                                  o_dwbm_stb_o=d.stb,
                                  o_dwbm_we_o=d.we,
                                  o_dwbm_cti_o=d.cti,
                                  o_dwbm_bte_o=d.bte,
                                  i_dwbm_dat_i=d.dat_r,
                                  i_dwbm_ack_i=d.ack,
                                  i_dwbm_err_i=d.err,
                                  i_dwbm_rty_i=0,

                                  **parameters)

        self.comb += [
            self.ibus.adr.eq(i_adr_o[2:]),
            self.dbus.adr.eq(d_adr_o[2:])
        ]

        # add Verilog sources
        vdir = os.path.join(
            os.path.abspath(os.path.dirname(__file__)),
            "verilog", "rtl", "verilog")
        platform.add_source_dir(vdir)
