theorem qlean_iota_succ (P : Prop) (h k : P) : @Eq P (@Nat.rec (fun (n : Nat) => P) h (fun n ih => k) (Nat.succ Nat.zero)) k := rfl
