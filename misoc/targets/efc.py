#!/usr/bin/env python3

import argparse

from migen import *
from migen.genlib.resetsync import AsyncResetSynchronizer
from migen.genlib.cdc import MultiReg
from migen.build.platforms.sinara import efc

from misoc.cores.sdram_settings import MT41K256M16
from misoc.cores.sdram_phy import a7ddrphy
from misoc.cores import spi_flash, icap
from misoc.cores.a7_gtp import *
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


class ClockSwitchFSM(Module):
    def __init__(self):
        self.i_clk_sw = Signal()

        self.o_clk_sw = Signal()
        self.o_reset = Signal()

        ###

        i_switch = Signal()
        o_switch = Signal()
        reset = Signal()

        # at 125MHz bootstrap cd, will get around 0.5ms
        delay_counter = Signal(16, reset=0xFFFF)

        # register to prevent glitches
        self.sync.bootstrap += [
            self.o_clk_sw.eq(o_switch),
            self.o_reset.eq(reset),
        ]

        self.o_clk_sw.attr.add("no_retiming")
        self.o_reset.attr.add("no_retiming")
        self.i_clk_sw.attr.add("no_retiming")
        i_switch.attr.add("no_retiming")

        self.specials += MultiReg(self.i_clk_sw, i_switch, "bootstrap")

        fsm = ClockDomainsRenamer("bootstrap")(FSM(reset_state="START"))

        self.submodules += fsm

        fsm.act("START",
            If(i_switch & ~o_switch,
                NextState("RESET_START"))
        )
        
        fsm.act("RESET_START",
            reset.eq(1),
            If(delay_counter == 0,
                NextValue(delay_counter, 0xFFFF),
                NextState("CLOCK_SWITCH")
            ).Else(
                NextValue(delay_counter, delay_counter-1),
            )
        )

        fsm.act("CLOCK_SWITCH",
            reset.eq(1),
            NextValue(o_switch, 1),
            NextValue(delay_counter, delay_counter-1),
            If(delay_counter == 0,
                NextState("START"))
        )


class _RtioSysCRG(Module, AutoCSR):
    def __init__(self, platform):
        self.clock_domains.cd_sys = ClockDomain()
        self.clock_domains.cd_sys4x = ClockDomain(reset_less=True)
        self.clock_domains.cd_sys4x_dqs = ClockDomain(reset_less=True)
        self.clock_domains.cd_clk200 = ClockDomain()

        # for FSM only
        self.clock_domains.cd_bootstrap = ClockDomain(reset_less=True)
        self.switch_done = CSRStatus()

        self._configured = False

        # bootstrap clock
        clk125 = platform.request("gtp_clk")
        platform.add_period_constraint(clk125, 8.)
        self.clk125_buf = Signal()
        self.clk125_div2 = Signal()
        self.specials += Instance("IBUFDS_GTE2",
            i_CEB=0,
            i_I=clk125.p, i_IB=clk125.n,
            o_O=self.clk125_buf,
            o_ODIV2=self.clk125_div2)

        self.submodules.clk_sw_fsm = ClockSwitchFSM()

        pll_clk200 = Signal()
        pll_clk125 = Signal()
        pll_fb = Signal()
        self.pll_locked = Signal()
        self.specials += [
            Instance("PLLE2_BASE",
                p_CLKIN1_PERIOD=16.0,
                i_CLKIN1=self.clk125_div2,

                i_CLKFBIN=pll_fb,
                o_CLKFBOUT=pll_fb,
                o_LOCKED=self.pll_locked,

                # VCO @ 1GHz
                p_CLKFBOUT_MULT=16, p_DIVCLK_DIVIDE=1,

                # 200MHz for IDELAYCTRL
                p_CLKOUT0_DIVIDE=5, p_CLKOUT0_PHASE=0.0, o_CLKOUT0=pll_clk200,
                # 125MHz for bootstrap
                p_CLKOUT1_DIVIDE=8, p_CLKOUT1_PHASE=0.0, o_CLKOUT1=pll_clk125
            ),
            Instance("BUFG", i_I=pll_clk125, o_O=self.cd_bootstrap.clk),
            Instance("BUFG", i_I=pll_clk200, o_O=self.cd_clk200.clk),
            AsyncResetSynchronizer(self.cd_clk200, ~self.pll_locked),
            MultiReg(self.clk_sw_fsm.o_clk_sw, self.switch_done.status)
        ]

        platform.add_false_path_constraints(self.cd_sys.clk, 
            self.clk125_buf, self.cd_bootstrap.clk, pll_clk125)

        reset_counter = Signal(4, reset=15)
        ic_reset = Signal(reset=1)
        self.sync.clk200 += \
            If(reset_counter != 0,
                reset_counter.eq(reset_counter - 1)
            ).Else(
                ic_reset.eq(0)
            )
        self.specials += Instance("IDELAYCTRL", i_REFCLK=ClockSignal("clk200"), i_RST=ic_reset)

    def configure(self, main_clk, clk_sw=None):
        # allow configuration of the MMCME2, depending on clock source
        # if using RtioSysCRG, this function *must* be called
        self._configured = True

        mmcm_fb_in = Signal()
        mmcm_fb_out = Signal()
        mmcm_locked = Signal()
        mmcm_sys = Signal()
        mmcm_sys4x = Signal()
        mmcm_sys4x_dqs = Signal()
        self.specials += [
            Instance("MMCME2_ADV",
                p_CLKIN1_PERIOD=8.0,
                i_CLKIN1=main_clk,
                p_CLKIN2_PERIOD=8.0,
                i_CLKIN2=self.cd_bootstrap.clk,

                i_CLKINSEL=self.clk_sw_fsm.o_clk_sw,
                i_RST=self.clk_sw_fsm.o_reset,

                i_CLKFBIN=mmcm_fb_in,
                o_CLKFBOUT=mmcm_fb_out,
                o_LOCKED=mmcm_locked,

                # VCO @ 1GHz with MULT=8
                p_CLKFBOUT_MULT_F=8, p_DIVCLK_DIVIDE=1,

                # 125MHz
                p_CLKOUT0_DIVIDE_F=8, p_CLKOUT0_PHASE=0.0, o_CLKOUT0=mmcm_sys,

                # 500MHz. Must be more than 400MHz as per DDR3 specs.
                p_CLKOUT1_DIVIDE=2, p_CLKOUT1_PHASE=0.0, o_CLKOUT1=mmcm_sys4x,
                p_CLKOUT2_DIVIDE=2, p_CLKOUT2_PHASE=90.0, o_CLKOUT2=mmcm_sys4x_dqs,
            ),
            Instance("BUFG", i_I=mmcm_sys, o_O=self.cd_sys.clk),
            Instance("BUFG", i_I=mmcm_sys4x, o_O=self.cd_sys4x.clk),
            Instance("BUFG", i_I=mmcm_sys4x_dqs, o_O=self.cd_sys4x_dqs.clk),
            Instance("BUFG", i_I=mmcm_fb_out, o_O=mmcm_fb_in),
        ]
        # reset if MMCM or PLL loses lock or when switching
        self.submodules += AsyncResetSynchronizerBUFG(self.cd_sys, 
            ~self.pll_locked | ~mmcm_locked | self.clk_sw_fsm.o_reset)

        # allow triggering the clock switch through either CSR,
        # or a different event, e.g. tx_init.done
        if clk_sw is not None:
            self.comb += self.clk_sw_fsm.i_clk_sw.eq(clk_sw)
        else:
            self.clock_sel = CSRStorage()
            self.comb += self.clk_sw_fsm.i_clk_sw.eq(self.clock_sel.storage)

    def do_finalize(self):
        if not self._configured:
            raise FinalizeError("RtioSysCRG must be configured")
        

class _SysCRG(Module):
    def __init__(self, platform):
        self.clock_domains.cd_sys = ClockDomain()
        self.clock_domains.cd_sys4x = ClockDomain(reset_less=True)
        self.clock_domains.cd_sys4x_dqs = ClockDomain(reset_less=True)
        self.clock_domains.cd_clk200 = ClockDomain()

        clk125 = platform.request("gtp_clk")
        platform.add_period_constraint(clk125, 8.)
        self.clk125_buf = Signal()
        self.clk125_div2 = Signal()
        self.specials += Instance("IBUFDS_GTE2",
            i_CEB=0,
            i_I=clk125.p, i_IB=clk125.n,
            o_O=self.clk125_buf,
            o_ODIV2=self.clk125_div2)

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
                p_CLKIN1_PERIOD=16.0,
                i_CLKIN1=self.clk125_div2,

                i_CLKFBIN=mmcm_fb,
                o_CLKFBOUT=mmcm_fb,
                o_LOCKED=mmcm_locked,

                # VCO @ 1GHz with MULT=16
                p_CLKFBOUT_MULT_F=14.5, p_DIVCLK_DIVIDE=1,

                # ~125MHz
                p_CLKOUT0_DIVIDE_F=8.0, p_CLKOUT0_PHASE=0.0, o_CLKOUT0=mmcm_sys,

                # ~500MHz. Must be more than 400MHz as per DDR3 specs.
                p_CLKOUT1_DIVIDE=2, p_CLKOUT1_PHASE=0.0, o_CLKOUT1=mmcm_sys4x,
                p_CLKOUT2_DIVIDE=2, p_CLKOUT2_PHASE=90.0, o_CLKOUT2=mmcm_sys4x_dqs,
            ),
            Instance("PLLE2_BASE",
                p_CLKIN1_PERIOD=16.0,
                i_CLKIN1=self.clk125_div2,

                i_CLKFBIN=pll_fb,
                o_CLKFBOUT=pll_fb,
                o_LOCKED=pll_locked,

                # VCO @ 1GHz
                p_CLKFBOUT_MULT=16, p_DIVCLK_DIVIDE=1,

                # 200MHz for IDELAYCTRL
                p_CLKOUT0_DIVIDE=5, p_CLKOUT0_PHASE=0.0, o_CLKOUT0=pll_clk200,
            ),
            Instance("BUFG", i_I=mmcm_sys, o_O=self.cd_sys.clk),
            Instance("BUFG", i_I=mmcm_sys4x, o_O=self.cd_sys4x.clk),
            Instance("BUFG", i_I=mmcm_sys4x_dqs, o_O=self.cd_sys4x_dqs.clk),
            Instance("BUFG", i_I=pll_clk200, o_O=self.cd_clk200.clk),
            AsyncResetSynchronizer(self.cd_clk200, ~pll_locked),
        ]
        self.submodules += AsyncResetSynchronizerBUFG(self.cd_sys, ~mmcm_locked),

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
    def __init__(self, sdram_controller_type="minicon", rtio_sys_merge=False, 
                 clk_freq=None, **kwargs):
        platform = efc.Platform()

        if not clk_freq:
            clk_freq = 125e6 if rtio_sys_merge else 125e6*14.5/16

        SoCSDRAM.__init__(self, platform, cpu_reset_address=0x400000, clk_freq=clk_freq, **kwargs)

        if rtio_sys_merge:
            self.submodules.crg = _RtioSysCRG(platform)
            self.csr_devices.append("crg")
        else:
            self.submodules.crg = _SysCRG(platform)

        self.platform.add_period_constraint(self.crg.cd_sys.clk, 1e9/self.clk_freq)

        self.submodules.ddrphy = a7ddrphy.A7DDRPHY(platform.request("ddram"))
        sdram_module = MT41K256M16(self.clk_freq, "1:4")
        self.register_sdram(self.ddrphy, sdram_controller_type,
                            sdram_module.geom_settings, sdram_module.timing_settings)
        self.csr_devices.append("ddrphy")

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


def main():
    parser = argparse.ArgumentParser(description="MiSoC port to Sinara EEM FMC Carrier")
    builder_args(parser)
    soc_sdram_args(parser)
    args = parser.parse_args()

    soc = BaseSoC(**soc_sdram_argdict(args))
    builder = Builder(soc, **builder_argdict(args))
    builder.build()


if __name__ == "__main__":
    main()
