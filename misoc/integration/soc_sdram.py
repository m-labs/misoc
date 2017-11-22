from migen import *
from migen.genlib.record import *

from misoc.interconnect import wishbone, wishbone2lasmi, lasmi_bus
from misoc.interconnect.csr import AutoCSR
from misoc.cores import dfii, minicon, lasmicon
from misoc.integration.soc_core import *


__all__ = ["SoCSDRAM", "soc_sdram_args", "soc_sdram_argdict"]


class SoCSDRAM(SoCCore):
    def __init__(self, platform, clk_freq, l2_size=8192, **kwargs):
        SoCCore.__init__(self, platform, clk_freq,
                         integrated_main_ram_size=0, **kwargs)
        self.csr_devices += ["dfii", "l2_cache"]

        if l2_size:
            self.config["L2_SIZE"] = l2_size
        self.l2_size = l2_size

        self._sdram_phy = []
        self._cpulevel_sdram_ifs = []
        self._cpulevel_sdram_if_arbitrated = wishbone.Interface()

    def add_cpulevel_sdram_if(self, interface):
        """Registers a 32-bit Wishbone interface, capable of accessing SDRAM,
        at the same level as the CPU.

        This can be called anytime until finalization.
        """
        if self.finalized:
            raise FinalizeError
        self._cpulevel_sdram_ifs.append(interface)

    def get_native_sdram_if(self):
        """Creates and registers a native SDRAM interface, tightly coupled to
        the controller.

        This can only be called after ``register_sdram``.
        """
        if isinstance(self.sdram_controller, minicon.Minicon):
            bus = wishbone.Interface(len(self.sdram_controller.bus.dat_w))
            self._native_sdram_ifs.append(bus)
            return bus
        elif isinstance(self.sdram_controller, lasmicon.LASMIcon):
            return self.lasmi_crossbar.get_master()
        else:
            raise TypeError

    def register_sdram(self, phy, sdram_controller_type, geom_settings, timing_settings):
        # register PHY
        assert not self._sdram_phy
        self._sdram_phy.append(phy)  # encapsulate in list to prevent CSR scanning

        # connect CPU to SDRAM, needs to be done here so that we know the size
        dfi_databits_divisor = 1 if phy.settings.memtype == "SDR" else 2
        sdram_width = phy.settings.dfi_databits//dfi_databits_divisor
        main_ram_size = 2**(geom_settings.bankbits +
                            geom_settings.rowbits +
                            geom_settings.colbits)*sdram_width//8
        # TODO: modify mem_map to allow larger memories.
        main_ram_size = min(main_ram_size, 256*1024*1024)
        wb_sdram = wishbone.Interface()
        self.add_cpulevel_sdram_if(wb_sdram)
        self.register_mem("main_ram", self.mem_map["main_ram"],
                          main_ram_size, wb_sdram)

        # create DFI injector
        self.submodules.dfii = dfii.DFIInjector(
            geom_settings.addressbits, geom_settings.bankbits,
            phy.settings.dfi_databits, phy.settings.nphases)
        self.comb += self.dfii.master.connect(phy.dfi)

        # create controller
        if sdram_controller_type == "minicon":
            self.submodules.sdram_controller = minicon.Minicon(
                phy.settings, geom_settings, timing_settings)
            self._native_sdram_ifs = []

            bridge_if = self.get_native_sdram_if()
            if self.l2_size:
                l2_cache = wishbone.Cache(self.l2_size//4,
                    self._cpulevel_sdram_if_arbitrated, bridge_if)
                # XXX Vivado ->2015.1 workaround, Vivado is not able to map correctly our L2 cache.
                # Issue is reported to Xilinx and should be fixed in next releases (> 2017.2).
                # Remove this workaround when fixed by Xilinx.
                from migen.build.xilinx.vivado import XilinxVivadoToolchain
                if isinstance(self.platform.toolchain, XilinxVivadoToolchain):
                    from migen.fhdl.simplify import FullMemoryWE
                    self.submodules.l2_cache = FullMemoryWE()(l2_cache)
                else:
                    self.submodules.l2_cache = l2_cache
            else:
                self.submodules.converter = wishbone.Converter(
                    self._cpulevel_sdram_if_arbitrated, bridge_if)
        elif sdram_controller_type == "lasmicon":
            self.submodules.sdram_controller = lasmicon.LASMIcon(
                phy.settings, geom_settings, timing_settings)
            self.submodules.lasmi_crossbar = lasmi_bus.LASMIxbar(
                [self.sdram_controller.lasmic],
                self.sdram_controller.nrowbits)

            bridge_if = self.get_native_sdram_if()
            if self.l2_size:
                l2_cache = wishbone.Cache(self.l2_size//4,
                    self._cpulevel_sdram_if_arbitrated,
                    wishbone.Interface(bridge_if.dw))
                # XXX Vivado ->2015.1 workaround, Vivado is not able to map correctly our L2 cache.
                # Issue is reported to Xilinx and should be fixed in next releases (> 2017.2).
                # Remove this workaround when fixed by Xilinx.
                from migen.build.xilinx.vivado import XilinxVivadoToolchain
                if isinstance(self.platform.toolchain, XilinxVivadoToolchain):
                    from migen.fhdl.simplify import FullMemoryWE
                    self.submodules.l2_cache = FullMemoryWE()(l2_cache)
                else:
                    self.submodules.l2_cache = l2_cache
                self.submodules.wishbone2lasmi = wishbone2lasmi.WB2LASMI(
                    self.l2_cache.slave, bridge_if)
            else:
                raise NotImplementedError
        else:
            raise ValueError("Incorrect SDRAM controller type specified")
        self.comb += self.sdram_controller.dfi.connect(self.dfii.slave)

    def do_finalize(self):
        if not self._sdram_phy:
            raise FinalizeError("Need to call SDRAMSoC.register_sdram()")

        # arbitrate CPU-level interfaces
        self.submodules.sdram_cpulevel_arbiter = wishbone.Arbiter(
            self._cpulevel_sdram_ifs, self._cpulevel_sdram_if_arbitrated)

        # arbitrate native interfaces
        # with LASMI, the crossbar is integrated in the controller, we do not
        # do anything here.
        if hasattr(self, "_native_sdram_ifs"):
            self.submodules.sdram_native_arbiter = wishbone.Arbiter(
                self._native_sdram_ifs, self.sdram_controller.bus)

        SoCCore.do_finalize(self)


def soc_sdram_args(parser):
    parser.add_argument("--cpu-type", default=None,
                        help="select CPU: lm32, or1k")
    parser.add_argument("--integrated-rom-size", default=None, type=int,
                        help="size/enable the integrated (BIOS) ROM")


def soc_sdram_argdict(args):
    r = dict()
    for a in "cpu_type", "integrated_rom_size":
        arg = getattr(args, a)
        if arg is not None:
            r[a] = arg
    return r
