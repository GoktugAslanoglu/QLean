theorem qlean_bad_iota_erased : @Eq (0 = 0) (@Nat.rec (fun (n : Nat) => 0 = 0) rfl (fun n ih => 0) 0) (Eq.refl 0) := rfl
