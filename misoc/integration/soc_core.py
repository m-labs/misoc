from operator import itemgetter

from migen import *

from misoc.cores import lm32, mor1kx, identifier, timer, uart, vexriscv
from misoc.interconnect import wishbone, csr_bus, wishbone2csr
from misoc.integration.wb_slaves import WishboneSlaveManager


__all__ = ["SoCCore", "soc_core_args", "soc_core_argdict"]


class SoCCore(Module):
    mem_map = {
        "rom":      0x00000000,
        "sram":     0x10000000,
        "main_ram": 0x40000000,
        "csr":      0x60000000,
    }
    def __init__(self, platform, clk_freq,
                cpu_type="lm32", cpu_reset_address=0x00000000,
                cpu_bus_width=32,
                integrated_rom_size=0,
                integrated_sram_size=4096,
                integrated_main_ram_size=16*1024,
                shadow_base=0x80000000,
                csr_data_width=8, csr_address_width=14,
                with_uart=True, uart_baudrate=115200,
                ident="",
                with_timer=True):
        self.platform = platform
        self.clk_freq = clk_freq

        self.cpu_type = cpu_type
        if integrated_rom_size:
            cpu_reset_address = 0
        self.cpu_reset_address = cpu_reset_address

        self.integrated_rom_size = integrated_rom_size
        self.integrated_sram_size = integrated_sram_size
        self.integrated_main_ram_size = integrated_main_ram_size

        self.with_uart = with_uart
        self.uart_baudrate = uart_baudrate

        self.shadow_base = shadow_base

        self._memory_regions = []  # list of (name, origin, length)
        self._csr_regions = []  # list of (name, origin, busword, csr_list/Memory)
        self._constants = []  # list of (name, value)

        self._wb_masters = []

        self.config = dict()

        self.csr_devices = [
            "uart_phy",
            "uart",
            "identifier",
            "timer0",
        ]
        self._memory_groups = []  # list of (group_name, (group_member0, group_member1, ...))
        self._csr_groups = []  # list of (group_name, (group_member0, group_member1, ...))
        self.interrupt_devices = []

        if cpu_type == "lm32" and cpu_bus_width == 32:
            self.submodules.cpu = lm32.LM32(platform, self.cpu_reset_address)
        elif cpu_type == "or1k" and cpu_bus_width == 32:
            self.submodules.cpu = mor1kx.MOR1KX(platform,
                    OPTION_RESET_PC=self.cpu_reset_address)
        elif cpu_type == "vexriscv" and cpu_bus_width in (32, 64):
            if cpu_bus_width == 32:
                self.submodules.cpu = vexriscv.VexRiscv(platform,
                        self.cpu_reset_address, variant="VexRiscv_IMA")
            else:
                self.submodules.cpu = vexriscv.VexRiscv(platform,
                        self.cpu_reset_address, variant="VexRiscv_IMA_wide")
        elif cpu_type == "vexriscv-g" and cpu_bus_width == 64:
            assert(cpu_bus_width == 64)
            self.submodules.cpu = vexriscv.VexRiscv(platform,
                    self.cpu_reset_address, variant="VexRiscv_G")
        else:
            raise ValueError("Unsupported CPU type: {}; Bus width: {}".format(cpu_type, cpu_bus_width))
        self.add_wb_master(self.cpu.ibus)
        self.add_wb_master(self.cpu.dbus)

        self.cpu_dw = len(self.cpu.dbus.dat_w)
        assert(self.cpu_dw, cpu_bus_width)
        self.config["DATA_WIDTH_BYTES"] = self.cpu_dw//8

        self.csr_data_width = csr_data_width
        self.csr_address_width = csr_address_width

        self._wb_slaves = WishboneSlaveManager(self.shadow_base, dw=self.cpu_dw)

        if integrated_rom_size:
            self.submodules.rom = wishbone.SRAM(integrated_rom_size, read_only=True, data_width=self.cpu_dw)
            self.register_rom(self.rom.bus, integrated_rom_size)

        if integrated_sram_size:
            self.submodules.sram = wishbone.SRAM(integrated_sram_size, data_width=self.cpu_dw)
            self.register_mem("sram", self.mem_map["sram"], integrated_sram_size, self.sram.bus)

        # Main Ram can be used when no external SDRAM is present, and use SDRAM mapping.
        if integrated_main_ram_size:
            self.submodules.main_ram = wishbone.SRAM(integrated_main_ram_size, data_width=self.cpu_dw)
            self.register_mem("main_ram", self.mem_map["main_ram"], integrated_main_ram_size, self.main_ram.bus)

        self.submodules.wishbone2csr = wishbone2csr.WB2CSR(
            bus_csr=csr_bus.Interface(self.csr_data_width, self.csr_address_width), wb_bus_dw=self.cpu_dw)
        self.register_mem("csr", self.mem_map["csr"], (self.cpu_dw//8)*2**self.csr_address_width, self.wishbone2csr.wishbone)

        if with_uart:
            self.submodules.uart_phy = uart.RS232PHY(platform.request("serial"), clk_freq, uart_baudrate)
            self.submodules.uart = uart.UART(self.uart_phy)
            self.interrupt_devices.append("uart")

        if ident:
            self.submodules.identifier = identifier.Identifier(ident)
        self.config["CLOCK_FREQUENCY"] = int(clk_freq)
        self.config["SOC_PLATFORM"] = platform.name

        if with_timer:
            self.submodules.timer0 = timer.Timer()
            self.interrupt_devices.append("timer0")

    def add_wb_master(self, wbm):
        if self.finalized:
            raise FinalizeError
        self._wb_masters.append(wbm)

    def add_wb_slave(self, origin, length, interface):
        if self.finalized:
            raise FinalizeError
        self._wb_slaves.add(origin, length, interface)

    # This function simply registers the memory region for firmware purposes
    # (linker script, generated headers)
    def add_memory_region(self, name, origin, length):
        self._memory_regions.append((name, origin, length))

    def add_memory_group(self, group_name, members):
        self._memory_groups.append((group_name, members))

    def register_mem(self, name, origin, length, interface):
        self.add_wb_slave(origin, length, interface)
        self.add_memory_region(name, origin, length)

    def register_rom(self, interface, rom_size=0xa000):
        self.add_wb_slave(self.mem_map["rom"], rom_size, interface)
        assert self.cpu_reset_address < rom_size
        self.add_memory_region("rom", self.cpu_reset_address,
                               rom_size-self.cpu_reset_address)

    def get_memory_regions(self):
        return self._memory_regions

    def get_memory_groups(self):
        return self._memory_groups

    def check_csr_region(self, name, origin):
        for n, o, l, obj in self._csr_regions:
            if n == name or o == origin:
                raise ValueError("CSR region conflict between {} and {}".format(n, name))

    def add_csr_region(self, name, origin, busword, obj):
        self.check_csr_region(name, origin)
        self._csr_regions.append((name, origin, busword, obj))

    def add_csr_group(self, group_name, members):
        self._csr_groups.append((group_name, members))

    def get_csr_regions(self):
        return self._csr_regions

    def get_csr_groups(self):
        return self._csr_groups

    def get_constants(self):
        r = []
        for nr, name in enumerate(self.interrupt_devices):
            r.append((name.upper() + "_INTERRUPT", nr))
        r += self._constants
        return r

    def get_csr_dev_address(self, name, memory):
        if memory is not None:
            name = name + "_" + memory.name_override
        try:
            return self.csr_devices.index(name)
        except ValueError:
            return None

    def do_finalize(self):
        registered_mems = {regions[0] for regions in self._memory_regions}

        # Wishbone
        self.submodules.wishbonecon = wishbone.InterconnectShared(self._wb_masters,
            self._wb_slaves.get_interconnect_slaves(), register=True, dw=self.cpu_dw)

        # CSR
        self.submodules.csrbankarray = csr_bus.CSRBankArray(self,
            self.get_csr_dev_address,
            data_width=self.csr_data_width, address_width=self.csr_address_width,
            align_bits=log2_int(self.cpu_dw//8))
        self.submodules.csrcon = csr_bus.Interconnect(
            self.wishbone2csr.csr, self.csrbankarray.get_buses())
        for name, csrs, mapaddr, rmap in self.csrbankarray.banks:
            self.add_csr_region(name, (self.mem_map["csr"] + 0x800*mapaddr) | self.shadow_base, self.csr_data_width, csrs)
        for name, memory, mapaddr, mmap in self.csrbankarray.srams:
            self.add_csr_region(name + "_" + memory.name_override, (self.mem_map["csr"] + 0x800*mapaddr) | self.shadow_base, self.csr_data_width, memory)
        for name, constant in self.csrbankarray.constants:
            self._constants.append(((name + "_" + constant.name).upper(), constant.value.value))
        for name, value in sorted(self.config.items(), key=itemgetter(0)):
            self._constants.append(("CONFIG_" + name.upper(), value))

        # Interrupts
        for nr, name in enumerate(self.interrupt_devices):
            self.comb += self.cpu.interrupt[nr].eq(getattr(self, name).ev.irq)

    def build(self, *args, **kwargs):
        self.platform.build(self, *args, **kwargs)


def soc_core_args(parser):
    parser.add_argument("--cpu-type", default=None,
                        help="select CPU: lm32, or1k, vexriscv, vexriscv-g")
    parser.add_argument("--cpu-bus-width", default=None, type=int,
                        help="width of CPU IBus/DBus in bits: 32 or 64")
    parser.add_argument("--integrated-rom-size", default=None, type=int,
                        help="size/enable the integrated (BIOS) ROM")
    parser.add_argument("--integrated-main-ram-size", default=None, type=int,
                        help="size/enable the integrated main RAM")


def soc_core_argdict(args):
    r = dict()
    for a in "cpu_type", "cpu_bus_width", "integrated_rom_size", "integrated_main_ram_size":
        arg = getattr(args, a)
        if arg is not None:
            r[a] = arg
    return r
