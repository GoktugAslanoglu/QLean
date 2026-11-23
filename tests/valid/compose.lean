theorem qlean_compose : ∀ P Q R : Prop, (P → Q) → (Q → R) → P → R := fun P Q R f g h => g (f h)
