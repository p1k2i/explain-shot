"""
Data models for prompt preset functionality.

This module contains the data structures used for managing AI prompt presets,
including preset metadata, usage statistics, and categorization.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List, Dict, Any
import json


@dataclass
class PresetMetadata:
    """Metadata for a prompt preset."""

    name: str
    prompt: str
    description: str = ""
    category: str = "general"
    tags: List[str] = field(default_factory=list)
    usage_count: int = 0
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    id: Optional[int] = None  # Database ID after registration
    is_favorite: bool = False
    is_builtin: bool = False  # Built-in presets cannot be deleted

    def __post_init__(self):
        """Set timestamps if not provided."""
        if self.created_at is None:
            self.created_at = datetime.now()
        if self.updated_at is None:
            self.updated_at = self.created_at

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for database storage."""
        return {
            'name': self.name,
            'prompt': self.prompt,
            'description': self.description,
            'category': self.category,
            'tags': json.dumps(self.tags) if self.tags else "[]",
            'usage_count': self.usage_count,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'is_favorite': self.is_favorite,
            'is_builtin': self.is_builtin
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'PresetMetadata':
        """Create PresetMetadata from dictionary."""
        # Parse timestamps
        created_at = None
        if data.get('created_at'):
            try:
                created_at = datetime.fromisoformat(data['created_at'])
            except ValueError:
                created_at = datetime.now()

        updated_at = None
        if data.get('updated_at'):
            try:
                updated_at = datetime.fromisoformat(data['updated_at'])
            except ValueError:
                updated_at = created_at or datetime.now()

        # Parse tags
        tags = []
        if data.get('tags'):
            try:
                tags = json.loads(data['tags'])
            except json.JSONDecodeError:
                tags = []

        return cls(
            id=data.get('id'),
            name=data.get('name', ''),
            prompt=data.get('prompt', ''),
            description=data.get('description', ''),
            category=data.get('category', 'general'),
            tags=tags,
            usage_count=data.get('usage_count', 0),
            created_at=created_at,
            updated_at=updated_at,
            is_favorite=bool(data.get('is_favorite', False)),
            is_builtin=bool(data.get('is_builtin', False))
        )

    def increment_usage(self) -> None:
        """Increment usage count and update timestamp."""
        self.usage_count += 1
        self.updated_at = datetime.now()

    def update_content(self, prompt: Optional[str] = None, description: Optional[str] = None) -> None:
        """Update preset content and timestamp."""
        if prompt is not None:
            self.prompt = prompt
        if description is not None:
            self.description = description
        self.updated_at = datetime.now()

    def add_tag(self, tag: str) -> None:
        """Add a tag if not already present."""
        if tag and tag not in self.tags:
            self.tags.append(tag)
            self.updated_at = datetime.now()

    def remove_tag(self, tag: str) -> None:
        """Remove a tag if present."""
        if tag in self.tags:
            self.tags.remove(tag)
            self.updated_at = datetime.now()

    def matches_search(self, query: str) -> bool:
        """Check if preset matches a search query."""
        query_lower = query.lower()
        return (
            query_lower in self.name.lower() or
            query_lower in self.description.lower() or
            query_lower in self.prompt.lower() or
            any(query_lower in tag.lower() for tag in self.tags) or
            query_lower in self.category.lower()
        )


@dataclass
class PresetCategory:
    """Category for organizing presets."""

    name: str
    description: str = ""
    color: str = "#007ACC"  # Hex color for UI display
    icon: Optional[str] = None  # Icon identifier
    sort_order: int = 0
    id: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for database storage."""
        return {
            'name': self.name,
            'description': self.description,
            'color': self.color,
            'icon': self.icon,
            'sort_order': self.sort_order
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'PresetCategory':
        """Create PresetCategory from dictionary."""
        return cls(
            id=data.get('id'),
            name=data.get('name', ''),
            description=data.get('description', ''),
            color=data.get('color', '#007ACC'),
            icon=data.get('icon'),
            sort_order=data.get('sort_order', 0)
        )


@dataclass
class PresetUsageStats:
    """Statistics for preset usage tracking."""

    preset_id: int
    total_uses: int = 0
    last_used: Optional[datetime] = None
    average_session_uses: float = 0.0
    most_common_context: Optional[str] = None  # e.g., "ui_analysis", "bug_detection"

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for storage."""
        return {
            'preset_id': self.preset_id,
            'total_uses': self.total_uses,
            'last_used': self.last_used.isoformat() if self.last_used else None,
            'average_session_uses': self.average_session_uses,
            'most_common_context': self.most_common_context
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'PresetUsageStats':
        """Create PresetUsageStats from dictionary."""
        last_used = None
        if data.get('last_used'):
            try:
                last_used = datetime.fromisoformat(data['last_used'])
            except ValueError:
                pass

        return cls(
            preset_id=data['preset_id'],
            total_uses=data.get('total_uses', 0),
            last_used=last_used,
            average_session_uses=data.get('average_session_uses', 0.0),
            most_common_context=data.get('most_common_context')
        )


# Built-in preset definitions
BUILTIN_PRESETS = [
    PresetMetadata(
        name="Explain UI",
        prompt="Analyze this user interface element and explain what it does, how to use it, and any important details a user should know.",
        description="General UI explanation for interface elements",
        category="ui_analysis",
        tags=["ui", "explanation", "interface"],
        is_builtin=True
    ),
    PresetMetadata(
        name="Find Bugs",
        prompt="Carefully examine this screenshot for potential bugs, usability issues, visual problems, or inconsistencies. List any issues you find and suggest solutions.",
        description="Bug detection and quality assurance analysis",
        category="quality_assurance",
        tags=["bugs", "qa", "testing", "issues"],
        is_builtin=True
    ),
    PresetMetadata(
        name="Accessibility Review",
        prompt="Review this interface for accessibility issues. Check for proper contrast, text readability, navigation clarity, and compliance with accessibility guidelines. Suggest improvements.",
        description="Accessibility compliance and usability review",
        category="accessibility",
        tags=["accessibility", "a11y", "usability", "compliance"],
        is_builtin=True
    ),
    PresetMetadata(
        name="Design Critique",
        prompt="Provide a detailed design critique of this interface. Consider visual hierarchy, color usage, typography, spacing, and overall user experience. Suggest design improvements.",
        description="Comprehensive design review and feedback",
        category="design",
        tags=["design", "critique", "ux", "visual"],
        is_builtin=True
    ),
    PresetMetadata(
        name="Security Analysis",
        prompt="Analyze this screenshot for potential security issues, data exposure, or privacy concerns. Look for sensitive information, insecure practices, or security warnings.",
        description="Security and privacy assessment",
        category="security",
        tags=["security", "privacy", "data", "sensitive"],
        is_builtin=True
    ),
    PresetMetadata(
        name="Performance Review",
        prompt="Evaluate this interface for performance indicators, loading states, responsiveness issues, or efficiency problems. Suggest performance optimizations.",
        description="Performance analysis and optimization suggestions",
        category="performance",
        tags=["performance", "optimization", "speed", "efficiency"],
        is_builtin=True
    )
]

# Default categories
DEFAULT_CATEGORIES = [
    PresetCategory(name="general", description="General purpose presets", color="#6C757D"),
    PresetCategory(name="ui_analysis", description="User interface analysis", color="#007ACC"),
    PresetCategory(name="quality_assurance", description="Bug detection and QA", color="#DC3545"),
    PresetCategory(name="accessibility", description="Accessibility review", color="#28A745"),
    PresetCategory(name="design", description="Design critique and review", color="#6F42C1"),
    PresetCategory(name="security", description="Security analysis", color="#FD7E14"),
    PresetCategory(name="performance", description="Performance evaluation", color="#20C997")
]


class PresetError(Exception):
    """Base exception for preset-related errors."""
    pass


class PresetNotFoundError(PresetError):
    """Raised when a preset is not found."""
    pass


class PresetValidationError(PresetError):
    """Raised when preset data is invalid."""
    pass


class PresetDuplicateError(PresetError):
    """Raised when attempting to create a duplicate preset."""
    pass
