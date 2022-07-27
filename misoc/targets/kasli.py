#!/usr/bin/env python3

import argparse

from migen import *
from migen.genlib.resetsync import AsyncResetSynchronizer
from migen.genlib.cdc import MultiReg
from migen.build.platforms.sinara import kasli

from misoc.cores.sdram_settings import MT41K256M16
from misoc.cores.sdram_phy import a7ddrphy
from misoc.cores import virtual_leds, spi_flash, icap
from misoc.cores.a7_gtp import *
from misoc.cores.liteeth_mini.phy.a7_1000basex import A7_1000BASEX
from misoc.cores.liteeth_mini.mac import LiteEthMAC
from misoc.integration.soc_sdram import *
from misoc.integration.builder import *
from misoc.interconnect.csr import *


class AsyncResetSynchronizerBUFG(Module):
    def __init__(self, cd, async_reset):
        if not hasattr(async_reset, "attr"):
            i, async_reset = async_reset, Signal()
            self.comb += async_reset.eq(i)
        rst_meta = Signal()
        rst_unbuf = Signal()
        self.specials += [
            Instance("FDPE", p_INIT=1, i_D=0, i_PRE=async_reset,
                i_CE=1, i_C=cd.clk, o_Q=rst_meta,
                attr={"async_reg", "ars_ff1"}),
            Instance("FDPE", p_INIT=1, i_D=rst_meta, i_PRE=async_reset,
                i_CE=1, i_C=cd.clk, o_Q=rst_unbuf,
                attr={"async_reg", "ars_ff2"}),
            Instance("BUFG", i_I=rst_unbuf, o_O=cd.rst)
        ]


class _CRG(Module, AutoCSR):
    def __init__(self, platform, freq=125.0e6):
        self.clock_domains.cd_sys = ClockDomain()
        self.clock_domains.cd_sys4x = ClockDomain(reset_less=True)
        self.clock_domains.cd_sys4x_dqs = ClockDomain(reset_less=True)
        self.clock_domains.cd_clk200 = ClockDomain()

        self.clock_sel = CSRStorage()
        self.pll_locked = CSRStatus()
        self.mmcm_locked = CSRStatus()

        # old "sys" clock, now bootstrap
        bootstrap = platform.request("clk125_gtp")
        platform.add_period_constraint(bootstrap, 8.)
        bootstrap_buf = Signal()
        bootstrap_div2 = Signal()
        self.specials += Instance("IBUFDS_GTE2",
            i_CEB=0,
            i_I=bootstrap.p, i_IB=bootstrap.n,
            o_O=bootstrap_buf,
            o_ODIV2=bootstrap_div2)

        # ex-rtio clock
        if platform.hw_rev == "v2.0":
            si5324_out = platform.request("cdr_clk_clean_fabric")
        else:
            si5324_out = platform.request("si5324_clkout_fabric")

        if freq == 125.0e6:
            si5324_period = 8.
            pll_mult = 8
        elif freq == 100.0e6:
            si5324_period = 10.
            pll_mult = 10
        else:
            raise NotImplementedError
         
        si5324_buf = Signal()

        platform.add_period_constraint(si5324_out, si5324_period)

        self.specials += [
            Instance("IBUFGDS",
                p_DIFF_TERM="TRUE", p_IBUF_LOW_PWR="FALSE",
                i_I=si5324_out.p, i_IB=si5324_out.n, o_O=si5324_buf),
        ]

        # required for qpll
        self.clk125_buf = bootstrap_buf

        mmcm_locked = Signal()
        mmcm_fb = Signal()
        mmcm_sys = Signal()
        mmcm_sys4x = Signal()
        mmcm_sys4x_dqs = Signal()
        pll_locked = Signal()
        pll_fb = Signal()
        pll_clk200 = Signal()
        self.specials += [
            Instance("MMCME2_BASE",
                p_CLKIN1_PERIOD=si5324_period,
                i_CLKIN1=si5324_buf,

                i_CLKFBIN=mmcm_fb,
                o_CLKFBOUT=mmcm_fb,
                o_LOCKED=mmcm_locked,

                # VCO @ 1GHz with MULT=8 (125MHz - Kasli 2.0)
                # VCO @ 800MHz (100MHz - Kasli 1.0/1.1)
                p_CLKFBOUT_MULT_F=8, p_DIVCLK_DIVIDE=1,

                # ~125MHz (or 100MHz)
                p_CLKOUT0_DIVIDE_F=8.0, p_CLKOUT0_PHASE=0.0, o_CLKOUT0=mmcm_sys,

                # ~500MHz (or 400MHz). Must be more than 400MHz as per DDR3 specs.
                p_CLKOUT1_DIVIDE=2, p_CLKOUT1_PHASE=0.0, o_CLKOUT1=mmcm_sys4x,
                p_CLKOUT2_DIVIDE=2, p_CLKOUT2_PHASE=90.0, o_CLKOUT2=mmcm_sys4x_dqs,
            ),
            Instance("PLLE2_BASE",
                p_CLKIN1_PERIOD=si5324_period,
                i_CLKIN1=si5324_buf,

                i_CLKFBIN=pll_fb,
                o_CLKFBOUT=pll_fb,
                o_LOCKED=pll_locked,

                # VCO @ 1GHz (multiplier depends on frequency)
                p_CLKFBOUT_MULT=pll_mult*2, p_DIVCLK_DIVIDE=1,

                # 200MHz for IDELAYCTRL
                p_CLKOUT0_DIVIDE=5, p_CLKOUT0_PHASE=0.0, o_CLKOUT0=pll_clk200,
            ),
            Instance("BUFGMUX", 
                i_I0=bootstrap_div2, 
                i_I1=mmcm_sys, 
                o_O=self.cd_sys.clk, 
                i_S=self.clock_sel.storage
            ),
            Instance("BUFG", i_I=mmcm_sys4x, o_O=self.cd_sys4x.clk),
            Instance("BUFG", i_I=mmcm_sys4x_dqs, o_O=self.cd_sys4x_dqs.clk),
            Instance("BUFG", i_I=pll_clk200, o_O=self.cd_clk200.clk),
            AsyncResetSynchronizer(self.cd_clk200, ~pll_locked),
            MultiReg(pll_locked, self.pll_locked.status),
            MultiReg(mmcm_locked, self.mmcm_locked.status)
        ]
        
        self.submodules += AsyncResetSynchronizerBUFG(self.cd_sys, ~mmcm_locked),

        platform.add_false_path_constraints(
            bootstrap_buf,
            self.cd_sys.clk, self.cd_sys4x.clk, self.cd_sys4x_dqs.clk, self.cd_clk200.clk)

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
    def __init__(self, sdram_controller_type="minicon", hw_rev=None,
                 **kwargs):
        if hw_rev is None:
            hw_rev = "v1.0"
        platform = kasli.Platform(hw_rev=hw_rev)

        SoCSDRAM.__init__(self, platform, cpu_reset_address=0x400000,
                          **kwargs) 

        self.config["HW_REV"] = hw_rev

        self.submodules.crg = _CRG(platform, self.clk_freq)

        self.csr_devices.append("crg")

        self.platform.add_period_constraint(self.crg.cd_sys.clk, 1e9/self.clk_freq)

        self.submodules.ddrphy = a7ddrphy.A7DDRPHY(platform.request("ddram"))
        sdram_module = MT41K256M16(self.clk_freq, "1:4")
        self.register_sdram(self.ddrphy, sdram_controller_type,
                            sdram_module.geom_settings, sdram_module.timing_settings)
        self.csr_devices.append("ddrphy")

        if hw_rev == "v2.0":
            self.submodules.virtual_leds = virtual_leds.VirtualLeds()
            self.csr_devices.append("virtual_leds")

        if not self.integrated_rom_size:
            spiflash_pads = platform.request("spiflash2x")
            spiflash_pads.clk = Signal()
            self.specials += Instance("STARTUPE2",
                                      i_CLK=0, i_GSR=0, i_GTS=0, i_KEYCLEARB=0, i_PACK=0,
                                      i_USRCCLKO=spiflash_pads.clk, i_USRCCLKTS=0, i_USRDONEO=1, i_USRDONETS=1)
            self.submodules.spiflash = spi_flash.SpiFlash(
                spiflash_pads, dummy=5, div=2,
                endianness=self.cpu.endianness, dw=self.cpu_dw)
            self.config["SPIFLASH_PAGE_SIZE"] = 256
            self.config["SPIFLASH_SECTOR_SIZE"] = 0x10000
            self.flash_boot_address = 0x450000
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
        self.create_qpll()

        self.csr_devices += ["ethphy", "ethmac"]
        self.interrupt_devices.append("ethmac")

        sfp = self.platform.request("sfp", 0)
        self.submodules.ethphy = A7_1000BASEX(self.ethphy_qpll_channel, sfp, self.clk_freq)
        self.platform.add_period_constraint(self.ethphy.txoutclk, 16.)
        self.platform.add_period_constraint(self.ethphy.rxoutclk, 16.)
        self.platform.add_false_path_constraints(
            self.crg.cd_sys.clk,
            self.ethphy.txoutclk, self.ethphy.rxoutclk)

        if self.platform.hw_rev in ("v1.0", "v1.1"):
            sfp_ctl = self.platform.request("sfp_ctl", 0)
            if hasattr(sfp_ctl, "mod_present"):
                mod_present = sfp_ctl.mod_present
            else:
                mod_present = ~sfp_ctl.mod_present_n
            self.comb += [
                sfp_ctl.rate_select.eq(0),
                sfp_ctl.tx_disable.eq(0),
                sfp_ctl.led.eq(~sfp_ctl.los & ~sfp_ctl.tx_fault & mod_present &
                    self.ethphy.link_up),
            ]
        if self.platform.hw_rev == "v2.0":
            self.comb += self.virtual_leds.get(0).eq(self.ethphy.link_up)

        self.submodules.ethmac = LiteEthMAC(
                phy=self.ethphy, dw=self.cpu_dw, interface="wishbone",
                endianness=self.cpu.endianness, nrxslots=ethmac_nrxslots, ntxslots=ethmac_ntxslots)
        ethmac_len = (ethmac_nrxslots + ethmac_ntxslots) * 0x800
        self.add_wb_slave(self.mem_map["ethmac"], ethmac_len, self.ethmac.bus)
        self.add_memory_region("ethmac",
                self.mem_map["ethmac"] | self.shadow_base, ethmac_len)

    def create_qpll(self):
        qpll_settings = QPLLSettings(
            refclksel=0b001,
            fbdiv=4,
            fbdiv_45=5,
            refclk_div=1)
        qpll = QPLL(self.crg.clk125_buf, qpll_settings)
        self.submodules += qpll
        self.ethphy_qpll_channel = qpll.channels[0]


def soc_kasli_args(parser):
    soc_sdram_args(parser)
    parser.add_argument("--hw-rev", default=None,
                        help="Kasli hardware revision: v1.0/v1.1/v2.0 "
                             "(default: variant-dependent)")


def soc_kasli_argdict(args):
    r = soc_sdram_argdict(args)
    r["hw_rev"] = args.hw_rev
    return r


def main():
    parser = argparse.ArgumentParser(description="MiSoC port to Kasli")
    builder_args(parser)
    soc_kasli_args(parser)
    parser.add_argument("--with-ethernet", action="store_true",
                        help="enable Ethernet support")
    args = parser.parse_args()

    cls = MiniSoC if args.with_ethernet else BaseSoC
    soc = cls(**soc_kasli_argdict(args))
    builder = Builder(soc, **builder_argdict(args))
    builder.build()


if __name__ == "__main__":
    main()
