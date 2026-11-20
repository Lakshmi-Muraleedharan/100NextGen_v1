"""Fetch the LLM gateway API key from Azure Key Vault.

The key is never stored in the project. At run time we authenticate to the vault
with `DefaultAzureCredential`, which for the service principal (SPN) uses these
environment variables:

    AZURE_TENANT_ID, AZURE_CLIENT_ID, AZURE_CLIENT_SECRET

(or a managed identity / `az login` session when running interactively).
"""

from __future__ import annotations

import logging

from .errors import ConfigError

logger = logging.getLogger(__name__)


def fetch_api_key(vault_url: str, secret_name: str) -> str:
    """Return the secret value from the vault, or raise ConfigError with a clear reason."""
    try:
        from azure.identity import DefaultAzureCredential
        from azure.keyvault.secrets import SecretClient
    except ImportError as exc:
        raise ConfigError(
            "azure-identity and azure-keyvault-secrets are required: pip install -r requirements.txt"
        ) from exc

    logger.info("Fetching secret '%s' from %s", secret_name, vault_url)
    try:
        client = SecretClient(vault_url=vault_url, credential=DefaultAzureCredential())
        value = client.get_secret(secret_name).value
    except Exception as exc:  # azure raises many distinct types; all mean "no key"
        raise ConfigError(
            f"could not read secret '{secret_name}' from {vault_url} ({type(exc).__name__}). "
            "Check AZURE_TENANT_ID / AZURE_CLIENT_ID / AZURE_CLIENT_SECRET and the SPN's "
            "'get' permission on the vault."
        ) from exc
    if not value:
        raise ConfigError(f"secret '{secret_name}' in {vault_url} is empty")
    return value
