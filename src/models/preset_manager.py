"""
Preset Manager for file-based preset storage.

This module provides preset management using JSON files stored in the
%APPDATA%/ExplainShot/presets/ directory, replacing database-based storage.
"""

import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from .. import get_app_data_dir, EventTypes
from .preset_models import (
    PresetMetadata, PresetCategory, PresetError, PresetNotFoundError,
    PresetValidationError, PresetDuplicateError, BUILTIN_PRESETS, DEFAULT_CATEGORIES
)

logger = logging.getLogger(__name__)


class PresetManager:
    """
    Manages preset storage using JSON files.

    Provides file-based preset storage in %APPDATA%/ExplainShot/presets/
    with async operations for CRUD functionality.
    """

    def __init__(self, presets_dir: Optional[str] = None):
        """
        Initialize PresetManager.

        Args:
            presets_dir: Custom presets directory (uses default if None)
        """
        self.presets_dir = Path(presets_dir) if presets_dir else Path(get_app_data_dir()) / "presets"
        self.user_presets_dir = self.presets_dir / "user"
        self.builtin_presets_dir = self.presets_dir / "builtin"

        # In-memory cache of loaded presets
        self._preset_cache: Dict[str, PresetMetadata] = {}
        self._cache_lock = asyncio.Lock()
        self._initialized = False

        # Event bus for notifications (lazy-loaded to avoid circular imports)
        self._event_bus = None

        logger.info(f"PresetManager initialized with directory: {self.presets_dir}")

    def _get_event_bus(self):
        """Get event bus instance, lazy-loaded to avoid circular imports."""
        if self._event_bus is None:
            try:
                from ..controllers.event_bus import get_event_bus
                self._event_bus = get_event_bus()
            except ImportError:
                # Event bus not available, continue without it
                pass
        return self._event_bus

    async def initialize(self) -> None:
        """Initialize preset directories and load built-in presets."""
        if self._initialized:
            return

        try:
            # Create directories
            self.presets_dir.mkdir(parents=True, exist_ok=True)
            self.user_presets_dir.mkdir(parents=True, exist_ok=True)
            self.builtin_presets_dir.mkdir(parents=True, exist_ok=True)

            # Initialize built-in presets
            await self._initialize_builtin_presets()

            # Load all presets into cache
            await self._load_all_presets()

            self._initialized = True
            logger.debug("PresetManager initialized successfully")

        except Exception as e:
            logger.error(f"Failed to initialize PresetManager: {e}")
            raise PresetError(f"PresetManager initialization failed: {e}") from e

    async def create_preset(self, preset: PresetMetadata) -> str:
        """
        Create a new user preset.

        Args:
            preset: PresetMetadata to create

        Returns:
            The preset ID (filename without extension)

        Raises:
            PresetDuplicateError: If preset name already exists
            PresetValidationError: If preset data is invalid
        """
        if not self._initialized:
            await self.initialize()

        async with self._cache_lock:
            # Check for duplicate names
            if await self._preset_name_exists(preset.name):
                raise PresetDuplicateError(f"Preset with name '{preset.name}' already exists")

            # Validate preset
            self._validate_preset(preset)

            # Generate unique ID
            preset_id = self._generate_preset_id(preset.name)

            # Set timestamps and metadata
            preset.created_at = datetime.now()
            preset.updated_at = preset.created_at
            preset.is_builtin = False

            # Save to file
            file_path = self.user_presets_dir / f"{preset_id}.json"
            await self._save_preset_file(file_path, preset)

            # Update cache
            self._preset_cache[preset_id] = preset

            logger.info(f"Created preset: {preset.name} (ID: {preset_id})")

            # Emit event
            event_bus = self._get_event_bus()
            if event_bus:
                await event_bus.emit(
                    EventTypes.PRESET_CREATED,
                    {"preset_id": preset_id, "preset": preset}
                )

            return preset_id

    async def get_presets(self, category: Optional[str] = None,
                         limit: int = 50, offset: int = 0) -> List[PresetMetadata]:
        """
        Retrieve presets with optional filtering.

        Args:
            category: Optional category filter
            limit: Maximum number of presets to return
            offset: Number of presets to skip

        Returns:
            List of PresetMetadata objects
        """
        if not self._initialized:
            await self.initialize()

        async with self._cache_lock:
            presets = list(self._preset_cache.values())

            # Apply category filter
            if category:
                presets = [p for p in presets if p.category == category]

            # Sort by usage count (desc) then name (asc)
            presets.sort(key=lambda p: (-p.usage_count, p.name.lower()))

            # Apply pagination
            start = offset
            end = offset + limit
            return presets[start:end]

    async def get_preset_by_id(self, preset_id: str) -> Optional[PresetMetadata]:
        """
        Get a specific preset by ID.

        Args:
            preset_id: The preset ID to retrieve

        Returns:
            PresetMetadata object or None if not found
        """
        if not self._initialized:
            await self.initialize()

        async with self._cache_lock:
            return self._preset_cache.get(preset_id)

    async def update_preset(self, preset_id: str, preset: PresetMetadata) -> bool:
        """
        Update an existing preset.

        Args:
            preset_id: ID of preset to update
            preset: Updated PresetMetadata

        Returns:
            True if update successful

        Raises:
            PresetNotFoundError: If preset not found
            PresetValidationError: If preset data is invalid
        """
        if not self._initialized:
            await self.initialize()

        async with self._cache_lock:
            if preset_id not in self._preset_cache:
                raise PresetNotFoundError(f"Preset with ID '{preset_id}' not found")

            old_preset = self._preset_cache[preset_id]

            # Check if it's a built-in preset
            if old_preset.is_builtin:
                logger.warning(f"Cannot update built-in preset {preset_id}")
                return False

            # Validate preset
            self._validate_preset(preset)

            # Check for name conflicts (excluding current preset)
            if (preset.name != old_preset.name and
                await self._preset_name_exists(preset.name, exclude_id=preset_id)):
                raise PresetDuplicateError(f"Preset with name '{preset.name}' already exists")

            # Update timestamps
            preset.updated_at = datetime.now()
            preset.created_at = old_preset.created_at  # Preserve original creation time
            preset.is_builtin = False

            # Save to file
            file_path = self.user_presets_dir / f"{preset_id}.json"
            await self._save_preset_file(file_path, preset)

            # Update cache
            self._preset_cache[preset_id] = preset

            logger.info(f"Updated preset: {preset.name}")

            # Emit event
            event_bus = self._get_event_bus()
            if event_bus:
                await event_bus.emit(
                    EventTypes.PRESET_UPDATED,
                    {"preset_id": preset_id, "preset": preset}
                )

            return True

    async def delete_preset(self, preset_id: str) -> bool:
        """
        Delete a preset.

        Args:
            preset_id: ID of preset to delete

        Returns:
            True if deletion successful
        """
        if not self._initialized:
            await self.initialize()

        async with self._cache_lock:
            if preset_id not in self._preset_cache:
                return False

            preset = self._preset_cache[preset_id]

            # Check if it's a built-in preset
            if preset.is_builtin:
                logger.warning(f"Cannot delete built-in preset {preset_id}")
                return False

            # Delete file
            file_path = self.user_presets_dir / f"{preset_id}.json"
            try:
                if file_path.exists():
                    file_path.unlink()

                # Remove from cache
                del self._preset_cache[preset_id]

                logger.info(f"Deleted preset: {preset.name}")

                # Emit event
                event_bus = self._get_event_bus()
                if event_bus:
                    await event_bus.emit(
                        EventTypes.PRESET_DELETED,
                        {"preset_id": preset_id}
                    )

                return True

            except Exception as e:
                logger.error(f"Failed to delete preset file {file_path}: {e}")
                return False

    async def increment_preset_usage(self, preset_id: str) -> bool:
        """
        Increment the usage count for a preset.

        Args:
            preset_id: ID of the preset

        Returns:
            True if increment successful
        """
        if not self._initialized:
            await self.initialize()

        async with self._cache_lock:
            preset = self._preset_cache.get(preset_id)
            if not preset:
                return False

            # Increment usage
            preset.increment_usage()

            # Save to file
            if preset.is_builtin:
                file_path = self.builtin_presets_dir / f"{preset_id}.json"
            else:
                file_path = self.user_presets_dir / f"{preset_id}.json"

            try:
                await self._save_preset_file(file_path, preset)
                logger.debug(f"Incremented usage for preset: {preset.name}")
                return True

            except Exception as e:
                logger.error(f"Failed to save usage increment for preset {preset_id}: {e}")
                return False

    async def search_presets(self, query: str, category: Optional[str] = None) -> List[PresetMetadata]:
        """
        Search presets by query string.

        Args:
            query: Search query
            category: Optional category filter

        Returns:
            List of matching PresetMetadata objects
        """
        if not self._initialized:
            await self.initialize()

        async with self._cache_lock:
            results = []

            for preset in self._preset_cache.values():
                if category and preset.category != category:
                    continue

                if preset.matches_search(query):
                    results.append(preset)

            # Sort by relevance (usage count) and name
            results.sort(key=lambda p: (-p.usage_count, p.name.lower()))
            return results

    async def get_categories(self) -> List[PresetCategory]:
        """
        Get all available preset categories.

        Returns:
            List of PresetCategory objects
        """
        if not self._initialized:
            await self.initialize()

        # For now, return the default categories
        # In the future, this could be dynamically determined from existing presets
        return DEFAULT_CATEGORIES.copy()

    async def export_presets(self, file_path: str, include_builtin: bool = False) -> bool:
        """
        Export presets to a JSON file.

        Args:
            file_path: Path to export file
            include_builtin: Whether to include built-in presets

        Returns:
            True if export successful
        """
        if not self._initialized:
            await self.initialize()

        try:
            async with self._cache_lock:
                presets_data = []

                for preset in self._preset_cache.values():
                    if not include_builtin and preset.is_builtin:
                        continue

                    presets_data.append(preset.to_dict())

                export_data = {
                    "export_timestamp": datetime.now().isoformat(),
                    "version": "1.0",
                    "presets": presets_data
                }

                # Save to file
                with open(file_path, 'w', encoding='utf-8') as f:
                    json.dump(export_data, f, indent=2, ensure_ascii=False)

                logger.info(f"Exported {len(presets_data)} presets to {file_path}")
                return True

        except Exception as e:
            logger.error(f"Failed to export presets to {file_path}: {e}")
            return False

    async def import_presets(self, file_path: str, overwrite: bool = False) -> int:
        """
        Import presets from a JSON file.

        Args:
            file_path: Path to import file
            overwrite: Whether to overwrite existing presets

        Returns:
            Number of presets imported
        """
        if not self._initialized:
            await self.initialize()

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                import_data = json.load(f)

            presets_data = import_data.get("presets", [])
            imported_count = 0

            for preset_dict in presets_data:
                try:
                    preset = PresetMetadata.from_dict(preset_dict)

                    # Check if preset already exists
                    if await self._preset_name_exists(preset.name):
                        if not overwrite:
                            logger.warning(f"Skipping existing preset: {preset.name}")
                            continue
                        else:
                            # Find and delete existing preset
                            existing_id = await self._find_preset_id_by_name(preset.name)
                            if existing_id:
                                await self.delete_preset(existing_id)

                    # Create new preset
                    await self.create_preset(preset)
                    imported_count += 1
                    logger.info(f"Imported preset: {preset.name}")

                except Exception as e:
                    logger.error(f"Failed to import preset {preset_dict.get('name', 'unknown')}: {e}")
                    continue

            logger.info(f"Imported {imported_count} presets from {file_path}")
            return imported_count

        except Exception as e:
            logger.error(f"Failed to import presets from {file_path}: {e}")
            return 0

    # Private methods

    async def _initialize_builtin_presets(self) -> None:
        """Initialize built-in presets if they don't exist."""
        try:
            for preset_def in BUILTIN_PRESETS:
                # Check if a built-in preset with this name already exists
                if await self._builtin_preset_exists(preset_def.name):
                    logger.debug(f"Built-in preset already exists: {preset_def.name}")
                    continue

                # Generate deterministic ID for built-in presets
                preset_id = self._generate_builtin_preset_id(preset_def.name)
                file_path = self.builtin_presets_dir / f"{preset_id}.json"

                preset_def.created_at = datetime.now()
                preset_def.updated_at = preset_def.created_at
                preset_def.is_builtin = True

                await self._save_preset_file(file_path, preset_def)
                logger.info(f"Initialized built-in preset: {preset_def.name}")

        except Exception as e:
            logger.error(f"Failed to initialize built-in presets: {e}")

    async def _load_all_presets(self) -> None:
        """Load all presets from files into cache."""
        try:
            # Clear existing cache
            self._preset_cache.clear()

            # Load built-in presets
            await self._load_presets_from_directory(self.builtin_presets_dir, is_builtin=True)

            # Load user presets
            await self._load_presets_from_directory(self.user_presets_dir, is_builtin=False)

            logger.debug(f"Loaded {len(self._preset_cache)} presets into cache")

        except Exception as e:
            logger.error(f"Failed to load presets: {e}")

    async def _load_presets_from_directory(self, directory: Path, is_builtin: bool) -> None:
        """Load presets from a specific directory."""
        if not directory.exists():
            return

        for file_path in directory.glob("*.json"):
            try:
                preset = await self._load_preset_file(file_path)
                preset.is_builtin = is_builtin

                preset_id = file_path.stem  # Filename without extension
                self._preset_cache[preset_id] = preset

            except Exception as e:
                logger.error(f"Failed to load preset from {file_path}: {e}")

    async def _load_preset_file(self, file_path: Path) -> PresetMetadata:
        """Load a preset from a JSON file."""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                preset_data = json.load(f)

            return PresetMetadata.from_dict(preset_data)

        except Exception as e:
            logger.error(f"Failed to load preset from {file_path}: {e}")
            raise PresetError(f"Failed to load preset from {file_path}: {e}") from e

    async def _save_preset_file(self, file_path: Path, preset: PresetMetadata) -> None:
        """Save a preset to a JSON file."""
        try:
            # Ensure directory exists
            file_path.parent.mkdir(parents=True, exist_ok=True)

            preset_data = preset.to_dict()

            # Write to temporary file first, then rename for atomic operation
            temp_path = file_path.with_suffix('.tmp')
            with open(temp_path, 'w', encoding='utf-8') as f:
                json.dump(preset_data, f, indent=2, ensure_ascii=False)

            # Atomic rename
            temp_path.replace(file_path)

        except Exception as e:
            logger.error(f"Failed to save preset to {file_path}: {e}")
            raise PresetError(f"Failed to save preset to {file_path}: {e}") from e

    def _generate_preset_id(self, name: str) -> str:
        """Generate a unique ID for a preset based on its name."""
        # Create a filename-safe ID from the name
        base_id = "".join(c if c.isalnum() or c in "_-" else "_" for c in name.lower())
        base_id = base_id.strip("_")[:50]  # Limit length

        # Ensure uniqueness by adding timestamp if needed
        if not base_id:
            base_id = "preset"

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return f"{base_id}_{timestamp}"

    def _generate_builtin_preset_id(self, name: str) -> str:
        """Generate a deterministic ID for built-in presets."""
        # Create a filename-safe ID from the name (no timestamp for built-ins)
        base_id = "".join(c if c.isalnum() or c in "_-" else "_" for c in name.lower())
        base_id = base_id.strip("_")[:50]  # Limit length

        if not base_id:
            base_id = "builtin_preset"

        return f"builtin_{base_id}"

    async def _builtin_preset_exists(self, name: str) -> bool:
        """Check if a built-in preset with the given name already exists."""
        if not self.builtin_presets_dir.exists():
            return False

        for file_path in self.builtin_presets_dir.glob("*.json"):
            try:
                preset = await self._load_preset_file(file_path)
                if preset.name == name and preset.is_builtin:
                    return True
            except Exception as e:
                logger.warning(f"Error checking preset file {file_path}: {e}")
                continue

        return False

    def _validate_preset(self, preset: PresetMetadata) -> None:
        """Validate a preset object."""
        if not preset.name or not preset.name.strip():
            raise PresetValidationError("Preset name cannot be empty")

        if not preset.prompt or not preset.prompt.strip():
            raise PresetValidationError("Preset prompt cannot be empty")

        if len(preset.name) > 255:
            raise PresetValidationError("Preset name too long (max 255 characters)")

        if len(preset.prompt) > 10000:
            raise PresetValidationError("Preset prompt too long (max 10000 characters)")

    async def _preset_name_exists(self, name: str, exclude_id: Optional[str] = None) -> bool:
        """Check if a preset with the given name already exists."""
        for preset_id, preset in self._preset_cache.items():
            if preset_id == exclude_id:
                continue
            if preset.name.lower() == name.lower():
                return True
        return False

    async def _find_preset_id_by_name(self, name: str) -> Optional[str]:
        """Find preset ID by name."""
        for preset_id, preset in self._preset_cache.items():
            if preset.name.lower() == name.lower():
                return preset_id
        return None

    async def refresh_presets(self) -> None:
        """
        Refresh presets from disk, reloading any new or modified files.

        This method should be called when presets may have been added or modified
        outside of the normal PresetManager operations (e.g., manual file editing).
        """
        if not self._initialized:
            await self.initialize()
            return

        async with self._cache_lock:
            try:
                # Get current preset files on disk
                current_files = set()

                # Check builtin presets
                if self.builtin_presets_dir.exists():
                    for file_path in self.builtin_presets_dir.glob("*.json"):
                        current_files.add(file_path)

                # Check user presets
                if self.user_presets_dir.exists():
                    for file_path in self.user_presets_dir.glob("*.json"):
                        current_files.add(file_path)

                # Get cached preset IDs
                cached_ids = set(self._preset_cache.keys())

                # Find new or modified files
                files_to_load = []
                for file_path in current_files:
                    preset_id = file_path.stem  # filename without extension

                    # Check if this is a new file or if the file has been modified
                    if preset_id not in cached_ids:
                        files_to_load.append((file_path, preset_id))
                    else:
                        # Check if file has been modified since last load
                        try:
                            # For now, we'll reload all files to be safe
                            # In the future, we could track modification times
                            files_to_load.append((file_path, preset_id))
                        except OSError:
                            continue

                # Reload presets
                for file_path, preset_id in files_to_load:
                    try:
                        preset = await self._load_preset_file(file_path)
                        preset.is_builtin = (file_path.parent == self.builtin_presets_dir)
                        self._preset_cache[preset_id] = preset
                        logger.debug(f"Refreshed preset: {preset.name} (ID: {preset_id})")
                    except Exception as e:
                        logger.error(f"Failed to refresh preset from {file_path}: {e}")

                # Remove presets that no longer exist on disk
                files_to_remove = []
                for cached_id in cached_ids:
                    preset = self._preset_cache[cached_id]
                    if preset.is_builtin:
                        expected_path = self.builtin_presets_dir / f"{cached_id}.json"
                    else:
                        expected_path = self.user_presets_dir / f"{cached_id}.json"

                    if not expected_path.exists():
                        files_to_remove.append(cached_id)

                for preset_id in files_to_remove:
                    del self._preset_cache[preset_id]
                    logger.debug(f"Removed preset no longer on disk: {preset_id}")

                logger.debug(f"Refreshed presets: loaded {len(files_to_load)}, removed {len(files_to_remove)}")

            except Exception as e:
                logger.error(f"Failed to refresh presets: {e}")

    async def close(self) -> None:
        """Clean shutdown of the PresetManager."""
        try:
            # Clear the cache to free memory
            async with self._cache_lock:
                self._preset_cache.clear()

            self._initialized = False
            logger.debug("PresetManager shutdown complete")

        except Exception as e:
            logger.error(f"Error during PresetManager shutdown: {e}")
