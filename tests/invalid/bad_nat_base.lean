theorem qlean_bad_nat_base (n : Nat) : n = n := @Nat.rec (fun (k : Nat) => k = k) 0 (fun k ih => rfl) n
