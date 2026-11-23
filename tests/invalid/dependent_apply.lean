theorem qlean_dependent_apply (P : Nat → Prop) (f : ∀ n : Nat, P n) : P 0 := by
  apply f
  exact f 0
