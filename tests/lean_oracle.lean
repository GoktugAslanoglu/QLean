-- Official Lean oracle for the fragment's sort hierarchy and Nat recursor.
-- This file is a development test, not input to QLean.

/-- info: Prop : Type -/
#guard_msgs in
#check Prop

/-- info: Type : Type 1 -/
#guard_msgs in
#check Type

example :
    (m : Nat → Prop) → m Nat.zero →
    ((n : Nat) → m n → m (Nat.succ n)) →
    (n : Nat) → m n :=
  @Nat.rec

set_option pp.proofs true

/-- info: Eq.refl 0 -/
#guard_msgs in
#reduce (proofs := true) @Nat.rec (fun (_ : Nat) => 0 = 0)
  (Eq.refl 0) (fun _ ih => Eq.symm ih) Nat.zero

/-- info: Eq.symm (Eq.refl 0) -/
#guard_msgs in
#reduce (proofs := true) @Nat.rec (fun (_ : Nat) => 0 = 0)
  (Eq.refl 0) (fun _ ih => Eq.symm ih) (Nat.succ Nat.zero)
