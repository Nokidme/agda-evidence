"""Versioned JSON schemas distributed with agda-evidence.

Use ``importlib.resources.files('agda_evidence.schemas')`` to read resources.
Keep related schemas together when exporting them: several use relative $refs.
These schemas describe structure; the existing offline verifiers additionally
check semantic identities and evidence bindings without a jsonschema dependency.
"""
