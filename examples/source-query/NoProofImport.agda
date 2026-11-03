{-# OPTIONS --safe --warning=noUnsupportedIndexedMatch #-}
module NoProofImport where

open import Data.Nat.Base using (ℕ)
open import Relation.Binary.PropositionalEquality.Core using (_≡_)

reverseEquality : (m n : ℕ) → m ≡ n → n ≡ m
reverseEquality m n p = {! !}
