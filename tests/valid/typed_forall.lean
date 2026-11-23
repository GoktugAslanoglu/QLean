theorem qlean_typed_forall : ∀ (A : Type) (P : A → Prop) (a : A), (∀ x : A, P x) → P a := fun A P a h => h a
