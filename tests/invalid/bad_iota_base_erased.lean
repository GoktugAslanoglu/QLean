theorem qlean_bad_iota_base_erased : @Eq (0 = 0) (@Nat.rec (fun (n : Nat) => 0 = 0) 0 (fun n ih => rfl) 1) (Eq.refl 0) := rfl
