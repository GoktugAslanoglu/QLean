theorem qlean_bad_nat_step (n : Nat) : n = n := @Nat.rec (fun (k : Nat) => k = k) rfl (fun k ih => 0) n
