from migen import *

from misoc.interconnect.csr import CSRStatus


def get_cpu_mak(cpu):
    if cpu == "lm32":
        triple = "lm32-elf"
        cpuflags = "-mbarrel-shift-enabled -mmultiply-enabled -mdivide-enabled -msign-extend-enabled"
        clang = ""
    elif cpu == "or1k":
        triple = "or1k-linux"
        cpuflags = "-mhard-mul -mhard-div -mror -mffl1 -maddc"
        clang = "1"
    elif cpu == "vexriscv":
        triple = "riscv64-unknown-elf"
        cpuflags = "-D__vexriscv__ -march=rv32im  -mabi=ilp32"
        clang = ""
    else:
        raise ValueError("Unsupported CPU type: "+cpu)
    return [
        ("TRIPLE", triple),
        ("CPU", cpu),
        ("CPUFLAGS", cpuflags),
        ("CLANG", clang)
    ]


def get_linker_output_format(cpu_type):
    if cpu_type == "vexriscv":
        return "OUTPUT_FORMAT(\"elf32-littleriscv\", \"elf32-littleriscv\", \"elf32-littleriscv\")"
    else:
        return "OUTPUT_FORMAT(\"elf32-{}\")\n".format(cpu_type)


def get_linker_regions(regions):
    r = "MEMORY {\n"
    for name, origin, length in regions:
        r += "\t{} : ORIGIN = 0x{:08x}, LENGTH = 0x{:08x}\n".format(name, origin, length)
    r += "}\n"
    return r


def get_mem_header(regions, flash_boot_address):
    r = "#ifndef __GENERATED_MEM_H\n#define __GENERATED_MEM_H\n\n"
    for name, base, size in regions:
        r += "#define {name}_BASE 0x{base:08x}\n#define {name}_SIZE 0x{size:08x}\n\n".format(name=name.upper(), base=base, size=size)
    if flash_boot_address is not None:
        r += "#define FLASH_BOOT_ADDRESS 0x{:08x}\n\n".format(flash_boot_address)
    r += "#endif\n"
    return r


def get_mem_rust(regions, groups, flash_boot_address):
    r  = "// Include this file as:\n"
    r += "//     include!(concat!(env!(\"BUILDINC_DIRECTORY\"), \"/generated/mem.rs\"));\n"
    r += "#[allow(dead_code)]\n"
    r += "pub mod mem {\n"
    for name, base, size in regions:
        r += "  pub const {name}_BASE: usize = 0x{base:08x};\n". \
            format(name=name.upper(), base=base)
        r += "  pub const {name}_SIZE: usize = 0x{size:08x};\n\n". \
            format(name=name.upper(), size=size)

    if groups:
        r += "  pub struct MemoryRegion {\n"
        r += "    pub base: usize,\n"
        r += "    pub size: usize,\n"
        r += "  }\n\n"

        for group_name, group_members in groups:
            r += ("  pub static " + group_name.upper() +
                  ": [MemoryRegion; " + str(len(group_members)) + "] = [\n")
            for member in group_members:
                r += "    MemoryRegion { "
                r += "base: "+member.upper()+"_BASE, "
                r += "size: "+member.upper()+"_SIZE, "
                r += "},\n"
            r += "  ];\n\n"

    if flash_boot_address is not None:
        r += "  pub const FLASH_BOOT_ADDRESS: usize = 0x{:08x};\n\n". \
            format(flash_boot_address)

    r += "}\n"
    return r


def is_readonly(csr):
    return isinstance(csr, CSRStatus)


def _get_rw_functions_c(reg_name, reg_base, nwords, busword, read_only):
    r = ""

    r += "#define CSR_"+reg_name.upper()+"_ADDR "+hex(reg_base)+"\n"
    r += "#define CSR_"+reg_name.upper()+"_SIZE "+str(nwords)+"\n"

    size = nwords*busword
    if size > 64:
        return r
    elif size > 32:
        ctype = "unsigned long long int"
    elif size > 16:
        ctype = "unsigned int"
    elif size > 8:
        ctype = "unsigned short int"
    else:
        ctype = "unsigned char"

    r += "static inline "+ctype+" "+reg_name+"_read(void) {\n"
    if size > 1:
        r += "\t"+ctype+" r = MMPTR("+hex(reg_base)+");\n"
        for byte in range(1, nwords):
            r += "\tr <<= "+str(busword)+";\n\tr |= MMPTR("+hex(reg_base+4*byte)+");\n"
        r += "\treturn r;\n}\n"
    else:
        r += "\treturn MMPTR("+hex(reg_base)+");\n}\n"

    if not read_only:
        r += "static inline void "+reg_name+"_write("+ctype+" value) {\n"
        for word in range(nwords):
            shift = (nwords-word-1)*busword
            if shift:
                value_shifted = "value >> "+str(shift)
            else:
                value_shifted = "value"
            r += "\tMMPTR("+hex(reg_base+4*word)+") = "+value_shifted+";\n"
        r += "}\n"
    return r


def get_csr_header(regions, constants):
    r = "#ifndef __GENERATED_CSR_H\n#define __GENERATED_CSR_H\n"
    r += "#include <hw/common.h>\n"
    for name, origin, busword, obj in regions:
        if isinstance(obj, Memory):
            r += "#define CSR_"+name.upper()+"_BASE "+hex(origin)+"\n"
        else:
            r += "\n/* "+name+" */\n"
            r += "#define CSR_"+name.upper()+"_BASE "+hex(origin)+"\n"
            for csr in obj:
                nr = (csr.size + busword - 1)//busword
                r += _get_rw_functions_c(name + "_" + csr.name, origin, nr, busword, is_readonly(csr))
                origin += 4*nr

    r += "\n/* constants */\n"
    for name, value in constants:
        if value is None:
            r += "#define "+name+"\n"
            continue
        if isinstance(value, str):
            value = "\"" + value + "\""
            ctype = "const char *"
        else:
            value = str(value)
            ctype = "int"
        r += "#define "+name+" "+value+"\n"
        r += "static inline "+ctype+" "+name.lower()+"_read(void) {\n"
        r += "\treturn "+value+";\n}\n"

    r += "\n#endif\n"
    return r


def _get_rstype(size):
    if size > 64:
        return None
    elif size > 32:
        return "u64"
    elif size > 16:
        return "u32"
    elif size > 8:
        return "u16"
    else:
        return "u8"


def _get_rw_functions_rs(reg_name, reg_base, size, nwords, busword, read_only):
    r = ""

    r += "    pub const "+reg_name.upper()+"_ADDR: *mut u32 = "+hex(reg_base)+" as *mut u32;\n"
    r += "    pub const "+reg_name.upper()+"_SIZE: usize = "+str(nwords)+";\n\n"

    rstype = _get_rstype(size)
    if rstype is None:
        return r
    rsname = reg_name.upper()+"_ADDR"

    r += "    #[inline(always)]\n"
    r += "    pub unsafe fn "+reg_name+"_read() -> "+rstype+" {\n"
    if nwords > 1:
        r += "      let r = read_volatile("+rsname+") as "+rstype+";\n"
        for word in range(1, nwords):
            r += "      let r = r << "+str(busword)+" | " + \
                 "read_volatile("+rsname+".offset("+str(word)+")) as "+rstype+";\n"
        r += "      r\n"
    else:
        r += "      read_volatile("+rsname+") as "+rstype+"\n"
    r += "    }\n\n"

    if not read_only:
        r += "    #[inline(always)]\n"
        r += "    pub unsafe fn "+reg_name+"_write(w: "+rstype+") {\n"
        for word in range(nwords):
            shift = (nwords-word-1)*busword
            if shift:
                value_shifted = "w >> "+str(shift)
            else:
                value_shifted = "w"
            r += "      write_volatile("+rsname+".offset("+str(word)+"), "+\
                 "("+value_shifted+") as u32);\n"
        r += "    }\n\n"
    return r


def _region_by_name(regions, search_name):
    for name, origin, busword, obj in regions:
        if name == search_name:
            return origin, busword, obj
    raise KeyError


def get_csr_rust(regions, groups, constants):
    r  = "// Include this file as:\n"
    r += "//     include!(concat!(env!(\"BUILDINC_DIRECTORY\"), \"/generated/csr.rs\"));\n"
    r += "#[allow(dead_code)]\n"
    r += "pub mod csr {\n"

    for name, origin, busword, obj in regions:
        r += "  pub const "+name.upper()+"_BASE: *mut u32 = "+hex(origin)+" as *mut u32;\n"
        if not isinstance(obj, Memory):
            r += "\n"
            r += "  pub mod "+name+" {\n"
            r += "    #[allow(unused_imports)]\n"
            r += "    use core::ptr::{read_volatile, write_volatile};\n\n"
            for csr in obj:
                nwords = (csr.size + busword - 1)//busword
                r += _get_rw_functions_rs(csr.name, origin, csr.size, nwords, busword,
                                          is_readonly(csr))
                origin += 4*nwords
            r += "  }\n\n"

    for group_name, group_members in groups:
        if group_members:
            struct_name = group_name.capitalize() + "Struct"

            csrs = _region_by_name(regions, group_members[0])[2]
            r += "  pub struct " + struct_name + " {\n"
            for csr in csrs:
                nwords = (csr.size + busword - 1)//busword
                rstype = _get_rstype(nwords*busword)
                r += "    pub " + csr.name + "_read: unsafe fn() -> " + rstype + ",\n"
                if not is_readonly(csr):
                    r += "    pub " + csr.name + "_write: unsafe fn(" + rstype + "),\n";
            r += "  }\n\n"

            r += ("  pub const " + group_name.upper() +
                  ": [" + struct_name + "; " + str(len(group_members)) + "] = [\n")
            for member in group_members:
                r += "    " + struct_name + " {\n"
                for csr in csrs:
                    r += "      " + csr.name + "_read: " + member + "::"  + csr.name + "_read,\n"
                    if not is_readonly(csr):
                        r += "      " + csr.name + "_write: " + member + "::"  + csr.name + "_write,\n"
                r += "    },\n"
            r += "  ];\n\n"
        r += "  pub const " + group_name.upper() + "_LEN: usize = " + str(len(group_members)) + ";\n\n"

    for name, value in constants:
        if value is None:
            value = "1"
            rstype = "u32"
        elif isinstance(value, str):
            value = "\"" + value + "\""
            rstype = "&'static str"
        else:
            value = str(value)
            rstype = "u32"
        r += "  pub const "+name.upper()+": "+rstype+" = "+value+";\n"

    r += "}\n"
    return r


def get_rust_cfg(regions, constants):
    r = ""
    for name, origin, busword, obj in regions:
        r += "has_"+name.lower()+"\n"
    for name, value in constants:
        if name.upper().startswith("CONFIG_"):
            if value is None:
                r += name.lower()[7:]+"\n"
            else:
                r += name.lower()[7:]+"=\""+str(value)+"\"\n"
    return r


def get_csr_csv(regions):
    r = ""
    for name, origin, busword, obj in regions:
        if not isinstance(obj, Memory):
            for csr in obj:
                nr = (csr.size + busword - 1)//busword
                r += "{}.{},0x{:08x},{},{}\n".format(name, csr.name, origin, csr.size, "ro" if is_readonly(csr) else "rw")
                origin += 4*nr
    return r
