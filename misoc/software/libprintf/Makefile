include ../include/generated/variables.mak
include $(MISOC_DIRECTORY)/software/common.mak

OBJECTS=ctype.o

all: libprintf-float.a libprintf-nofloat.a

libprintf-%.a: $(OBJECTS) printf-%.o
	$(AR) crs $@ $^

printf-float.o: $(LIBPRINTF_DIRECTORY)/printf.c
	$(compile)

printf-nofloat.o: $(LIBPRINTF_DIRECTORY)/printf.c
	$(compile) -D_PRINTF_NO_FLOAT

%.o: $(LIBPRINTF_DIRECTORY)/%.c
	$(compile)

.PHONY: all clean

clean:
	$(RM) *.a *.o
