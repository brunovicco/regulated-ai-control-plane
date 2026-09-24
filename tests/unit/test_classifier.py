from regulated_ai.adapters.classifier import DeterministicDataClassifier
from regulated_ai.domain import DataClassification, DataItem

from ..helpers import synthetic_cnpj, synthetic_cpf


def test_classifier_detects_only_supported_structural_identifiers() -> None:
    classifier = DeterministicDataClassifier()

    cpf = classifier.classify(DataItem("document", synthetic_cpf()))[0]
    cnpj = classifier.classify(DataItem("company_document", synthetic_cnpj()))[0]
    account = classifier.classify(DataItem("account_identifier", "synthetic-account"))[0]
    secret = classifier.classify(DataItem("api_key", "synthetic-secret-sentinel"))[0]
    embedded_secret = classifier.classify(
        DataItem("message", "password=synthetic-secret-sentinel")
    )[0]

    assert DataClassification.BRAZIL_CPF in cpf.labels
    assert DataClassification.BRAZIL_CNPJ in cnpj.labels
    assert DataClassification.FINANCIAL_ACCOUNT_IDENTIFIER in account.labels
    assert DataClassification.AUTHENTICATION_SECRET in secret.labels
    assert DataClassification.AUTHENTICATION_SECRET in embedded_secret.labels


def test_classifier_rejects_invalid_check_digits_and_preserves_supplied_labels() -> None:
    classifier = DeterministicDataClassifier()
    item = DataItem(
        "free_text",
        "00000000000",
        supplied_labels=(DataClassification.FINANCIAL_TRANSACTION_DATA,),
    )

    result = classifier.classify(item)[0]

    assert result.labels == (DataClassification.FINANCIAL_TRANSACTION_DATA,)
