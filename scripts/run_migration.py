#!/usr/bin/env python3
"""
Script to run SQL migration for dispatch_log table.
Execute with: python3 run_migration.py
"""

import os
import sys

# Add the app directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()

from supabase import create_client

def run_migration():
    """Execute the dispatch_log migration."""

    supabase_url = os.getenv("SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_SERVICE_KEY")

    if not supabase_url or not supabase_key:
        print("ERROR: SUPABASE_URL or SUPABASE_SERVICE_KEY not set")
        return False

    print(f"Connecting to Supabase: {supabase_url[:30]}...")

    client = create_client(supabase_url, supabase_key)

    # Read migration file
    migration_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "migrations",
        "004_create_dispatch_log.sql"
    )

    with open(migration_path, "r") as f:
        migration_sql = f.read()

    print("Executing migration...")
    print("-" * 50)

    # Split into individual statements and execute
    # Remove comments and empty lines for cleaner execution
    statements = []
    current_stmt = []

    for line in migration_sql.split('\n'):
        stripped = line.strip()
        if stripped.startswith('--') or not stripped:
            continue
        current_stmt.append(line)
        if stripped.endswith(';'):
            statements.append('\n'.join(current_stmt))
            current_stmt = []

    # Execute via RPC - Supabase doesn't support raw SQL directly
    # We need to use the REST API or Dashboard
    print("Migration SQL ready. Please execute in Supabase Dashboard SQL Editor:")
    print("=" * 60)
    print(migration_sql)
    print("=" * 60)

    # Try to verify if table exists
    try:
        result = client.table("dispatch_log").select("id").limit(1).execute()
        print("\n✓ Table 'dispatch_log' already exists!")
        return True
    except Exception as e:
        if "does not exist" in str(e).lower() or "42P01" in str(e):
            print("\n✗ Table 'dispatch_log' does not exist yet.")
            print("Please run the migration SQL above in Supabase Dashboard.")
            return False
        else:
            print(f"\nNote: Could not verify table existence: {e}")
            return False

if __name__ == "__main__":
    run_migration()
