theorem qlean_bad_nat_motive (n : Nat) : n = n := @Nat.rec (fun (k : Nat) => Nat) 0 (fun k ih => k) n
