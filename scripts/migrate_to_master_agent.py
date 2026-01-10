"""
Migration script to update existing clinic phone numbers to use the master agent.

This script:
1. Fetches all active clinic phone numbers from the database
2. Updates each phone number in Retell to use the master agent
3. Sets the inbound_webhook_url for each phone number
4. Updates the database with new agent_id and webhook_url

Usage:
    python backend/scripts/migrate_to_master_agent.py [--dry-run]
"""

import asyncio
import sys
import os
import httpx
import logging
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.config import settings, supabase

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

RETELL_API_BASE = "https://api.retellai.com"


def _get_headers() -> dict:
    """Get Retell API headers"""
    return {
        "Authorization": f"Bearer {settings.retell_api_key}",
        "Content-Type": "application/json",
    }


async def migrate_phone_numbers(dry_run: bool = False):
    """
    Migrate all clinic phone numbers to use the master agent.
    
    Args:
        dry_run: If True, only log changes without applying them
    """
    if not settings.retell_api_key:
        logger.error("RETELL_API_KEY not set in environment")
        return {"success": False, "error": "Missing API key"}
    
    if not settings.retell_master_agent_id:
        logger.error("RETELL_MASTER_AGENT_ID not set in environment")
        return {"success": False, "error": "Missing master agent ID"}
    
    webhook_base = os.getenv("WEBHOOK_BASE_URL", "https://yourdomain.com")
    logger.info(f"Using webhook base URL: {webhook_base}")
    
    # Fetch all active phone numbers
    logger.info("Fetching clinic phone numbers from database...")
    response = supabase.table("clinic_phone_numbers").select(
        "id, clinic_id, phone_number, retell_phone_id, is_active"
    ).eq("is_active", True).execute()
    
    phone_numbers = response.data or []
    logger.info(f"Found {len(phone_numbers)} active phone numbers to migrate")
    
    if not phone_numbers:
        logger.info("No phone numbers to migrate")
        return {"success": True, "migrated": 0}
    
    migrated = 0
    failed = 0
    
    async with httpx.AsyncClient() as client:
        for phone in phone_numbers:
            phone_id = phone.get("retell_phone_id")
            phone_number = phone.get("phone_number")
            clinic_id = phone.get("clinic_id")
            
            if not phone_id:
                logger.warning(f"Phone number {phone_number} has no retell_phone_id, skipping")
                failed += 1
                continue
            
            # Construct webhook URL
            inbound_webhook_url = f"{webhook_base}/api/retell/inbound/{clinic_id}"
            
            logger.info(f"Migrating {phone_number} (clinic: {clinic_id})")
            logger.info(f"  Retell Phone ID: {phone_id}")
            logger.info(f"  Master Agent ID: {settings.retell_master_agent_id}")
            logger.info(f"  Webhook URL: {inbound_webhook_url}")
            
            if dry_run:
                logger.info("  [DRY RUN] Would update this phone number")
                migrated += 1
                continue
            
            try:
                # Update phone number in Retell
                update_response = await client.patch(
                    f"{RETELL_API_BASE}/update-phone-number/{phone_id}",
                    headers=_get_headers(),
                    json={
                        "inbound_agent_id": settings.retell_master_agent_id,
                        "inbound_webhook_url": inbound_webhook_url,
                        "metadata": {
                            "clinic_id": clinic_id,
                            "migrated": "true",
                        },
                    },
                    timeout=30.0,
                )
                
                if update_response.status_code >= 400:
                    logger.error(f"  Failed to update Retell: {update_response.text}")
                    failed += 1
                    continue
                
                logger.info(f"  ✓ Updated in Retell")
                
                # Update database
                supabase.table("clinic_phone_numbers").update({
                    "retell_agent_id": settings.retell_master_agent_id,
                    "webhook_url": inbound_webhook_url,
                }).eq("id", phone["id"]).execute()
                
                logger.info(f"  ✓ Updated in database")
                migrated += 1
                
            except Exception as e:
                logger.error(f"  ✗ Error: {e}")
                failed += 1
    
    logger.info("=" * 60)
    logger.info(f"Migration complete:")
    logger.info(f"  Total: {len(phone_numbers)}")
    logger.info(f"  Migrated: {migrated}")
    logger.info(f"  Failed: {failed}")
    
    return {"success": True, "migrated": migrated, "failed": failed}


async def main():
    """Main entry point"""
    dry_run = "--dry-run" in sys.argv
    
    if dry_run:
        logger.info("Running in DRY RUN mode - no changes will be made")
    
    logger.info("=" * 60)
    logger.info("Migrating clinic phone numbers to master agent")
    logger.info("=" * 60)
    
    result = await migrate_phone_numbers(dry_run=dry_run)
    
    if not result.get("success"):
        logger.error(f"Migration failed: {result.get('error')}")
        sys.exit(1)
    
    logger.info("Migration successful!")


if __name__ == "__main__":
    asyncio.run(main())

