{-# OPTIONS --safe #-}
module Example where

open import Agda.Builtin.Nat

identity : Nat → Nat
identity n = n

private
  secret : Nat → Nat
  secret n = n
