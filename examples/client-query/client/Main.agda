{-# OPTIONS --safe #-}
module Main where

open import Agda.Builtin.Nat
import Example
open Example using () renaming (identity to importedIdentity)
