theorem qlean_exchange : ∀ P Q R : Prop, (P → Q → R) → Q → P → R := fun P Q R f q p => f p q
