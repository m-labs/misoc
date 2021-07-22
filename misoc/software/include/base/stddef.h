#ifndef __STDDEF_H
#define __STDDEF_H

#ifdef __cplusplus
extern "C" {
#endif

#ifdef __cplusplus
#define NULL 0
#else
#define NULL ((void *)0)
#endif

typedef __SIZE_TYPE__ size_t;
typedef __PTRDIFF_TYPE__ ptrdiff_t;

#define offsetof(type, member) __builtin_offsetof(type, member)

#ifdef __cplusplus
}
#endif

#endif /* __STDDEF_H */
