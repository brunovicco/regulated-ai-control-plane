"""Deterministic, synthetic-safe data classifier for Phase 1."""

import re

from regulated_ai.domain import DataClassification, DataItem

_DIGITS = re.compile(r"\D")
_SECRET_FIELD = re.compile(
    r"(?:password|passphrase|api[_-]?key|access[_-]?token|auth(?:entication)?[_-]?secret)",
    re.IGNORECASE,
)
_SECRET_VALUE = re.compile(
    r"(?:password|passphrase|api[_-]?key|access[_-]?token|authorization)\s*[:=]\s*\S+",
    re.IGNORECASE,
)
_ACCOUNT_FIELD = re.compile(
    r"(?:account|conta)[_-]?(?:id|identifier|number|numero)$", re.IGNORECASE
)


class DeterministicDataClassifier:
    """Detect only explicitly supported, deterministic identifiers."""

    def classify(self, item: DataItem) -> tuple[DataItem, ...]:
        """Add validated identifier labels without changing the raw value."""
        labels: set[DataClassification] = set()
        digits = _DIGITS.sub("", item.value)
        if _valid_brazil_identifier(digits, base_length=9):
            labels.add(DataClassification.BRAZIL_CPF)
            labels.add(DataClassification.PERSONAL_DIRECT_IDENTIFIER)
        if _valid_brazil_identifier(digits, base_length=12):
            labels.add(DataClassification.BRAZIL_CNPJ)
            labels.add(DataClassification.PERSONAL_DIRECT_IDENTIFIER)
        if _SECRET_FIELD.search(item.field) or _SECRET_VALUE.search(item.value):
            labels.add(DataClassification.AUTHENTICATION_SECRET)
        if item.value and _ACCOUNT_FIELD.search(item.field):
            labels.add(DataClassification.FINANCIAL_ACCOUNT_IDENTIFIER)
        return (
            DataItem(
                field=item.field,
                value=item.value,
                supplied_labels=item.supplied_labels,
                detected_labels=tuple(sorted(labels, key=str)),
            ),
        )


def _valid_brazil_identifier(value: str, *, base_length: int) -> bool:
    expected_length = base_length + 2
    if len(value) != expected_length or len(set(value)) == 1:
        return False
    base = [int(character) for character in value[:base_length]]
    if base_length == 9:
        first_weights = tuple(range(10, 1, -1))
        second_weights = tuple(range(11, 1, -1))
    else:
        first_weights = (5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2)
        second_weights = (6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2)
    first = _check_digit(base, first_weights)
    second = _check_digit([*base, first], second_weights)
    return value[-2:] == f"{first}{second}"


def _check_digit(numbers: list[int], weights: tuple[int, ...]) -> int:
    remainder = sum(number * weight for number, weight in zip(numbers, weights, strict=True)) % 11
    return 0 if remainder < 2 else 11 - remainder
