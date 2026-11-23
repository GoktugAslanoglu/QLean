theorem qlean_apply_wrong (P Q R : Prop) (f : P → Q) (h : P) : R := by
  apply f
  exact h
