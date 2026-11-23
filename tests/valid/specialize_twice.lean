theorem qlean_specialize_twice (P : Nat → Nat → Prop) (h : ∀ n m : Nat, P n m) : P 0 1 := h 0 1
