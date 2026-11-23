#include "internal.h"

enum { PRINT_TASKS = 24, FIELD_LIMIT = QLEAN_DIAGNOSTIC_BYTES - 4 };

typedef struct {
    char *buffer;
    unsigned used;
    unsigned clipped;
} Writer;

typedef struct {
    const char *literal;
    Id term;
    uint8_t bound;
} Task;

static QLeanDiagnostic diagnostic;
static Task tasks[PRINT_TASKS];

const QLeanDiagnostic *qlean_diagnostic(void) { return &diagnostic; }

static void byte(Writer *w, unsigned c)
{
    static const char hex[] = "0123456789ABCDEF";
    int escape = c < 32 || c >= 127 || c == '"' || c == '\\';
    if (w->clipped || w->used + (escape ? 4u : 1u) > FIELD_LIMIT) {
        w->clipped = 1;
    } else if (escape) {
        w->buffer[w->used++] = '\\';
        w->buffer[w->used++] = 'x';
        w->buffer[w->used++] = hex[c >> 4];
        w->buffer[w->used++] = hex[c & 15];
    } else {
        w->buffer[w->used++] = (char)c;
    }
}

static void literal(Writer *w, const char *s)
{
    while (*s && !w->clipped)
        byte(w, (uint8_t)*s++);
}

static void finish(Writer *w)
{
    if (w->clipped) {
        w->buffer[w->used++] = '.';
        w->buffer[w->used++] = '.';
        w->buffer[w->used++] = '.';
    }
    w->buffer[w->used] = 0;
}

static void unsigned_decimal(Writer *w, uint32_t value)
{
    uint32_t place = 1000000000;
    while (value < place && place > 1)
        place /= 10;
    for (; place; place /= 10) {
        byte(w, '0' + value / place);
        value %= place;
    }
}

static void variable(Writer *w, Id index, uint8_t bound)
{
    if (index >= bound && index - bound < ql.scope) {
        Binding binding = ql.context[ql.scope - 1 - (index - bound)];
        if (binding.length) {
            for (uint8_t i = 0; i < binding.length && !w->clipped; ++i)
                byte(w, ql.source[binding.at + i]);
            return;
        }
    }
    byte(w, '#');
    unsigned_decimal(w, index);
}

/* Render already allocated core terms. Diagnostics never run the evaluator,
 * allocate nodes or recurse, even when the failing term is very large. */
static void term(Writer *w, Id id)
{
    static const char *const names[K_COUNT] = {
        "Nat", "Nat.succ", "Nat.add", "@Eq", "@Eq.refl", "@Eq.subst", "@Nat.rec"
    };
    unsigned count = 1;
    tasks[0] = (Task){NULL, id, 0};
    while (count && !w->clipped) {
        Task task = tasks[--count];
        if (task.literal != NULL) {
            literal(w, task.literal);
            continue;
        }
        Node n = nodes[task.term];
        switch (n.tag) {
        case C_SORT:
            literal(w, n.a == 0 ? "Prop" : "Type");
            if (n.a > 1) {
                byte(w, ' ');
                unsigned_decimal(w, n.a - 1u);
            }
            break;
        case C_VAR: variable(w, n.a, task.bound); break;
        case C_CONST: literal(w, names[n.a]); break;
        case C_NUM: unsigned_decimal(w, numeral(n)); break;
        case C_APP: case C_PI: case C_LAM: {
            if (count + 4 > PRINT_TASKS) {
                w->clipped = 1;
                break;
            }
            const char *join = n.tag == C_PI ? " -> " : n.tag == C_LAM ? " => " : " ";
            Id left = n.a;
            if (n.tag == C_APP && nodes[n.a].tag == C_APP) {
                Node partial = nodes[n.a];
                Node head = nodes[partial.a];
                if (head.tag == C_CONST && head.a == K_ADD) {
                    join = " + ";
                    left = partial.b;
                } else if (head.tag == C_APP && nodes[head.a].tag == C_CONST
                           && nodes[head.a].a == K_EQ) {
                    join = " = ";
                    left = partial.b;
                }
            }
            literal(w, n.tag == C_LAM ? "(fun " : "(");
            tasks[count++] = (Task){")", 0, 0};
            tasks[count++] = (Task){NULL, n.b, (uint8_t)(task.bound + (n.tag != C_APP))};
            tasks[count++] = (Task){join, 0, 0};
            tasks[count++] = (Task){NULL, left, task.bound};
            break;
        }
        default: literal(w, "unavailable"); break;
        }
    }
}

static void describe(char *buffer, const char *label, Id id)
{
    Writer w = {buffer, 0, 0};
    if (label != NULL)
        literal(&w, label);
    else
        term(&w, id);
    finish(&w);
}

Id type_mismatch(uint16_t at, Id expected, Id actual)
{
    if (ql.result.code == QLEAN_OK) {
        describe(diagnostic.expected, NULL, expected);
        describe(diagnostic.got, NULL, actual);
    }
    return fail(QLEAN_ERR_TYPE_MISMATCH, at);
}

Id shape_mismatch(uint16_t at, const char *expected, Id actual)
{
    if (ql.result.code == QLEAN_OK) {
        describe(diagnostic.expected, expected, 0);
        describe(diagnostic.got, NULL, actual);
    }
    return fail(QLEAN_ERR_TYPE_MISMATCH, at);
}

Id refl_mismatch(uint16_t at, Id expected, Id left)
{
    if (ql.result.code == QLEAN_OK) {
        describe(diagnostic.expected, NULL, expected);
        Writer w = {diagnostic.got, 0, 0};
        byte(&w, '(');
        term(&w, left);
        literal(&w, " = ");
        term(&w, left);
        byte(&w, ')');
        finish(&w);
    }
    return fail(QLEAN_ERR_TYPE_MISMATCH, at);
}

static void header_field(char *buffer, const uint8_t *header, size_t length, size_t start)
{
    Writer w = {buffer, 0, 0};
    if (start)
        literal(&w, "...");
    for (size_t i = start; i < length && !w.clipped; ++i)
        byte(&w, header[i]);
    finish(&w);
}

Id goal_mismatch(uint16_t at, const char *header, size_t length, uint16_t header_end)
{
    size_t difference = 0;
    while (difference < length && difference < header_end
           && (uint8_t)header[difference] == ql.source[difference])
        ++difference;
    size_t start = difference < 32 ? 0 : difference - 12;
    header_field(diagnostic.expected, (const uint8_t *)header, length, start);
    header_field(diagnostic.got, ql.source, header_end, start);
    return fail(QLEAN_ERR_GOAL_MISMATCH, at);
}
