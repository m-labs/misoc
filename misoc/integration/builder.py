import os
import io
import subprocess
import struct

from misoc.integration import cpu_interface, soc_sdram, sdram_init


__all__ = ["misoc_software_packages", "misoc_extra_software_packages",
           "misoc_directory",
           "Builder", "builder_args", "builder_argdict"]


misoc_software_packages = [
    "libcompiler-rt",
    "libprintf",
    "libbase",
    "libnet",
    "bios"
]


misoc_extra_software_packages = [
    "liballoc",
    "libm",
    "libdyld",
    "libunwind"
]


misoc_directory = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def _makefile_escape(s):
    return s.replace("\\", "\\\\")


class WriteGenerated(io.StringIO):
    def __init__(self, generated_dir, name):
        super().__init__()
        self.name = os.path.join(generated_dir, name)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        try:
            with open(self.name, "r") as f:
                content = f.read()
        except:
            content = ""
        if content != self.getvalue():
            with open(self.name, "w") as f:
                f.write(self.getvalue())


class Builder:
    def __init__(self, soc, output_dir=None,
                 compile_software=True, compile_gateware=True,
                 csr_csv=None):
        self.soc = soc
        if output_dir is None:
            output_dir = "misoc_{}_{}".format(
                soc.__class__.__name__.lower(),
                soc.platform.name)
        # From Python doc: makedirs() will become confused if the path
        # elements to create include '..'
        self.output_dir = os.path.abspath(output_dir)
        self.compile_software = compile_software
        self.compile_gateware = compile_gateware
        self.csr_csv = csr_csv

        self.software_packages = []
        for name in misoc_software_packages:
            self.add_software_package(name)

    def add_extra_software_packages(self):
        for name in misoc_extra_software_packages:
            self.add_software_package(name)

    def add_software_package(self, name, src_dir=None):
        if src_dir is None:
            src_dir = os.path.join(misoc_directory, "software", name)
        self.software_packages.append((name, src_dir))

    def generate_includes(self):
        cpu_type = self.soc.cpu_type
        memory_regions = self.soc.get_memory_regions()
        memory_groups = self.soc.get_memory_groups()
        flash_boot_address = getattr(self.soc, "flash_boot_address", None)
        csr_regions = self.soc.get_csr_regions()
        csr_groups = self.soc.get_csr_groups()
        constants = self.soc.get_constants()
        if isinstance(self.soc, soc_sdram.SoCSDRAM) and self.soc._sdram_phy:
            sdram_phy_settings = self.soc._sdram_phy[0].settings
        else:
            sdram_phy_settings = None

        buildinc_dir = os.path.join(self.output_dir, "software", "include")
        generated_dir = os.path.join(buildinc_dir, "generated")
        os.makedirs(generated_dir, exist_ok=True)

        with WriteGenerated(generated_dir, "variables.mak") as f:
            def define(k, v):
                f.write("{}={}\n".format(k, _makefile_escape(v)))
            for k, v in cpu_interface.get_cpu_mak(cpu_type):
                define(k, v)
            define("MISOC_DIRECTORY", misoc_directory)
            define("BUILDINC_DIRECTORY", buildinc_dir)
            f.write("export BUILDINC_DIRECTORY\n")
            for name, src_dir in self.software_packages:
                define(name.upper() + "_DIRECTORY", src_dir)

        with WriteGenerated(generated_dir, "output_format.ld") as f:
            f.write(cpu_interface.get_linker_output_format(cpu_type))
        with WriteGenerated(generated_dir, "regions.ld") as f:
            f.write(cpu_interface.get_linker_regions(memory_regions))

        with WriteGenerated(generated_dir, "mem.h") as f:
            f.write(cpu_interface.get_mem_header(memory_regions, flash_boot_address))
        with WriteGenerated(generated_dir, "csr.h") as f:
            f.write(cpu_interface.get_csr_header(csr_regions, constants))

        with WriteGenerated(generated_dir, "mem.rs") as f:
            f.write(cpu_interface.get_mem_rust(memory_regions, memory_groups, flash_boot_address))
        with WriteGenerated(generated_dir, "csr.rs") as f:
            f.write(cpu_interface.get_csr_rust(csr_regions, csr_groups, constants))
        with WriteGenerated(generated_dir, "rust-cfg") as f:
            f.write(cpu_interface.get_rust_cfg(csr_regions, constants))

        if sdram_phy_settings is not None:
            with WriteGenerated(generated_dir, "sdram_phy.h") as f:
                f.write(sdram_init.get_sdram_phy_header(sdram_phy_settings))
            with WriteGenerated(generated_dir, "sdram_phy.rs") as f:
                f.write(sdram_init.get_sdram_phy_rust(sdram_phy_settings))

        if self.csr_csv is not None:
            with open(self.csr_csv, "w") as f:
                f.write(cpu_interface.get_csr_csv(csr_regions))

    def generate_software(self):
        for name, src_dir in self.software_packages:
            dst_dir = os.path.join(self.output_dir, "software", name)
            os.makedirs(dst_dir, exist_ok=True)
            src = os.path.join(src_dir, "Makefile")
            if os.name != "nt":
                dst = os.path.join(dst_dir, "Makefile")
                try:
                    os.remove(dst)
                except FileNotFoundError:
                    pass
                os.symlink(src, dst)
            if self.compile_software:
                if os.name != "nt":
                    cmd = ["make", "-C", dst_dir]
                else:
                    cmd = ["make", "-C", dst_dir, "-f", src]
                subprocess.check_call(cmd)

    def initialize_memory(self):
        if self.soc.integrated_rom_size:
            bios_file = os.path.join(self.output_dir, "software", "bios",
                                     "bios.bin")
            with open(bios_file, "rb") as boot_file:
                boot_data = []
                unpack_endian = ">I" if self.soc.cpu_type != "vexriscv" else "<I"
                while True:
                    w = boot_file.read(4)
                    if not w:
                        break
                    boot_data.append(struct.unpack(unpack_endian, w)[0])

            self.soc.rom.mem.init = boot_data

    def build(self):
        self.soc.finalize()

        if self.soc.integrated_rom_size and not self.compile_software:
            raise ValueError("Software must be compiled in order to "
                             "intitialize integrated ROM")

        self.generate_includes()
        self.generate_software()
        self.initialize_memory()
        self.soc.build(build_dir=os.path.join(self.output_dir, "gateware"),
                       run=self.compile_gateware)


def builder_args(parser):
    parser.add_argument("--output-dir", default=None,
                        help="output directory for generated "
                             "source files and binaries")
    parser.add_argument("--no-compile-software", action="store_true",
                        help="do not compile the software, only generate "
                             "build infrastructure")
    parser.add_argument("--no-compile-gateware", action="store_true",
                        help="do not compile the gateware, only generate "
                             "HDL source files and build scripts")
    parser.add_argument("--csr-csv", default=None,
                        help="store CSR map in CSV format into the "
                             "specified file")


def builder_argdict(args):
    if hasattr(args, "variant") and args.output_dir:
        args.output_dir = os.path.join(args.output_dir, args.variant.lower())

    return {
        "output_dir": args.output_dir,
        "compile_software": not args.no_compile_software,
        "compile_gateware": not args.no_compile_gateware,
        "csr_csv": args.csr_csv
    }
