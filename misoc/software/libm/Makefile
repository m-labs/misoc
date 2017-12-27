include ../include/generated/variables.mak
include $(MISOC_DIRECTORY)/software/common.mak

COMMONFLAGS += -I$(MISOC_DIRECTORY)/software/include/fdlibm \
	-D_IEEE_LIBM

OBJECTS = k_standard.o k_rem_pio2.o \
	k_cos.o k_sin.o k_tan.o \
	e_acos.o e_acosh.o e_asin.o e_atan2.o \
	e_atanh.o e_cosh.o e_exp.o e_fmod.o \
	e_gamma.o e_gamma_r.o e_hypot.o e_j0.o \
	e_j1.o e_jn.o e_lgamma.o e_lgamma_r.o \
	e_log.o e_log10.o e_pow.o e_rem_pio2.o e_remainder.o  \
	e_scalb.o e_sinh.o e_sqrt.o \
	w_acos.o w_acosh.o w_asin.o w_atan2.o \
	w_atanh.o w_cosh.o w_exp.o w_fmod.o \
	w_gamma.o w_gamma_r.o w_hypot.o w_j0.o \
	w_j1.o w_jn.o w_lgamma.o w_lgamma_r.o \
	w_log.o w_log10.o w_pow.o w_remainder.o \
	w_scalb.o w_sinh.o w_sqrt.o \
	s_asinh.o s_atan.o s_cbrt.o s_ceil.o s_copysign.o \
	s_cos.o s_erf.o s_expm1.o s_fabs.o s_finite.o s_floor.o \
	s_frexp.o s_ilogb.o s_isnan.o s_ldexp.o s_lib_version.o \
	s_log1p.o s_logb.o s_matherr.o s_modf.o s_nextafter.o \
	s_rint.o s_scalbn.o s_signgam.o s_significand.o s_sin.o \
	s_tan.o s_tanh.o

all:: libm.a

libm.a: $(OBJECTS)
	$(archive)

%.o: $(LIBM_DIRECTORY)/%.c
	$(compile)
