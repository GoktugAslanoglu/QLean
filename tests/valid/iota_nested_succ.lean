theorem qlean_iota_nested_succ (P : Prop) (h : P) : @Eq P (@Nat.rec (fun (n : Nat) => P) h (fun n ih => ih) 3) h := rfl
