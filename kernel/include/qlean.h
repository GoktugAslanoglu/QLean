#ifndef QLEAN_H
#define QLEAN_H

#include <stddef.h>
#include <stdint.h>

enum {
    QLEAN_CAPTURE_ROWS = 80,
    QLEAN_ROW_BYTES = 16,
    QLEAN_FRAME_BYTES = (QLEAN_CAPTURE_ROWS - 1) * QLEAN_ROW_BYTES,
    QLEAN_PREFIX_BYTES = 7,
    QLEAN_INPUT_BYTES = QLEAN_FRAME_BYTES - QLEAN_PREFIX_BYTES,
    QLEAN_DIAGNOSTIC_BYTES = 64,
    QLEAN_NO_OFFSET = UINT16_MAX
};

typedef enum {
    QLEAN_OK,
    QLEAN_ERR_TRANSPORT,
    QLEAN_ERR_SYNTAX,
    QLEAN_ERR_GOAL_MISMATCH,
    QLEAN_ERR_UNBOUND,
    QLEAN_ERR_TACTIC,
    QLEAN_ERR_TYPE_MISMATCH,
    QLEAN_ERR_LIMIT,
    QLEAN_ERR_INPUT_TOO_LONG,
    QLEAN_ERR_OOM,
    QLEAN_ERR_FUEL
} QLeanCode;

typedef struct {
    QLeanCode code;
    uint16_t offset;
} QLeanResult;

typedef struct {
    char expected[QLEAN_DIAGNOSTIC_BYTES];
    char got[QLEAN_DIAGNOSTIC_BYTES];
} QLeanDiagnostic;

/* Single guest instance. The input and optional trusted header are read-only
 * for the duration of the call. The header, if supplied, ends with :=. */
QLeanResult qlean_check(const uint8_t *source, size_t length,
                        const char *header, size_t header_length);
const char *qlean_code_name(QLeanCode code);
/* Quoted-field contents for the most recent type or goal mismatch. */
const QLeanDiagnostic *qlean_diagnostic(void);

/* Rows 1 through 80, excluding the unused row at the MMIO base. The
 * caller supplies a capture opened and closed by the trusted bridge. */
QLeanResult qlean_capture(const volatile uint8_t *rows, uint8_t *buffer,
                          uint16_t *length);

#endif
