#!/usr/bin/env python3

#
# This file is based on LiteX-Boards Digilent Genesys 2 target.
#
# Copyright (c) 2019 Florent Kermarrec <florent@enjoy-digital.fr>
# Copyright (c) 2023 Mikolaj Sowinski <msowinski@technosystem.com.pl>
# SPDX-License-Identifier: BSD-2-Clause

import argparse

from migen import *
from migen.genlib.resetsync import AsyncResetSynchronizer
from migen.build.platforms import digilent_genesys2

from misoc.cores.sdram_settings import MT41J256M16
from misoc.cores.sdram_phy import k7ddrphy
from misoc.cores import spi_flash, icap
from misoc.cores.liteeth_mini.phy.s7rgmii import LiteEthPHYRGMII
from misoc.cores.liteeth_mini.mac import LiteEthMAC
from misoc.integration.soc_sdram import *
from misoc.integration.builder import *
from misoc.interconnect.csr import *


class _SysCRG(Module):
    def __init__(self, platform):
        self.clock_domains.cd_sys = ClockDomain()
        self.clock_domains.cd_sys4x = ClockDomain(reset_less=True)
        self.clock_domains.cd_clk200 = ClockDomain()

        clk200 = platform.request("clk200")
        clk200_se = Signal()
        self.specials += Instance("IBUFDS", i_I=clk200.p, i_IB=clk200.n, o_O=clk200_se)

        rst_n = platform.request("cpu_reset_n")

        pll_locked = Signal()
        pll_fb = Signal()
        pll_sys = Signal()
        pll_sys4x = Signal()
        pll_clk200 = Signal()
        self.specials += [
            Instance("PLLE2_BASE",
                     p_STARTUP_WAIT="FALSE", o_LOCKED=pll_locked,

                     # VCO @ 1GHz
                     p_REF_JITTER1=0.01, p_CLKIN1_PERIOD=5.0,
                     p_CLKFBOUT_MULT=5, p_DIVCLK_DIVIDE=1,
                     i_CLKIN1=clk200_se, i_CLKFBIN=pll_fb, o_CLKFBOUT=pll_fb,

                     # 125MHz
                     p_CLKOUT0_DIVIDE=8, p_CLKOUT0_PHASE=0.0, o_CLKOUT0=pll_sys,

                     # 500MHz
                     p_CLKOUT1_DIVIDE=2, p_CLKOUT1_PHASE=0.0, o_CLKOUT1=pll_sys4x,

                     # 200MHz
                     p_CLKOUT2_DIVIDE=5, p_CLKOUT2_PHASE=0.0, o_CLKOUT2=pll_clk200,

                     p_CLKOUT3_DIVIDE=2, p_CLKOUT3_PHASE=0.0, #o_CLKOUT3=,

                     p_CLKOUT4_DIVIDE=4, p_CLKOUT4_PHASE=0.0, #o_CLKOUT4=
            ),
            Instance("BUFG", i_I=pll_sys, o_O=self.cd_sys.clk),
            Instance("BUFG", i_I=pll_sys4x, o_O=self.cd_sys4x.clk),
            Instance("BUFG", i_I=pll_clk200, o_O=self.cd_clk200.clk),
            AsyncResetSynchronizer(self.cd_sys, ~pll_locked | ~rst_n),
            AsyncResetSynchronizer(self.cd_clk200, ~pll_locked | ~rst_n),
        ]

        reset_counter = Signal(4, reset=15)
        ic_reset = Signal(reset=1)
        self.sync.clk200 += \
            If(reset_counter != 0,
                reset_counter.eq(reset_counter - 1)
            ).Else(
                ic_reset.eq(0)
            )
        self.specials += Instance("IDELAYCTRL", i_REFCLK=ClockSignal("clk200"), i_RST=ic_reset)


class BaseSoC(SoCSDRAM):
    def __init__(self, fmc1_vadj, sdram_controller_type="minicon", clk_freq=125e6, **kwargs):
        platform = digilent_genesys2.Platform(fmc1_vadj)
        SoCSDRAM.__init__(self, platform,
                          clk_freq=clk_freq, cpu_reset_address=0xaf0000,
                          **kwargs)

        self.submodules.crg = _SysCRG(platform)

        self.submodules.ddrphy = k7ddrphy.K7DDRPHY(platform.request("ddram"))
        self.config["DDRPHY_WLEVEL"] = None
        sdram_module = MT41J256M16(self.clk_freq, "1:4")
        self.register_sdram(self.ddrphy, sdram_controller_type,
                            sdram_module.geom_settings, sdram_module.timing_settings)
        self.csr_devices.append("ddrphy")

        if not self.integrated_rom_size:
            spiflash_pads = platform.request("spiflash")
            spiflash_pads.clk = Signal()
            self.specials += Instance("STARTUPE2",
                                      i_CLK=0, i_GSR=0, i_GTS=0, i_KEYCLEARB=0, i_PACK=0,
                                      i_USRCCLKO=spiflash_pads.clk, i_USRCCLKTS=0, i_USRDONEO=1, i_USRDONETS=1)
            self.submodules.spiflash = spi_flash.SpiFlash(
                spiflash_pads, dummy=8, div=4,
                endianness=self.cpu.endianness, dw=self.cpu_dw)
            self.config["SPIFLASH_PAGE_SIZE"] = 256
            self.config["SPIFLASH_SECTOR_SIZE"] = 0x10000
            self.flash_boot_address = 0xb40000
            self.register_rom(self.spiflash.bus, 16*1024*1024)
            self.csr_devices.append("spiflash")
        self.submodules.icap = icap.ICAP("7series")
        self.csr_devices.append("icap")


class MiniSoC(BaseSoC):
    mem_map = {
        "ethmac": 0x30000000,  # (shadow @0xb0000000)
    }
    mem_map.update(BaseSoC.mem_map)

    def __init__(self, *args, ethmac_nrxslots=2, ethmac_ntxslots=2, **kwargs):
        BaseSoC.__init__(self, *args, **kwargs)

        self.csr_devices += ["ethphy", "ethmac"]
        self.interrupt_devices.append("ethmac")

        eth_clocks = self.platform.request("eth_clocks")
        eth_pads = self.platform.request("eth")
        self.comb += eth_pads.rst_n.eq(1)
        self.submodules.ethphy = LiteEthPHYRGMII(eth_clocks, eth_pads)
        self.platform.add_period_constraint(self.ethphy.crg.cd_eth_tx.clk, 8.)
        self.platform.add_period_constraint(self.ethphy.crg.cd_eth_rx.clk, 8.)
        self.submodules.ethmac = LiteEthMAC(phy=self.ethphy, dw=self.cpu_dw, interface="wishbone",
                                            endianness=self.cpu.endianness,
                                            nrxslots=ethmac_nrxslots, ntxslots=ethmac_ntxslots)
        ethmac_len = (ethmac_nrxslots + ethmac_ntxslots) * 0x800
        self.add_wb_slave(self.mem_map["ethmac"], ethmac_len, self.ethmac.bus)
        self.add_memory_region("ethmac", self.mem_map["ethmac"] | self.shadow_base,
                               ethmac_len)
        
        self.platform.add_false_path_constraints(
            self.crg.cd_sys.clk,
            self.ethphy.crg.cd_eth_tx.clk, eth_clocks.rx)


def main():
    parser = argparse.ArgumentParser(description="MiSoC port to the Digilent Genesys2")
    builder_args(parser)
    soc_sdram_args(parser)
    parser.add_argument("--with-ethernet", action="store_true",
                        help="enable Ethernet support")
    args = parser.parse_args()

    cls = MiniSoC if args.with_ethernet else BaseSoC
    soc = cls(**soc_sdram_argdict(args)(args))
    builder = Builder(soc, **builder_argdict(args))
    builder.build()


if __name__ == "__main__":
    main()
