#include "qlean.h"

#include <stdio.h>
#include <string.h>

static uint8_t bytes[QLEAN_INPUT_BYTES + 1];
static uint8_t rows[QLEAN_CAPTURE_ROWS * QLEAN_ROW_BYTES + 1];

static int read_bounded(FILE *input, uint8_t *buffer, size_t capacity, size_t *length)
{
    *length = fread(buffer, 1, capacity, input);
    return ferror(input) == 0;
}

static void verdict(QLeanResult result)
{
    printf("QLEAN1 %s", qlean_code_name(result.code));
    if (result.code != QLEAN_OK) {
        if (result.offset == QLEAN_NO_OFFSET)
            printf(" -");
        else
            printf(" %u", (unsigned)result.offset);
    }
    if (result.code == QLEAN_ERR_TYPE_MISMATCH || result.code == QLEAN_ERR_GOAL_MISMATCH) {
        const QLeanDiagnostic *detail = qlean_diagnostic();
        printf(" expected=\"%s\" got=\"%s\"", detail->expected, detail->got);
    }
    putchar('\n');
}

int main(int argc, char **argv)
{
    const char *header = NULL;
    int mmio = 0;
    for (int i = 1; i < argc; ++i) {
        if (strcmp(argv[i], "--rows") == 0 && !mmio)
            mmio = 1;
        else if (strcmp(argv[i], "--goal") == 0 && header == NULL && i + 1 < argc)
            header = argv[++i];
        else {
            fputs("usage: qlean-host [--rows] [--goal 'theorem ... :='] < input\n", stderr);
            return 2;
        }
    }

    size_t length;
    if (mmio) {
        if (!read_bounded(stdin, rows, sizeof(rows), &length))
            return 2;
        if (length != sizeof(rows) - 1) {
            verdict((QLeanResult){QLEAN_ERR_TRANSPORT, QLEAN_NO_OFFSET});
            return 1;
        }
        uint16_t captured;
        QLeanResult status = qlean_capture(rows, bytes, &captured);
        if (status.code != QLEAN_OK) {
            verdict(status);
            return 1;
        }
        length = captured;
    } else if (!read_bounded(stdin, bytes, sizeof(bytes), &length)) {
        return 2;
    }

    QLeanResult result = qlean_check(bytes, length, header, header ? strlen(header) : 0);
    verdict(result);
    return result.code == QLEAN_OK ? 0 : 1;
}
