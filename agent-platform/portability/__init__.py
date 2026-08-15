"""Cortxt-ägd, formatneutral portabilitets- och tillståndspaket (ADR-012-komplement).

Cortxt äger det neutrala kontraktet; Hermes är en adapter/provider bakom porten
(samma mönster som adapters/inference i Fas 2A). Kärnan beror bara på de neutrala
artefakterna och importerar aldrig Hermes-runtime.
"""
