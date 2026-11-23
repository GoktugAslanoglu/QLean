theorem qlean_transport (A : Type) (P : A → Prop) (a b : A) (h : a = b) (k : P a) : P b := @Eq.subst A P a b h k
