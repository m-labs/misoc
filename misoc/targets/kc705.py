#!/usr/bin/env python3

import argparse

from migen import *
from migen.build.generic_platform import *
from migen.genlib.resetsync import AsyncResetSynchronizer
from migen.genlib.cdc import MultiReg
from migen.build.platforms import kc705

from misoc.cores.sdram_settings import MT8JTF12864
from misoc.cores.sdram_phy import k7ddrphy
from misoc.cores import spi_flash, icap
from misoc.cores.liteeth_mini.phy import LiteEthPHY
from misoc.cores.liteeth_mini.mac import LiteEthMAC
from misoc.integration.soc_sdram import *
from misoc.integration.builder import *
from misoc.interconnect.csr import *


class ClockSwitchFSM(Module):
    def __init__(self):
        self.i_clk_sw = Signal()

        self.o_clk_sw = Signal()
        self.o_reset = Signal()

        ###

        i_switch = Signal()
        o_switch = Signal()
        reset = Signal()

        delay_counter = Signal(16, reset=0xFFFF)

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
                NextValue(delay_counter, 0xFFFF),
                NextState("START")
            ).Else(
                NextValue(delay_counter, delay_counter-1),
            )
        )


class _RtioSysCRG(Module, AutoCSR):
    def __init__(self, platform, bootstrap_freq=125e6):
        self.clock_domains.cd_sys = ClockDomain()
        self.clock_domains.cd_sys4x = ClockDomain(reset_less=True)
        self.clock_domains.cd_clk200 = ClockDomain()
        self.bootstrap_freq = bootstrap_freq

        # for FSM only
        self.clock_domains.cd_bootstrap = ClockDomain(reset_less=True)
        self.switch_done = CSRStatus()

        self._configured = False

        # bootstrap clock
        clk200 = platform.request("clk200")
        clk200_se = Signal()
        self.specials += Instance("IBUFDS", i_I=clk200.p, i_IB=clk200.n, o_O=clk200_se)

        self.platform = platform

        self.submodules.clk_sw_fsm = ClockSwitchFSM()

        pll_clk200 = Signal()
        pll_clk_bootstrap = Signal()
        pll_fb = Signal()
        pll_locked = Signal()
        if bootstrap_freq == 125e6 or bootstrap_freq == 100e6:
            clkout1_div = 1e9/bootstrap_freq
        else:
            raise ValueError("Only 100, 125MHz supported for bootstrap clock")
        self.specials += [
            Instance("PLLE2_BASE",
                p_CLKIN1_PERIOD=5.0,
                i_CLKIN1=clk200_se,

                i_CLKFBIN=pll_fb,
                o_CLKFBOUT=pll_fb,
                o_LOCKED=pll_locked,

                # VCO @ 1GHz
                p_CLKFBOUT_MULT=5, p_DIVCLK_DIVIDE=1,

                # 200MHz for IDELAYCTRL
                p_CLKOUT0_DIVIDE=5, p_CLKOUT0_PHASE=0.0, o_CLKOUT0=pll_clk200,
                # 125MHz/100MHz for bootstrap
                p_CLKOUT1_DIVIDE=clkout1_div, p_CLKOUT1_PHASE=0.0, o_CLKOUT1=pll_clk_bootstrap,
            ),
            Instance("BUFG", i_I=pll_clk_bootstrap, o_O=self.cd_bootstrap.clk),
            Instance("BUFG", i_I=pll_clk200, o_O=self.cd_clk200.clk),
            MultiReg(self.clk_sw_fsm.o_clk_sw, self.switch_done.status),
            AsyncResetSynchronizer(self.cd_clk200, ~pll_locked),
            AsyncResetSynchronizer(self.cd_bootstrap, ~pll_locked),
        ]

        self.platform.add_false_path_constraints(self.cd_sys.clk, 
            clk200_se, self.cd_bootstrap.clk, pll_clk_bootstrap)

        reset_counter = Signal(4, reset=15)
        ic_reset = Signal(reset=1)
        self.sync.clk200 += \
            If(reset_counter != 0,
                reset_counter.eq(reset_counter - 1)
            ).Else(
                ic_reset.eq(0)
            )
        self.specials += Instance("IDELAYCTRL", i_REFCLK=ClockSignal("clk200"), i_RST=ic_reset)

    def configure(self, main_clk, clk_sw=None, ext_async_rst=None):
        # allow configuration of the MMCME2, depending on clock source
        # if using RtioSysCRG, this function *must* be called
        self._configured = True

        mmcm_fb_in = Signal()
        mmcm_fb_out = Signal()
        mmcm_fb = Signal()
        self.mmcm_locked = Signal()

        mmcm_sys = Signal()
        mmcm_sys4x = Signal()
        clkin_period = 1e9/self.bootstrap_freq
        mult = 8 if self.bootstrap_freq == 125e6 else 12
        self.specials += [
            Instance("MMCME2_ADV",
                p_CLKIN1_PERIOD=clkin_period,
                i_CLKIN1=main_clk,
                p_CLKIN2_PERIOD=clkin_period,
                i_CLKIN2=self.cd_bootstrap.clk,

                i_CLKINSEL=self.clk_sw_fsm.o_clk_sw,
                i_RST=self.clk_sw_fsm.o_reset,

                i_CLKFBIN=mmcm_fb_in,
                o_CLKFBOUT=mmcm_fb_out,
                o_LOCKED=self.mmcm_locked,

                # VCO @ 1GHz/1.2GHz with MULT=8 (125MHz)/12 (100MHz)
                p_CLKFBOUT_MULT_F=mult, p_DIVCLK_DIVIDE=1,

                # 125MHz/100MHz
                p_CLKOUT0_DIVIDE_F=mult, p_CLKOUT0_PHASE=0.0, o_CLKOUT0=mmcm_sys,
                # 500MHz/400MHz
                p_CLKOUT1_DIVIDE=mult/4, p_CLKOUT1_PHASE=0.0, o_CLKOUT1=mmcm_sys4x,
            ),
            Instance("BUFG", i_I=mmcm_sys, o_O=self.cd_sys.clk),
            Instance("BUFG", i_I=mmcm_sys4x, o_O=self.cd_sys4x.clk),
            Instance("BUFG", i_I=mmcm_fb_out, o_O=mmcm_fb_in),
        ]

        if ext_async_rst is not None:
            self.specials += AsyncResetSynchronizer(self.cd_sys, ~self.mmcm_locked | ext_async_rst)
        else:
            self.specials += AsyncResetSynchronizer(self.cd_sys, ~self.mmcm_locked)

        self.platform.add_false_path_constraints(self.cd_sys.clk, main_clk)

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
        self.clock_domains.cd_clk200 = ClockDomain()

        clk200 = platform.request("clk200")
        clk200_se = Signal()
        self.specials += Instance("IBUFDS", i_I=clk200.p, i_IB=clk200.n, o_O=clk200_se)

        rst = platform.request("cpu_reset")

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
            AsyncResetSynchronizer(self.cd_sys, ~pll_locked | rst),
            AsyncResetSynchronizer(self.cd_clk200, ~pll_locked | rst),
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
    def __init__(self, toolchain="vivado", sdram_controller_type="minicon", clk_freq=125e6, rtio_sys_merge=False, **kwargs):
        platform = kc705.Platform(toolchain=toolchain)
        SoCSDRAM.__init__(self, platform,
                          clk_freq=clk_freq, cpu_reset_address=0xaf0000,
                          **kwargs)

        if rtio_sys_merge:
            self.submodules.crg = _RtioSysCRG(platform, bootstrap_freq=clk_freq)
            self.csr_devices.append("crg")
        else:
            self.submodules.crg = _SysCRG(platform)

        self.submodules.ddrphy = k7ddrphy.K7DDRPHY(platform.request("ddram"))
        self.config["DDRPHY_WLEVEL"] = None
        sdram_module = MT8JTF12864(self.clk_freq, "1:4")
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
                spiflash_pads, dummy=11, div=2,
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
        self.submodules.ethphy = LiteEthPHY(eth_clocks,
                                            self.platform.request("eth"), clk_freq=self.clk_freq)
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

def soc_kc705_args(parser):
    soc_sdram_args(parser)
    parser.add_argument("--toolchain", default="vivado",
                        help="FPGA toolchain to use: ise, vivado")


def soc_kc705_argdict(args):
    r = soc_sdram_argdict(args)
    r["toolchain"] = args.toolchain
    return r


def main():
    parser = argparse.ArgumentParser(description="MiSoC port to the KC705")
    builder_args(parser)
    soc_kc705_args(parser)
    parser.add_argument("--with-ethernet", action="store_true",
                        help="enable Ethernet support")
    args = parser.parse_args()

    cls = MiniSoC if args.with_ethernet else BaseSoC
    soc = cls(**soc_kc705_argdict(args))
    builder = Builder(soc, **builder_argdict(args))
    builder.build()


if __name__ == "__main__":
    main()
