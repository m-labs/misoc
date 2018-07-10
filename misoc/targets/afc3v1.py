#!/usr/bin/env python3

import argparse

from migen import *
from migen.genlib.io import DifferentialInput
from migen.build.platforms import afc3v1
from migen.genlib.resetsync import AsyncResetSynchronizer

from misoc.cores.a7_gtp import *
from misoc.cores.liteeth_mini.phy.a7_1000basex import A7_1000BASEX
from misoc.cores.liteeth_mini.mac import LiteEthMAC
from misoc.cores import spi_flash

from misoc.cores.sdram_settings import MT41J512M8
from misoc.cores.sdram_phy import a7ddrphy
from misoc.integration.soc_sdram import *
from misoc.integration.builder import *
from misoc.interconnect.csr import AutoCSR, CSRStorage
from misoc.cores import gpio


class _CRG(Module):
    def __init__(self, platform):
        self.clock_domains.cd_sys = ClockDomain()
        self.clock_domains.cd_sys4x = ClockDomain(reset_less=True)
        self.clock_domains.cd_sys4x_dqs = ClockDomain(reset_less=True)
        self.clock_domains.cd_clk200 = ClockDomain()

        clk125 = platform.request("mgt113_clk0")
        platform.add_period_constraint(clk125, 8.)
        self.clk125_buf = Signal()
        clk125_div2 = Signal()
        self.specials += Instance("IBUFDS_GTE2",
                                  i_CEB=0,
                                  i_I=clk125.p, i_IB=clk125.n,
                                  o_O=self.clk125_buf,
                                  o_ODIV2=clk125_div2)

        self.mmcm_locked = mmcm_locked = Signal()
        mmcm_fb = Signal()
        mmcm_sys = Signal()
        mmcm_sys4x = Signal()
        mmcm_sys4x_dqs = Signal()
        mmcm_clk200 = Signal()
        self.specials += [
            Instance("MMCME2_BASE",
                p_CLKIN1_PERIOD=16.0,
                i_CLKIN1=clk125_div2,

                i_CLKFBIN=mmcm_fb,
                o_CLKFBOUT=mmcm_fb,
                o_LOCKED=mmcm_locked,

                # VCO @ 1GHz with MULT=16
                p_CLKFBOUT_MULT_F=16, p_DIVCLK_DIVIDE=1,

                # ~125MHz
                p_CLKOUT0_DIVIDE_F=8.0, p_CLKOUT0_PHASE=0.0, o_CLKOUT0=mmcm_sys,

                # ~500MHz. Must be more than 400MHz as per DDR3 specs.
                p_CLKOUT1_DIVIDE=2, p_CLKOUT1_PHASE=0.0, o_CLKOUT1=mmcm_sys4x,

                # ~200MHz for IDELAYCTRL. Datasheet specified tolerance +/- 10MHz.
                p_CLKOUT2_DIVIDE=5, p_CLKOUT2_PHASE=0.0, o_CLKOUT2=mmcm_clk200,

                p_CLKOUT3_DIVIDE=2, p_CLKOUT3_PHASE=90.0, o_CLKOUT3=mmcm_sys4x_dqs,
            ),
            Instance("BUFG", i_I=mmcm_sys, o_O=self.cd_sys.clk),
            Instance("BUFG", i_I=mmcm_sys4x, o_O=self.cd_sys4x.clk),
            Instance("BUFG", i_I=mmcm_sys4x_dqs, o_O=self.cd_sys4x_dqs.clk),
            Instance("BUFG", i_I=mmcm_clk200, o_O=self.cd_clk200.clk),
            AsyncResetSynchronizer(self.cd_sys, ~mmcm_locked),
            AsyncResetSynchronizer(self.cd_clk200, ~mmcm_locked),
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


class BaseSoC(SoCSDRAM, AutoCSR):
    mem_map = {
        "spiflash": 0x70000000
    }
    mem_map.update(SoCSDRAM.mem_map)

    def __init__(self, sdram_controller_type="minicon", with_spiflash=False, **kwargs):
        platform = afc3v1.Platform()

        SoCSDRAM.__init__(self, platform,
                          clk_freq=125000000,
                          **kwargs)

        self.submodules.crg = _CRG(platform)
        self.platform.add_period_constraint(self.crg.cd_sys.clk, 8.)

        self.submodules.ddrphy = a7ddrphy.A7DDRPHY(platform.request("ddram"))
        sdram_module = MT41J512M8(self.clk_freq, "1:4")
        self.register_sdram(self.ddrphy, sdram_controller_type,
                            sdram_module.geom_settings, sdram_module.timing_settings)
        self.csr_devices.append("ddrphy")

        self.submodules.si570_oen = gpio.GPIOIn(platform.request("si570_en", 0))
        self.csr_devices.append("si570_oen")

        if not self.integrated_rom_size or with_spiflash:
            spiflash_pads = platform.request("spiflash")
            spiflash_pads.clk = Signal()
            self.specials += Instance("STARTUPE2",
                                      i_CLK=0, i_GSR=0, i_GTS=0, i_KEYCLEARB=0, i_PACK=0,
                                      i_USRCCLKO=spiflash_pads.clk, i_USRCCLKTS=0, i_USRDONEO=1, i_USRDONETS=1)
            self.submodules.spiflash = spi_flash.SpiFlash(spiflash_pads, dummy=11, div=2)
            self.config["SPIFLASH_PAGE_SIZE"] = 256
            self.config["SPIFLASH_SECTOR_SIZE"] = 0x10000
            self.csr_devices.append("spiflash")

        if with_spiflash:
            self.add_wb_slave(self.mem_map["spiflash"], 16*1024*1024, self.spiflash.bus)

        if not self.integrated_rom_size:
            self.flash_boot_address = 0x350000
            self.register_rom(self.spiflash.bus, 16*1024*1024)


class MiniSoC(BaseSoC):
    mem_map = {
        "ethmac": 0x30000000,  # (shadow @0xb0000000)
    }
    mem_map.update(BaseSoC.mem_map)

    def __init__(self, *args, ethmac_nrxslots=2, ethmac_ntxslots=2, **kwargs):
        BaseSoC.__init__(self, *args, **kwargs)

        self.create_qpll()

        self.csr_devices += ["ethphy", "ethmac"]
        self.interrupt_devices.append("ethmac")

        self.submodules.ethphy = A7_1000BASEX(self.ethphy_qpll_channel,
                                              self.platform.request("mgt113", 3),
                                              self.clk_freq)
        self.platform.add_period_constraint(self.ethphy.txoutclk, 16.)
        self.platform.add_period_constraint(self.ethphy.rxoutclk, 16.)
        self.platform.add_false_path_constraints(
            self.crg.cd_sys.clk,
            self.ethphy.txoutclk, self.ethphy.rxoutclk)

        self.submodules.ethmac = LiteEthMAC(
            phy=self.ethphy, dw=32, interface="wishbone",
            nrxslots=2, ntxslots=2)
        ethmac_len = (ethmac_nrxslots + ethmac_ntxslots) * 0x800
        self.add_wb_slave(self.mem_map["ethmac"], ethmac_len, self.ethmac.bus)
        self.add_memory_region("ethmac",
                               self.mem_map["ethmac"] | self.shadow_base, ethmac_len)

    def create_qpll(self):
        qpll_settings = QPLLSettings(
            refclksel=0b111,
            fbdiv=4,
            fbdiv_45=5,
            refclk_div=1)
        qpll = QPLL(self.crg.clk125_buf, qpll_settings)
        self.submodules += qpll
        self.ethphy_qpll_channel = qpll.channels[0]


def soc_afc3v1_args(parser):
    soc_sdram_args(parser)
    parser.add_argument("--with-spi-flash", action="store_false",
                        help="enable SPI Flash support ")


def soc_afc3v1_argdict(args):
    r = soc_sdram_argdict(args)
    r["with_spiflash"] = args.with_spi_flash
    return r


def main():
    parser = argparse.ArgumentParser(description="MiSoC port to AFC 3v1")
    builder_args(parser)
    parser.add_argument("--with-ethernet", action="store_true",
                        help="enable Ethernet support")
    soc_afc3v1_args(parser)

    args = parser.parse_args()

    cls = MiniSoC if args.with_ethernet else BaseSoC
    soc = cls(**soc_afc3v1_argdict(args))
    builder = Builder(soc, **builder_argdict(args))
    builder.build()


if __name__ == "__main__":
    main()
