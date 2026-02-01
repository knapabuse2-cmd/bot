"""
Session encryption utilities.

Provides secure encryption/decryption of Telethon session data
using Fernet symmetric encryption.
"""

from cryptography.fernet import Fernet, InvalidToken

from src.config import get_settings


class SessionEncryption:
    """
    Handles encryption and decryption of session data.
    
    Uses Fernet symmetric encryption for secure storage
    of Telethon session files.
    """
    
    def __init__(self, key: bytes | str | None = None):
        """
        Initialize with encryption key.
        
        Args:
            key: Fernet key (uses settings if not provided)
        """
        if key is None:
            settings = get_settings()
            key = settings.security.session_encryption_key.get_secret_value()
        
        if isinstance(key, str):
            key = key.encode()
        
        self.fernet = Fernet(key)
    
    def encrypt(self, data: bytes) -> bytes:
        """
        Encrypt session data.
        
        Args:
            data: Raw session data
            
        Returns:
            Encrypted data
        """
        return self.fernet.encrypt(data)
    
    def decrypt(self, encrypted_data: bytes) -> bytes:
        """
        Decrypt session data.
        
        Args:
            encrypted_data: Encrypted session data
            
        Returns:
            Decrypted raw data
            
        Raises:
            InvalidToken: If decryption fails
        """
        return self.fernet.decrypt(encrypted_data)
    
    def encrypt_string(self, data: str) -> bytes:
        """Encrypt string data."""
        return self.encrypt(data.encode())
    
    def decrypt_string(self, encrypted_data: bytes) -> str:
        """Decrypt to string."""
        return self.decrypt(encrypted_data).decode()


# Singleton instance
_encryption: SessionEncryption | None = None


def get_session_encryption() -> SessionEncryption:
    """Get or create session encryption singleton."""
    global _encryption
    
    if _encryption is None:
        _encryption = SessionEncryption()
    
    return _encryption
