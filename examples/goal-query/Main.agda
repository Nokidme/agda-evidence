{-# OPTIONS --safe #-}
module Main where

open import Agda.Builtin.Nat
open import Agda.Builtin.Equality

identity : Nat → Nat
identity n = ?

unicodeIdentity : Nat → Nat
unicodeIdentity λ₁ = {! λ₁ !}

reflexive : (n : Nat) → n ≡ n
reflexive n = ?
