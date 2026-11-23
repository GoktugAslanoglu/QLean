#include "internal.h"

static Id constant(Constant k, unsigned u)
{
    return core(C_CONST, (Id)k, (Id)u);
}

static Id app(Id fn, Id arg)
{
    return core(C_APP, fn, arg);
}

static int universe(Id term)
{
    Id type = whnf(infer(term));
    if (nodes[type].tag != C_SORT) {
        shape_mismatch(nodes[term].at, "sort", type);
        return -1;
    }
    return nodes[type].a;
}

static Id polymorphic(Constant k, Id carrier)
{
    int u = universe(carrier);
    if (u < 0)
        return 0;
    if (u >= QL_MAX_SORT)
        return fail(QLEAN_ERR_LIMIT, ql.focus);
    return constant(k, (unsigned)u);
}

static Id reflexivity(Id expected, uint16_t at)
{
    Id args[3];
    Id head = equality_head(expected, args);
    if (head == 0)
        return shape_mismatch(at, "equality goal", expected);
    if (!convert(args[1], args[2]))
        return refl_mismatch(at, expected, args[1]);
    Id refl = constant(K_REFL, nodes[head].b);
    return app(app(refl, args[0]), args[1]);
}

static Id builtin(Node n, Id expected)
{
    switch (n.a) {
    case B_NAT: return constant(K_NAT, 0);
    case B_ZERO: return number(0);
    case B_SUCC: return constant(K_SUCC, 0);
    case B_ADD: return constant(K_ADD, 0);
    case B_RFL: return reflexivity(expected, n.at);
    default: return fail(QLEAN_ERR_SYNTAX, n.at);
    }
}

static Id check_arg(Id raw, Id expected)
{
    Id arg = elaborate(raw, expected);
    return check_type(infer(arg), expected, nodes[raw].at) ? arg : 0;
}

/* Elaborate an explicit telescope from left to right. Check each argument
 * before instantiating the tail or passing an expected type to a lambda. */
static Id explicit_args(Id fn, Id type, const Id *raw, unsigned count)
{
    for (unsigned i = 0; i < count; ++i) {
        Id head = whnf(type);
        Node shape = nodes[head];
        if (shape.tag != C_PI)
            return shape_mismatch(nodes[raw[i]].at, "function type", head);
        Id arg = check_arg(raw[i], shape.a);
        if (arg == 0)
            return 0;
        fn = app(fn, arg);
        if (i + 1 < count)
            type = instantiate(shape.b, arg);
    }
    return fn;
}

static Id special_args(SurfaceBuiltin kind, const Id *raw)
{
    if (kind == B_REC) {
        Id fn = constant(K_REC, 0);
        return explicit_args(fn, ql.signatures[K_REC][0], raw, 4);
    }

    Id first = elaborate(raw[0], 0);
    if (first == 0)
        return 0;
    if (kind == B_EQ || kind == B_REFL) {
        Id carrier = infer(first);
        Id fn = polymorphic(kind == B_EQ ? K_EQ : K_REFL, carrier);
        Id partial = app(app(fn, carrier), first);
        if (kind == B_REFL)
            return partial;
        return app(partial, check_arg(raw[1], carrier));
    }

    /* Fully explicit Eq and Eq.subst have a carrier as their first input. */
    Id fn = polymorphic(kind == B_EXPLICIT_EQ ? K_EQ : K_SUBST, first);
    if (fn == 0)
        return 0;
    Id signature = ql.signatures[nodes[fn].a][nodes[fn].b];
    Id tail = instantiate(nodes[signature].b, first);
    return explicit_args(app(fn, first), tail, raw + 1,
                         kind == B_EXPLICIT_EQ ? 2 : 5);
}

static Id application(Id term)
{
    Id args[6];
    Id head = term;
    unsigned start = 6;
    while (start != 0 && nodes[head].tag == S_APP) {
        args[--start] = nodes[head].b;
        head = nodes[head].a;
    }
    Node sym = nodes[head];
    if (sym.tag == S_SYM) {
        unsigned count = 6 - start;
        if ((sym.a == B_EQ && count == 2) || (sym.a == B_REFL && count == 1)
            || (sym.a == B_EXPLICIT_EQ && count == 3)
            || (sym.a == B_SUBST && count == 6) || (sym.a == B_REC && count == 4))
            return special_args((SurfaceBuiltin)sym.a, args + start);
    }
    Node n = nodes[term];
    Id fn = elaborate(n.a, 0);
    Id type = infer(fn);
    return explicit_args(fn, type, &n.b, 1);
}

static Id binder(Node n, Id expected)
{
    Node shape = nodes[whnf(expected)];
    Id domain = 0;
    if (n.a != 0) {
        domain = elaborate(n.a, 0);
        if (universe(domain) < 0)
            return 0;
    } else if (n.tag == S_LAM && shape.tag == C_PI) {
        domain = shape.a;
    } else {
        return shape_mismatch(n.at, "function type for an untyped binder", expected);
    }
    if (n.tag == S_LAM && shape.tag == C_PI && !check_type(domain, shape.a, n.at))
        return 0;
    if (!push(domain, n.at, n.detail))
        return 0;
    Id body = elaborate(n.b, n.tag == S_LAM && shape.tag == C_PI ? shape.b : 0);
    if (n.tag == S_PI)
        universe(body);
    --ql.scope;
    return core(n.tag == S_PI ? C_PI : C_LAM, domain, body);
}

Id elaborate(Id term, Id expected)
{
    if (term == 0 || !enter())
        return 0;
    Node n = nodes[term];
    ql.focus = n.at;
    Id result;
    switch (n.tag) {
    case C_SORT: case C_NUM: result = term; break;
    case S_NAME: result = lookup(n); break;
    case S_SYM: result = builtin(n, expected); break;
    case S_APP: result = application(term); break;
    case S_PI: case S_LAM: result = binder(n, expected); break;
    default: result = fail(QLEAN_ERR_SYNTAX, n.at); break;
    }
    leave();
    return result;
}

static int rigid(Id goal)
{
    Id head = whnf(goal);
    while (nodes[head].tag == C_APP)
        head = nodes[head].a;
    return nodes[head].tag == C_VAR
        || (nodes[head].tag == C_CONST && nodes[head].a == K_EQ);
}

Id tactic(Id term, Id goal)
{
    if (term == 0 || goal == 0 || !enter())
        return 0;
    Node n = nodes[term];
    ql.focus = n.at;
    Id result = 0;
    if (n.tag == S_INTRO) {
        Node shape = nodes[goal];
        if (shape.tag != C_PI) {
            fail(QLEAN_ERR_TACTIC, n.at);
        } else if (push(shape.a, n.at, n.detail)) {
            Id body = tactic(n.b, shape.b);
            --ql.scope;
            result = core(C_LAM, shape.a, body);
        }
    } else if (n.tag == S_APPLY) {
        Id fn = lookup(n);
        Node shape = nodes[whnf(infer(fn))];
        if (shape.tag == C_PI && rigid(goal) && convert(lower(shape.b), goal)) {
            Id premise = tactic(n.b, shape.a);
            result = app(fn, premise);
        } else {
            fail(QLEAN_ERR_TACTIC, n.at);
        }
    } else if (n.tag == S_EXACT) {
        result = elaborate(n.a, goal);
    } else {
        fail(QLEAN_ERR_TACTIC, n.at);
    }
    leave();
    return result;
}
