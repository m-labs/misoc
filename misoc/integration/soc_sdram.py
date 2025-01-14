from migen import *
from migen.genlib.record import *

from misoc.interconnect import wishbone, wishbone2lasmi, lasmi_bus
from misoc.interconnect.csr import AutoCSR
from misoc.cores import dfii, minicon
from misoc.integration.soc_core import *


__all__ = ["SoCSDRAM", "soc_sdram_args", "soc_sdram_argdict"]


class SoCSDRAM(SoCCore):
    def __init__(self, platform, clk_freq, l2_size=8192, l2_line_size=None, **kwargs):
        SoCCore.__init__(self, platform, clk_freq,
                         integrated_main_ram_size=0, **kwargs)
        self.csr_devices += ["dfii", "l2_cache"]

        if l2_size:
            self.config["L2_SIZE"] = l2_size
        self.l2_size = l2_size
        self.l2_line_size = l2_line_size

        self._sdram_phy = []
        self._cpulevel_sdram_ifs = []
        self._cpulevel_sdram_if_arbitrated = wishbone.Interface(data_width=self.cpu_dw, adr_width=32-log2_int(self.cpu_dw//8))

    def add_cpulevel_sdram_if(self, interface):
        """Registers a 32/64-bit Wishbone interface, capable of accessing SDRAM,
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
            bus = wishbone.Interface(len(self.sdram_controller.bus.dat_w), adr_width=32-log2_int(self.cpu_dw//8))
            self._native_sdram_ifs.append(bus)
            return bus
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
        wb_sdram = wishbone.Interface(data_width=self.cpu_dw, adr_width=32-log2_int(self.cpu_dw//8))
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
                phy.settings, geom_settings, timing_settings, adr_width=32-log2_int(self.cpu_dw//8))
            self._native_sdram_ifs = []

            bridge_if = self.get_native_sdram_if()
            if self.l2_size:
                if self.l2_line_size is None: 
                    self.l2_line_size = len(bridge_if.dat_w)//8

                l2_cache = wishbone.Cache(self.l2_size//(self.cpu_dw//8),
                    self._cpulevel_sdram_if_arbitrated, bridge_if, linesize=self.l2_line_size//(len(bridge_if.dat_w)//8))
                # XXX Vivado ->2015.1 workaround, Vivado is not able to map correctly our L2 cache.
                # Issue is reported to Xilinx and should be fixed in next releases (> 2017.2).
                # Remove this workaround when fixed by Xilinx.
                from migen.build.xilinx.vivado import XilinxVivadoToolchain
                if isinstance(self.platform.toolchain, XilinxVivadoToolchain):
                    from migen.fhdl.simplify import ModuleTransformer

                    class CacheWidthDivider(ModuleTransformer):
                        """Splitting cache data memory into synthesizable grains by dividing width.

                        The splitted memories always preserve its original depth.
                        See RAMB36E* documentation regarding the block RAM dimensional constraints.

                        Memory width must be powers of 2."""
                        def transform_fragment(self, i, f):
                            old_mem, old_port = i.data_mem, i.data_port

                            if old_mem.width < 64:
                                return

                            f.specials -= set([old_mem, old_port])

                            grain_width = 64
                            for i in range(old_mem.width//grain_width):
                                newmem = Memory(grain_width, old_mem.depth,
                                    name=old_mem.name_override + "_grain" + str(i))
                                f.specials.add(newmem)
                                for port in old_mem.ports:
                                    newport = newmem.get_port(write_capable=True, we_granularity=8)

                                    f.comb += [
                                        newport.adr.eq(port.adr),
                                        port.dat_r[i*grain_width:(i+1)*grain_width].eq(newport.dat_r),
                                        newport.we.eq(port.we[i*grain_width//8:(i+1)*grain_width//8]),
                                        newport.dat_w.eq(port.dat_w[i*grain_width:(i+1)*grain_width]),
                                    ]
                                    f.specials.add(newport)

                    self.submodules.l2_cache = CacheWidthDivider()(l2_cache)
                else:
                    self.submodules.l2_cache = l2_cache
            else:
                self.submodules.converter = wishbone.Converter(
                    self._cpulevel_sdram_if_arbitrated, bridge_if)
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
        if hasattr(self, "_native_sdram_ifs"):
            self.submodules.sdram_native_arbiter = wishbone.Arbiter(
                self._native_sdram_ifs, self.sdram_controller.bus)

        SoCCore.do_finalize(self)


def soc_sdram_args(parser):
    parser.add_argument("--cpu-type", default=None,
                        help="select CPU: lm32, or1k, vexriscv, vexriscv-g")
    parser.add_argument("--cpu-bus-width", default=None, type=int,
                        help="width of CPU IBus/DBus in bits: 32 or 64")
    parser.add_argument("--integrated-rom-size", default=None, type=int,
                        help="size/enable the integrated (BIOS) ROM")


def soc_sdram_argdict(args):
    r = dict()
    for a in "cpu_type", "cpu_bus_width", "integrated_rom_size":
        arg = getattr(args, a)
        if arg is not None:
            r[a] = arg
    return r
