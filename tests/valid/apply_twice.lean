theorem qlean_apply_twice (P Q R : Prop) (f : P → Q) (g : Q → R) (h : P) : R := by
  apply g
  apply f
  exact h
