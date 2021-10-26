INCLUDE generated/output_format.ld
ENTRY(_start)

INCLUDE generated/regions.ld

SECTIONS
{
	.text :
	{
		_ftext = .;
		*crt0*.o(.text)
		*(.text .stub .text.* .gnu.linkonce.t.*)
		_etext = .;
	} > rom

	.rodata :
	{
		. = ALIGN(4);
		_frodata = .;
		*(.rodata .rodata.* .gnu.linkonce.r.*)
		*(.rodata1)

		/* Make sure the file is aligned on disk as well as in memory;
		   1. CRC calculation requires 4-bytes alignment.
		   2. The ROM needs to be 8-bytes aligned overall. It is to
		      convert the binary from big endian to little endian for
			  little endian CPUs. (e.g. RISC-V).
		   Solution: Misalign the CRC by exactly 4 bytes */
		FILL(0);
		. = ALIGN(8) + 4;
		_erodata = .;
	} > rom

	.bss :
	{
		. = ALIGN(4);
		_fbss = .;
		*(.dynsbss)
		*(.sbss .sbss.* .gnu.linkonce.sb.*)
		*(.scommon)
		*(.dynbss)
		*(.bss .bss.* .gnu.linkonce.b.*)
		*(COMMON)
		. = ALIGN(4);
		_ebss = .;
		_end = .;
	} > sram

	/DISCARD/ :
	{
		*(.eh_frame)
		*(.comment)
		*(.data .data.* .gnu.linkonce.d.*)
		*(.data1)
		*(.sdata .sdata.* .gnu.linkonce.s.*)
	}
}

PROVIDE(_fstack = ORIGIN(sram) + LENGTH(sram) - 4);
