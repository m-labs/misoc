include ../include/generated/variables.mak
include $(MISOC_DIRECTORY)/software/common.mak

OBJECTS=alloc.o

all: liballoc.a

liballoc.a: $(OBJECTS)
	$(AR) crs liballoc.a $(OBJECTS)

%.o: $(LIBALLOC_DIRECTORY)/%.c
	$(compile)

%.o: %.S
	$(assemble)

.PHONY: all clean

clean:
	$(RM) $(OBJECTS) liballoc.a .*~ *~
