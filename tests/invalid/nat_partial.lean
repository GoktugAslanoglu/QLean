theorem qlean_nat_partial (n : Nat) : n = n := @Nat.rec (fun (k : Nat) => k = k) rfl (fun k ih => ih)
