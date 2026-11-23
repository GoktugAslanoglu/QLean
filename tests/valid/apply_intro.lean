theorem qlean_apply_intro : ∀ P Q : Prop, (P → Q) → P → Q := by
  intro P Q f h
  apply f
  exact h
