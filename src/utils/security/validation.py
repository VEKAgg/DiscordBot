"""
Input Validation and Sanitization Utilities
Prevents injection attacks and malformed data
"""

import re
import html
import logging
from typing import Optional, List, Dict, Any

logger = logging.getLogger('VEKA.security.validation')

class InputValidator:
    """Validates and sanitizes user inputs"""
    
    # Profanity list (basic - expand as needed)
    PROFANITY = {
        'fuck', 'shit', 'bitch', 'asshole', 'damn',
        # Add more as needed
    }
    
    # Allowed URL schemes
    ALLOWED_SCHEMES = {'http', 'https'}
    
    @staticmethod
    def sanitize_text(text: str, max_length: int = 2000, allow_markdown: bool = False) -> str:
        """
        Sanitize text input
        
        Args:
            text: Input text
            max_length: Maximum allowed length
            allow_markdown: Whether to preserve markdown formatting
        
        Returns:
            Sanitized text
        """
        if not text:
            return ""
        
        # HTML escape to prevent injection
        text = html.escape(text)
        
        # Remove null bytes
        text = text.replace('\x00', '')
        
        # Limit length
        if len(text) > max_length:
            text = text[:max_length]
        
        if not allow_markdown:
            # Remove Discord markdown if not allowed
            text = re.sub(r'([*_~`>|])', r'\\\1', text)
        
        return text.strip()
    
    @staticmethod
    def validate_discord_id(discord_id: str) -> bool:
        """Validate Discord ID format (17-20 digits)"""
        if not discord_id:
            return False
        return bool(re.match(r'^\d{17,20}$', str(discord_id)))
    
    @staticmethod
    def validate_url(url: str, allowed_schemes: Optional[List[str]] = None) -> bool:
        """Validate URL format and scheme"""
        if not url:
            return False
        
        schemes = allowed_schemes or InputValidator.ALLOWED_SCHEMES
        
        # Basic URL pattern
        url_pattern = re.compile(
            r'^(https?://)'  # scheme
            r'(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+[A-Z]{2,6}\.?|'  # domain
            r'localhost|'  # localhost
            r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})'  # ip
            r'(?::\d+)?'  # optional port
            r'(?:/?|[/?]\S+)$', re.IGNORECASE)
        
        if not url_pattern.match(url):
            return False
        
        # Check scheme
        scheme = url.split('://')[0].lower()
        return scheme in schemes
    
    @staticmethod
    def validate_email(email: str) -> bool:
        """Validate email format"""
        if not email:
            return False
        
        pattern = re.compile(
            r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        )
        return bool(pattern.match(email))
    
    @staticmethod
    def contains_profanity(text: str) -> bool:
        """Check if text contains profanity"""
        if not text:
            return False
        
        words = set(text.lower().split())
        return bool(words & InputValidator.PROFANITY)
    
    @staticmethod
    def is_spam(text: str, threshold: float = 0.7) -> bool:
        """
        Detect spam (repeated characters, excessive caps, etc.)
        
        Args:
            text: Input text
            threshold: Ratio of caps to total (0.0-1.0)
        
        Returns:
            True if spam detected
        """
        if not text:
            return False
        
        # Check for excessive caps
        caps_count = sum(1 for c in text if c.isupper())
        if len(text) > 10 and caps_count / len(text) > threshold:
            return True
        
        # Check for repeated characters (e.g., "aaaaaa")
        if re.search(r'(.)\1{5,}', text):
            return True
        
        # Check for excessive exclamation/question marks
        if text.count('!') > 5 or text.count('?') > 5:
            return True
        
        return False
    
    @staticmethod
    def validate_price(price: str) -> Optional[float]:
        """
        Validate and parse price
        
        Args:
            price: Price string (e.g., "99.99", "$100")
        
        Returns:
            Float price or None if invalid
        """
        if not price:
            return None
        
        # Remove currency symbols and whitespace
        cleaned = re.sub(r'[^\d.]', '', price.strip())
        
        try:
            value = float(cleaned)
            if value < 0 or value > 999999.99:
                return None
            return round(value, 2)
        except ValueError:
            return None
    
    @staticmethod
    def validate_marketplace_item(title: str, description: str, price: float) -> Dict[str, Any]:
        """
        Validate marketplace listing data
        
        Returns:
            Dict with 'valid' bool and 'errors' list
        """
        errors = []
        
        # Validate title
        if not title or len(title.strip()) < 3:
            errors.append("Title must be at least 3 characters")
        elif len(title) > 100:
            errors.append("Title must be less than 100 characters")
        
        # Validate description
        if not description or len(description.strip()) < 10:
            errors.append("Description must be at least 10 characters")
        elif len(description) > 1000:
            errors.append("Description must be less than 1000 characters")
        
        # Validate price
        if price is None or price <= 0:
            errors.append("Price must be greater than 0")
        elif price > 999999.99:
            errors.append("Price exceeds maximum limit")
        
        # Check for profanity
        if InputValidator.contains_profanity(title) or InputValidator.contains_profanity(description):
            errors.append("Content contains inappropriate language")
        
        return {
            'valid': len(errors) == 0,
            'errors': errors
        }
    
    @staticmethod
    def sanitize_filename(filename: str) -> str:
        """Sanitize filename to prevent path traversal"""
        if not filename:
            return "unnamed"
        
        # Remove path separators and null bytes
        filename = re.sub(r'[\\/:*?"<>|\x00]', '', filename)
        
        # Limit length
        if len(filename) > 100:
            name, ext = filename.rsplit('.', 1) if '.' in filename else (filename, '')
            filename = name[:100] + ('.' + ext if ext else '')
        
        return filename or "unnamed"

# Convenience functions
def sanitize(text: str, max_length: int = 2000) -> str:
    """Quick sanitize function"""
    return InputValidator.sanitize_text(text, max_length)

def validate_id(discord_id: str) -> bool:
    """Quick ID validation"""
    return InputValidator.validate_discord_id(discord_id)

def is_safe(text: str) -> bool:
    """Quick safety check (no profanity, no spam)"""
    return not InputValidator.contains_profanity(text) and not InputValidator.is_spam(text)
