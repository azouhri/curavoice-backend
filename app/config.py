"""Application configuration and environment variables"""

import logging
import os
from typing import Optional
from pydantic_settings import BaseSettings
from supabase import create_client, Client

# Configure structured logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    """Application settings from environment variables"""

    # Supabase configuration
    supabase_url: str
    supabase_service_role_key: str

    # Vapi.ai configuration
    vapi_api_key: Optional[str] = None  # Private key for API authentication
    vapi_public_key: Optional[str] = None  # Public key (may be used for webhook verification)
    vapi_webhook_secret: Optional[str] = None  # Webhook secret for verification

    # Termii SMS/WhatsApp configuration
    termii_api_key: Optional[str] = None
    termii_secret_key: Optional[str] = None  # May be needed for some Termii features

    # Retell AI configuration
    retell_api_key: Optional[str] = None
    retell_master_agent_id: Optional[str] = None  # Master agent ID for multi-tenant conversation flow
    webhook_base_url: Optional[str] = None  # Base URL for webhooks (e.g., https://yourdomain.com)

    model_config = {
        "env_file": ".env",
        "case_sensitive": False,
        "extra": "ignore",  # Ignore extra environment variables (like NEXT_PUBLIC_*)
    }


# Global settings instance
settings = Settings()

# Supabase client with service role key (bypasses RLS for backend operations)
try:
    supabase: Client = create_client(
        settings.supabase_url,
        settings.supabase_service_role_key,
    )
    logger.info("Supabase client initialized successfully")
except Exception as e:
    logger.error(f"Failed to initialize Supabase client: {e}")
    raise

