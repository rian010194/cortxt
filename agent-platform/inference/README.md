# Inference policy

`provider_policy.py` implements the deterministic data-class gate from
ADR-016 without provider SDKs or network access. L0 requires explicit provider
approval. L1 also requires zero-data-retention and encryption. L2 additionally
requires contractual and operational disclosures plus completed independent
assurance; `in_progress` is insufficient. L3 and unknown inputs fail closed.

Run `python -m unittest -v test_provider_policy.py` from this directory.
