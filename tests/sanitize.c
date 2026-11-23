#include "qlean.h"

#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static uint32_t state = 0x8b547d31;

static uint32_t random_word(void)
{
    state ^= state << 13;
    state ^= state >> 17;
    state ^= state << 5;
    return state;
}

static void check(const uint8_t *source, size_t length)
{
    /* Allocate exactly the advertised bytes so ASan can see a cursor error. */
    uint8_t *input = malloc(length == 0 ? 1 : length);
    if (input == NULL)
        abort();
    memcpy(input, source, length);
    QLeanResult a = qlean_check(input, length, NULL, 0);
    QLeanDiagnostic diagnostic = *qlean_diagnostic();
    QLeanResult b = qlean_check(input, length, NULL, 0);
    assert(a.code >= QLEAN_OK && a.code <= QLEAN_ERR_FUEL);
    assert(a.offset == QLEAN_NO_OFFSET || a.offset <= length);
    assert(a.code == b.code && a.offset == b.offset);
    if (a.code == QLEAN_ERR_TYPE_MISMATCH) {
        const QLeanDiagnostic *again = qlean_diagnostic();
        assert(memchr(diagnostic.expected, 0, sizeof(diagnostic.expected)) != NULL);
        assert(memchr(diagnostic.got, 0, sizeof(diagnostic.got)) != NULL);
        assert(strcmp(diagnostic.expected, again->expected) == 0);
        assert(strcmp(diagnostic.got, again->got) == 0);
        assert(strpbrk(diagnostic.expected, "\n\r\"") == NULL);
        assert(strpbrk(diagnostic.got, "\n\r\"") == NULL);
    }
    free(input);
}

int main(void)
{
    static const char *const seeds[] = {
        "theorem qlean_tail : 0 = 0 := by \xe2",
        "theorem qlean_tail : 0 = 0 := by\n  \xe2",
        "theorem qlean_false : 2 + 2 = 5 := rfl",
        "theorem qlean_apply (P Q : Prop) (f : P → Q) (h : P) : Q := by\n"
        "  apply f\n  exact h\n",
        "theorem qlean_rec (n : Nat) : n = n := @Nat.rec "
        "(fun (k : Nat) => k = k) rfl (fun k ih => rfl) n",
        "theorem qlean_subst (A : Type) (P : A → Prop) (a b : A) (h : a = b)"
        " (k : P a) : P b := @Eq.subst A P a b h k"
    };
    static const uint8_t goal[] = "theorem qlean_goal : 0 = 0 := rfl";
    static const char header[] = "theorem qlean_goal : 0 = 0 \\\"\r\n";
    QLeanResult mismatch = qlean_check(goal, sizeof(goal) - 1, header, sizeof(header) - 1);
    assert(mismatch.code == QLEAN_ERR_GOAL_MISMATCH);
    assert(strstr(qlean_diagnostic()->expected, "\\x5C\\x22\\x0D\\x0A") != NULL);
    uint8_t bytes[QLEAN_INPUT_BYTES + 16];
    unsigned count = 0;
    for (unsigned i = 0; i < sizeof(seeds) / sizeof(*seeds); ++i) {
        size_t length = strlen(seeds[i]);
        memcpy(bytes, seeds[i], length);
        for (size_t prefix = 0; prefix <= length; ++prefix) {
            check(bytes, prefix);
            ++count;
        }
    }
    for (unsigned i = 0; i < 10000; ++i) {
        unsigned sample = random_word() % (sizeof(seeds) / sizeof(*seeds));
        size_t length;
        if ((i & 3) == 0) {
            length = random_word() % sizeof(bytes);
            for (size_t j = 0; j < length; ++j)
                bytes[j] = (uint8_t)random_word();
        } else {
            length = strlen(seeds[sample]);
            memcpy(bytes, seeds[sample], length);
            unsigned changes = random_word() % 8;
            for (unsigned j = 0; j <= changes; ++j) {
                size_t position = random_word() % length;
                bytes[position] = (uint8_t)random_word();
            }
        }
        check(bytes, length);
        ++count;
    }
    printf("ASan/UBSan: %u exact-length inputs, two checks per input\n", count);
}
