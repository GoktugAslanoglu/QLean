theorem qlean_iota_zero (P : Prop) (h k : P) : @Eq P (@Nat.rec (fun (n : Nat) => P) h (fun n ih => k) Nat.zero) h := rfl
