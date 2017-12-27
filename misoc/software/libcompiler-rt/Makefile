include ../include/generated/variables.mak
include $(MISOC_DIRECTORY)/software/common.mak

CFLAGS += -D_YUGA_LITTLE_ENDIAN=0 -D_YUGA_BIG_ENDIAN=1 -Wno-missing-prototypes

OBJECTS = divsi3.o modsi3.o comparesf2.o comparedf2.o negsf2.o negdf2.o \
	addsf3.o subsf3.o mulsf3.o divsf3.o lshrdi3.o muldi3.o divdi3.o ashldi3.o ashrdi3.o \
	udivmoddi4.o floatsisf.o floatunsisf.o fixsfsi.o fixdfdi.o fixunssfsi.o fixunsdfdi.o \
	adddf3.o subdf3.o muldf3.o divdf3.o floatsidf.o floatunsidf.o floatdidf.o fixdfsi.o \
	fixunsdfsi.o clzsi2.o ctzsi2.o udivdi3.o umoddi3.o moddi3.o ucmpdi2.o \
  powidf2.o powisf2.o mulodi4.o floatundisf.o floatundidf.o extendsfdf2.o truncdfsf2.o

all:: libcompiler-rt.a

libcompiler-rt.a: $(OBJECTS)
	$(archive)

%.o: $(MISOC_DIRECTORY)/software/compiler_rt/lib/builtins/%.c
	$(compile)
