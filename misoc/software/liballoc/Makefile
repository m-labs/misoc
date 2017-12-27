include ../include/generated/variables.mak
include $(MISOC_DIRECTORY)/software/common.mak

all:: liballoc.a

liballoc.a: alloc.o
	$(archive)

%.o: $(LIBALLOC_DIRECTORY)/%.c
	$(compile)
