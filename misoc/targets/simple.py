#!/usr/bin/env python3

import argparse
import importlib

from migen import *
from migen.genlib.io import CRG

from misoc.cores.liteeth_mini.phy import LiteEthPHY
from misoc.cores.liteeth_mini.mac import LiteEthMAC
from misoc.integration.soc_core import *
from misoc.integration.builder import *


class BaseSoC(SoCCore):
    def __init__(self, platform, **kwargs):
        SoCCore.__init__(self, platform,
            clk_freq=int((1/(platform.default_clk_period))*1000000000),
            integrated_rom_size=0x8000,
            integrated_main_ram_size=16*1024,
            **kwargs)
        self.submodules.crg = CRG(platform.request(platform.default_clk_name))


class MiniSoC(BaseSoC):
    mem_map = {
        "ethmac": 0x30000000,  # (shadow @0xb0000000)
    }
    mem_map.update(BaseSoC.mem_map)

    def __init__(self, platform, **kwargs):
        BaseSoC.__init__(self, platform, **kwargs)

        self.submodules.ethphy = LiteEthPHY(platform.request("eth_clocks"),
                                            platform.request("eth"))
        self.submodules.ethmac = LiteEthMAC(phy=self.ethphy, dw=self.cpu_dw,
                                            interface="wishbone",
                                            endianness="little" if self.cpu_type == "vexriscv" else "big",
                                            with_preamble_crc=False)
        self.add_wb_slave(self.mem_map["ethmac"], 0x2000, self.ethmac.bus)
        self.add_memory_region("ethmac", self.mem_map["ethmac"] | self.shadow_base, 0x2000)
        self.csr_devices += ["ethphy", "ethmac"]
        self.interrupt_devices.append("ethmac")


def main():
    parser = argparse.ArgumentParser(description="Generic MiSoC port")
    builder_args(parser)
    soc_core_args(parser)
    parser.add_argument("--with-ethernet", action="store_true",
                        help="enable Ethernet support")
    parser.add_argument("platform",
                        help="module name of the Migen platform to build for")
    args = parser.parse_args()

    platform_module = importlib.import_module(args.platform)
    platform = platform_module.Platform()
    cls = MiniSoC if args.with_ethernet else BaseSoC
    soc = cls(platform, **soc_core_argdict(args))
    builder = Builder(soc, **builder_argdict(args))
    builder.build()


if __name__ == "__main__":
    main()
