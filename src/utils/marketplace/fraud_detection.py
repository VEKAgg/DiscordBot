"""
Marketplace Fraud Detection System
Identifies and prevents fraudulent marketplace activity
"""

import logging
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
from decimal import Decimal
from src.database.database import db

logger = logging.getLogger('VEKA.marketplace.fraud')

class FraudDetector:
    """
    Detects fraudulent marketplace activity
    
    Checks for:
    - Self-purchasing (buying own items)
    - Price manipulation (extreme prices)
    - Rapid transaction patterns
    - Suspicious buyer/seller behavior
    """
    
    def __init__(self):
        # Price thresholds for different conditions
        self.price_thresholds = {
            'new': (Decimal('0.01'), Decimal('50000')),
            'like_new': (Decimal('0.01'), Decimal('40000')),
            'good': (Decimal('0.01'), Decimal('30000')),
            'fair': (Decimal('0.01'), Decimal('20000')),
            'poor': (Decimal('0.01'), Decimal('10000')),
        }
        
        # Rapid transaction thresholds
        self.rapid_listing_threshold = 5  # listings per hour
        self.rapid_purchase_threshold = 3  # purchases per hour
    
    async def check_listing(self, seller_id: int, price: Decimal, 
                          condition: str, category_id: int) -> Tuple[bool, List[str]]:
        """
        Check if a new listing is suspicious
        
        Returns: (is_clean, list_of_warnings)
        """
        warnings = []
        
        # Check price range
        min_price, max_price = self.price_thresholds.get(condition, (Decimal('0'), Decimal('999999')))
        if price < min_price:
            warnings.append(f"Price below minimum threshold for {condition} items")
        elif price > max_price:
            warnings.append(f"Price above typical range for {condition} items")
        
        # Check for rapid listing (spam)
        recent_listings = await db.fetch_one(
            """SELECT COUNT(*) as count 
               FROM marketplace_listings 
               WHERE seller_id = $1 
               AND created_at > NOW() - INTERVAL '1 hour'""",
            seller_id
        )
        
        if recent_listings and recent_listings['count'] > self.rapid_listing_threshold:
            warnings.append(f"Rapid listing detected ({recent_listings['count']} items in last hour)")
        
        # Check seller reputation (new sellers with high-value items)
        seller_stats = await db.fetch_one(
            """SELECT total_sales, average_rating, review_count 
               FROM marketplace_seller_stats 
               WHERE user_id = $1""",
            seller_id
        )
        
        if seller_stats:
            if seller_stats['total_sales'] == 0 and price > Decimal('1000'):
                warnings.append("New seller listing high-value item")
            
            if seller_stats['average_rating'] and seller_stats['average_rating'] < 2.0:
                warnings.append("Seller has low rating")
        elif price > Decimal('500'):
            warnings.append("First-time seller listing high-value item")
        
        return len(warnings) == 0, warnings
    
    async def check_purchase(self, buyer_id: int, seller_id: int, 
                           listing_id: str, price: Decimal) -> Tuple[bool, Optional[str]]:
        """
        Check if a purchase transaction is suspicious
        
        Returns: (is_clean, reason_if_fraudulent)
        """
        # Check for self-purchase
        if buyer_id == seller_id:
            await self._flag_fraud(
                listing_id=listing_id,
                user_id=buyer_id,
                flag_type='self_purchase',
                severity='high',
                details={'price': str(price)}
            )
            return False, "Cannot purchase your own item"
        
        # Check for rapid purchases (potential scam)
        recent_purchases = await db.fetch_one(
            """SELECT COUNT(*) as count 
               FROM marketplace_transactions 
               WHERE buyer_id = $1 
               AND created_at > NOW() - INTERVAL '1 hour'""",
            buyer_id
        )
        
        if recent_purchases and recent_purchases['count'] > self.rapid_purchase_threshold:
            await self._flag_fraud(
                listing_id=listing_id,
                user_id=buyer_id,
                flag_type='rapid_purchases',
                severity='medium',
                details={'recent_count': recent_purchases['count'], 'price': str(price)}
            )
            return False, "Unusual purchasing pattern detected"
        
        # Check if buyer has history of disputes
        buyer_disputes = await db.fetch_one(
            """SELECT COUNT(*) as count 
               FROM marketplace_transactions 
               WHERE buyer_id = $1 
               AND status = 'disputed'""",
            buyer_id
        )
        
        if buyer_disputes and buyer_disputes['count'] > 2:
            await self._flag_fraud(
                listing_id=listing_id,
                user_id=buyer_id,
                flag_type='frequent_disputes',
                severity='medium',
                details={'dispute_count': buyer_disputes['count']}
            )
        
        return True, None
    
    async def check_offer(self, listing_id: str, buyer_id: int, 
                         seller_id: int, offer_price: Decimal) -> Tuple[bool, Optional[str]]:
        """
        Check if an offer is suspicious
        """
        # Check for self-offer
        if buyer_id == seller_id:
            return False, "Cannot make offer on your own item"
        
        # Get listing details
        listing = await db.fetch_one(
            "SELECT price FROM marketplace_listings WHERE id = $1",
            listing_id
        )
        
        if not listing:
            return False, "Listing not found"
        
        listing_price = listing['price']
        
        # Check for extremely low offers (less than 10% of asking price)
        if listing_price > 0 and offer_price / listing_price < Decimal('0.1'):
            return False, "Offer is too low (less than 10% of asking price)"
        
        # Check for excessive offers (more than 2x asking price)
        if offer_price / listing_price > Decimal('2.0'):
            await self._flag_fraud(
                listing_id=listing_id,
                user_id=buyer_id,
                flag_type='suspicious_high_offer',
                severity='low',
                details={'offer_price': str(offer_price), 'listing_price': str(listing_price)}
            )
        
        return True, None
    
    async def validate_transaction_completion(self, transaction_id: int) -> Tuple[bool, Optional[str]]:
        """
        Final validation before completing a transaction
        """
        # Get transaction details
        transaction = await db.fetch_one(
            """SELECT t.*, l.seller_id as actual_seller_id
               FROM marketplace_transactions t
               JOIN marketplace_listings l ON t.listing_id = l.id
               WHERE t.id = $1""",
            transaction_id
        )
        
        if not transaction:
            return False, "Transaction not found"
        
        # Verify seller hasn't changed
        if transaction['seller_id'] != transaction['actual_seller_id']:
            return False, "Listing ownership has changed"
        
        # Check if item is still available
        listing = await db.fetch_one(
            "SELECT status FROM marketplace_listings WHERE id = $1",
            transaction['listing_id']
        )
        
        if not listing or listing['status'] != 'active':
            return False, "Item is no longer available"
        
        return True, None
    
    async def _flag_fraud(self, listing_id: Optional[str], user_id: int,
                         flag_type: str, severity: str, details: Dict):
        """Record a fraud flag in the database"""
        try:
            import json
            await db.execute(
                """INSERT INTO marketplace_fraud_flags 
                   (listing_id, user_id, flag_type, severity, details)
                   VALUES ($1, $2, $3, $4, $5)""",
                listing_id, user_id, flag_type, severity, json.dumps(details)
            )
            logger.warning(f"Fraud flag created: {flag_type} for user {user_id}")
        except Exception as e:
            logger.error(f"Failed to create fraud flag: {str(e)}")
    
    async def get_user_risk_score(self, user_id: int) -> Tuple[int, List[Dict]]:
        """
        Calculate risk score for a user (0-100)
        Higher score = higher risk
        """
        risk_score = 0
        flags = []
        
        # Get unresolved fraud flags
        user_flags = await db.fetch_many(
            """SELECT flag_type, severity, created_at 
               FROM marketplace_fraud_flags 
               WHERE user_id = $1 
               AND is_resolved = FALSE""",
            user_id
        )
        
        severity_weights = {
            'low': 10,
            'medium': 25,
            'high': 50
        }
        
        for flag in user_flags:
            weight = severity_weights.get(flag['severity'], 10)
            risk_score += weight
            flags.append({
                'type': flag['flag_type'],
                'severity': flag['severity'],
                'date': flag['created_at']
            })
        
        # Cap at 100
        risk_score = min(risk_score, 100)
        
        return risk_score, flags
    
    async def is_user_blocked(self, user_id: int) -> Tuple[bool, Optional[str]]:
        """Check if user is blocked from marketplace"""
        blocked = await db.fetch_one(
            """SELECT blocked_until, blocked_reason 
               FROM user_security 
               WHERE user_id = $1 
               AND is_blocked = TRUE 
               AND (blocked_until IS NULL OR blocked_until > NOW())""",
            str(user_id)
        )
        
        if blocked:
            if blocked['blocked_until']:
                return True, f"Blocked until {blocked['blocked_until']}: {blocked['blocked_reason']}"
            else:
                return True, f"Permanently blocked: {blocked['blocked_reason']}"
        
        return False, None

# Global fraud detector instance
fraud_detector = FraudDetector()
