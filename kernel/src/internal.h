#ifndef QLEAN_INTERNAL_H
#define QLEAN_INTERNAL_H

#include "qlean.h"

enum {
    QL_NODES = 2048,
    QL_CONTEXT = 32,
    QL_DEPTH = 28,
    QL_WHNF_FUEL = 2048,
    QL_WORK_FUEL = 32768,
    QL_MAX_SORT = 3,
    QL_MAX_NAME = 63
};

typedef uint16_t Id;

typedef enum {
    S_NAME = 1, S_PI, S_LAM, S_APP, S_SYM, S_INTRO, S_APPLY, S_EXACT,
    C_VAR, C_PI, C_LAM, C_APP, C_SORT, C_CONST, C_NUM
} Tag;

typedef enum {
    K_NAT, K_SUCC, K_ADD, K_EQ, K_REFL, K_SUBST, K_REC, K_COUNT
} Constant;

typedef enum {
    B_NAT, B_ZERO, B_SUCC, B_ADD, B_EQ, B_EXPLICIT_EQ, B_REFL,
    B_SUBST, B_REC, B_RFL
} SurfaceBuiltin;

/* Index zero is permanently invalid. Nodes become immutable when allocated. */
typedef struct {
    Id a;
    Id b;
    uint16_t at;
    uint8_t tag;
    uint8_t detail;
} Node;

typedef struct {
    Id type;
    uint16_t at;
    uint8_t length;
} Binding;

typedef struct {
    const uint8_t *source;
    Binding context[QL_CONTEXT];
    Id signatures[K_COUNT][QL_MAX_SORT];
    QLeanResult result;
    uint32_t work;
    uint16_t length;
    uint16_t cursor;
    uint16_t focus;
    uint16_t next;
    uint16_t whnf_fuel;
    uint8_t scope;
    uint8_t depth;
} Checker;

typedef struct {
    Id statement;
    Id proof;
    uint16_t header_end;
    uint8_t tactics;
} Declaration;

extern Checker ql;
extern Node nodes[QL_NODES];

Id make(Tag tag, Id a, Id b, uint16_t at, uint8_t detail);
Id core(Tag tag, Id a, Id b);
Id number(uint32_t n);
uint32_t numeral(Node n);
Id fail(QLeanCode code, uint16_t at);
Id type_mismatch(uint16_t at, Id expected, Id actual);
Id shape_mismatch(uint16_t at, const char *expected, Id actual);
Id refl_mismatch(uint16_t at, Id expected, Id left);
Id goal_mismatch(uint16_t at, const char *header, size_t length, uint16_t header_end);
int enter(void);
void leave(void);
int charge(void);
int same_bytes(uint16_t a, uint16_t b, uint8_t length);

Declaration parse(void);
void init_signatures(void);
Id infer(Id term);
Id equality_head(Id type, Id args[3]);
Id whnf(Id term);
int convert(Id lhs, Id rhs);
int check_type(Id actual, Id expected, uint16_t at);
Id instantiate(Id body, Id argument);
Id lower(Id body);
int push(Id type, uint16_t at, uint8_t length);
Id lookup(Node name);
Id elaborate(Id term, Id expected);
Id tactic(Id term, Id goal);

#endif
