"""
Performance Optimization Integration Guide.

This module provides documentation and examples for integrating
the performance optimization components with existing application code.
"""

# INTEGRATION EXAMPLE 1: Enhanced Main Controller
"""
To use the optimized main controller:

1. Import the optimization wrapper:
   from src.controllers.optimized_main_controller import create_optimized_controller

2. Wrap your existing main controller:
   # Original initialization
   main_controller = MainController(event_bus, settings_manager, ...)
   await main_controller.initialize()

   # Add optimization layer
   optimized_controller = create_optimized_controller(main_controller)
   await optimized_controller.initialize_optimization()

3. Use the optimized controller instead of the original:
   # All original methods work the same
   status = await optimized_controller.get_application_status()

   # Plus new optimization features
   opt_status = await optimized_controller.get_optimization_status()
"""

# INTEGRATION EXAMPLE 2: Gallery Window Optimization
"""
To optimize gallery thumbnail loading:

1. Import the gallery optimizer:
   from src.views.gallery_optimization import create_gallery_optimizer

2. Add to your gallery window initialization:
   # In GalleryWindow.__init__ or similar
   if optimization_manager:
       thumbnail_manager = optimization_manager.get_thumbnail_manager()
       self.gallery_optimizer = create_gallery_optimizer(self, thumbnail_manager)
       await self.gallery_optimizer.initialize()

3. Use optimized loading in your scroll/viewport change handlers:
   async def on_viewport_changed(self, visible_start, visible_count):
       if self.gallery_optimizer:
           await self.gallery_optimizer.optimize_viewport_loading(
               self.screenshot_metadata,
               visible_start,
               visible_count
           )
"""

# INTEGRATION EXAMPLE 3: Database Schema Migration
"""
To ensure your database has the performance optimization schema:

1. Run the migration script:
   python -m src.models.migrate_db

2. Or integrate into your application startup:
   from src.models.database_schema_migration import DatabaseSchemaMigration

   migration_manager = DatabaseSchemaMigration(database_manager)
   success = await migration_manager.migrate_to_latest()

   if not success:
       logger.error("Database migration failed")
"""

# INTEGRATION EXAMPLE 4: Manual Component Usage
"""
To use individual optimization components:

1. Initialize the components you need:
   # Cache Manager
   cache_manager = CacheManager(db_manager, settings_manager, event_bus)
   await cache_manager.initialize()

   # Storage Manager
   storage_manager = StorageManager(screenshot_manager, db_manager, settings_manager, event_bus)
   await storage_manager.initialize()

2. Use in your application logic:
   # Check for cached AI response
   cached_response = await cache_manager.get_cached_response(prompt, model_name)
   if cached_response:
       return cached_response

   # Generate new response and cache it
   response = await ollama_client.generate_response(prompt)
   await cache_manager.store_response(prompt, response, model_name)

   # Monitor storage usage
   if await storage_manager.check_storage_limit():
       await storage_manager.execute_pruning()
"""

# CONFIGURATION EXAMPLE
"""
Performance optimization settings can be configured through SettingsManager:

# Cache configuration
await settings_manager.set_setting("optimization.cache_max_entries", 1000)
await settings_manager.set_setting("optimization.cache_ttl_hours", 48)

# Storage configuration
await settings_manager.set_setting("optimization.max_storage_gb", 20.0)
await settings_manager.set_setting("optimization.max_file_count", 5000)

# Performance monitoring
await settings_manager.set_setting("optimization.enable_performance_monitoring", True)
await settings_manager.set_setting("optimization.memory_threshold_mb", 2048)

# Thumbnail configuration
await settings_manager.set_setting("optimization.thumbnail_cache_size", 200)
"""

# EVENT INTEGRATION EXAMPLE
"""
The optimization components emit events for monitoring and integration:

# Subscribe to optimization events
await event_bus.subscribe("optimization.components.initialized", on_optimization_ready)
await event_bus.subscribe("performance.threshold_exceeded", on_performance_issue)
await event_bus.subscribe("storage.cleanup_needed", on_storage_cleanup)
await event_bus.subscribe("cache.cleanup_needed", on_cache_cleanup)

async def on_optimization_ready(event_data):
    components = event_data.data.get('components', {})
    logger.info(f"Optimization components ready: {components}")

async def on_performance_issue(event_data):
    metric_type = event_data.data.get('metric_type')
    value = event_data.data.get('value')
    logger.warning(f"Performance threshold exceeded: {metric_type} = {value}")

    # Trigger cleanup or other response
    if metric_type == 'memory_usage':
        await trigger_memory_cleanup()
"""

# BACKWARDS COMPATIBILITY
"""
All optimization components are designed to be backwards compatible:

1. Existing code continues to work without changes
2. Optimization is additive, not replacing existing functionality
3. Components gracefully degrade if optimization is not available
4. Original APIs are preserved and enhanced, not replaced

Example - ScreenshotManager remains the same:
# This code works with or without optimization
result = await screenshot_manager.capture_screenshot()

But with optimization, storage is automatically managed:
# Storage cleanup happens automatically in background
# Performance metrics are collected automatically
# No code changes required
"""

# PERFORMANCE MONITORING
"""
Performance monitoring provides insights into application behavior:

# Get performance statistics
if optimization_manager:
    stats = await optimization_manager.get_performance_stats()

    cache_stats = stats.get('cache', {})
    storage_stats = stats.get('storage', {})
    performance_stats = stats.get('performance', {})

    logger.info(f"Cache hit rate: {cache_stats.get('hit_rate', 0)}%")
    logger.info(f"Storage usage: {storage_stats.get('total_size_mb', 0)} MB")
    logger.info(f"Memory usage: {performance_stats.get('avg', 0)} MB")
"""

# ERROR HANDLING
"""
Optimization components include comprehensive error handling:

1. Failed optimization initialization doesn't break the application
2. Individual component failures are isolated
3. Graceful degradation when optimization features are unavailable
4. Detailed logging for troubleshooting

Example:
try:
    success = await optimization_manager.initialize()
    if not success:
        logger.warning("Optimization unavailable, continuing without it")
except Exception as e:
    logger.error(f"Optimization error (non-critical): {e}")
    # Application continues normally
"""
