#include <stddef.h>

void *memset(void *destination, int value, size_t length)
{
    unsigned char *out = destination;
    for (size_t i = 0; i < length; ++i)
        out[i] = (unsigned char)value;
    return destination;
}

void *memcpy(void *restrict destination, const void *restrict source, size_t length)
{
    unsigned char *out = destination;
    const unsigned char *in = source;
    for (size_t i = 0; i < length; ++i)
        out[i] = in[i];
    return destination;
}
