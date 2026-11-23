#include "internal.h"

static Id pi(Id domain, Id body) { return core(C_PI, domain, body); }
static Id var(unsigned i) { return core(C_VAR, (Id)i, 0); }
static Id sort(unsigned level) { return core(C_SORT, (Id)level, 0); }
static Id constant(Constant k, unsigned level) { return core(C_CONST, (Id)k, (Id)level); }
static Id app(Id fn, Id arg) { return core(C_APP, fn, arg); }

static Id equality(unsigned level, Id carrier, Id lhs, Id rhs)
{
    return app(app(app(constant(K_EQ, level), carrier), lhs), rhs);
}

void init_signatures(void)
{
    Id nat = constant(K_NAT, 0);
    Id prop = sort(0);
    ql.signatures[K_NAT][0] = sort(1);
    ql.signatures[K_SUCC][0] = pi(nat, nat);
    ql.signatures[K_ADD][0] = pi(nat, pi(nat, nat));

    for (unsigned u = 0; u < QL_MAX_SORT; ++u) {
        Id carrier = sort(u);
        /* A : Sort u, x : A, y : A */
        ql.signatures[K_EQ][u] = pi(carrier, pi(var(0), pi(var(1), prop)));
        /* A : Sort u, x : A */
        Id reflexive = equality(u, var(1), var(0), var(0));
        ql.signatures[K_REFL][u] = pi(carrier, pi(var(0), reflexive));
        /* A, motive, a, b, equality proof, motive a proof */
        Id result = app(var(4), var(2));
        Id premise = app(var(3), var(2));
        Id witness = equality(u, var(3), var(1), var(0));
        Id subjects = pi(var(1), pi(var(2), pi(witness, pi(premise, result))));
        ql.signatures[K_SUBST][u] = pi(carrier, pi(pi(var(0), prop), subjects));
    }

    /* Nat.rec at motive universe 0. Comments use the scope of each term. */
    Id motive = pi(nat, prop);
    Id base = app(var(0), number(0));                   /* m */
    Id hypothesis = app(var(2), var(0));                /* m z k */
    Id successor = app(constant(K_SUCC, 0), var(1));     /* m z k ih */
    Id conclusion = app(var(3), successor);             /* m z k ih */
    Id step = pi(nat, pi(hypothesis, conclusion));       /* m z */
    Id result = app(var(3), var(0));                    /* m z s t */
    ql.signatures[K_REC][0] = pi(motive, pi(base, pi(step, pi(nat, result))));
}

/* All binding operations use de Bruijn indices. A substitution also removes
 * the target binder. Under binders the inserted argument is shifted to avoid
 * capture; domains are outside the new binder's scope. */
static Id rewrite(Id id, unsigned cutoff, int delta, Id replacement)
{
    if (id == 0 || !enter())
        return 0;
    Node n = nodes[id];
    Id out = id;

    switch (n.tag) {
    case C_VAR:
        if (n.a == cutoff && replacement != 0) {
            out = cutoff == 0 ? replacement : rewrite(replacement, 0, (int)cutoff, 0);
        } else if (n.a >= cutoff) {
            int index = n.a + delta;
            if (index < (int)cutoff || (uint32_t)index > UINT16_MAX)
                out = fail(QLEAN_ERR_TACTIC, ql.focus);
            else if (index != n.a)
                out = var((unsigned)index);
        }
        break;
    case C_PI: case C_LAM: case C_APP: {
        Id a = rewrite(n.a, cutoff, delta, replacement);
        Id b = rewrite(n.b, cutoff + (n.tag != C_APP), delta, replacement);
        if (a != n.a || b != n.b)
            out = core((Tag)n.tag, a, b);
        break;
    }
    default:
        break;
    }
    leave();
    return out;
}

Id instantiate(Id body, Id argument)
{
    return argument == 0 ? 0 : rewrite(body, 0, -1, argument);
}

Id lower(Id body)
{
    return rewrite(body, 0, -1, 0);
}

static Id unapply(Id term, Id *args, unsigned count)
{
    while (count != 0 && nodes[term].tag == C_APP) {
        args[--count] = nodes[term].b;
        term = nodes[term].a;
    }
    return count == 0 ? term : 0;
}

static int is_const(Id id, Constant k)
{
    return nodes[id].tag == C_CONST && nodes[id].a == k;
}

/* Return true only for a constructor with a predecessor. A positive packed
 * literal represents the same natural as the corresponding successor. */
static Id predecessor(Id term)
{
    Node n = nodes[term];
    if (n.tag == C_NUM && numeral(n) != 0)
        return number(numeral(n) - 1);
    if (n.tag == C_APP && is_const(n.a, K_SUCC))
        return n.b;
    return 0;
}

static Id reduce_add(Id head, Id *args, Id original)
{
    Id right = whnf(args[1]);
    if (nodes[right].tag == C_NUM) {
        uint32_t b = numeral(nodes[right]);
        if (b == 0)
            return args[0];
        Id left = whnf(args[0]);
        if (nodes[left].tag == C_NUM) {
            uint32_t a = numeral(nodes[left]);
            if (UINT32_MAX - a < b)
                return fail(QLEAN_ERR_LIMIT, ql.focus);
            return number(a + b);
        }
    }
    Id pred = predecessor(right);
    if (pred == 0)
        return original;
    Id sum = app(app(head, args[0]), pred);
    return app(constant(K_SUCC, 0), sum);
}

static Id reduce_rec(Id head, Id *args, Id original)
{
    Id scrutinee = whnf(args[3]);
    if (nodes[scrutinee].tag == C_NUM && numeral(nodes[scrutinee]) == 0)
        return args[1];
    Id pred = predecessor(scrutinee);
    if (pred == 0)
        return original;
    Id recursive = app(app(app(app(head, args[0]), args[1]), args[2]), pred);
    return app(app(args[2], pred), recursive);
}

Id whnf(Id term)
{
    if (term == 0 || !enter())
        return 0;
    while (ql.result.code == QLEAN_OK) {
        if (ql.whnf_fuel == 0) {
            term = fail(QLEAN_ERR_FUEL, ql.focus);
            break;
        }
        --ql.whnf_fuel;
        Node n = nodes[term];
        if (n.tag != C_APP)
            break;
        Id fn = whnf(n.a);
        if (nodes[fn].tag == C_LAM) {
            term = instantiate(nodes[fn].b, n.b);
            continue;
        }
        if (fn != n.a)
            term = app(fn, n.b);

        Id args[4];
        Id reduced = term;
        Id head = unapply(term, args, 2);
        if (is_const(head, K_ADD)) {
            reduced = reduce_add(head, args, term);
        } else {
            head = unapply(term, args, 4);
            if (is_const(head, K_REC))
                reduced = reduce_rec(head, args, term);
        }
        if (reduced == term)
            break;
        term = reduced;
    }
    leave();
    return ql.result.code == QLEAN_OK ? term : 0;
}

int convert(Id lhs, Id rhs)
{
    if (lhs == 0 || rhs == 0 || !enter())
        return 0;
    int equal = lhs == rhs;
    if (!equal) {
        lhs = whnf(lhs);
        rhs = whnf(rhs);
        Node a = nodes[lhs], b = nodes[rhs];
        if (lhs != 0 && rhs != 0 && a.tag == b.tag) {
            switch (a.tag) {
            case C_PI: case C_LAM: case C_APP:
                equal = convert(a.a, b.a) && convert(a.b, b.b);
                break;
            default:
                equal = a.a == b.a && a.b == b.b;
                break;
            }
        } else if (a.tag == C_NUM && b.tag == C_APP) {
            equal = numeral(a) != 0 && is_const(b.a, K_SUCC)
                && convert(number(numeral(a) - 1), b.b);
        } else if (b.tag == C_NUM && a.tag == C_APP) {
            equal = numeral(b) != 0 && is_const(a.a, K_SUCC)
                && convert(a.b, number(numeral(b) - 1));
        }
    }
    leave();
    return ql.result.code == QLEAN_OK && equal;
}

int check_type(Id actual, Id expected, uint16_t at)
{
    if (convert(actual, expected))
        return 1;
    return type_mismatch(at, expected, actual);
}

static Id infer_binder(Node n)
{
    Id domain_sort = whnf(infer(n.a));
    if (nodes[domain_sort].tag != C_SORT)
        return shape_mismatch(n.at, "sort", domain_sort);
    if (!push(n.a, n.at, 0))
        return 0;
    Id body_type = infer(n.b);
    --ql.scope;
    if (n.tag == C_LAM)
        return pi(n.a, body_type);
    Id codomain_sort = whnf(body_type);
    if (nodes[codomain_sort].tag != C_SORT)
        return shape_mismatch(n.at, "sort", codomain_sort);
    unsigned i = nodes[domain_sort].a;
    unsigned j = nodes[codomain_sort].a;
    return sort(j == 0 ? 0 : (i > j ? i : j));
}

Id infer(Id term)
{
    if (term == 0 || !enter())
        return 0;
    Node n = nodes[term];
    Id type = 0;

    switch (n.tag) {
    case C_SORT:
        type = n.a >= QL_MAX_SORT ? fail(QLEAN_ERR_LIMIT, n.at) : sort(n.a + 1);
        break;
    case C_CONST:
        if (n.a < K_COUNT && n.b < QL_MAX_SORT)
            type = ql.signatures[n.a][n.b];
        break;
    case C_NUM:
        type = constant(K_NAT, 0);
        break;
    case C_VAR:
        if (n.a < ql.scope) {
            Binding b = ql.context[ql.scope - 1 - n.a];
            type = rewrite(b.type, 0, n.a + 1, 0);
        } else {
            fail(QLEAN_ERR_UNBOUND, n.at);
        }
        break;
    case C_PI: case C_LAM:
        type = infer_binder(n);
        break;
    case C_APP: {
        Id function = whnf(infer(n.a));
        Node shape = nodes[function];
        if (shape.tag == C_PI) {
            if (check_type(infer(n.b), shape.a, n.at))
                type = instantiate(shape.b, n.b);
        } else {
            shape_mismatch(n.at, "function type", function);
        }
        break;
    }
    default:
        break;
    }
    if (type == 0)
        shape_mismatch(n.at, "typed term", term);
    leave();
    return type;
}

/* Inspector for already typed proposition expressions. */
Id equality_head(Id type, Id args[3])
{
    Id head = unapply(whnf(type), args, 3);
    return is_const(head, K_EQ) ? head : 0;
}
