#include "qlean.h"

enum {
    TEXT_MMIO = 0x8000,
    OPEN_RESPONSE = 256,
    CLOSE_RESPONSE = 257
};

static uint8_t source[QLEAN_INPUT_BYTES];

#ifdef QLEAN_CAPTURE_TELEMETRY
/* Phase 3 reads this and source from the committed RAM heads after HALT. */
static uint16_t source_length;
#endif

#ifdef QLEAN_GOAL_FILE
static const char trusted_header[] =
#include QLEAN_GOAL_FILE
;
#else
static const char trusted_header[] = "";
#endif

_Static_assert(sizeof(source) <= 4096, "input partition");

static void emit(unsigned value)
{
    register unsigned arg __asm__("a0") = value;
    register unsigned call __asm__("a7") = 1;
    __asm__ volatile("ecall" : "+r"(arg) : "r"(call) : "memory");
}

static void text(const char *s)
{
    for (; *s != 0; ++s)
        emit((uint8_t)*s);
}

static void decimal(uint16_t n)
{
    unsigned place = 10000;
    while (place > 1 && n < place)
        place /= 10;
    while (place != 0) {
        emit('0' + n / place);
        n = (uint16_t)(n % place);
        place /= 10;
    }
}

unsigned qlean_request(void)
{
#ifndef QLEAN_CAPTURE_TELEMETRY
    uint16_t source_length;
#endif
    QLeanResult result = qlean_capture(
        (const volatile uint8_t *)(TEXT_MMIO + QLEAN_ROW_BYTES),
        source, &source_length);
    if (result.code == QLEAN_OK)
        result = qlean_check(source, source_length,
                             sizeof(trusted_header) > 1 ? trusted_header : NULL,
                             sizeof(trusted_header) - 1);

    emit(OPEN_RESPONSE);
    text("QLEAN1 ");
    text(qlean_code_name(result.code));
    if (result.code != QLEAN_OK) {
        emit(' ');
        if (result.offset == QLEAN_NO_OFFSET)
            emit('-');
        else
            decimal(result.offset);
    }
    if (result.code == QLEAN_ERR_TYPE_MISMATCH || result.code == QLEAN_ERR_GOAL_MISMATCH) {
        const QLeanDiagnostic *detail = qlean_diagnostic();
        text(" expected=\"");
        text(detail->expected);
        text("\" got=\"");
        text(detail->got);
        emit('"');
    }
    emit('\n');
    emit(CLOSE_RESPONSE);
    return (unsigned)result.code;
}
