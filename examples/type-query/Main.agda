{-# OPTIONS --safe #-}
module Main where

open import Agda.Builtin.Nat

identity : Nat → Nat
identity n = n

_⊕_ : Nat → Nat → Nat
m ⊕ n = m + n

private
  localIdentity : Nat → Nat
  localIdentity n = n
