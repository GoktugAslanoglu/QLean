theorem qlean_iota_wrong_selection (P : Prop) (h k : P) : @Eq P (@Nat.rec (fun (n : Nat) => P) h (fun n ih => k) 1) h := rfl
