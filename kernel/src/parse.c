#include "internal.h"

typedef enum {
    T_BAD, T_EOF, T_LF, T_ID, T_NUM, T_THEOREM, T_BY, T_INTRO,
    T_APPLY, T_EXACT, T_FORALL, T_FUN, T_ARROW, T_FATARROW, T_ASSIGN,
    T_COLON, T_COMMA, T_LP, T_RP, T_EQ, T_PLUS, T_SORT, T_BUILTIN
} TokenKind;

typedef struct {
    uint16_t at;
    uint16_t value;
    uint8_t kind;
    uint8_t size;
} Token;

typedef struct {
    Id first;
    Id last;
} List;

static int alpha(uint8_t c)
{
    return (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z');
}

static int digit(uint8_t c)
{
    return c >= '0' && c <= '9';
}

static int word(uint8_t c)
{
    return alpha(c) || digit(c) || c == '_';
}

static int spelling(Token t, const char *s)
{
    for (unsigned i = 0; i < t.size; ++i)
        if (s[i] == 0 || ql.source[t.at + i] != (uint8_t)s[i])
            return 0;
    return s[t.size] == 0;
}

static int prefix(Token t, const char *s)
{
    for (unsigned i = 0; s[i] != 0; ++i)
        if (i == t.size || ql.source[t.at + i] != (uint8_t)s[i])
            return 0;
    return 1;
}

static Token peek(void)
{
    static const struct {
        const char *text;
        uint8_t kind;
        uint8_t value;
    } words[] = {
        {"theorem", T_THEOREM, 0}, {"by", T_BY, 0}, {"intro", T_INTRO, 0},
        {"apply", T_APPLY, 0}, {"exact", T_EXACT, 0}, {"fun", T_FUN, 0},
        {"Prop", T_SORT, 0}, {"Type", T_SORT, 1},
        {"Nat", T_BUILTIN, B_NAT}, {"Nat.zero", T_BUILTIN, B_ZERO},
        {"Nat.succ", T_BUILTIN, B_SUCC}, {"Nat.add", T_BUILTIN, B_ADD},
        {"Eq", T_BUILTIN, B_EQ}, {"@Eq", T_BUILTIN, B_EXPLICIT_EQ},
        {"Eq.refl", T_BUILTIN, B_REFL}, {"rfl", T_BUILTIN, B_RFL},
        {"@Eq.subst", T_BUILTIN, B_SUBST}, {"@Nat.rec", T_BUILTIN, B_REC}
    };
    uint16_t p = ql.cursor;
    while (p < ql.length && ql.source[p] == ' ')
        ++p;
    Token t = {p, 0, T_BAD, 0};
    if (p >= ql.length) {
        t.kind = T_EOF;
        return t;
    }
    uint8_t c = ql.source[p++];
    t.size = 1;
    switch (c) {
    case '\n': t.kind = T_LF; return t;
    case '(': t.kind = T_LP; return t;
    case ')': t.kind = T_RP; return t;
    case ',': t.kind = T_COMMA; return t;
    case '+': t.kind = T_PLUS; return t;
    case ':':
        t.kind = T_COLON;
        if (p < ql.length && ql.source[p] == '=') {
            t.kind = T_ASSIGN;
            t.size = 2;
        }
        return t;
    case '=':
        t.kind = T_EQ;
        if (p < ql.length && ql.source[p] == '>') {
            t.kind = T_FATARROW;
            t.size = 2;
        }
        return t;
    case 0xe2:
        if (p + 1 < ql.length) {
            if (ql.source[p] == 0x88 && ql.source[p + 1] == 0x80)
                t.kind = T_FORALL;
            if (ql.source[p] == 0x86 && ql.source[p + 1] == 0x92)
                t.kind = T_ARROW;
        }
        if (t.kind != T_BAD)
            t.size = 3;
        return t;
    default:
        break;
    }

    if (!alpha(c) && c != '@' && !digit(c))
        return t;
    int plain = alpha(c);
    while (p < ql.length && (word(ql.source[p]) || ql.source[p] == '.')) {
        if (ql.source[p] == '.')
            plain = 0;
        ++p;
    }
    if (p - t.at > QL_MAX_NAME)
        return t;
    t.size = (uint8_t)(p - t.at);
    if (digit(c)) {
        uint32_t value = 0;
        for (uint16_t i = t.at; i < p; ++i) {
            if (!digit(ql.source[i]) || (t.size != 1 && c == '0'))
                return t;
            value = value * 10 + (uint32_t)(ql.source[i] - '0');
            if (value > UINT16_MAX) {
                fail(QLEAN_ERR_LIMIT, t.at);
                return t;
            }
        }
        t.kind = T_NUM;
        t.value = (uint16_t)value;
        return t;
    }
    for (unsigned i = 0; i < sizeof(words) / sizeof(words[0]); ++i) {
        if (spelling(t, words[i].text)) {
            t.kind = words[i].kind;
            t.value = words[i].value;
            return t;
        }
    }
    if (plain)
        t.kind = T_ID;
    return t;
}

static Token take(TokenKind kind, QLeanCode error)
{
    Token t = peek();
    if (t.kind == kind)
        ql.cursor = (uint16_t)(t.at + t.size);
    else
        fail(error, t.at);
    return t;
}

static int local_name(Token t)
{
    static const char *const reserved[] = {
#include "lean_keywords.inc"
    };
    if (t.kind != T_ID)
        return 0;
    unsigned lo = 0;
    unsigned hi = sizeof(reserved) / sizeof(*reserved);
    while (lo < hi) {
        unsigned mid = lo + (hi - lo) / 2;
        const char *word = reserved[mid];
        unsigned i = 0;
        while (i < t.size && word[i] != 0 && ql.source[t.at + i] == (uint8_t)word[i])
            ++i;
        int comparison = (i == t.size ? 0 : ql.source[t.at + i]) - (uint8_t)word[i];
        if (comparison == 0)
            return 0;
        if (comparison < 0)
            hi = mid;
        else
            lo = mid + 1;
    }
    return 1;
}

static Token binder_name(QLeanCode error)
{
    Token t = take(T_ID, error);
    if (!local_name(t))
        fail(error, t.at);
    return t;
}

static int theorem_name(Token t)
{
    if (!prefix(t, "qlean_") || t.size < 7)
        return 0;
    for (unsigned i = 6; i < t.size; ++i) {
        uint8_t c = ql.source[t.at + i];
        if ((c < 'a' || c > 'z') && !(i > 6 && (digit(c) || c == '_')))
            return 0;
    }
    return 1;
}

/* During parsing only, a binder or tactic chain has an open tail. */
static void append(List *list, Id member)
{
    if (member == 0)
        return;
    if (list->first == 0)
        list->first = member;
    else
        nodes[list->last].b = member;
    list->last = member;
}

static Id finish(List list, Id body)
{
    if (list.first == 0)
        return body;
    nodes[list.last].b = body;
    return list.first;
}

static Id expr(unsigned min);

static void names(List *list, Tag tag, QLeanCode error)
{
    do {
        Token t = binder_name(error);
        append(list, make(tag, 0, 0, t.at, t.size));
    } while (ql.result.code == QLEAN_OK && peek().kind == T_ID);
}

static void group(List *list, Tag tag, int parens)
{
    if (parens)
        take(T_LP, QLEAN_ERR_SYNTAX);
    Id previous = list->last;
    names(list, tag, QLEAN_ERR_SYNTAX);
    take(T_COLON, QLEAN_ERR_SYNTAX);
    Id domain = expr(0);
    if (parens)
        take(T_RP, QLEAN_ERR_SYNTAX);
    Id first = previous != 0 ? nodes[previous].b : list->first;
    /* Distinguish the shared annotation from separate source annotations. */
    for (Id id = first; id != 0; id = nodes[id].b)
        nodes[id].a = domain;
}

static int starts_atom(Token t)
{
    return t.kind == T_ID || t.kind == T_NUM || t.kind == T_SORT
        || t.kind == T_BUILTIN || t.kind == T_LP;
}

static Id atom(Token t)
{
    ql.cursor = (uint16_t)(t.at + t.size);
    switch ((TokenKind)t.kind) {
    case T_ID:
        if (!local_name(t))
            return fail(QLEAN_ERR_UNBOUND, t.at);
        return make(S_NAME, 0, 0, t.at, t.size);
    case T_NUM: return make(C_NUM, t.value, 0, t.at, 0);
    case T_SORT: return make(C_SORT, t.value, 0, t.at, 0);
    case T_BUILTIN: return make(S_SYM, t.value, 0, t.at, 0);
    case T_LP: {
        Id inside = expr(0);
        take(T_RP, QLEAN_ERR_SYNTAX);
        return inside;
    }
    default:
        return fail(QLEAN_ERR_SYNTAX, t.at);
    }
}

static Id lambda_or_forall(Token t)
{
    List binders = {0};
    ql.cursor = (uint16_t)(t.at + t.size);
    if (t.kind == T_FORALL) {
        if (peek().kind == T_LP) {
            do {
                group(&binders, S_PI, 1);
            } while (ql.result.code == QLEAN_OK && peek().kind == T_LP);
        } else {
            group(&binders, S_PI, 0);
        }
        take(T_COMMA, QLEAN_ERR_SYNTAX);
    } else {
        do {
            if (peek().kind == T_LP) {
                group(&binders, S_LAM, 1);
            } else {
                Token name = binder_name(QLEAN_ERR_SYNTAX);
                append(&binders, make(S_LAM, 0, 0, name.at, name.size));
            }
        } while (ql.result.code == QLEAN_OK
                 && (peek().kind == T_ID || peek().kind == T_LP));
        take(T_FATARROW, QLEAN_ERR_SYNTAX);
    }
    return finish(binders, expr(0));
}

/* Precedence follows Lean for the admitted operators. */
static Id expr(unsigned min)
{
    Token first = peek();
    ql.focus = first.at;
    if (!enter())
        return 0;
    Id lhs = 0;
    if (min == 0 && (first.kind == T_FORALL || first.kind == T_FUN)) {
        lhs = lambda_or_forall(first);
    } else if (starts_atom(first)) {
        lhs = atom(first);
        while (ql.result.code == QLEAN_OK) {
            Token op = peek();
            if (starts_atom(op) && op.at > ql.cursor) {
                Id arg = atom(op);
                lhs = make(S_APP, lhs, arg, op.at, 0);
                continue;
            }
            unsigned prec = op.kind == T_ARROW ? 1
                : op.kind == T_EQ ? 2 : op.kind == T_PLUS ? 3 : 0;
            if (prec == 0 || prec < min)
                break;
            ql.cursor = (uint16_t)(op.at + op.size);
            Id rhs = expr(prec + (op.kind != T_ARROW));
            if (op.kind == T_ARROW) {
                lhs = make(S_PI, lhs, rhs, op.at, 0);
            } else {
                if (op.kind == T_EQ && peek().kind == T_EQ)
                    fail(QLEAN_ERR_SYNTAX, peek().at);
                Id sym = make(S_SYM, op.kind == T_EQ ? B_EQ : B_ADD, 0, op.at, 0);
                lhs = make(S_APP, make(S_APP, sym, lhs, op.at, 0), rhs, op.at, 0);
            }
        }
    } else {
        fail(QLEAN_ERR_SYNTAX, first.at);
    }
    leave();
    return lhs;
}

static void tactics(List *list)
{
    int multiline = peek().kind == T_LF;
    if (multiline)
        take(T_LF, QLEAN_ERR_SYNTAX);
    while (ql.result.code == QLEAN_OK) {
        Token step = peek();
        if (multiline && step.at != ql.cursor + 2) {
            fail(QLEAN_ERR_SYNTAX, step.at);
            break;
        }
        ql.cursor = (uint16_t)(step.at + step.size);
        if (step.kind == T_EXACT || (step.kind == T_BUILTIN && step.value == B_RFL)) {
            Id proof = step.kind == T_EXACT ? expr(0)
                : make(S_SYM, B_RFL, 0, step.at, 0);
            append(list, make(S_EXACT, proof, 0, step.at, 0));
            return;
        }
        if (!multiline) {
            fail(QLEAN_ERR_TACTIC, step.at);
            break;
        }
        if (step.kind == T_INTRO) {
            names(list, S_INTRO, QLEAN_ERR_TACTIC);
        } else if (step.kind == T_APPLY) {
            Token name = binder_name(QLEAN_ERR_TACTIC);
            append(list, make(S_APPLY, 0, 0, name.at, name.size));
        } else {
            fail(QLEAN_ERR_TACTIC, step.at);
        }
        take(T_LF, QLEAN_ERR_SYNTAX);
    }
}

Declaration parse(void)
{
    List header = {0};
    List proof = {0};
    Declaration decl = {0};
    Token start = take(T_THEOREM, QLEAN_ERR_SYNTAX);
    if (start.at != 0)
        fail(QLEAN_ERR_SYNTAX, start.at);
    Token name = take(T_ID, QLEAN_ERR_SYNTAX);
    if (!theorem_name(name))
        fail(QLEAN_ERR_SYNTAX, name.at);
    while (ql.result.code == QLEAN_OK && peek().kind == T_LP)
        group(&header, S_PI, 1);
    take(T_COLON, QLEAN_ERR_SYNTAX);
    Id statement = expr(0);
    take(T_ASSIGN, QLEAN_ERR_SYNTAX);
    decl.header_end = ql.cursor;
    decl.tactics = peek().kind == T_BY;
    for (Id id = header.first; id != 0; id = nodes[id].b) {
        Node binder = nodes[id];
        append(&proof, make(decl.tactics ? S_INTRO : S_LAM,
                            binder.a, 0, binder.at, binder.detail));
    }
    decl.statement = finish(header, statement);
    if (decl.tactics) {
        take(T_BY, QLEAN_ERR_SYNTAX);
        tactics(&proof);
        decl.proof = proof.first;
    } else {
        decl.proof = finish(proof, expr(0));
    }
    if (peek().kind == T_LF)
        take(T_LF, QLEAN_ERR_SYNTAX);
    if (ql.cursor != ql.length)
        fail(QLEAN_ERR_SYNTAX, peek().at);
    return decl;
}
