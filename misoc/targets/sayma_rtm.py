#!/usr/bin/env python3

import argparse

from migen import *
from migen.genlib.io import CRG
from migen.build.platforms.sinara import sayma_rtm

from misoc.integration.soc_core import *
from misoc.integration.builder import *


class BaseSoC(SoCCore):
    def __init__(self, platform, **kwargs):
        SoCCore.__init__(self, platform,
            clk_freq=50e6,
            integrated_rom_size=32*1024,
            integrated_main_ram_size=16*1024,
            **kwargs)
        self.submodules.crg = CRG(platform.request("clk50"))


def main():
    parser = argparse.ArgumentParser(description="MiSoC port to the Sayma RTM")
    builder_args(parser)
    soc_core_args(parser)
    args = parser.parse_args()

    platform = sayma_rtm.Platform()
    soc = BaseSoC(platform, **soc_core_argdict(args))
    builder = Builder(soc, **builder_argdict(args))
    builder.build()


if __name__ == "__main__":
    main()
