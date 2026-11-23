theorem qlean_specialize_zero (P : Nat → Prop) (h : ∀ n : Nat, P n) : P 0 := h 0
