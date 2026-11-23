theorem qlean_contract : ∀ P Q : Prop, (P → P → Q) → P → Q := fun P Q f p => f p p
