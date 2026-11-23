#include "internal.h"

Checker ql;
Node nodes[QL_NODES] __attribute__((section(".bss.ql_arena")));

_Static_assert(sizeof(Node) == 8, "arena layout");
_Static_assert(sizeof(nodes) == 16 * 1024, "arena partition");
_Static_assert(sizeof(Checker) <= 4096, "checker work partition");
_Static_assert(QL_NODES < UINT16_MAX, "16-bit node indices");

Id fail(QLeanCode code, uint16_t at)
{
    if (ql.result.code == QLEAN_OK) {
        ql.result.code = code;
        ql.result.offset = at;
    }
    return 0;
}

int charge(void)
{
    if (ql.result.code != QLEAN_OK)
        return 0;
    if (ql.work == 0)
        return fail(QLEAN_ERR_FUEL, ql.focus);
    --ql.work;
    return 1;
}

int enter(void)
{
    if (!charge())
        return 0;
    if (ql.depth == QL_DEPTH)
        return fail(QLEAN_ERR_OOM, ql.focus);
    ++ql.depth;
    return 1;
}

void leave(void)
{
    --ql.depth;
}

Id make(Tag tag, Id a, Id b, uint16_t at, uint8_t detail)
{
    if (ql.result.code != QLEAN_OK)
        return 0;
    if (ql.next == QL_NODES)
        return fail(QLEAN_ERR_OOM, at);
    Id id = ql.next++;
    nodes[id] = (Node){a, b, at, (uint8_t)tag, detail};
    return id;
}

Id core(Tag tag, Id a, Id b)
{
    return make(tag, a, b, ql.focus, 0);
}

Id number(uint32_t n)
{
    return core(C_NUM, (Id)n, (Id)(n >> 16));
}

uint32_t numeral(Node n)
{
    return n.a | ((uint32_t)n.b << 16);
}

int same_bytes(uint16_t a, uint16_t b, uint8_t length)
{
    for (uint8_t i = 0; i < length; ++i)
        if (ql.source[a + i] != ql.source[b + i])
            return 0;
    return 1;
}

int push(Id type, uint16_t at, uint8_t length)
{
    if (ql.result.code != QLEAN_OK)
        return 0;
    if (ql.scope == QL_CONTEXT)
        return fail(QLEAN_ERR_OOM, at);
    for (uint8_t i = 0; length != 0 && i < ql.scope; ++i) {
        Binding b = ql.context[i];
        if (b.length == length && same_bytes(b.at, at, length))
            return fail(QLEAN_ERR_UNBOUND, at);
    }
    ql.context[ql.scope++] = (Binding){type, at, length};
    return 1;
}

Id lookup(Node name)
{
    for (uint8_t i = ql.scope; i != 0; --i) {
        Binding b = ql.context[i - 1];
        if (b.length == name.detail && same_bytes(b.at, name.at, b.length))
            return core(C_VAR, (Id)(ql.scope - i), 0);
    }
    return fail(QLEAN_ERR_UNBOUND, name.at);
}

QLeanResult qlean_check(const uint8_t *source, size_t length,
                        const char *header, size_t header_length)
{
    if (length > QLEAN_INPUT_BYTES)
        return (QLeanResult){QLEAN_ERR_INPUT_TOO_LONG, QLEAN_INPUT_BYTES};
    if (source == NULL || (header == NULL && header_length != 0))
        return (QLeanResult){QLEAN_ERR_TRANSPORT, QLEAN_NO_OFFSET};
    ql = (Checker){0};
    ql.source = source;
    ql.length = (uint16_t)length;
    ql.next = 1;
    ql.work = QL_WORK_FUEL;
    ql.whnf_fuel = QL_WHNF_FUEL;
    ql.result.offset = QLEAN_NO_OFFSET;

    Declaration decl = parse();
    if (ql.result.code != QLEAN_OK)
        return ql.result;
    if (header != NULL) {
        if (header_length != decl.header_end)
            goal_mismatch(decl.header_end, header, header_length, decl.header_end);
        for (size_t i = 0; ql.result.code == QLEAN_OK && i < header_length; ++i)
            if (source[i] != (uint8_t)header[i])
                goal_mismatch((uint16_t)i, header, header_length, decl.header_end);
    }
    if (ql.result.code != QLEAN_OK)
        return ql.result;

    init_signatures();
    Id statement = elaborate(decl.statement, 0);
    Id sort = whnf(infer(statement));
    if (nodes[sort].tag != C_SORT || nodes[sort].a != 0)
        shape_mismatch(nodes[decl.statement].at, "Prop", sort);

    Id proof = decl.tactics ? tactic(decl.proof, statement)
                            : elaborate(decl.proof, statement);
    /* Independent pass over the closed, tactic-free core proof. */
    if (ql.result.code == QLEAN_OK)
        check_type(infer(proof), statement, nodes[decl.proof].at);
    return ql.result;
}

const char *qlean_code_name(QLeanCode code)
{
    static const char *const names[] = {
        "OK", "ERR_TRANSPORT", "ERR_SYNTAX", "ERR_GOAL_MISMATCH",
        "ERR_UNBOUND", "ERR_TACTIC", "ERR_TYPE_MISMATCH", "ERR_LIMIT",
        "ERR_INPUT_TOO_LONG", "ERR_OOM", "ERR_FUEL"
    };
    return (unsigned)code < sizeof(names) / sizeof(*names)
        ? names[code] : "ERR_TRANSPORT";
}

static int utf8(const uint8_t *bytes, unsigned length)
{
    unsigned i = 0;
    while (i < length) {
        uint8_t first = bytes[i++];
        if (first < 0x80)
            continue;
        unsigned count;
        uint8_t second_min = 0x80, second_max = 0xbf;
        if (first >= 0xc2 && first <= 0xdf) {
            count = 1;
        } else if (first >= 0xe0 && first <= 0xef) {
            count = 2;
            if (first == 0xe0)
                second_min = 0xa0;
            if (first == 0xed)
                second_max = 0x9f;
        } else if (first >= 0xf0 && first <= 0xf4) {
            count = 3;
            if (first == 0xf0)
                second_min = 0x90;
            if (first == 0xf4)
                second_max = 0x8f;
        } else {
            return 0;
        }
        if (length - i < count || bytes[i] < second_min || bytes[i] > second_max)
            return 0;
        ++i;
        for (unsigned more = 1; more < count; ++more, ++i)
            if ((bytes[i] & 0xc0) != 0x80)
                return 0;
    }
    return 1;
}

QLeanResult qlean_capture(const volatile uint8_t *rows, uint8_t *buffer,
                          uint16_t *length)
{
    const uint8_t prefix[QLEAN_PREFIX_BYTES] = {'Q','L','E','A','N','1','\n'};
    *length = 0;
    unsigned used = 0;
    unsigned have_gap = 0;
    for (unsigned i = 0; i < QLEAN_CAPTURE_ROWS; ++i) {
        unsigned padded = 0;
        for (unsigned j = 0; j < QLEAN_ROW_BYTES; ++j) {
            uint8_t byte = rows[i * QLEAN_ROW_BYTES + j];
            if (byte == 0) {
                padded = 1;
                if (j == 0)
                    have_gap = 1;
                continue;
            }
            if (i == QLEAN_CAPTURE_ROWS - 1)
                return (QLeanResult){QLEAN_ERR_INPUT_TOO_LONG, QLEAN_NO_OFFSET};
            if (byte == 255 || have_gap || padded)
                return (QLeanResult){QLEAN_ERR_TRANSPORT, QLEAN_NO_OFFSET};
            if (used < QLEAN_PREFIX_BYTES) {
                if (byte != prefix[used])
                    return (QLeanResult){QLEAN_ERR_TRANSPORT, QLEAN_NO_OFFSET};
            } else {
                buffer[used - QLEAN_PREFIX_BYTES] = byte;
            }
            ++used;
        }
    }
    if (used < QLEAN_PREFIX_BYTES || !utf8(buffer, used - QLEAN_PREFIX_BYTES))
        return (QLeanResult){QLEAN_ERR_TRANSPORT, QLEAN_NO_OFFSET};
    *length = (uint16_t)(used - QLEAN_PREFIX_BYTES);
    return (QLeanResult){QLEAN_OK, QLEAN_NO_OFFSET};
}
