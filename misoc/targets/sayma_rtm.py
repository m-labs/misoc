#!/usr/bin/env python3

import argparse

from migen import *
from migen.genlib.resetsync import AsyncResetSynchronizer
from migen.build.platforms.sinara import sayma_rtm, sayma_rtm2

from misoc.integration.soc_core import *
from misoc.integration.builder import *


class CRG(Module):
    def __init__(self, platform, hw_rev):
        self.clock_domains.cd_sys = ClockDomain()
        pll_fb = Signal()
        pll_locked = Signal()
        pll_clk625 = Signal()
        if hw_rev == "v1.0":
            clkin1_period = 20.0
            clkin1 = platform.request("clk50")
            clkfbout_mult = 20
        elif hw_rev == "v2.0":
            clkin1_period = 16.0
            clkin1 = Signal()
            clkfbout_mult = 16
            clk125 = platform.request("clk125_gtp")
            platform.add_period_constraint(clk125, 8.)
            self.specials += Instance("IBUFDS_GTE2",
                i_CEB=0,
                i_I=clk125.p, i_IB=clk125.n,
                o_ODIV2=clkin1)
        else:
            raise ValueError
        self.specials += [
            Instance("PLLE2_BASE",
                p_CLKIN1_PERIOD=clkin1_period,
                i_CLKIN1=clkin1,

                i_CLKFBIN=pll_fb,
                o_CLKFBOUT=pll_fb,
                o_LOCKED=pll_locked,

                p_CLKFBOUT_MULT=clkfbout_mult, p_DIVCLK_DIVIDE=1,
                p_CLKOUT0_DIVIDE=16, p_CLKOUT0_PHASE=0.0, o_CLKOUT0=pll_clk625,
            ),
            Instance("BUFG", i_I=pll_clk625, o_O=self.cd_sys.clk),
            AsyncResetSynchronizer(self.cd_sys, ~pll_locked)
        ]


# No SDRAM - execute everything from one large BRAM.
class BaseSoC(SoCCore):
    def __init__(self, hw_rev=None, **kwargs):
        if hw_rev is None:
            hw_rev = "v2.0"
        self.hw_rev = hw_rev

        if hw_rev == "v1.0":
            platform = sayma_rtm.Platform(larger=True)
        elif hw_rev == "v2.0":
            platform = sayma_rtm2.Platform()
        else:
            raise ValueError
        SoCCore.__init__(self, platform,
            clk_freq=62.5e6,
            integrated_rom_size=0,
            integrated_sram_size=0,
            integrated_main_ram_size=256*1024,
            cpu_reset_address=self.mem_map["main_ram"],
            **kwargs)
        self.submodules.crg = CRG(platform, hw_rev)


def soc_sayma_rtm_args(parser):
    parser.add_argument("--hw-rev", default=None,
                        help="Sayma RTM hardware revision: v1.0/v2.0")


def soc_sayma_rtm_argdict(args):
    return {"hw_rev": args.hw_rev}


def main():
    parser = argparse.ArgumentParser(description="MiSoC port to the Sayma RTM")
    builder_args(parser)
    soc_sayma_rtm_args(parser)
    args = parser.parse_args()

    # Enable BIOS for test/demo.
    soc = BaseSoC(platform, **soc_sayma_rtm_argdict(args),
        integrated_rom_size=32*1024, integrated_sram_size=4096,
        integrated_main_ram_size=16*1024)
    builder = Builder(soc, **builder_argdict(args))
    builder.build()


if __name__ == "__main__":
    main()
