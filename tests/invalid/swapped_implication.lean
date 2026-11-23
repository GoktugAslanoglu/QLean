theorem qlean_swapped_implication : ∀ P Q : Prop, (P → Q) → (Q → P) := fun P Q f h => f h
