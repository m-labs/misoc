/*
 * MiSoC
 * Copyright (C) 2007, 2008, 2009, 2010, 2011 Sebastien Bourdeauducq
 * Copyright (C) Linus Torvalds and Linux kernel developers
 *
 * This program is free software: you can redistribute it and/or modify
 * it under the terms of the GNU General Public License as published by
 * the Free Software Foundation, version 3 of the License.
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU General Public License for more details.
 *
 * You should have received a copy of the GNU General Public License
 * along with this program.  If not, see <http://www.gnu.org/licenses/>.
 */

#include <ctype.h>
#include <stdio.h>
#include <stdlib.h>
#include <stdarg.h>
#include <string.h>
#include <limits.h>

/**
 * strchr - Find the first occurrence of a character in a string
 * @s: The string to be searched
 * @c: The character to search for
 */
char *strchr(const char *s, int c)
{
	for (; *s != (char)c; ++s)
		if (*s == '\0')
			return NULL;
	return (char *)s;
}

/**
 * strpbrk - Find the first occurrence of a set of characters
 * @cs: The string to be searched
 * @ct: The characters to search for
 */
char *strpbrk(const char *cs, const char *ct)
{
	const char *sc1, *sc2;

	for (sc1 = cs; *sc1 != '\0'; ++sc1) {
		for (sc2 = ct; *sc2 != '\0'; ++sc2) {
			if (*sc1 == *sc2)
				return (char *)sc1;
		}
	}
	return NULL;
}

/**
 * strrchr - Find the last occurrence of a character in a string
 * @s: The string to be searched
 * @c: The character to search for
 */
char *strrchr(const char *s, int c)
{
       const char *p = s + strlen(s);
       do {
           if (*p == (char)c)
               return (char *)p;
       } while (--p >= s);
       return NULL;
}

/**
 * strnchr - Find a character in a length limited string
 * @s: The string to be searched
 * @count: The number of characters to be searched
 * @c: The character to search for
 */
char *strnchr(const char *s, size_t count, int c)
{
	for (; count-- && *s != '\0'; ++s)
		if (*s == (char)c)
			return (char *)s;
	return NULL;
}

/**
 * strcpy - Copy a %NUL terminated string
 * @dest: Where to copy the string to
 * @src: Where to copy the string from
 */
char *strcpy(char *dest, const char *src)
{
	char *tmp = dest;

	while ((*dest++ = *src++) != '\0')
		/* nothing */;
	return tmp;
}

/**
 * strncpy - Copy a length-limited, %NUL-terminated string
 * @dest: Where to copy the string to
 * @src: Where to copy the string from
 * @count: The maximum number of bytes to copy
 *
 * The result is not %NUL-terminated if the source exceeds
 * @count bytes.
 *
 * In the case where the length of @src is less than  that  of
 * count, the remainder of @dest will be padded with %NUL.
 *
 */
char *strncpy(char *dest, const char *src, size_t count)
{
	char *tmp = dest;

	while (count) {
		if ((*tmp = *src) != 0)
			src++;
		tmp++;
		count--;
	}
	return dest;
}

/**
 * strcmp - Compare two strings
 * @cs: One string
 * @ct: Another string
 */
int strcmp(const char *cs, const char *ct)
{
	signed char __res;

	while (1) {
		if ((__res = *cs - *ct++) != 0 || !*cs++)
			break;
	}
	return __res;
}

/**
 * strncmp - Compare two strings using the first characters only
 * @cs: One string
 * @ct: Another string
 * @count: Number of characters
 */
int strncmp(const char *cs, const char *ct, size_t count)
{
	signed char __res;
	size_t n;

	n = 0;
	__res = 0;
	while (n < count) {
		if ((__res = *cs - *ct++) != 0 || !*cs++)
			break;
		n++;
	}
	return __res;
}

/**
 * strcat - Append one %NUL-terminated string to another
 * @dest: The string to be appended to
 * @src: The string to append to it
 */
char *strcat(char *dest, const char *src)
{
  char *tmp = dest;

  while (*dest)
    dest++;
  while ((*dest++ = *src++) != '\0')
    ;
  return tmp;
}

/**
 * strncat - Append a length-limited, %NUL-terminated string to another
 * @dest: The string to be appended to
 * @src: The string to append to it
 * @count: The maximum numbers of bytes to copy
 *
 * Note that in contrast to strncpy(), strncat() ensures the result is
 * terminated.
 */
char *strncat(char *dest, const char *src, size_t count)
{
  char *tmp = dest;

  if (count) {
    while (*dest)
      dest++;
    while ((*dest++ = *src++) != 0) {
      if (--count == 0) {
        *dest = '\0';
        break;
      }
    }
  }
  return tmp;
}

/**
 * strlen - Find the length of a string
 * @s: The string to be sized
 */
size_t strlen(const char *s)
{
	const char *sc;

	for (sc = s; *sc != '\0'; ++sc)
		/* nothing */;
	return sc - s;
}

/**
 * strnlen - Find the length of a length-limited string
 * @s: The string to be sized
 * @count: The maximum number of bytes to search
 */
size_t strnlen(const char *s, size_t count)
{
	const char *sc;

	for (sc = s; count-- && *sc != '\0'; ++sc)
		/* nothing */;
	return sc - s;
}

/**
 * strspn - Calculate the length of the initial substring of @s which only contain letters in @accept
 * @s: The string to be searched
 * @accept: The string to search for
 */
size_t strspn(const char *s, const char *accept)
{
	const char *p;
	const char *a;
	size_t count = 0;

	for (p = s; *p != '\0'; ++p) {
		for (a = accept; *a != '\0'; ++a) {
			if (*p == *a)
				break;
		}
		if (*a == '\0')
			return count;
		++count;
	}
	return count;
}

/**
 * memcmp - Compare two areas of memory
 * @cs: One area of memory
 * @ct: Another area of memory
 * @count: The size of the area.
 */
int memcmp(const void *cs, const void *ct, size_t count)
{
	const unsigned char *su1, *su2;
	int res = 0;

	for (su1 = cs, su2 = ct; 0 < count; ++su1, ++su2, count--)
		if ((res = *su1 - *su2) != 0)
			break;
	return res;
}

/**
 * memset - Fill a region of memory with the given value
 * @s: Pointer to the start of the area.
 * @c: The byte to fill the area with
 * @count: The size of the area.
 */
void *memset(void *s, int c, size_t count)
{
	char *xs = s;

	while (count--)
		*xs++ = c;
	return s;
}

/**
 * memcpy - Copies one area of memory to another
 * @dest: Destination
 * @src: Source
 * @n: The size to copy.
 */
void *memcpy(void *to, const void *from, size_t n)
{
	void *xto = to;
	size_t temp;

	if(!n)
		return xto;
	if((long)to & 1) {
		char *cto = to;
		const char *cfrom = from;
		*cto++ = *cfrom++;
		to = cto;
		from = cfrom;
		n--;
	}
	if((long)from & 1) {
		char *cto = to;
		const char *cfrom = from;
		for (; n; n--)
			*cto++ = *cfrom++;
		return xto;
	}
	if(n > 2 && (long)to & 2) {
		short *sto = to;
		const short *sfrom = from;
		*sto++ = *sfrom++;
		to = sto;
		from = sfrom;
		n -= 2;
	}
	if((long)from & 2) {
		short *sto = to;
		const short *sfrom = from;
		temp = n >> 1;
		for (; temp; temp--)
			*sto++ = *sfrom++;
		to = sto;
		from = sfrom;
		if(n & 1) {
			char *cto = to;
			const char *cfrom = from;
			*cto = *cfrom;
		}
		return xto;
	}
	temp = n >> 2;
	if(temp) {
		long *lto = to;
		const long *lfrom = from;
		for(; temp; temp--)
			*lto++ = *lfrom++;
		to = lto;
		from = lfrom;
	}
	if(n & 2) {
		short *sto = to;
		const short *sfrom = from;
		*sto++ = *sfrom++;
		to = sto;
		from = sfrom;
	}
	if(n & 1) {
		char *cto = to;
		const char *cfrom = from;
		*cto = *cfrom;
	}
	return xto;
}

/**
 * memmove - Copies one area of memory to another, overlap possible
 * @dest: Destination
 * @src: Source
 * @n: The size to copy.
 */
void *memmove(void *dest, const void *src, size_t count)
{
	char *tmp, *s;

	if(dest <= src) {
		tmp = (char *) dest;
		s = (char *) src;
		while(count--)
			*tmp++ = *s++;
	} else {
		tmp = (char *)dest + count;
		s = (char *)src + count;
		while(count--)
			*--tmp = *--s;
	}

	return dest;
}

/**
 * strstr - Find the first substring in a %NUL terminated string
 * @s1: The string to be searched
 * @s2: The string to search for
 */
char *strstr(const char *s1, const char *s2)
{
	size_t l1, l2;

	l2 = strlen(s2);
	if (!l2)
		return (char *)s1;
	l1 = strlen(s1);
	while (l1 >= l2) {
		l1--;
		if (!memcmp(s1, s2, l2))
			return (char *)s1;
		s1++;
	}
	return NULL;
}

/**
 * memchr - Find a character in an area of memory.
 * @s: The memory area
 * @c: The byte to search for
 * @n: The size of the area.
 *
 * returns the address of the first occurrence of @c, or %NULL
 * if @c is not found
 */
void *memchr(const void *s, int c, size_t n)
{
	const unsigned char *p = s;
	while (n-- != 0) {
        	if ((unsigned char)c == *p++) {
			return (void *)(p - 1);
		}
	}
	return NULL;
}

/**
 * strtoul - convert a string to an unsigned long
 * @nptr: The start of the string
 * @endptr: A pointer to the end of the parsed string will be placed here
 * @base: The number base to use
 */
unsigned long strtoul(const char *nptr, char **endptr, int base)
{
	unsigned long result = 0,value;

	if (!base) {
		base = 10;
		if (*nptr == '0') {
			base = 8;
			nptr++;
			if ((toupper(*nptr) == 'X') && isxdigit(nptr[1])) {
				nptr++;
				base = 16;
			}
		}
	} else if (base == 16) {
		if (nptr[0] == '0' && toupper(nptr[1]) == 'X')
			nptr += 2;
	}
	while (isxdigit(*nptr) &&
	       (value = isdigit(*nptr) ? *nptr-'0' : toupper(*nptr)-'A'+10) < base) {
		result = result*base + value;
		nptr++;
	}
	if (endptr)
		*endptr = (char *)nptr;
	return result;
}

/**
 * strtol - convert a string to a signed long
 * @nptr: The start of the string
 * @endptr: A pointer to the end of the parsed string will be placed here
 * @base: The number base to use
 */
long strtol(const char *nptr, char **endptr, int base)
{
	if(*nptr=='-')
		return -strtoul(nptr+1,endptr,base);
	return strtoul(nptr,endptr,base);
}

/**
 * rand - Returns a pseudo random number
 */

static unsigned int randseed;
unsigned int rand(void)
{
	randseed = 129 * randseed + 907633385;
	return randseed;
}

void srand(unsigned int seed)
{
	randseed = seed;
}

void abort(void)
{
	printf("Aborted.");
	while(1);
}
