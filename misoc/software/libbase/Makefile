include ../include/generated/variables.mak
include $(MISOC_DIRECTORY)/software/common.mak

OBJECTS=exception.o libc.o errno.o crc16.o crc32.o console.o system.o id.o uart.o time.o qsort.o strtod.o spiflash.o ctype.o

all: crt0-$(CPU).o libbase.a libbase-nofloat.a

libbase.a: $(OBJECTS) printf.o
	$(archive)

libbase-nofloat.a: $(OBJECTS) printf-nofloat.o
	$(archive)

%.o: $(LIBBASE_DIRECTORY)/%.c
	$(compile)

%.o: $(LIBPRINTF_DIRECTORY)/%.c
	$(compile)

printf-nofloat.o: $(LIBPRINTF_DIRECTORY)/printf.c
	$(compile) -D_PRINTF_NO_FLOAT

%.o: $(LIBBASE_DIRECTORY)/%.S
	$(assemble)

.PHONY: all clean

clean:
	$(RM) *.a *.o
