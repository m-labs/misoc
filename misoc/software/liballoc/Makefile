include ../include/generated/variables.mak
include $(MISOC_DIRECTORY)/software/common.mak

OBJECTS = alloc.o

.PHONY: all
all: liballoc.a

liballoc.a: $(OBJECTS)
	$(archive)

%.o: $(LIBALLOC_DIRECTORY)/%.c
	$(compile)

%.o: %.S
	$(assemble)

.PHONY: clean
clean:
	$(clean)
