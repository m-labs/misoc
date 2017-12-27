include ../include/generated/variables.mak
include $(MISOC_DIRECTORY)/software/common.mak

LDFLAGS += -L../libcompiler-rt \
	-L../libbase \
	-L../libnet

all:: bios.bin

%.bin: %.elf
	$(objcopy) -O binary
	$(MSCIMG) $@

bios.elf: ../libbase/crt0-$(CPU).o isr.o sdram.o main.o boot-helper-$(CPU).o boot.o
	$(link) -T $(BIOS_DIRECTORY)/bios.ld \
		-lnet -lbase-nofloat -lcompiler-rt

%.o: $(BIOS_DIRECTORY)/%.S
	$(assemble)

%.o: $(BIOS_DIRECTORY)/%.c
	$(compile)
