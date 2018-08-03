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
                attr={("LOC", "MMCME3_ADV_X1Y0")},
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
                attr={("LOC", "BUFGCE_DIV_X1Y0")},
                p_BUFGCE_DIVIDE=4,
                i_CE=1, i_I=pll_sys4x, o_O=self.cd_sys.clk),
            Instance("BUFGCE", name="main_bufgce",
                attr={("LOC", "BUFGCE_X1Y14")},
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
    def __init__(self, sdram="ddram_32", sdram_controller_type="minicon", **kwargs):
        platform = sayma_amc.Platform()
        SoCSDRAM.__init__(self, platform, clk_freq=125*1000000,
                          **kwargs)

        self.submodules.crg = _CRG(platform)
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


class _EthernetCRG(Module):
    def __init__(self, platform, cd_sys):
        self.clock_domains.cd_eth_rx = ClockDomain()
        self.clock_domains.cd_eth_tx = ClockDomain()

        eth_clocks = platform.request("eth_clocks")
        # Note: Sharing the main MMCM is not advisable due to the
        # BUFGCE_DIV phase alignment problem.
        ethtx_pll_fb = Signal()
        ethtx_pll_out = Signal()
        ethtx_pll_out_buffered = Signal()
        self.specials += [
            Instance("PLLE2_BASE", name="crg_ethtx_mmcm",
                attr={("LOC", "MMCME3_ADV_X1Y4")},
                p_STARTUP_WAIT="FALSE",

                # VCO @ 1GHz
                p_REF_JITTER1=0.01, p_CLKIN1_PERIOD=8.0,
                p_CLKFBOUT_MULT=8, p_DIVCLK_DIVIDE=1,
                i_CLKIN1=cd_sys.clk, i_CLKFBIN=ethtx_pll_fb, o_CLKFBOUT=ethtx_pll_fb,

                # 125MHz
                p_CLKOUT0_DIVIDE=8, p_CLKOUT0_PHASE=180.0, o_CLKOUT0=ethtx_pll_out
            ),
            Instance("BUFG", i_I=ethtx_pll_out, o_O=ethtx_pll_out_buffered),
            DDROutput(0, 1, eth_clocks.tx, ethtx_pll_out_buffered)
        ]
        self.comb += [
            self.cd_eth_tx.clk.eq(cd_sys.clk),
            self.cd_eth_tx.rst.eq(cd_sys.rst)
        ]

        rx_clock_buffered = Signal()
        ethrx_pll_locked = Signal()
        ethrx_pll_fb = Signal()
        ethrx_pll_out = Signal()
        self.specials += [
            Instance("BUFG", i_I=eth_clocks.rx, o_O=rx_clock_buffered),
            Instance("PLLE2_BASE", name="crg_ethrx_mmcm",
                attr={("LOC", "MMCME3_ADV_X1Y3")},
                p_STARTUP_WAIT="FALSE", o_LOCKED=ethrx_pll_locked,

                # VCO @ 1GHz
                p_REF_JITTER1=0.01, p_CLKIN1_PERIOD=8.0,
                p_CLKFBOUT_MULT=8, p_DIVCLK_DIVIDE=1,
                i_CLKIN1=rx_clock_buffered, i_CLKFBIN=ethrx_pll_fb, o_CLKFBOUT=ethrx_pll_fb,

                # 125MHz
                p_CLKOUT0_DIVIDE=8, p_CLKOUT0_PHASE=247.5, o_CLKOUT0=ethrx_pll_out
            ),
            Instance("BUFG", i_I=ethrx_pll_out, o_O=self.cd_eth_rx.clk),
            AsyncResetSynchronizer(self.cd_eth_rx, ~ethrx_pll_locked),
        ]

        platform.add_platform_command("set_property CLOCK_DEDICATED_ROUTE BACKBONE [get_nets {sysc}]",
            sysc=cd_sys.clk)
        platform.add_platform_command("set_property CLOCK_DEDICATED_ROUTE BACKBONE [get_nets {rxc}]",
            rxc=rx_clock_buffered)

        self.cd_eth_rx.clk.attr.add("keep")
        platform.add_period_constraint(self.cd_eth_rx.clk, 8.0)
        platform.add_false_path_constraints(cd_sys.clk, self.cd_eth_rx.clk)


class MiniSoC(BaseSoC):
    mem_map = {
        "ethmac": 0x30000000,  # (shadow @0xb0000000)
    }
    mem_map.update(BaseSoC.mem_map)

    def __init__(self, *args, ethmac_nrxslots=2, ethmac_ntxslots=2, **kwargs):
        BaseSoC.__init__(self, *args, **kwargs)

        self.submodules.ethcrg = _EthernetCRG(self.platform, self.crg.cd_sys)

        self.csr_devices += ["ethphy", "ethmac"]
        self.interrupt_devices.append("ethmac")

        eth = self.platform.request("eth")
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
