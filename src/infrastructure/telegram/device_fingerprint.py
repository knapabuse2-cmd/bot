"""
Device fingerprint generation for Telegram clients.

Provides randomized device information to make each account
appear as a unique device to Telegram's anti-spam systems.
"""

import hashlib
import random
from dataclasses import dataclass
from typing import Optional


@dataclass
class DeviceFingerprint:
    """Device fingerprint for Telegram client."""
    device_model: str
    system_version: str
    app_version: str
    lang_code: str = "en"
    system_lang_code: str = "en-US"


# ============================================
# ANDROID DEVICES
# ============================================

ANDROID_SAMSUNG = [
    # Galaxy S Series (Flagships)
    ("Samsung SM-S928B", "Android 14"),      # Galaxy S24 Ultra
    ("Samsung SM-S926B", "Android 14"),      # Galaxy S24+
    ("Samsung SM-S921B", "Android 14"),      # Galaxy S24
    ("Samsung SM-S918B", "Android 14"),      # Galaxy S23 Ultra
    ("Samsung SM-S916B", "Android 14"),      # Galaxy S23+
    ("Samsung SM-S911B", "Android 14"),      # Galaxy S23
    ("Samsung SM-S908B", "Android 14"),      # Galaxy S22 Ultra
    ("Samsung SM-S906B", "Android 14"),      # Galaxy S22+
    ("Samsung SM-S901B", "Android 14"),      # Galaxy S22
    ("Samsung SM-G998B", "Android 13"),      # Galaxy S21 Ultra
    ("Samsung SM-G996B", "Android 13"),      # Galaxy S21+
    ("Samsung SM-G991B", "Android 13"),      # Galaxy S21
    ("Samsung SM-G988B", "Android 13"),      # Galaxy S20 Ultra
    ("Samsung SM-G986B", "Android 13"),      # Galaxy S20+
    ("Samsung SM-G981B", "Android 13"),      # Galaxy S20
    ("Samsung SM-G975F", "Android 12"),      # Galaxy S10+
    ("Samsung SM-G973F", "Android 12"),      # Galaxy S10
    ("Samsung SM-G970F", "Android 12"),      # Galaxy S10e

    # Galaxy A Series (Mid-range)
    ("Samsung SM-A546B", "Android 14"),      # Galaxy A54 5G
    ("Samsung SM-A536B", "Android 14"),      # Galaxy A53 5G
    ("Samsung SM-A526B", "Android 13"),      # Galaxy A52 5G
    ("Samsung SM-A525F", "Android 13"),      # Galaxy A52
    ("Samsung SM-A346B", "Android 14"),      # Galaxy A34 5G
    ("Samsung SM-A336B", "Android 14"),      # Galaxy A33 5G
    ("Samsung SM-A256B", "Android 14"),      # Galaxy A25 5G
    ("Samsung SM-A236B", "Android 13"),      # Galaxy A23 5G
    ("Samsung SM-A146B", "Android 14"),      # Galaxy A14 5G
    ("Samsung SM-A047F", "Android 13"),      # Galaxy A04s
    ("Samsung SM-A736B", "Android 14"),      # Galaxy A73 5G
    ("Samsung SM-A725F", "Android 13"),      # Galaxy A72
    ("Samsung SM-A715F", "Android 13"),      # Galaxy A71

    # Galaxy Z Series (Foldables)
    ("Samsung SM-F956B", "Android 14"),      # Galaxy Z Fold6
    ("Samsung SM-F946B", "Android 14"),      # Galaxy Z Fold5
    ("Samsung SM-F936B", "Android 14"),      # Galaxy Z Fold4
    ("Samsung SM-F926B", "Android 13"),      # Galaxy Z Fold3
    ("Samsung SM-F741B", "Android 14"),      # Galaxy Z Flip6
    ("Samsung SM-F731B", "Android 14"),      # Galaxy Z Flip5
    ("Samsung SM-F721B", "Android 14"),      # Galaxy Z Flip4
    ("Samsung SM-F711B", "Android 13"),      # Galaxy Z Flip3

    # Galaxy M Series (Budget)
    ("Samsung SM-M546B", "Android 14"),      # Galaxy M54 5G
    ("Samsung SM-M536B", "Android 13"),      # Galaxy M53 5G
    ("Samsung SM-M346B", "Android 13"),      # Galaxy M34 5G
    ("Samsung SM-M236B", "Android 13"),      # Galaxy M23 5G
    ("Samsung SM-M146B", "Android 13"),      # Galaxy M14 5G

    # Galaxy Note Series
    ("Samsung SM-N986B", "Android 13"),      # Galaxy Note 20 Ultra
    ("Samsung SM-N981B", "Android 13"),      # Galaxy Note 20
    ("Samsung SM-N975F", "Android 12"),      # Galaxy Note 10+
    ("Samsung SM-N970F", "Android 12"),      # Galaxy Note 10
]

ANDROID_XIAOMI = [
    # Xiaomi Series
    ("Xiaomi 14 Ultra", "Android 14"),
    ("Xiaomi 14 Pro", "Android 14"),
    ("Xiaomi 14", "Android 14"),
    ("Xiaomi 13 Ultra", "Android 14"),
    ("Xiaomi 13 Pro", "Android 14"),
    ("Xiaomi 13", "Android 14"),
    ("Xiaomi 13 Lite", "Android 13"),
    ("Xiaomi 12 Ultra", "Android 13"),
    ("Xiaomi 12 Pro", "Android 13"),
    ("Xiaomi 12", "Android 13"),
    ("Xiaomi 12 Lite", "Android 13"),
    ("Xiaomi 12T Pro", "Android 14"),
    ("Xiaomi 12T", "Android 14"),
    ("Xiaomi 11 Ultra", "Android 13"),
    ("Xiaomi 11 Pro", "Android 13"),
    ("Xiaomi 11", "Android 13"),
    ("Xiaomi 11 Lite 5G NE", "Android 13"),
    ("Xiaomi 11T Pro", "Android 13"),
    ("Xiaomi 11T", "Android 13"),
    ("Xiaomi Mix Fold 3", "Android 14"),
    ("Xiaomi Mix Fold 2", "Android 13"),

    # Redmi Series
    ("Redmi Note 13 Pro+ 5G", "Android 14"),
    ("Redmi Note 13 Pro 5G", "Android 14"),
    ("Redmi Note 13 5G", "Android 14"),
    ("Redmi Note 13 Pro", "Android 14"),
    ("Redmi Note 13", "Android 14"),
    ("Redmi Note 12 Pro+ 5G", "Android 13"),
    ("Redmi Note 12 Pro 5G", "Android 13"),
    ("Redmi Note 12 5G", "Android 13"),
    ("Redmi Note 12 Pro", "Android 13"),
    ("Redmi Note 12", "Android 13"),
    ("Redmi Note 11 Pro+ 5G", "Android 13"),
    ("Redmi Note 11 Pro 5G", "Android 13"),
    ("Redmi Note 11 Pro", "Android 13"),
    ("Redmi Note 11", "Android 13"),
    ("Redmi Note 10 Pro", "Android 13"),
    ("Redmi Note 10", "Android 12"),
    ("Redmi 13C", "Android 13"),
    ("Redmi 12C", "Android 13"),
    ("Redmi 12", "Android 13"),
    ("Redmi A3", "Android 14"),
    ("Redmi A2", "Android 13"),
    ("Redmi K70 Pro", "Android 14"),
    ("Redmi K70", "Android 14"),
    ("Redmi K60 Ultra", "Android 14"),
    ("Redmi K60 Pro", "Android 13"),
    ("Redmi K60", "Android 13"),

    # POCO Series
    ("POCO F6 Pro", "Android 14"),
    ("POCO F6", "Android 14"),
    ("POCO F5 Pro", "Android 14"),
    ("POCO F5", "Android 14"),
    ("POCO F4 GT", "Android 13"),
    ("POCO F4", "Android 13"),
    ("POCO X6 Pro 5G", "Android 14"),
    ("POCO X6 5G", "Android 14"),
    ("POCO X5 Pro 5G", "Android 14"),
    ("POCO X5 5G", "Android 13"),
    ("POCO X4 Pro 5G", "Android 13"),
    ("POCO M6 Pro", "Android 14"),
    ("POCO M5s", "Android 13"),
    ("POCO M5", "Android 13"),
    ("POCO C65", "Android 14"),
    ("POCO C55", "Android 13"),
]

ANDROID_ONEPLUS = [
    ("OnePlus 12", "Android 14"),
    ("OnePlus 12R", "Android 14"),
    ("OnePlus 11", "Android 14"),
    ("OnePlus 11R", "Android 14"),
    ("OnePlus 10 Pro", "Android 14"),
    ("OnePlus 10T", "Android 14"),
    ("OnePlus 10R", "Android 13"),
    ("OnePlus 9 Pro", "Android 14"),
    ("OnePlus 9", "Android 14"),
    ("OnePlus 9R", "Android 13"),
    ("OnePlus 9RT", "Android 13"),
    ("OnePlus 8 Pro", "Android 13"),
    ("OnePlus 8T", "Android 13"),
    ("OnePlus 8", "Android 13"),
    ("OnePlus Nord 3 5G", "Android 14"),
    ("OnePlus Nord CE 3 5G", "Android 14"),
    ("OnePlus Nord CE 3 Lite 5G", "Android 14"),
    ("OnePlus Nord 2T 5G", "Android 13"),
    ("OnePlus Nord CE 2 5G", "Android 13"),
    ("OnePlus Nord N30 5G", "Android 13"),
    ("OnePlus Nord N20 5G", "Android 13"),
    ("OnePlus Open", "Android 14"),
]

ANDROID_GOOGLE = [
    ("Google Pixel 9 Pro XL", "Android 15"),
    ("Google Pixel 9 Pro", "Android 15"),
    ("Google Pixel 9", "Android 15"),
    ("Google Pixel 9 Pro Fold", "Android 15"),
    ("Google Pixel 8 Pro", "Android 14"),
    ("Google Pixel 8", "Android 14"),
    ("Google Pixel 8a", "Android 14"),
    ("Google Pixel 7 Pro", "Android 14"),
    ("Google Pixel 7", "Android 14"),
    ("Google Pixel 7a", "Android 14"),
    ("Google Pixel Fold", "Android 14"),
    ("Google Pixel 6 Pro", "Android 14"),
    ("Google Pixel 6", "Android 14"),
    ("Google Pixel 6a", "Android 14"),
    ("Google Pixel 5", "Android 13"),
    ("Google Pixel 5a", "Android 13"),
    ("Google Pixel 4 XL", "Android 13"),
    ("Google Pixel 4", "Android 13"),
    ("Google Pixel 4a", "Android 13"),
]

ANDROID_HUAWEI = [
    ("HUAWEI Mate 60 Pro+", "HarmonyOS 4.0"),
    ("HUAWEI Mate 60 Pro", "HarmonyOS 4.0"),
    ("HUAWEI Mate 60", "HarmonyOS 4.0"),
    ("HUAWEI Mate 50 Pro", "HarmonyOS 3.0"),
    ("HUAWEI Mate 50", "HarmonyOS 3.0"),
    ("HUAWEI Mate 40 Pro", "HarmonyOS 3.0"),
    ("HUAWEI Mate 40", "HarmonyOS 3.0"),
    ("HUAWEI P60 Pro", "HarmonyOS 3.1"),
    ("HUAWEI P60", "HarmonyOS 3.1"),
    ("HUAWEI P50 Pro", "HarmonyOS 3.0"),
    ("HUAWEI P50", "HarmonyOS 3.0"),
    ("HUAWEI P40 Pro", "Android 12"),
    ("HUAWEI P40", "Android 12"),
    ("HUAWEI nova 12 Ultra", "HarmonyOS 4.0"),
    ("HUAWEI nova 12 Pro", "HarmonyOS 4.0"),
    ("HUAWEI nova 12", "HarmonyOS 4.0"),
    ("HUAWEI nova 11 Pro", "HarmonyOS 3.0"),
    ("HUAWEI nova 11", "HarmonyOS 3.0"),
    ("HUAWEI nova 10 Pro", "HarmonyOS 3.0"),
    ("HUAWEI nova 10", "HarmonyOS 3.0"),
    ("HUAWEI Pura 70 Ultra", "HarmonyOS 4.2"),
    ("HUAWEI Pura 70 Pro", "HarmonyOS 4.2"),
    ("HUAWEI Pura 70", "HarmonyOS 4.2"),
]

ANDROID_OPPO = [
    ("OPPO Find X7 Ultra", "Android 14"),
    ("OPPO Find X7", "Android 14"),
    ("OPPO Find X6 Pro", "Android 14"),
    ("OPPO Find X6", "Android 14"),
    ("OPPO Find X5 Pro", "Android 14"),
    ("OPPO Find X5", "Android 13"),
    ("OPPO Find N3 Flip", "Android 14"),
    ("OPPO Find N3", "Android 14"),
    ("OPPO Find N2 Flip", "Android 14"),
    ("OPPO Reno 11 Pro 5G", "Android 14"),
    ("OPPO Reno 11 5G", "Android 14"),
    ("OPPO Reno 10 Pro+ 5G", "Android 14"),
    ("OPPO Reno 10 Pro 5G", "Android 14"),
    ("OPPO Reno 10 5G", "Android 14"),
    ("OPPO Reno 9 Pro+ 5G", "Android 13"),
    ("OPPO Reno 9 Pro 5G", "Android 13"),
    ("OPPO Reno 8 Pro 5G", "Android 13"),
    ("OPPO Reno 8 5G", "Android 13"),
    ("OPPO A79 5G", "Android 14"),
    ("OPPO A78 5G", "Android 13"),
    ("OPPO A58 5G", "Android 13"),
    ("OPPO A38", "Android 13"),
    ("OPPO A18", "Android 13"),
]

ANDROID_VIVO = [
    ("vivo X100 Ultra", "Android 14"),
    ("vivo X100 Pro", "Android 14"),
    ("vivo X100", "Android 14"),
    ("vivo X90 Pro+", "Android 14"),
    ("vivo X90 Pro", "Android 14"),
    ("vivo X90", "Android 14"),
    ("vivo X80 Pro", "Android 13"),
    ("vivo X80", "Android 13"),
    ("vivo X Fold 3 Pro", "Android 14"),
    ("vivo X Fold 3", "Android 14"),
    ("vivo X Fold 2", "Android 14"),
    ("vivo X Flip", "Android 14"),
    ("vivo V30 Pro", "Android 14"),
    ("vivo V30", "Android 14"),
    ("vivo V29 Pro", "Android 14"),
    ("vivo V29", "Android 14"),
    ("vivo V27 Pro", "Android 13"),
    ("vivo V27", "Android 13"),
    ("vivo Y100 5G", "Android 14"),
    ("vivo Y78 5G", "Android 13"),
    ("vivo Y56 5G", "Android 13"),
    ("vivo Y36", "Android 13"),
    ("vivo iQOO 12 Pro", "Android 14"),
    ("vivo iQOO 12", "Android 14"),
    ("vivo iQOO 11 Pro", "Android 13"),
    ("vivo iQOO 11", "Android 13"),
    ("vivo iQOO Neo 9 Pro", "Android 14"),
    ("vivo iQOO Neo 9", "Android 14"),
]

ANDROID_REALME = [
    ("realme GT 5 Pro", "Android 14"),
    ("realme GT 5", "Android 14"),
    ("realme GT 3", "Android 14"),
    ("realme GT Neo 6 SE", "Android 14"),
    ("realme GT Neo 5 SE", "Android 14"),
    ("realme GT Neo 5", "Android 14"),
    ("realme GT 2 Pro", "Android 14"),
    ("realme GT 2", "Android 13"),
    ("realme 12 Pro+ 5G", "Android 14"),
    ("realme 12 Pro 5G", "Android 14"),
    ("realme 12 5G", "Android 14"),
    ("realme 12+ 5G", "Android 14"),
    ("realme 11 Pro+ 5G", "Android 14"),
    ("realme 11 Pro 5G", "Android 13"),
    ("realme 11 5G", "Android 13"),
    ("realme 10 Pro+ 5G", "Android 13"),
    ("realme 10 Pro 5G", "Android 13"),
    ("realme C67 5G", "Android 14"),
    ("realme C55", "Android 13"),
    ("realme C53", "Android 13"),
    ("realme Narzo 70 Pro 5G", "Android 14"),
    ("realme Narzo 60 Pro 5G", "Android 14"),
    ("realme Narzo 60 5G", "Android 14"),
]

ANDROID_MOTOROLA = [
    ("motorola razr+ 2024", "Android 14"),
    ("motorola razr 2024", "Android 14"),
    ("motorola razr+ 2023", "Android 14"),
    ("motorola razr 2023", "Android 14"),
    ("motorola edge 50 ultra", "Android 14"),
    ("motorola edge 50 pro", "Android 14"),
    ("motorola edge 50 fusion", "Android 14"),
    ("motorola edge 40 pro", "Android 14"),
    ("motorola edge 40", "Android 14"),
    ("motorola edge 40 neo", "Android 14"),
    ("motorola edge 30 ultra", "Android 14"),
    ("motorola edge 30 pro", "Android 13"),
    ("motorola moto g84 5G", "Android 14"),
    ("motorola moto g73 5G", "Android 13"),
    ("motorola moto g54 5G", "Android 14"),
    ("motorola moto g34 5G", "Android 14"),
    ("motorola moto g24", "Android 14"),
    ("motorola moto g stylus 5G (2024)", "Android 14"),
    ("motorola moto g power 5G (2024)", "Android 14"),
    ("motorola ThinkPhone", "Android 14"),
]

ANDROID_SONY = [
    ("Sony Xperia 1 VI", "Android 14"),
    ("Sony Xperia 1 V", "Android 14"),
    ("Sony Xperia 1 IV", "Android 14"),
    ("Sony Xperia 5 V", "Android 14"),
    ("Sony Xperia 5 IV", "Android 14"),
    ("Sony Xperia 10 VI", "Android 14"),
    ("Sony Xperia 10 V", "Android 14"),
    ("Sony Xperia 10 IV", "Android 13"),
    ("Sony Xperia Pro-I", "Android 13"),
]

ANDROID_ASUS = [
    ("ASUS ROG Phone 8 Pro", "Android 14"),
    ("ASUS ROG Phone 8", "Android 14"),
    ("ASUS ROG Phone 7 Ultimate", "Android 14"),
    ("ASUS ROG Phone 7", "Android 14"),
    ("ASUS ROG Phone 6 Pro", "Android 13"),
    ("ASUS ROG Phone 6", "Android 13"),
    ("ASUS Zenfone 11 Ultra", "Android 14"),
    ("ASUS Zenfone 10", "Android 14"),
    ("ASUS Zenfone 9", "Android 14"),
]

ANDROID_NOTHING = [
    ("Nothing Phone (2a)", "Android 14"),
    ("Nothing Phone (2)", "Android 14"),
    ("Nothing Phone (1)", "Android 14"),
]

ANDROID_OTHER = [
    ("Tecno Phantom X2 Pro", "Android 13"),
    ("Tecno Phantom V Fold", "Android 14"),
    ("Tecno Camon 30 Pro", "Android 14"),
    ("Tecno Spark 20 Pro", "Android 14"),
    ("Infinix Zero 30 5G", "Android 14"),
    ("Infinix Note 40 Pro", "Android 14"),
    ("Infinix GT 20 Pro", "Android 14"),
    ("ZTE Axon 60 Ultra", "Android 14"),
    ("ZTE nubia Z60 Ultra", "Android 14"),
    ("ZTE nubia Red Magic 9 Pro", "Android 14"),
    ("Honor Magic 6 Pro", "Android 14"),
    ("Honor Magic 6", "Android 14"),
    ("Honor Magic V2", "Android 14"),
    ("Honor 200 Pro", "Android 14"),
    ("Honor 200", "Android 14"),
    ("Honor 90", "Android 14"),
    ("Honor X9b", "Android 14"),
    ("Meizu 21 Pro", "Android 14"),
    ("Meizu 21", "Android 14"),
    ("Meizu 20 Pro", "Android 13"),
    ("Black Shark 5 Pro", "Android 13"),
    ("Black Shark 5", "Android 13"),
    ("Lenovo Legion Y90", "Android 12"),
    ("Lenovo Legion Duel 2", "Android 12"),
]

# ============================================
# iOS DEVICES
# ============================================

IOS_IPHONE = [
    # iPhone 16 Series
    ("iPhone 16 Pro Max", "iOS 18.2"),
    ("iPhone 16 Pro Max", "iOS 18.1"),
    ("iPhone 16 Pro Max", "iOS 18.0"),
    ("iPhone 16 Pro", "iOS 18.2"),
    ("iPhone 16 Pro", "iOS 18.1"),
    ("iPhone 16 Pro", "iOS 18.0"),
    ("iPhone 16 Plus", "iOS 18.2"),
    ("iPhone 16 Plus", "iOS 18.1"),
    ("iPhone 16", "iOS 18.2"),
    ("iPhone 16", "iOS 18.1"),
    ("iPhone 16", "iOS 18.0"),

    # iPhone 15 Series
    ("iPhone 15 Pro Max", "iOS 18.2"),
    ("iPhone 15 Pro Max", "iOS 18.1"),
    ("iPhone 15 Pro Max", "iOS 17.7"),
    ("iPhone 15 Pro Max", "iOS 17.6"),
    ("iPhone 15 Pro Max", "iOS 17.5"),
    ("iPhone 15 Pro", "iOS 18.2"),
    ("iPhone 15 Pro", "iOS 18.1"),
    ("iPhone 15 Pro", "iOS 17.7"),
    ("iPhone 15 Pro", "iOS 17.6"),
    ("iPhone 15 Plus", "iOS 18.1"),
    ("iPhone 15 Plus", "iOS 17.7"),
    ("iPhone 15 Plus", "iOS 17.6"),
    ("iPhone 15", "iOS 18.2"),
    ("iPhone 15", "iOS 18.1"),
    ("iPhone 15", "iOS 17.7"),
    ("iPhone 15", "iOS 17.6"),

    # iPhone 14 Series
    ("iPhone 14 Pro Max", "iOS 18.1"),
    ("iPhone 14 Pro Max", "iOS 17.7"),
    ("iPhone 14 Pro Max", "iOS 17.6"),
    ("iPhone 14 Pro Max", "iOS 17.5"),
    ("iPhone 14 Pro", "iOS 18.1"),
    ("iPhone 14 Pro", "iOS 17.7"),
    ("iPhone 14 Pro", "iOS 17.6"),
    ("iPhone 14 Plus", "iOS 18.1"),
    ("iPhone 14 Plus", "iOS 17.7"),
    ("iPhone 14", "iOS 18.1"),
    ("iPhone 14", "iOS 17.7"),
    ("iPhone 14", "iOS 17.6"),

    # iPhone 13 Series
    ("iPhone 13 Pro Max", "iOS 18.1"),
    ("iPhone 13 Pro Max", "iOS 17.7"),
    ("iPhone 13 Pro Max", "iOS 17.6"),
    ("iPhone 13 Pro", "iOS 18.1"),
    ("iPhone 13 Pro", "iOS 17.7"),
    ("iPhone 13 Pro", "iOS 17.6"),
    ("iPhone 13", "iOS 18.1"),
    ("iPhone 13", "iOS 17.7"),
    ("iPhone 13", "iOS 17.6"),
    ("iPhone 13 mini", "iOS 17.7"),
    ("iPhone 13 mini", "iOS 17.6"),

    # iPhone 12 Series
    ("iPhone 12 Pro Max", "iOS 17.7"),
    ("iPhone 12 Pro Max", "iOS 17.6"),
    ("iPhone 12 Pro", "iOS 17.7"),
    ("iPhone 12 Pro", "iOS 17.6"),
    ("iPhone 12", "iOS 17.7"),
    ("iPhone 12", "iOS 17.6"),
    ("iPhone 12 mini", "iOS 17.7"),
    ("iPhone 12 mini", "iOS 17.6"),

    # iPhone 11 Series
    ("iPhone 11 Pro Max", "iOS 17.7"),
    ("iPhone 11 Pro Max", "iOS 17.6"),
    ("iPhone 11 Pro", "iOS 17.7"),
    ("iPhone 11 Pro", "iOS 17.6"),
    ("iPhone 11", "iOS 17.7"),
    ("iPhone 11", "iOS 17.6"),

    # iPhone SE
    ("iPhone SE (3rd generation)", "iOS 18.1"),
    ("iPhone SE (3rd generation)", "iOS 17.7"),
    ("iPhone SE (2nd generation)", "iOS 17.6"),

    # Older iPhones (still supported)
    ("iPhone XS Max", "iOS 17.6"),
    ("iPhone XS", "iOS 17.6"),
    ("iPhone XR", "iOS 17.6"),
]

# ============================================
# TELEGRAM APP VERSIONS
# ============================================

# Android Telegram versions (2024-2025)
TELEGRAM_ANDROID_VERSIONS = [
    "11.6.2",
    "11.6.1",
    "11.6.0",
    "11.5.5",
    "11.5.4",
    "11.5.3",
    "11.5.2",
    "11.5.1",
    "11.5.0",
    "11.4.5",
    "11.4.4",
    "11.4.3",
    "11.4.2",
    "11.4.1",
    "11.4.0",
    "11.3.4",
    "11.3.3",
    "11.3.2",
    "11.3.1",
    "11.3.0",
    "11.2.3",
    "11.2.2",
    "11.2.1",
    "11.2.0",
    "11.1.4",
    "11.1.3",
    "11.1.2",
    "11.1.1",
    "11.1.0",
    "11.0.3",
    "11.0.2",
    "11.0.1",
    "11.0.0",
    "10.14.5",
    "10.14.4",
    "10.14.3",
    "10.14.2",
    "10.14.1",
    "10.14.0",
    "10.13.3",
    "10.13.2",
    "10.12.1",
    "10.12.0",
    "10.11.2",
    "10.11.1",
    "10.10.1",
    "10.9.4",
    "10.8.3",
    "10.7.2",
    "10.6.5",
]

# iOS Telegram versions (2024-2025)
TELEGRAM_IOS_VERSIONS = [
    "11.5.3",
    "11.5.2",
    "11.5.1",
    "11.5.0",
    "11.4.3",
    "11.4.2",
    "11.4.1",
    "11.4.0",
    "11.3.2",
    "11.3.1",
    "11.3.0",
    "11.2.2",
    "11.2.1",
    "11.2.0",
    "11.1.2",
    "11.1.1",
    "11.1.0",
    "11.0.3",
    "11.0.2",
    "11.0.1",
    "11.0.0",
    "10.15.2",
    "10.15.1",
    "10.15.0",
    "10.14.2",
    "10.14.1",
    "10.14.0",
    "10.13.1",
    "10.12.2",
    "10.11.1",
    "10.10.1",
    "10.9.3",
    "10.8.2",
    "10.7.1",
    "10.6.3",
    "10.5.1",
    "10.4.2",
    "10.3.1",
    "10.2.0",
    "10.1.2",
    "10.0.1",
    "9.8.1",
    "9.7.2",
]

# Desktop versions (less common for our use case)
TELEGRAM_DESKTOP_VERSIONS = [
    "5.10.2",
    "5.10.1",
    "5.9.0",
    "5.8.3",
    "5.8.2",
    "5.7.2",
    "5.6.3",
    "5.5.0",
    "5.4.1",
    "5.3.2",
    "5.2.3",
    "5.1.7",
    "5.0.4",
    "4.16.8",
    "4.15.2",
    "4.14.9",
]

# ============================================
# LANGUAGE CODES
# ============================================

LANG_CODES = [
    ("en", "en-US"),
    ("ru", "ru-RU"),
    ("uk", "uk-UA"),
    ("de", "de-DE"),
    ("fr", "fr-FR"),
    ("es", "es-ES"),
    ("it", "it-IT"),
    ("pt", "pt-BR"),
    ("tr", "tr-TR"),
    ("ar", "ar-SA"),
    ("fa", "fa-IR"),
    ("id", "id-ID"),
    ("vi", "vi-VN"),
    ("th", "th-TH"),
    ("ko", "ko-KR"),
    ("ja", "ja-JP"),
    ("zh", "zh-CN"),
    ("zh", "zh-TW"),
    ("pl", "pl-PL"),
    ("nl", "nl-NL"),
    ("cs", "cs-CZ"),
    ("ro", "ro-RO"),
    ("hu", "hu-HU"),
    ("el", "el-GR"),
    ("he", "he-IL"),
    ("hi", "hi-IN"),
    ("bn", "bn-BD"),
    ("ms", "ms-MY"),
]


# ============================================
# GENERATION FUNCTIONS
# ============================================

# Combine all Android devices
ALL_ANDROID_DEVICES = (
    ANDROID_SAMSUNG +
    ANDROID_XIAOMI +
    ANDROID_ONEPLUS +
    ANDROID_GOOGLE +
    ANDROID_HUAWEI +
    ANDROID_OPPO +
    ANDROID_VIVO +
    ANDROID_REALME +
    ANDROID_MOTOROLA +
    ANDROID_SONY +
    ANDROID_ASUS +
    ANDROID_NOTHING +
    ANDROID_OTHER
)


def generate_random_fingerprint(
    prefer_android: bool = True,
    lang_code: Optional[str] = None,
) -> DeviceFingerprint:
    """
    Generate a random device fingerprint.

    Args:
        prefer_android: If True, 80% chance of Android, 20% iOS
                       If False, 50/50 split
        lang_code: Optional language code to use (e.g., "ru")
                  If None, random language is selected

    Returns:
        DeviceFingerprint with randomized values
    """
    # Determine platform
    if prefer_android:
        is_android = random.random() < 0.8
    else:
        is_android = random.random() < 0.5

    if is_android:
        # Pick random Android device
        device_model, system_version = random.choice(ALL_ANDROID_DEVICES)
        app_version = random.choice(TELEGRAM_ANDROID_VERSIONS)
    else:
        # Pick random iOS device
        device_model, system_version = random.choice(IOS_IPHONE)
        app_version = random.choice(TELEGRAM_IOS_VERSIONS)

    # Pick language
    if lang_code:
        # Find matching system_lang_code or use default
        system_lang_code = f"{lang_code}-{lang_code.upper()}"
        for code, sys_code in LANG_CODES:
            if code == lang_code:
                system_lang_code = sys_code
                break
    else:
        lang_code, system_lang_code = random.choice(LANG_CODES)

    return DeviceFingerprint(
        device_model=device_model,
        system_version=system_version,
        app_version=app_version,
        lang_code=lang_code,
        system_lang_code=system_lang_code,
    )


def generate_fingerprint_for_account(
    account_id: str,
    lang_code: Optional[str] = None,
    rotation_days: int = 0,
) -> DeviceFingerprint:
    """
    Generate a fingerprint for an account with optional rotation.

    Anti-detection: Fingerprints can rotate periodically to simulate
    app updates or device changes.

    Args:
        account_id: Account identifier (used as seed)
        lang_code: Optional language code to use
        rotation_days: If > 0, fingerprint rotates every N days.
                      0 means static fingerprint (old behavior).

    Returns:
        DeviceFingerprint
    """
    from datetime import datetime

    # Base seed from account_id
    base_seed = int(hashlib.md5(account_id.encode()).hexdigest()[:8], 16)

    # Add rotation component if enabled
    if rotation_days > 0:
        # Calculate current rotation period
        days_since_epoch = (datetime.utcnow() - datetime(2020, 1, 1)).days
        rotation_period = days_since_epoch // rotation_days

        # Combine base seed with rotation period
        # This ensures same fingerprint within a rotation period
        rotation_seed = int(hashlib.md5(
            f"{account_id}:{rotation_period}".encode()
        ).hexdigest()[:8], 16)
        seed = base_seed ^ rotation_seed
    else:
        seed = base_seed

    rng = random.Random(seed)

    # Determine platform (80% Android)
    is_android = rng.random() < 0.8

    if is_android:
        device_model, system_version = rng.choice(ALL_ANDROID_DEVICES)
        app_version = rng.choice(TELEGRAM_ANDROID_VERSIONS)
    else:
        device_model, system_version = rng.choice(IOS_IPHONE)
        app_version = rng.choice(TELEGRAM_IOS_VERSIONS)

    # Pick language
    if lang_code:
        system_lang_code = f"{lang_code}-{lang_code.upper()}"
        for code, sys_code in LANG_CODES:
            if code == lang_code:
                system_lang_code = sys_code
                break
    else:
        lang_code, system_lang_code = rng.choice(LANG_CODES)

    return DeviceFingerprint(
        device_model=device_model,
        system_version=system_version,
        app_version=app_version,
        lang_code=lang_code,
        system_lang_code=system_lang_code,
    )


def generate_fingerprint_with_app_update(
    account_id: str,
    lang_code: Optional[str] = None,
    update_probability: float = 0.1,
) -> DeviceFingerprint:
    """
    Generate fingerprint with random app version updates.

    Simulates users who update their Telegram app periodically.
    Device stays the same, but app version may change.

    Args:
        account_id: Account identifier
        lang_code: Optional language code
        update_probability: Probability of using a newer app version (0-1)

    Returns:
        DeviceFingerprint with potentially updated app version
    """
    from datetime import datetime

    # Get base fingerprint (device stays consistent)
    base_seed = int(hashlib.md5(account_id.encode()).hexdigest()[:8], 16)
    rng = random.Random(base_seed)

    # Determine platform (consistent)
    is_android = rng.random() < 0.8

    if is_android:
        device_model, system_version = rng.choice(ALL_ANDROID_DEVICES)
        base_version_idx = rng.randint(0, len(TELEGRAM_ANDROID_VERSIONS) - 1)
        versions = TELEGRAM_ANDROID_VERSIONS
    else:
        device_model, system_version = rng.choice(IOS_IPHONE)
        base_version_idx = rng.randint(0, len(TELEGRAM_IOS_VERSIONS) - 1)
        versions = TELEGRAM_IOS_VERSIONS

    # Decide if user has "updated" their app
    # Use current date to make this decision change over time
    day_seed = int(hashlib.md5(
        f"{account_id}:{datetime.utcnow().date()}".encode()
    ).hexdigest()[:8], 16)
    day_rng = random.Random(day_seed)

    if day_rng.random() < update_probability:
        # User "updated" - pick a newer version (lower index = newer)
        new_idx = max(0, base_version_idx - day_rng.randint(1, 5))
        app_version = versions[new_idx]
    else:
        app_version = versions[base_version_idx]

    # Pick language (consistent)
    if lang_code:
        system_lang_code = f"{lang_code}-{lang_code.upper()}"
        for code, sys_code in LANG_CODES:
            if code == lang_code:
                system_lang_code = sys_code
                break
    else:
        lang_code, system_lang_code = rng.choice(LANG_CODES)

    return DeviceFingerprint(
        device_model=device_model,
        system_version=system_version,
        app_version=app_version,
        lang_code=lang_code,
        system_lang_code=system_lang_code,
    )


def get_fingerprint_stats() -> dict:
    """Get statistics about available fingerprints."""
    return {
        "total_android_devices": len(ALL_ANDROID_DEVICES),
        "total_ios_devices": len(IOS_IPHONE),
        "total_devices": len(ALL_ANDROID_DEVICES) + len(IOS_IPHONE),
        "android_app_versions": len(TELEGRAM_ANDROID_VERSIONS),
        "ios_app_versions": len(TELEGRAM_IOS_VERSIONS),
        "languages": len(LANG_CODES),
        "brands": {
            "samsung": len(ANDROID_SAMSUNG),
            "xiaomi": len(ANDROID_XIAOMI),
            "oneplus": len(ANDROID_ONEPLUS),
            "google": len(ANDROID_GOOGLE),
            "huawei": len(ANDROID_HUAWEI),
            "oppo": len(ANDROID_OPPO),
            "vivo": len(ANDROID_VIVO),
            "realme": len(ANDROID_REALME),
            "motorola": len(ANDROID_MOTOROLA),
            "sony": len(ANDROID_SONY),
            "asus": len(ANDROID_ASUS),
            "nothing": len(ANDROID_NOTHING),
            "other": len(ANDROID_OTHER),
            "iphone": len(IOS_IPHONE),
        }
    }
