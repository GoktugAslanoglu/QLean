theorem qlean_transport_endpoints (A : Type) (P : A → Prop) (a b : A) (h : a = b) (k : P a) : P b := @Eq.subst A P b a h k
