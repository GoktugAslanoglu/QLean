theorem qlean_rec_cases (n : Nat) : n = n := @Nat.rec (fun (k : Nat) => k = k) rfl (fun k ih => rfl) n
