"""Controlled vocabularies used across the system."""
from enum import Enum


class Severity(str, Enum):
    """How bad is this finding?"""
    CRITICAL = "critical"   # Immediate safety hazard
    MAJOR = "major"         # Significant issue, fix soon
    MINOR = "minor"         # Cosmetic or low-risk
    INFO = "info"           # Observation, no action needed


class Priority(str, Enum):
    """Work order priority (set by Risk Agent later)."""
    P1 = "P1"   # SLA: 4 hours
    P2 = "P2"   # SLA: 24 hours
    P3 = "P3"   # SLA: 7 days
    P4 = "P4"   # SLA: 30 days


class ComplianceStatus(str, Enum):
    """Overall compliance verdict for the building."""
    COMPLIANT = "compliant"
    NON_COMPLIANT = "non_compliant"
    PARTIAL = "partial"
    UNKNOWN = "unknown"


class IssueCategory(str, Enum):
    """Type of issue detected. Used to route to right team later."""
    FIRE_SAFETY = "fire_safety"
    ELECTRICAL = "electrical"
    STRUCTURAL = "structural"
    PLUMBING = "plumbing"
    HVAC = "hvac"
    GENERAL = "general"