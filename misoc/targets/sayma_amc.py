#!/usr/bin/env python3

import argparse

from migen import *
from migen.genlib.resetsync import AsyncResetSynchronizer
from migen.genlib.io import *
from migen.build.platforms.sinara import sayma_amc

from misoc.cores.sdram_settings import MT41J256M16
from misoc.cores.sdram_phy import kusddrphy
from misoc.cores import spi_flash
from misoc.cores.liteeth_mini.phy.rgmii import LiteEthPHYRGMII
from misoc.cores.liteeth_mini.mac import LiteEthMAC
from misoc.integration.soc_sdram import *
from misoc.integration.builder import *


class _CRG(Module):
    def __init__(self, platform, with_ethernet):
        self.clock_domains.cd_sys = ClockDomain()
        self.clock_domains.cd_sys4x = ClockDomain(reset_less=True)
        self.clock_domains.cd_sys4x_dqs = ClockDomain(reset_less=True)
        self.clock_domains.cd_clk200 = ClockDomain()
        if with_ethernet:
            self.clock_domains.cd_eth_rx = ClockDomain()
            self.clock_domains.cd_eth_tx = ClockDomain()

        clk50 = platform.request("clk50")

        clk50_buffered = Signal()
        pll_locked = Signal()
        pll_fb = Signal()
        pll_sys = Signal()
        pll_sys4x = Signal()
        pll_sys4x_dqs = Signal()
        pll_clk200 = Signal()
        pll_eth_txclk = Signal()
        self.specials += [
            Instance("BUFG", i_I=clk50, o_O=clk50_buffered),
            Instance("PLLE2_BASE", name="crg_main_mmcm",
                p_STARTUP_WAIT="FALSE", o_LOCKED=pll_locked,

                # VCO @ 1GHz
                p_REF_JITTER1=0.01, p_CLKIN1_PERIOD=20.0,
                p_CLKFBOUT_MULT=20, p_DIVCLK_DIVIDE=1,
                i_CLKIN1=clk50_buffered, i_CLKFBIN=pll_fb, o_CLKFBOUT=pll_fb,

                # 125MHz
                p_CLKOUT0_DIVIDE=8, p_CLKOUT0_PHASE=0.0, o_CLKOUT0=pll_sys,

                # 500MHz
                p_CLKOUT1_DIVIDE=2, p_CLKOUT1_PHASE=0.0, o_CLKOUT1=pll_sys4x,

                # 200MHz
                p_CLKOUT2_DIVIDE=5, p_CLKOUT2_PHASE=0.0, o_CLKOUT2=pll_clk200,

                # 125MHz
                p_CLKOUT3_DIVIDE=8, p_CLKOUT3_PHASE=90.0, o_CLKOUT3=pll_eth_txclk,
            ),
            Instance("BUFG", i_I=pll_sys, o_O=self.cd_sys.clk),
            Instance("BUFG", i_I=pll_sys4x, o_O=self.cd_sys4x.clk),
            Instance("BUFG", i_I=pll_sys4x_dqs, o_O=self.cd_sys4x_dqs.clk),
            Instance("BUFG", i_I=pll_clk200, o_O=self.cd_clk200.clk),
            AsyncResetSynchronizer(self.cd_sys, ~pll_locked),
            AsyncResetSynchronizer(self.cd_clk200, ~pll_locked),
        ]

        reset_counter = Signal(4, reset=15)
        ic_reset = Signal(reset=1)
        self.sync.clk200 += \
            If(reset_counter != 0,
                reset_counter.eq(reset_counter - 1)
            ).Else(
                ic_reset.eq(0)
            )
        self.specials += Instance("IDELAYCTRL", p_SIM_DEVICE="ULTRASCALE",
            i_REFCLK=ClockSignal("clk200"), i_RST=ic_reset)

        if with_ethernet:
            eth_clocks = platform.request("eth_clocks")
            pll_eth_txclk_buffered = Signal()
            self.specials += [
                Instance("BUFG", i_I=pll_eth_txclk, o_O=pll_eth_txclk_buffered),
                DDROutput(0, 1, eth_clocks.tx, pll_eth_txclk_buffered)
            ]
            self.comb += [
                self.cd_eth_tx.clk.eq(self.cd_sys.clk),
                self.cd_eth_tx.rst.eq(self.cd_sys.rst)
            ]

            rx_clock_buffered = Signal()
            eth_pll_locked = Signal()
            eth_pll_fb = Signal()
            eth_pll_rx = Signal()
            self.specials += [
                Instance("BUFG", i_I=eth_clocks.rx, o_O=rx_clock_buffered),
                Instance("PLLE2_BASE", name="crg_ethrx_mmcm",
                    p_STARTUP_WAIT="FALSE", o_LOCKED=eth_pll_locked,

                    # VCO @ 1GHz
                    p_REF_JITTER1=0.01, p_CLKIN1_PERIOD=8.0,
                    p_CLKFBOUT_MULT=8, p_DIVCLK_DIVIDE=1,
                    i_CLKIN1=rx_clock_buffered, i_CLKFBIN=eth_pll_fb, o_CLKFBOUT=eth_pll_fb,

                    # 125MHz
                    p_CLKOUT0_DIVIDE=8, p_CLKOUT0_PHASE=135.0, o_CLKOUT0=eth_pll_rx
                ),
                Instance("BUFG", i_I=eth_pll_rx, o_O=self.cd_eth_rx.clk),
                AsyncResetSynchronizer(self.cd_eth_rx, ~eth_pll_locked),
            ]

            platform.add_platform_command("set_property CLOCK_DEDICATED_ROUTE BACKBONE [get_nets {rxc}]",
                rxc=rx_clock_buffered)

            self.cd_eth_rx.clk.attr.add("keep")
            platform.add_period_constraint(self.cd_eth_rx.clk, 8.0)
            platform.add_false_path_constraints(self.cd_sys.clk, self.cd_eth_rx.clk)


class BaseSoC(SoCSDRAM):
    def __init__(self, sdram="ddram_64", sdram_controller_type="minicon", clock_ethernet=False, **kwargs):
        platform = sayma_amc.Platform()
        SoCSDRAM.__init__(self, platform, clk_freq=125*1000000,
                          **kwargs)

        self.submodules.crg = _CRG(platform, clock_ethernet)
        self.crg.cd_sys.clk.attr.add("keep")
        platform.add_period_constraint(self.crg.cd_sys.clk, 8.0)

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
        BaseSoC.__init__(self, clock_ethernet=True, *args, **kwargs)

        self.csr_devices += ["ethphy", "ethmac"]
        self.interrupt_devices.append("ethmac")

        eth = self.platform.request("eth_rgmii")
        self.submodules.ethphy = LiteEthPHYRGMII(eth)
        self.comb += eth.mdc.eq(0)
        self.submodules.ethmac = LiteEthMAC(phy=self.ethphy, dw=32, interface="wishbone",
                                            nrxslots=ethmac_nrxslots, ntxslots=ethmac_ntxslots)
        ethmac_len = (ethmac_nrxslots + ethmac_ntxslots) * 0x800
        self.add_wb_slave(self.mem_map["ethmac"], ethmac_len, self.ethmac.bus)
        self.add_memory_region("ethmac", self.mem_map["ethmac"] | self.shadow_base,
                               ethmac_len)



def main():
    parser = argparse.ArgumentParser(description="MiSoC port to the Sayma AMC")
    builder_args(parser)
    soc_sdram_args(parser)
    parser.add_argument("--with-ethernet", action="store_true",
                        help="enable Ethernet support")
    args = parser.parse_args()

    cls = MiniSoC if args.with_ethernet else BaseSoC
    soc = cls(**soc_sdram_argdict(args))
    builder = Builder(soc, **builder_argdict(args))
    builder.build()


if __name__ == "__main__":
    main()
