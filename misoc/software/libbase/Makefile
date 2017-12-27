include ../include/generated/variables.mak
include $(MISOC_DIRECTORY)/software/common.mak

OBJECTS  = libc.o ctype.o strtod.o qsort.o errno.o crc16.o crc32.o
OBJECTS += id.o system.o uart.o console.o time.o spiflash.o exception.o

all:: crt0-$(CPU).o libbase.a libbase-nofloat.a

libbase.a: $(OBJECTS) printf.o
	$(archive)

libbase-nofloat.a: $(OBJECTS) printf-nofloat.o
	$(archive)

%.o: $(LIBBASE_DIRECTORY)/%.S
	$(assemble)

%.o: $(LIBBASE_DIRECTORY)/%.c
	$(compile)

%.o: $(LIBPRINTF_DIRECTORY)/%.c
	$(compile)

printf-nofloat.o: $(LIBPRINTF_DIRECTORY)/printf.c
	$(compile) -D_PRINTF_NO_FLOAT
