# Inference policy

`provider_policy.py` implements the deterministic data-class gate from
ADR-016 without provider SDKs or network access. L0 requires explicit provider
approval. L1 also requires zero-data-retention and encryption. L2 additionally
requires contractual and operational disclosures plus completed independent
assurance; `in_progress` is insufficient. L3 and unknown inputs fail closed.

Use the offline CLI with a JSON file or stdin:

```text
python provider_policy_cli.py fixtures/l0-inferx-like.json
type request.json | python provider_policy_cli.py -
```

The CLI writes one compact JSON object. Exit `0` means allowed, `2` means the
policy denied the request, and `3` means malformed JSON/request input. It never
contacts a provider or echoes the original payload.

Run all offline tests from this directory with:

```text
python -m unittest -v test_provider_policy.py test_provider_policy_cli.py
```
