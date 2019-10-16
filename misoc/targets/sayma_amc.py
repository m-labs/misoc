#!/usr/bin/env python3

import argparse

from migen import *
from migen.genlib.resetsync import AsyncResetSynchronizer
from migen.genlib.io import *
from migen.build.platforms.sinara import sayma_amc, sayma_amc2

from misoc.cores.sdram_settings import MT41J256M16
from misoc.cores.sdram_phy import kusddrphy
from misoc.cores import spi_flash
from misoc.cores.liteeth_mini.phy.ku_1000basex import KU_1000BASEX
from misoc.cores.liteeth_mini.mac import LiteEthMAC
from misoc.integration.soc_sdram import *
from misoc.integration.builder import *


class CRG(Module):
    def __init__(self, platform):
        self.clock_domains.cd_sys = ClockDomain()
        self.clock_domains.cd_sys4x = ClockDomain(reset_less=True)
        self.clock_domains.cd_clk200 = ClockDomain()
        self.clock_domains.cd_ic = ClockDomain()

        clk50 = platform.request("clk50")
        clk50_buffered = Signal()
        pll_locked = Signal()
        pll_fb = Signal()
        pll_sys4x = Signal()
        pll_clk200 = Signal()
        self.specials += [
            Instance("BUFG", i_I=clk50, o_O=clk50_buffered),
            Instance("PLLE2_BASE", name="crg_main_mmcm",
                p_STARTUP_WAIT="FALSE", o_LOCKED=pll_locked,

                # VCO @ 1GHz
                p_REF_JITTER1=0.01, p_CLKIN1_PERIOD=20.0,
                p_CLKFBOUT_MULT=20, p_DIVCLK_DIVIDE=1,
                i_CLKIN1=clk50_buffered, i_CLKFBIN=pll_fb, o_CLKFBOUT=pll_fb,

                # 500MHz
                p_CLKOUT0_DIVIDE=2, p_CLKOUT0_PHASE=0.0, o_CLKOUT0=pll_sys4x,

                # 200MHz
                p_CLKOUT1_DIVIDE=5, p_CLKOUT1_PHASE=0.0, o_CLKOUT1=pll_clk200,
            ),
            Instance("BUFGCE_DIV", name="main_bufgce_div",
                p_BUFGCE_DIVIDE=4,
                i_CE=1, i_I=pll_sys4x, o_O=self.cd_sys.clk),
            Instance("BUFGCE", name="main_bufgce",
                i_CE=1, i_I=pll_sys4x, o_O=self.cd_sys4x.clk),
            Instance("BUFG", i_I=pll_clk200, o_O=self.cd_clk200.clk),
            AsyncResetSynchronizer(self.cd_clk200, ~pll_locked),
        ]

        # https://www.xilinx.com/support/answers/67885.html
        platform.add_platform_command(
            "set_property CLOCK_DELAY_GROUP ULTRASCALE_IS_AWFUL [get_nets -of [get_pins main_bufgce_div/O]]")
        platform.add_platform_command(
            "set_property CLOCK_DELAY_GROUP ULTRASCALE_IS_AWFUL [get_nets -of [get_pins main_bufgce/O]]")
        platform.add_platform_command(
            "set_property USER_CLOCK_ROOT X2Y2 [get_nets -of [get_pins main_bufgce_div/O]]")
        platform.add_platform_command(
            "set_property USER_CLOCK_ROOT X2Y2 [get_nets -of [get_pins main_bufgce/O]]")

        ic_reset_counter = Signal(max=64, reset=63)
        ic_reset = Signal(reset=1)
        self.sync.clk200 += \
            If(ic_reset_counter != 0,
                ic_reset_counter.eq(ic_reset_counter - 1)
            ).Else(
                ic_reset.eq(0)
            )
        ic_rdy = Signal()
        ic_rdy_counter = Signal(max=64, reset=63)
        self.cd_sys.rst.reset = 1
        self.comb += self.cd_ic.clk.eq(self.cd_sys.clk)
        self.sync.ic += [
            If(ic_rdy,
                If(ic_rdy_counter != 0,
                    ic_rdy_counter.eq(ic_rdy_counter - 1)
                ).Else(
                    self.cd_sys.rst.eq(0)
                )
            )
        ]
        self.specials += [
            Instance("IDELAYCTRL", p_SIM_DEVICE="ULTRASCALE",
                     i_REFCLK=ClockSignal("clk200"), i_RST=ic_reset,
                     o_RDY=ic_rdy),
            AsyncResetSynchronizer(self.cd_ic, ic_reset)
        ]


class BaseSoC(SoCSDRAM):
    def __init__(self, hw_rev=None, sdram="ddram_32", sdram_controller_type="minicon", **kwargs):
        if hw_rev is None:
            hw_rev = "v2.0"
        self.hw_rev = hw_rev

        platform_module = {
            "v1.0": sayma_amc,
            "v2.0": sayma_amc2
        }[hw_rev]
        platform = platform_module.Platform()
        SoCSDRAM.__init__(self, platform, clk_freq=125*1000000,
                          **kwargs)
        self.config["HW_REV"] = hw_rev

        self.submodules.crg = CRG(platform)
        self.crg.cd_sys.clk.attr.add("keep")

        self.submodules.ddrphy = kusddrphy.KUSDDRPHY(platform.request(sdram))
        self.config["DDRPHY_WLEVEL"] = None
        self.config["KUSDDRPHY"] = None
        sdram_module = MT41J256M16(self.clk_freq, "1:4")
        self.register_sdram(self.ddrphy, sdram_controller_type,
                            sdram_module.geom_settings, sdram_module.timing_settings)
        self.csr_devices.append("ddrphy")

        if not self.integrated_rom_size:
            spiflash_pads = platform.request("spiflash")
            spiflash_pads.clk = Signal()
            self.specials += Instance("STARTUPE3", i_GSR=0, i_GTS=0,
                                      i_KEYCLEARB=0, i_PACK=1,
                                      i_USRDONEO=1, i_USRDONETS=1,
                                      i_USRCCLKO=spiflash_pads.clk, i_USRCCLKTS=0,
                                      i_FCSBO=1, i_FCSBTS=0,
                                      i_DO=0, i_DTS=0b1110)
            self.submodules.spiflash = spi_flash.SpiFlash(spiflash_pads, dummy=11, div=2)
            self.config["SPIFLASH_PAGE_SIZE"] = 256
            self.config["SPIFLASH_SECTOR_SIZE"] = 0x10000
            self.flash_boot_address = 0x50000
            self.register_rom(self.spiflash.bus, 16*1024*1024)
            self.csr_devices.append("spiflash")


class MiniSoC(BaseSoC):
    mem_map = {
        "ethmac": 0x30000000,  # (shadow @0xb0000000)
    }
    mem_map.update(BaseSoC.mem_map)

    def __init__(self, *args, ethmac_nrxslots=2, ethmac_ntxslots=2, **kwargs):
        BaseSoC.__init__(self, *args, **kwargs)

        self.csr_devices += ["ethphy", "ethmac"]
        self.interrupt_devices.append("ethmac")

        # SFP1 is connected to MicroTCA in-crate Ethernet by default
        self.comb += self.platform.request("sfp_tx_disable", 1).eq(0)
        self.submodules.ethphy = KU_1000BASEX(
           self.platform.request("gth_clk200"),
           self.platform.request("sfp", 1),
           self.clk_freq)
        self.submodules.ethmac = LiteEthMAC(phy=self.ethphy, dw=32, interface="wishbone",
                                            nrxslots=ethmac_nrxslots, ntxslots=ethmac_ntxslots)
        ethmac_len = (ethmac_nrxslots + ethmac_ntxslots) * 0x800
        self.add_wb_slave(self.mem_map["ethmac"], ethmac_len, self.ethmac.bus)
        self.add_memory_region("ethmac", self.mem_map["ethmac"] | self.shadow_base,
                               ethmac_len)
        self.crg.cd_sys.clk.attr.add("keep")
        self.ethphy.cd_eth_rx.clk.attr.add("keep")
        self.ethphy.cd_eth_tx.clk.attr.add("keep")
        self.platform.add_period_constraint(self.ethphy.cd_eth_rx.clk, 1e9/125e6)
        self.platform.add_period_constraint(self.ethphy.cd_eth_tx.clk, 1e9/125e6)
        self.platform.add_false_path_constraints(
            self.crg.cd_sys.clk,
            self.ethphy.cd_eth_rx.clk,
            self.ethphy.cd_eth_tx.clk)


def soc_sayma_amc_args(parser):
    soc_sdram_args(parser)
    parser.add_argument("--hw-rev", default=None,
                        help="Sayma AMC hardware revision: v1.0/v2.0")


def soc_sayma_amc_argdict(args):
    r = soc_sdram_argdict(args)
    r["hw_rev"] = args.hw_rev
    return r


def main():
    parser = argparse.ArgumentParser(description="MiSoC port to the Sayma AMC")
    builder_args(parser)
    soc_sayma_amc_args(parser)
    parser.add_argument("--with-ethernet", action="store_true",
                        help="enable Ethernet support")
    args = parser.parse_args()

    cls = MiniSoC if args.with_ethernet else BaseSoC
    soc = cls(**soc_sayma_amc_argdict(args))
    builder = Builder(soc, **builder_argdict(args))
    builder.build()


if __name__ == "__main__":
    main()
