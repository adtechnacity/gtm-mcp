#!/usr/bin/env python3
import asyncio
import json
import logging
import sys
import os
from typing import Any, Dict, List, Optional

import sqlite3

# Redirect logging to stderr
logging.basicConfig(
    level=logging.INFO,
    stream=sys.stderr,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("gtm-mcp-server")

from mcp.server import FastMCP

# Initialize the MCP server with a friendly name
mcp = FastMCP("gtm-mcp-server")

# Database initialization
def init_database():
    """Initialize SQLite database with required tables"""
    conn = sqlite3.connect('gtm_database.db')
    cursor = conn.cursor()
    
    # Create chatters table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS chatters (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            messages INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Create gtm_configs table for GTM configurations
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS gtm_configs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id TEXT NOT NULL,
            container_id TEXT NOT NULL,
            name TEXT NOT NULL,
            config_type TEXT NOT NULL,
            config_data TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Create gtm_components table for tracking created components
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS gtm_components (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            component_id TEXT NOT NULL,
            component_type TEXT NOT NULL,
            component_name TEXT NOT NULL,
            account_id TEXT NOT NULL,
            container_id TEXT NOT NULL,
            status TEXT DEFAULT 'active',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    conn.commit()
    conn.close()
    logger.info("Database initialized successfully")

# Initialize database on startup
init_database()

# GTM client initialization
gtm_client = None

def get_gtm_client():
    """Lazy initialization of GTM client"""
    global gtm_client
    if gtm_client is None:
        try:
            from gtm_client_fixed import GTMClient
            credentials_file = os.getenv('GTM_CREDENTIALS_FILE', 'credentials.json')
            token_file = os.getenv('GTM_TOKEN_FILE', 'token.json')
            gtm_client = GTMClient(credentials_file, token_file)
            logger.info("GTM client initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize GTM client: {e}")
            raise Exception(f"GTM authentication failed: {e}. Please ensure credentials.json is properly configured.")
    return gtm_client

# Load GTM components
try:
    from gtm_components import GTMComponentTemplates, GTMWorkflowBuilder
    HAS_GTM_COMPONENTS = True
    logger.info("GTM components loaded successfully")
except ImportError as e:
    logger.error(f"Failed to load GTM components: {e}")
    HAS_GTM_COMPONENTS = False

# ==================== CHATTER CRUD OPERATIONS ====================

@mcp.tool()
def get_top_chatters(limit: int = 10) -> dict:
    """Retrieve top chatters sorted by number of messages"""
    try:
        conn = sqlite3.connect('gtm_database.db')
        cursor = conn.cursor()
        
        cursor.execute("SELECT name, messages, created_at FROM chatters ORDER BY messages DESC LIMIT ?", (limit,))
        results = cursor.fetchall()
        conn.close()
        
        chatters = [{"name": name, "messages": messages, "created_at": created_at} for name, messages, created_at in results]
        
        return {
            "status": "success",
            "total_found": len(chatters),
            "chatters": chatters
        }
    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to get chatters: {str(e)}"
        }

@mcp.tool()
def add_chatter(name: str, messages: int = 0) -> dict:
    """Add a new chatter to the database"""
    try:
        conn = sqlite3.connect('gtm_database.db')
        cursor = conn.cursor()
        
        cursor.execute("INSERT INTO chatters (name, messages) VALUES (?, ?)", (name, messages))
        chatter_id = cursor.lastrowid
        conn.commit()
        conn.close()
        
        return {
            "status": "success",
            "message": f"Chatter '{name}' added successfully",
            "chatter_id": chatter_id,
            "name": name,
            "messages": messages
        }
    except sqlite3.IntegrityError:
        return {
            "status": "error",
            "message": f"Chatter '{name}' already exists"
        }
    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to add chatter: {str(e)}"
        }

@mcp.tool()
def update_chatter_messages(name: str, messages: int) -> dict:
    """Update message count for a chatter"""
    try:
        conn = sqlite3.connect('gtm_database.db')
        cursor = conn.cursor()
        
        cursor.execute("UPDATE chatters SET messages = ?, updated_at = CURRENT_TIMESTAMP WHERE name = ?", (messages, name))
        
        if cursor.rowcount == 0:
            conn.close()
            return {
                "status": "error",
                "message": f"Chatter '{name}' not found"
            }
        
        conn.commit()
        conn.close()
        
        return {
            "status": "success",
            "message": f"Updated '{name}' message count to {messages}",
            "name": name,
            "new_message_count": messages
        }
    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to update chatter: {str(e)}"
        }

@mcp.tool()
def delete_chatter(name: str) -> dict:
    """Delete a chatter from the database"""
    try:
        conn = sqlite3.connect('gtm_database.db')
        cursor = conn.cursor()
        
        cursor.execute("DELETE FROM chatters WHERE name = ?", (name,))
        
        if cursor.rowcount == 0:
            conn.close()
            return {
                "status": "error",
                "message": f"Chatter '{name}' not found"
            }
        
        conn.commit()
        conn.close()
        
        return {
            "status": "success",
            "message": f"Chatter '{name}' deleted successfully"
        }
    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to delete chatter: {str(e)}"
        }

@mcp.tool()
def search_chatters(search_term: str) -> dict:
    """Search chatters by name"""
    try:
        conn = sqlite3.connect('gtm_database.db')
        cursor = conn.cursor()
        
        cursor.execute("SELECT name, messages, created_at FROM chatters WHERE name LIKE ? ORDER BY messages DESC", (f'%{search_term}%',))
        results = cursor.fetchall()
        conn.close()
        
        chatters = [{"name": name, "messages": messages, "created_at": created_at} for name, messages, created_at in results]
        
        return {
            "status": "success",
            "search_term": search_term,
            "total_found": len(chatters),
            "chatters": chatters
        }
    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to search chatters: {str(e)}"
        }

# ==================== GTM CONFIG CRUD OPERATIONS ====================

@mcp.tool()
def save_gtm_config(account_id: str, container_id: str, name: str, config_type: str, config_data: dict) -> dict:
    """Save GTM configuration to database"""
    try:
        conn = sqlite3.connect('gtm_database.db')
        cursor = conn.cursor()
        
        config_json = json.dumps(config_data)
        
        cursor.execute('''
            INSERT INTO gtm_configs (account_id, container_id, name, config_type, config_data) 
            VALUES (?, ?, ?, ?, ?)
        ''', (account_id, container_id, name, config_type, config_json))
        
        config_id = cursor.lastrowid
        conn.commit()
        conn.close()
        
        return {
            "status": "success",
            "message": f"GTM config '{name}' saved successfully",
            "config_id": config_id,
            "account_id": account_id,
            "container_id": container_id,
            "name": name,
            "config_type": config_type
        }
    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to save GTM config: {str(e)}"
        }

@mcp.tool()
def get_gtm_configs(account_id: str = None, container_id: str = None, config_type: str = None) -> dict:
    """Get GTM configurations with optional filtering"""
    try:
        conn = sqlite3.connect('gtm_database.db')
        cursor = conn.cursor()
        
        query = "SELECT id, account_id, container_id, name, config_type, created_at FROM gtm_configs WHERE 1=1"
        params = []
        
        if account_id:
            query += " AND account_id = ?"
            params.append(account_id)
        
        if container_id:
            query += " AND container_id = ?"
            params.append(container_id)
        
        if config_type:
            query += " AND config_type = ?"
            params.append(config_type)
        
        query += " ORDER BY created_at DESC"
        
        cursor.execute(query, params)
        results = cursor.fetchall()
        conn.close()
        
        configs = [
            {
                "id": row[0],
                "account_id": row[1],
                "container_id": row[2],
                "name": row[3],
                "config_type": row[4],
                "created_at": row[5]
            }
            for row in results
        ]
        
        return {
            "status": "success",
            "total_found": len(configs),
            "configs": configs,
            "filters": {
                "account_id": account_id,
                "container_id": container_id,
                "config_type": config_type
            }
        }
    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to get GTM configs: {str(e)}"
        }

@mcp.tool()
def get_gtm_config_details(config_id: int) -> dict:
    """Get detailed GTM configuration by ID"""
    try:
        conn = sqlite3.connect('gtm_database.db')
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT id, account_id, container_id, name, config_type, config_data, created_at, updated_at 
            FROM gtm_configs WHERE id = ?
        ''', (config_id,))
        
        result = cursor.fetchone()
        conn.close()
        
        if not result:
            return {
                "status": "error",
                "message": f"GTM config with ID {config_id} not found"
            }
        
        config_data = json.loads(result[5])
        
        return {
            "status": "success",
            "config": {
                "id": result[0],
                "account_id": result[1],
                "container_id": result[2],
                "name": result[3],
                "config_type": result[4],
                "config_data": config_data,
                "created_at": result[6],
                "updated_at": result[7]
            }
        }
    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to get GTM config details: {str(e)}"
        }

@mcp.tool()
def delete_gtm_config(config_id: int) -> dict:
    """Delete GTM configuration by ID"""
    try:
        conn = sqlite3.connect('gtm_database.db')
        cursor = conn.cursor()
        
        cursor.execute("DELETE FROM gtm_configs WHERE id = ?", (config_id,))
        
        if cursor.rowcount == 0:
            conn.close()
            return {
                "status": "error",
                "message": f"GTM config with ID {config_id} not found"
            }
        
        conn.commit()
        conn.close()
        
        return {
            "status": "success",
            "message": f"GTM config with ID {config_id} deleted successfully"
        }
    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to delete GTM config: {str(e)}"
        }

# ==================== GTM COMPONENT TRACKING ====================

@mcp.tool()
def track_gtm_component(component_id: str, component_type: str, component_name: str, account_id: str, container_id: str) -> dict:
    """Track a GTM component that was created"""
    try:
        conn = sqlite3.connect('gtm_database.db')
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO gtm_components (component_id, component_type, component_name, account_id, container_id) 
            VALUES (?, ?, ?, ?, ?)
        ''', (component_id, component_type, component_name, account_id, container_id))
        
        tracking_id = cursor.lastrowid
        conn.commit()
        conn.close()
        
        return {
            "status": "success",
            "message": f"GTM component '{component_name}' tracked successfully",
            "tracking_id": tracking_id,
            "component_id": component_id,
            "component_type": component_type,
            "component_name": component_name
        }
    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to track GTM component: {str(e)}"
        }

@mcp.tool()
def get_gtm_components(account_id: str = None, container_id: str = None, component_type: str = None) -> dict:
    """Get tracked GTM components with optional filtering"""
    try:
        conn = sqlite3.connect('gtm_database.db')
        cursor = conn.cursor()
        
        query = '''
            SELECT component_id, component_type, component_name, account_id, container_id, status, created_at 
            FROM gtm_components WHERE 1=1
        '''
        params = []
        
        if account_id:
            query += " AND account_id = ?"
            params.append(account_id)
        
        if container_id:
            query += " AND container_id = ?"
            params.append(container_id)
        
        if component_type:
            query += " AND component_type = ?"
            params.append(component_type)
        
        query += " ORDER BY created_at DESC"
        
        cursor.execute(query, params)
        results = cursor.fetchall()
        conn.close()
        
        components = [
            {
                "component_id": row[0],
                "component_type": row[1],
                "component_name": row[2],
                "account_id": row[3],
                "container_id": row[4],
                "status": row[5],
                "created_at": row[6]
            }
            for row in results
        ]
        
        return {
            "status": "success",
            "total_found": len(components),
            "components": components,
            "filters": {
                "account_id": account_id,
                "container_id": container_id,
                "component_type": component_type
            }
        }
    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to get GTM components: {str(e)}"
        }

# ==================== DATABASE MANAGEMENT ====================

@mcp.tool()
def get_database_stats() -> dict:
    """Get database statistics"""
    try:
        conn = sqlite3.connect('gtm_database.db')
        cursor = conn.cursor()
        
        # Count chatters
        cursor.execute("SELECT COUNT(*) FROM chatters")
        chatter_count = cursor.fetchone()[0]
        
        # Count GTM configs
        cursor.execute("SELECT COUNT(*) FROM gtm_configs")
        config_count = cursor.fetchone()[0]
        
        # Count GTM components
        cursor.execute("SELECT COUNT(*) FROM gtm_components")
        component_count = cursor.fetchone()[0]
        
        # Get recent activity
        cursor.execute("""
            SELECT 'chatter' as type, name as item, created_at 
            FROM chatters 
            UNION ALL
            SELECT 'config' as type, name as item, created_at 
            FROM gtm_configs
            UNION ALL
            SELECT 'component' as type, component_name as item, created_at 
            FROM gtm_components
            ORDER BY created_at DESC 
            LIMIT 10
        """)
        recent_activity = cursor.fetchall()
        
        conn.close()
        
        return {
            "status": "success",
            "database_stats": {
                "total_chatters": chatter_count,
                "total_gtm_configs": config_count,
                "total_gtm_components": component_count
            },
            "recent_activity": [
                {
                    "type": row[0],
                    "item": row[1],
                    "created_at": row[2]
                }
                for row in recent_activity
            ]
        }
    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to get database stats: {str(e)}"
        }

# Run the MCP server locally
if __name__ == '__main__':
    logger.info("Starting MCP Server with SQLite database...")
    mcp.run()