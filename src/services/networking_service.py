import logging
from datetime import datetime
from typing import Dict, List, Optional
from src.database.mongodb import db

logger = logging.getLogger('VEKA.networking')

# Collection references
_profiles = db.profiles
_connections = db.connections
_connection_requests = db.connection_requests


class NetworkingService:
    """DB layer for networking profiles and connections."""

    # ------------------------------------------------------------------
    # Profiles
    # ------------------------------------------------------------------

    async def get_profile(self, user_id: str) -> Optional[Dict]:
        """Return the profile document for *user_id*, or None."""
        return await _profiles.find_one({'user_id': user_id})

    async def upsert_profile(self, user_id: str, data: Dict) -> None:
        """Create or update a profile document for *user_id*."""
        data['user_id'] = user_id
        data['last_updated'] = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')
        await _profiles.update_one(
            {'user_id': user_id},
            {'$set': data},
            upsert=True
        )

    # ------------------------------------------------------------------
    # Connections
    # ------------------------------------------------------------------

    async def connection_exists(self, user1_id: str, user2_id: str) -> bool:
        """Return True if a connection between the two users exists."""
        doc = await _connections.find_one({
            '$or': [
                {'user1_id': user1_id, 'user2_id': user2_id},
                {'user1_id': user2_id, 'user2_id': user1_id},
            ]
        })
        return doc is not None

    async def create_connection(self, user1_id: str, user2_id: str) -> None:
        """Insert a new connection document between two users."""
        await _connections.insert_one({
            'user1_id': user1_id,
            'user2_id': user2_id,
            'connected_at': datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC'),
        })

    async def get_connections(self, user_id: str) -> List[Dict]:
        """Return all connection documents for *user_id*."""
        cursor = _connections.find({
            '$or': [
                {'user1_id': user_id},
                {'user2_id': user_id},
            ]
        })
        return await cursor.to_list(length=None)

    # ------------------------------------------------------------------
    # Connection requests
    # ------------------------------------------------------------------

    async def get_pending_request(
        self, from_user_id: str, to_user_id: str
    ) -> Optional[Dict]:
        """Return a pending request from *from_user_id* to *to_user_id*, or None."""
        return await _connection_requests.find_one({
            'user1_id': from_user_id,
            'user2_id': to_user_id,
            'status': 'pending',
        })

    async def create_request(
        self, from_user_id: str, to_user_id: str, message: str = ''
    ) -> None:
        """Insert a new pending connection request."""
        await _connection_requests.insert_one({
            'user1_id': from_user_id,
            'user2_id': to_user_id,
            'status': 'pending',
            'created_at': datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC'),
            'message': message or 'Would like to connect with you!',
        })

    async def update_request_status(
        self, request_id, status: str
    ) -> None:
        """Update the status field of a connection request document."""
        from bson import ObjectId
        await _connection_requests.update_one(
            {'_id': ObjectId(str(request_id))},
            {'$set': {'status': status}}
        )
