theorem qlean_rec_induction (n : Nat) : 0 + n = n := @Nat.rec (fun (k : Nat) => 0 + k = k) rfl (fun k ih => @Eq.subst Nat (fun (j : Nat) => Nat.succ (0 + k) = Nat.succ j) (0 + k) k ih rfl) n
