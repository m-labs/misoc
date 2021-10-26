#!/usr/bin/env python3

import argparse
import os
from fractions import Fraction
from math import ceil

from migen import *
from migen.build.generic_platform import ConstraintError
from migen.build.platforms import mixxeo, m1

from misoc.cores.sdram_settings import MT46V32M16
from misoc.cores.sdram_phy import S6HalfRateDDRPHY
from misoc.cores import nor_flash_16
# TODO: from misoc.cores import framebuffer
from misoc.cores import gpio
from misoc.cores.liteeth_mini.phy import LiteEthPHY
from misoc.cores.liteeth_mini.mac import LiteEthMAC
from misoc.integration.soc_sdram import *
from misoc.integration.builder import *


class _MXCRG(Module):
    def __init__(self, pads, outfreq1x):
        self.clock_domains.cd_sys = ClockDomain()
        self.clock_domains.cd_sdram_half = ClockDomain()
        self.clock_domains.cd_sdram_full_wr = ClockDomain()
        self.clock_domains.cd_sdram_full_rd = ClockDomain()
        self.clock_domains.cd_base50 = ClockDomain(reset_less=True)

        self.clk4x_wr_strb = Signal()
        self.clk4x_rd_strb = Signal()

        ###

        infreq = 50*1000000
        ratio = Fraction(outfreq1x)/Fraction(infreq)
        in_period = float(Fraction(1000000000)/Fraction(infreq))

        self.specials += Instance("mxcrg",
                                  Instance.Parameter("in_period", in_period),
                                  Instance.Parameter("f_mult", ratio.numerator),
                                  Instance.Parameter("f_div", ratio.denominator),
                                  Instance.Input("clk50_pad", pads.clk50),
                                  Instance.Input("trigger_reset", pads.trigger_reset),

                                  Instance.Output("sys_clk", self.cd_sys.clk),
                                  Instance.Output("sys_rst", self.cd_sys.rst),
                                  Instance.Output("clk2x_270", self.cd_sdram_half.clk),
                                  Instance.Output("clk4x_wr", self.cd_sdram_full_wr.clk),
                                  Instance.Output("clk4x_rd", self.cd_sdram_full_rd.clk),
                                  Instance.Output("base50_clk", self.cd_base50.clk),

                                  Instance.Output("clk4x_wr_strb", self.clk4x_wr_strb),
                                  Instance.Output("clk4x_rd_strb", self.clk4x_rd_strb),
                                  Instance.Output("norflash_rst_n", pads.norflash_rst_n),
                                  Instance.Output("ddr_clk_pad_p", pads.ddr_clk_p),
                                  Instance.Output("ddr_clk_pad_n", pads.ddr_clk_n))


class _MXClockPads:
    def __init__(self, platform):
        self.clk50 = platform.request("clk50")
        self.trigger_reset = 0
        try:
            self.trigger_reset = platform.request("user_btn", 1)
        except ConstraintError:
            pass
        self.norflash_rst_n = platform.request("norflash_rst_n")
        ddram_clock = platform.request("ddram_clock")
        self.ddr_clk_p = ddram_clock.p
        self.ddr_clk_n = ddram_clock.n


class BaseSoC(SoCSDRAM):
    def __init__(self, platform_name="mixxeo", **kwargs):
        if platform_name == "mixxeo":
            platform = mixxeo.Platform()
        elif platform_name == "m1":
            platform = m1.Platform()
        else:
            raise ValueError
        SoCSDRAM.__init__(self, platform,
                          clk_freq=(83 + Fraction(1, 3))*1000000,
                          cpu_reset_address=0x00180000,
                          **kwargs)

        self.submodules.crg = _MXCRG(_MXClockPads(platform), self.clk_freq)

        sdram_module = MT46V32M16(self.clk_freq, "1:2")
        self.submodules.ddrphy = S6HalfRateDDRPHY(platform.request("ddram"),
                                                  sdram_module.memtype,
                                                  rd_bitslip=0,
                                                  wr_bitslip=3,
                                                  dqs_ddr_alignment="C1")
        self.register_sdram(self.ddrphy, "lasmicon",
                            sdram_module.geom_settings, sdram_module.timing_settings)
        self.comb += [
            self.ddrphy.clk4x_wr_strb.eq(self.crg.clk4x_wr_strb),
            self.ddrphy.clk4x_rd_strb.eq(self.crg.clk4x_rd_strb)
        ]

        if not self.integrated_rom_size:
            clk_period_ns = 1000000000/self.clk_freq
            self.submodules.norflash = nor_flash_16.NorFlash16(
                platform.request("norflash"),
                ceil(110/clk_period_ns), ceil(50/clk_period_ns))
            self.flash_boot_address = 0x001a0000
            self.register_rom(self.norflash.bus)

        platform.add_platform_command("""
INST "mxcrg/wr_bufpll" LOC = "BUFPLL_X0Y2";
INST "mxcrg/rd_bufpll" LOC = "BUFPLL_X0Y3";
""")
        platform.add_source(os.path.join(misoc_directory, "cores", "mxcrg.v"))


class MiniSoC(BaseSoC):
    mem_map = {
        "ethmac": 0x30000000,  # (shadow @0xb0000000)
    }
    mem_map.update(BaseSoC.mem_map)

    def __init__(self, *args, **kwargs):
        BaseSoC.__init__(self, *args, **kwargs)

        platform = self.platform
        if platform.name == "mixxeo":
            self.submodules.leds = gpio.GPIOOut(platform.request("user_led"))
            self.csr_devices.append("leds")
        if platform.name == "m1":
            self.submodules.buttons = gpio.GPIOIn(Cat(platform.request("user_btn", 0),
                                                      platform.request("user_btn", 2)))
            self.submodules.leds = gpio.GPIOOut(Cat(platform.request("user_led", i) for i in range(2)))
            self.csr_devices += ["buttons", "leds"]

        eth_clocks = platform.request("eth_clocks")
        self.sync.base50 += eth_clocks.phy.eq(~eth_clocks.phy)
        self.submodules.ethphy = LiteEthPHY(eth_clocks,
                                            platform.request("eth"))
        self.submodules.ethmac = LiteEthMAC(phy=self.ethphy, dw=self.cpu_dw, interface="wishbone",
                                            endianness="little" if self.cpu_type == "vexriscv" else "big")
        self.add_wb_slave(self.mem_map["ethmac"], 0x2000, self.ethmac.bus)
        self.add_memory_region("ethmac", self.mem_map["ethmac"] | self.shadow_base, 0x2000)
        self.csr_devices += ["ethphy", "ethmac"]
        self.interrupt_devices.append("ethmac")


def get_vga_dvi(platform):
    try:
        pads_vga = platform.request("vga_out")
    except ConstraintError:
        pads_vga = None
    try:
        pads_dvi = platform.request("dvi_out")
    except ConstraintError:
        pads_dvi = None
    else:
        platform.add_platform_command("""
PIN "dviout_pix_bufg.O" CLOCK_DEDICATED_ROUTE = FALSE;
""")
    return pads_vga, pads_dvi


def add_vga_tig(platform, fb):
    platform.add_platform_command("""
NET "{vga_clk}" TNM_NET = "GRPvga_clk";
NET "sys_clk" TNM_NET = "GRPsys_clk";
TIMESPEC "TSise_sucks1" = FROM "GRPvga_clk" TO "GRPsys_clk" TIG;
TIMESPEC "TSise_sucks2" = FROM "GRPsys_clk" TO "GRPvga_clk" TIG;
""", vga_clk=fb.driver.clocking.cd_pix.clk)


class FramebufferSoC(MiniSoC):
    def __init__(self, *args, **kwargs):
        MiniSoC.__init__(self, *args, **kwargs)
        pads_vga, pads_dvi = get_vga_dvi(platform)
        self.submodules.fb = framebuffer.Framebuffer(pads_vga, pads_dvi,
                                                     self.get_native_sdram_if())
        add_vga_tig(platform, self.fb)
        self.csr_devices.append("fb")


def main():
    parser = argparse.ArgumentParser(description="MiSoC port to the Mixxeo and Milkymist One")
    builder_args(parser)
    soc_sdram_args(parser)
    parser.add_argument("--platform", default="mixxeo",
                        help="platform to build for: mixxeo, m1")
    parser.add_argument("--soc-type", default="base",
                        help="SoC type: base, mini, framebuffer")
    args = parser.parse_args()

    cls = {
        "base": BaseSoC,
        "mini": MiniSoC,
        "framebuffer": FramebufferSoC
    }[args.soc_type]
    soc = cls(args.platform, **soc_sdram_argdict(args))
    builder = Builder(soc, **builder_argdict(args))
    builder.build()


if __name__ == "__main__":
    main()
