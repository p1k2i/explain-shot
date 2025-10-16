"""
Performance Monitor for Application Optimization

This module provides comprehensive performance monitoring with metrics collection,
profiling integration, threshold management, and automated performance responses.
"""

import asyncio
import logging
import psutil
import gc
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Callable
from enum import Enum

logger = logging.getLogger(__name__)


class PerformanceLevel(Enum):
    """Performance status levels."""
    EXCELLENT = "excellent"
    GOOD = "good"
    FAIR = "fair"
    POOR = "poor"
    CRITICAL = "critical"


class MetricType(Enum):
    """Types of metrics to collect."""
    MEMORY = "memory"
    CPU = "cpu"
    DISK = "disk"
    RESPONSE_TIME = "response_time"
    CACHE_HIT_RATIO = "cache_hit_ratio"
    QUEUE_DEPTH = "queue_depth"
    ERROR_RATE = "error_rate"


@dataclass
class PerformanceThreshold:
    """Performance threshold configuration."""
    metric_type: MetricType
    excellent_max: float
    good_max: float
    fair_max: float
    poor_max: float
    # Above poor_max is critical


@dataclass
class MetricSample:
    """A single metric sample."""
    timestamp: datetime
    metric_type: MetricType
    value: float
    context: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PerformanceSnapshot:
    """Complete performance snapshot."""
    timestamp: datetime
    memory_usage_mb: float
    memory_usage_percent: float
    cpu_usage_percent: float
    disk_usage_percent: float
    response_times: Dict[str, float]
    cache_hit_ratios: Dict[str, float]
    queue_depths: Dict[str, int]
    error_rates: Dict[str, float]
    overall_level: PerformanceLevel
    recommendations: List[str]


@dataclass
class PerformanceConfig:
    """Configuration for performance monitoring."""
    collection_interval: float = 10.0  # seconds
    retention_hours: int = 24
    enable_profiling: bool = False
    enable_gc_monitoring: bool = True
    memory_threshold_mb: float = 500.0
    cpu_threshold_percent: float = 80.0
    response_time_threshold_ms: float = 1000.0
    enable_automated_responses: bool = True


class PerformanceMonitor:
    """
    Comprehensive performance monitoring system.

    Provides:
    - Real-time metrics collection (memory, CPU, disk, response times)
    - Performance threshold monitoring with alerting
    - Automated optimization responses
    - Historical performance tracking
    - Profiling integration
    - Performance recommendations
    """

    def __init__(self, event_bus, settings_manager=None):
        """
        Initialize the performance monitor.

        Args:
            event_bus: EventBus for communication
            settings_manager: Optional settings manager
        """
        self.event_bus = event_bus
        self.settings_manager = settings_manager

        # Configuration
        self._config = PerformanceConfig()
        self._initialized = False

        # Thresholds
        self._thresholds = self._create_default_thresholds()

        # Metrics storage
        self._metric_history: Dict[MetricType, List[MetricSample]] = {
            metric_type: [] for metric_type in MetricType
        }
        self._metrics_lock = asyncio.Lock()

        # Component references (set during integration)
        self._thumbnail_manager = None
        self._cache_manager = None
        self._request_manager = None
        self._storage_manager = None

        # Monitoring tasks
        self._collection_task: Optional[asyncio.Task] = None
        self._cleanup_task: Optional[asyncio.Task] = None

        # Performance tracking
        self._last_snapshot: Optional[PerformanceSnapshot] = None
        self._performance_callbacks: List[Callable] = []

        # Profiling state
        self._profiling_active = False
        self._profiling_data = {}

        logger.info("PerformanceMonitor initialized")

    def _create_default_thresholds(self) -> Dict[MetricType, PerformanceThreshold]:
        """Create default performance thresholds."""
        return {
            MetricType.MEMORY: PerformanceThreshold(
                metric_type=MetricType.MEMORY,
                excellent_max=200.0,  # MB
                good_max=350.0,
                fair_max=450.0,
                poor_max=500.0
            ),
            MetricType.CPU: PerformanceThreshold(
                metric_type=MetricType.CPU,
                excellent_max=20.0,  # %
                good_max=40.0,
                fair_max=60.0,
                poor_max=80.0
            ),
            MetricType.RESPONSE_TIME: PerformanceThreshold(
                metric_type=MetricType.RESPONSE_TIME,
                excellent_max=100.0,  # ms
                good_max=500.0,
                fair_max=1000.0,
                poor_max=2000.0
            ),
            MetricType.CACHE_HIT_RATIO: PerformanceThreshold(
                metric_type=MetricType.CACHE_HIT_RATIO,
                excellent_max=90.0,  # %
                good_max=75.0,
                fair_max=60.0,
                poor_max=40.0
            ),
            MetricType.QUEUE_DEPTH: PerformanceThreshold(
                metric_type=MetricType.QUEUE_DEPTH,
                excellent_max=2.0,  # items
                good_max=5.0,
                fair_max=8.0,
                poor_max=10.0
            ),
            MetricType.ERROR_RATE: PerformanceThreshold(
                metric_type=MetricType.ERROR_RATE,
                excellent_max=1.0,  # %
                good_max=5.0,
                fair_max=10.0,
                poor_max=20.0
            )
        }

    async def initialize(self) -> None:
        """Initialize the performance monitor."""
        try:
            # Load configuration
            await self._load_settings()

            # Subscribe to events
            if self.event_bus:
                self.event_bus.subscribe("settings.changed", self._handle_settings_changed)
                self.event_bus.subscribe("performance.profiling_requested", self._handle_profiling_requested)
                self.event_bus.subscribe("performance.snapshot_requested", self._handle_snapshot_requested)

            # Start monitoring tasks
            await self._start_monitoring()

            self._initialized = True
            logger.info("PerformanceMonitor initialized successfully")

        except Exception as e:
            logger.error(f"Failed to initialize PerformanceMonitor: {e}")
            raise

    async def _load_settings(self) -> None:
        """Load performance monitoring configuration."""
        try:
            if not self.settings_manager:
                return

            settings = await self.settings_manager.load_settings()

            # Load performance configuration if available
            if hasattr(settings, 'performance'):
                perf_config = settings.performance
                self._config.collection_interval = getattr(perf_config, 'collection_interval', 10.0)
                self._config.retention_hours = getattr(perf_config, 'retention_hours', 24)
                self._config.enable_profiling = getattr(perf_config, 'enable_profiling', False)
                self._config.enable_gc_monitoring = getattr(perf_config, 'enable_gc_monitoring', True)
                self._config.memory_threshold_mb = getattr(perf_config, 'memory_threshold_mb', 500.0)
                self._config.cpu_threshold_percent = getattr(perf_config, 'cpu_threshold_percent', 80.0)
                self._config.enable_automated_responses = getattr(perf_config, 'enable_automated_responses', True)

            logger.debug(f"Loaded performance settings - Interval: {self._config.collection_interval}s")

        except Exception as e:
            logger.warning(f"Failed to load performance settings: {e}")

    def register_components(self, thumbnail_manager=None, cache_manager=None,
                          request_manager=None, storage_manager=None) -> None:
        """Register optimization components for monitoring."""
        self._thumbnail_manager = thumbnail_manager
        self._cache_manager = cache_manager
        self._request_manager = request_manager
        self._storage_manager = storage_manager

        logger.debug("Registered components for performance monitoring")

    def add_performance_callback(self, callback: Callable) -> None:
        """Add callback for performance updates."""
        self._performance_callbacks.append(callback)

    async def _start_monitoring(self) -> None:
        """Start performance monitoring tasks."""
        try:
            # Start metric collection
            self._collection_task = asyncio.create_task(self._metric_collection_loop())

            # Start cleanup task
            self._cleanup_task = asyncio.create_task(self._cleanup_loop())

            logger.info("Performance monitoring started")

        except Exception as e:
            logger.error(f"Failed to start monitoring: {e}")

    async def _metric_collection_loop(self) -> None:
        """Main metric collection loop."""
        try:
            while True:
                await asyncio.sleep(self._config.collection_interval)

                try:
                    await self._collect_metrics()
                    await self._analyze_performance()

                except Exception as e:
                    logger.error(f"Error in metric collection: {e}")

        except asyncio.CancelledError:
            logger.info("Metric collection loop cancelled")
        except Exception as e:
            logger.error(f"Metric collection loop failed: {e}")

    async def _collect_metrics(self) -> None:
        """Collect all performance metrics."""
        try:
            now = datetime.now()

            # System metrics
            await self._collect_system_metrics(now)

            # Component metrics
            await self._collect_component_metrics(now)

            # Custom metrics
            await self._collect_custom_metrics(now)

        except Exception as e:
            logger.error(f"Failed to collect metrics: {e}")

    async def _collect_system_metrics(self, timestamp: datetime) -> None:
        """Collect system-level metrics."""
        try:
            # Memory usage
            process = psutil.Process()
            memory_info = process.memory_info()
            memory_mb = memory_info.rss / 1024 / 1024

            await self._record_metric(MetricType.MEMORY, memory_mb, timestamp, {
                'vms': memory_info.vms / 1024 / 1024,
                'shared': getattr(memory_info, 'shared', 0) / 1024 / 1024
            })

            # CPU usage
            cpu_percent = process.cpu_percent()
            await self._record_metric(MetricType.CPU, cpu_percent, timestamp)

            # Disk usage (if we can determine screenshot directory)
            try:
                # Try to get screenshot directory from storage manager
                if self._storage_manager and hasattr(self._storage_manager, 'screenshot_manager'):
                    screenshot_manager = self._storage_manager.screenshot_manager
                    if hasattr(screenshot_manager, '_current_directory'):
                        screenshot_dir = screenshot_manager._current_directory
                        if screenshot_dir:
                            disk_usage = psutil.disk_usage(screenshot_dir)
                            disk_percent = (disk_usage.used / disk_usage.total) * 100
                            await self._record_metric(MetricType.DISK, disk_percent, timestamp)
            except Exception:
                pass  # Disk metrics are optional

        except Exception as e:
            logger.error(f"Failed to collect system metrics: {e}")

    async def _collect_component_metrics(self, timestamp: datetime) -> None:
        """Collect metrics from optimization components."""
        try:
            # Thumbnail manager metrics
            if self._thumbnail_manager:
                try:
                    stats = self._thumbnail_manager.get_cache_statistics()
                    hit_ratio = stats.get('hit_ratio', 0)
                    await self._record_metric(MetricType.CACHE_HIT_RATIO, hit_ratio, timestamp, {
                        'component': 'thumbnail_cache',
                        'memory_mb': stats.get('memory_usage_mb', 0)
                    })
                except Exception as e:
                    logger.warning(f"Failed to collect thumbnail metrics: {e}")

            # Cache manager metrics
            if self._cache_manager:
                try:
                    stats = self._cache_manager.get_cache_statistics()
                    hit_ratio = stats.get('hit_ratio', 0)
                    await self._record_metric(MetricType.CACHE_HIT_RATIO, hit_ratio, timestamp, {
                        'component': 'response_cache',
                        'memory_mb': stats.get('memory_usage_mb', 0)
                    })
                except Exception as e:
                    logger.warning(f"Failed to collect cache metrics: {e}")

            # Request manager metrics
            if self._request_manager:
                try:
                    stats = self._request_manager.get_request_statistics()
                    queue_status = await self._request_manager.get_queue_status()

                    # Queue depth
                    total_queued = queue_status.total_queued
                    await self._record_metric(MetricType.QUEUE_DEPTH, total_queued, timestamp, {
                        'component': 'request_queue'
                    })

                    # Response time
                    avg_time_ms = stats.get('average_processing_time', 0) * 1000
                    await self._record_metric(MetricType.RESPONSE_TIME, avg_time_ms, timestamp, {
                        'component': 'ollama_requests'
                    })

                    # Error rate
                    total_requests = stats.get('total_requests', 0)
                    failed_requests = stats.get('failed_requests', 0)
                    error_rate = (failed_requests / total_requests * 100) if total_requests > 0 else 0
                    await self._record_metric(MetricType.ERROR_RATE, error_rate, timestamp, {
                        'component': 'ollama_requests'
                    })
                except Exception as e:
                    logger.warning(f"Failed to collect request metrics: {e}")

        except Exception as e:
            logger.error(f"Failed to collect component metrics: {e}")

    async def _collect_custom_metrics(self, timestamp: datetime) -> None:
        """Collect custom application metrics."""
        try:
            # Garbage collection metrics
            if self._config.enable_gc_monitoring:
                gc_stats = gc.get_stats()
                if gc_stats:
                    for i, gen_stats in enumerate(gc_stats):
                        collections = gen_stats.get('collections', 0)
                        await self._record_metric(MetricType.MEMORY, collections, timestamp, {
                            'metric_subtype': f'gc_gen_{i}_collections'
                        })

        except Exception as e:
            logger.error(f"Failed to collect custom metrics: {e}")

    async def _record_metric(self, metric_type: MetricType, value: float,
                           timestamp: datetime, context: Optional[Dict] = None) -> None:
        """Record a metric sample."""
        try:
            sample = MetricSample(
                timestamp=timestamp,
                metric_type=metric_type,
                value=value,
                context=context or {}
            )

            async with self._metrics_lock:
                self._metric_history[metric_type].append(sample)

                # Limit history size
                max_samples = int(self._config.retention_hours * 3600 / self._config.collection_interval)
                if len(self._metric_history[metric_type]) > max_samples:
                    self._metric_history[metric_type] = self._metric_history[metric_type][-max_samples:]

        except Exception as e:
            logger.error(f"Failed to record metric: {e}")

    async def _analyze_performance(self) -> None:
        """Analyze current performance and trigger responses."""
        try:
            snapshot = await self.collect_performance_snapshot()

            if snapshot:
                self._last_snapshot = snapshot

                # Trigger automated responses if enabled
                if self._config.enable_automated_responses:
                    await self._trigger_automated_responses(snapshot)

                # Notify callbacks
                for callback in self._performance_callbacks:
                    try:
                        callback(snapshot)
                    except Exception as e:
                        logger.error(f"Error in performance callback: {e}")

                # Emit performance event
                if self.event_bus:
                    await self.event_bus.emit("performance.snapshot_collected", {
                        'snapshot': self._snapshot_to_dict(snapshot),
                        'timestamp': snapshot.timestamp.isoformat()
                    })

        except Exception as e:
            logger.error(f"Failed to analyze performance: {e}")

    async def collect_performance_snapshot(self) -> Optional[PerformanceSnapshot]:
        """Collect a comprehensive performance snapshot."""
        try:
            now = datetime.now()

            # Get latest metrics
            async with self._metrics_lock:
                latest_memory = self._get_latest_metric(MetricType.MEMORY)
                latest_cpu = self._get_latest_metric(MetricType.CPU)
                latest_disk = self._get_latest_metric(MetricType.DISK)

            # Collect component-specific metrics
            response_times = {}
            cache_hit_ratios = {}
            queue_depths = {}
            error_rates = {}

            if self._request_manager:
                stats = self._request_manager.get_request_statistics()
                response_times['ollama'] = stats.get('average_processing_time', 0) * 1000
                error_rates['ollama'] = (
                    stats.get('failed_requests', 0) / stats.get('total_requests', 1) * 100
                )

                queue_status = await self._request_manager.get_queue_status()
                queue_depths['requests'] = queue_status.total_queued

            if self._cache_manager:
                stats = self._cache_manager.get_cache_statistics()
                cache_hit_ratios['responses'] = stats.get('hit_ratio', 0)

            if self._thumbnail_manager:
                stats = self._thumbnail_manager.get_cache_statistics()
                cache_hit_ratios['thumbnails'] = stats.get('hit_ratio', 0)

            # Determine overall performance level
            overall_level = self._calculate_overall_performance_level(
                latest_memory, latest_cpu, response_times, cache_hit_ratios, error_rates
            )

            # Generate recommendations
            recommendations = self._generate_recommendations(
                latest_memory, latest_cpu, response_times, cache_hit_ratios, queue_depths, error_rates
            )

            return PerformanceSnapshot(
                timestamp=now,
                memory_usage_mb=latest_memory or 0,
                memory_usage_percent=0,  # Would need system memory info
                cpu_usage_percent=latest_cpu or 0,
                disk_usage_percent=latest_disk or 0,
                response_times=response_times,
                cache_hit_ratios=cache_hit_ratios,
                queue_depths=queue_depths,
                error_rates=error_rates,
                overall_level=overall_level,
                recommendations=recommendations
            )

        except Exception as e:
            logger.error(f"Failed to collect performance snapshot: {e}")
            return None

    def _get_latest_metric(self, metric_type: MetricType) -> Optional[float]:
        """Get the latest value for a metric type."""
        try:
            samples = self._metric_history.get(metric_type, [])
            if samples:
                return samples[-1].value
            return None
        except Exception:
            return None

    def _calculate_overall_performance_level(self, memory: Optional[float], cpu: Optional[float],
                                           response_times: Dict, cache_hit_ratios: Dict,
                                           error_rates: Dict) -> PerformanceLevel:
        """Calculate overall performance level based on metrics."""
        try:
            scores = []

            # Memory score
            if memory is not None:
                memory_threshold = self._thresholds[MetricType.MEMORY]
                memory_score = self._calculate_metric_score(memory, memory_threshold)
                scores.append(memory_score)

            # CPU score
            if cpu is not None:
                cpu_threshold = self._thresholds[MetricType.CPU]
                cpu_score = self._calculate_metric_score(cpu, cpu_threshold)
                scores.append(cpu_score)

            # Response time score (average of all response times)
            if response_times:
                avg_response_time = sum(response_times.values()) / len(response_times)
                rt_threshold = self._thresholds[MetricType.RESPONSE_TIME]
                rt_score = self._calculate_metric_score(avg_response_time, rt_threshold)
                scores.append(rt_score)

            # Cache hit ratio score (average of all cache ratios)
            if cache_hit_ratios:
                avg_cache_ratio = sum(cache_hit_ratios.values()) / len(cache_hit_ratios)
                cache_threshold = self._thresholds[MetricType.CACHE_HIT_RATIO]
                # For cache hit ratio, higher is better, so invert the logic
                cache_score = self._calculate_metric_score(100 - avg_cache_ratio, cache_threshold, invert=True)
                scores.append(cache_score)

            # Error rate score (average of all error rates)
            if error_rates:
                avg_error_rate = sum(error_rates.values()) / len(error_rates)
                error_threshold = self._thresholds[MetricType.ERROR_RATE]
                error_score = self._calculate_metric_score(avg_error_rate, error_threshold)
                scores.append(error_score)

            # Calculate overall score
            if scores:
                avg_score = sum(scores) / len(scores)

                if avg_score >= 4:
                    return PerformanceLevel.EXCELLENT
                elif avg_score >= 3:
                    return PerformanceLevel.GOOD
                elif avg_score >= 2:
                    return PerformanceLevel.FAIR
                elif avg_score >= 1:
                    return PerformanceLevel.POOR
                else:
                    return PerformanceLevel.CRITICAL

            return PerformanceLevel.GOOD  # Default if no metrics available

        except Exception as e:
            logger.error(f"Failed to calculate performance level: {e}")
            return PerformanceLevel.FAIR

    def _calculate_metric_score(self, value: float, threshold: PerformanceThreshold,
                              invert: bool = False) -> int:
        """Calculate a score (1-5) for a metric value against thresholds."""
        try:
            if invert:
                # For metrics where higher is better (like cache hit ratio)
                if value >= threshold.excellent_max:
                    return 5
                elif value >= threshold.good_max:
                    return 4
                elif value >= threshold.fair_max:
                    return 3
                elif value >= threshold.poor_max:
                    return 2
                else:
                    return 1
            else:
                # For metrics where lower is better (like response time)
                if value <= threshold.excellent_max:
                    return 5
                elif value <= threshold.good_max:
                    return 4
                elif value <= threshold.fair_max:
                    return 3
                elif value <= threshold.poor_max:
                    return 2
                else:
                    return 1

        except Exception:
            return 3  # Fair default

    def _generate_recommendations(self, memory: Optional[float], cpu: Optional[float],
                                response_times: Dict, cache_hit_ratios: Dict,
                                queue_depths: Dict, error_rates: Dict) -> List[str]:
        """Generate performance recommendations."""
        recommendations = []

        try:
            # Memory recommendations
            if memory and memory > self._config.memory_threshold_mb:
                recommendations.append(f"High memory usage ({memory:.1f}MB). Consider reducing cache sizes or closing unused features.")

            # CPU recommendations
            if cpu and cpu > self._config.cpu_threshold_percent:
                recommendations.append(f"High CPU usage ({cpu:.1f}%). Consider reducing concurrent operations or thumbnail generation quality.")

            # Response time recommendations
            avg_response_time = sum(response_times.values()) / len(response_times) if response_times else 0
            if avg_response_time > self._config.response_time_threshold_ms:
                recommendations.append(f"Slow response times ({avg_response_time:.1f}ms). Consider enabling response caching or reducing image quality.")

            # Cache recommendations
            for component, ratio in cache_hit_ratios.items():
                if ratio < 60:  # Below 60% hit ratio
                    recommendations.append(f"Low cache hit ratio for {component} ({ratio:.1f}%). Consider increasing cache size or adjusting retention.")

            # Queue depth recommendations
            for component, depth in queue_depths.items():
                if depth > 5:
                    recommendations.append(f"High queue depth for {component} ({depth} items). Consider increasing concurrency or optimizing request processing.")

            # Error rate recommendations
            for component, rate in error_rates.items():
                if rate > 10:  # Above 10% error rate
                    recommendations.append(f"High error rate for {component} ({rate:.1f}%). Check connectivity and server status.")

            # General recommendations
            if not recommendations:
                recommendations.append("Performance is optimal. No specific recommendations at this time.")

        except Exception as e:
            logger.error(f"Failed to generate recommendations: {e}")
            recommendations.append("Unable to generate specific recommendations due to analysis error.")

        return recommendations

    async def _trigger_automated_responses(self, snapshot: PerformanceSnapshot) -> None:
        """Trigger automated performance responses."""
        try:
            # Memory pressure responses
            if snapshot.memory_usage_mb > self._config.memory_threshold_mb:
                logger.warning(f"Memory pressure detected: {snapshot.memory_usage_mb:.1f}MB")

                # Trigger cache cleanup
                if self._cache_manager:
                    asyncio.create_task(self._cache_manager.optimize_cache_database())

                if self._thumbnail_manager:
                    # Could trigger cache reduction
                    pass

                # Emit memory pressure event
                if self.event_bus:
                    await self.event_bus.emit("performance.memory_pressure", {
                        'memory_mb': snapshot.memory_usage_mb,
                        'threshold_mb': self._config.memory_threshold_mb,
                        'timestamp': snapshot.timestamp.isoformat()
                    })

            # Response time responses
            avg_response_time = sum(snapshot.response_times.values()) / len(snapshot.response_times) if snapshot.response_times else 0
            if avg_response_time > self._config.response_time_threshold_ms:
                logger.warning(f"Slow response times detected: {avg_response_time:.1f}ms")

                # Could adjust request concurrency
                if self._request_manager:
                    # Reduce concurrency if response times are too high
                    await self._request_manager.configure_limits(max_concurrent=1)

                # Emit slow response event
                if self.event_bus:
                    await self.event_bus.emit("performance.slow_responses", {
                        'avg_response_time_ms': avg_response_time,
                        'threshold_ms': self._config.response_time_threshold_ms,
                        'timestamp': snapshot.timestamp.isoformat()
                    })

        except Exception as e:
            logger.error(f"Failed to trigger automated responses: {e}")

    def _snapshot_to_dict(self, snapshot: PerformanceSnapshot) -> Dict[str, Any]:
        """Convert performance snapshot to dictionary for serialization."""
        return {
            'timestamp': snapshot.timestamp.isoformat(),
            'memory_usage_mb': snapshot.memory_usage_mb,
            'memory_usage_percent': snapshot.memory_usage_percent,
            'cpu_usage_percent': snapshot.cpu_usage_percent,
            'disk_usage_percent': snapshot.disk_usage_percent,
            'response_times': snapshot.response_times,
            'cache_hit_ratios': snapshot.cache_hit_ratios,
            'queue_depths': snapshot.queue_depths,
            'error_rates': snapshot.error_rates,
            'overall_level': snapshot.overall_level.value,
            'recommendations': snapshot.recommendations
        }

    async def _cleanup_loop(self) -> None:
        """Periodic cleanup of old metrics."""
        try:
            while True:
                await asyncio.sleep(3600)  # Run every hour

                try:
                    await self._cleanup_old_metrics()
                except Exception as e:
                    logger.error(f"Error in metric cleanup: {e}")

        except asyncio.CancelledError:
            logger.info("Cleanup loop cancelled")
        except Exception as e:
            logger.error(f"Cleanup loop failed: {e}")

    async def _cleanup_old_metrics(self) -> None:
        """Clean up old metric samples."""
        try:
            cutoff_time = datetime.now() - timedelta(hours=self._config.retention_hours)

            async with self._metrics_lock:
                for metric_type in MetricType:
                    samples = self._metric_history[metric_type]
                    # Keep only samples newer than cutoff
                    self._metric_history[metric_type] = [
                        sample for sample in samples if sample.timestamp > cutoff_time
                    ]

        except Exception as e:
            logger.error(f"Failed to cleanup old metrics: {e}")

    def get_performance_statistics(self) -> Dict[str, Any]:
        """Get performance monitoring statistics."""
        try:
            total_samples = sum(len(samples) for samples in self._metric_history.values())

            return {
                'monitoring_active': self._collection_task is not None and not self._collection_task.done(),
                'total_metric_samples': total_samples,
                'collection_interval': self._config.collection_interval,
                'retention_hours': self._config.retention_hours,
                'last_snapshot': self._snapshot_to_dict(self._last_snapshot) if self._last_snapshot else None,
                'metric_types_tracked': len(self._metric_history),
                'profiling_active': self._profiling_active,
                'automated_responses_enabled': self._config.enable_automated_responses
            }

        except Exception as e:
            logger.error(f"Failed to get performance statistics: {e}")
            return {}

    async def _handle_settings_changed(self, event_data) -> None:
        """Handle settings change events."""
        try:
            data = event_data.get('data', {})
            key = data.get('key', '')

            if key.startswith('performance.'):
                await self._load_settings()
                logger.info("Reloaded performance settings")

        except Exception as e:
            logger.error(f"Failed to handle settings change: {e}")

    async def _handle_profiling_requested(self, event_data) -> None:
        """Handle profiling request events."""
        try:
            # Simple profiling toggle
            self._profiling_active = not self._profiling_active

            if self.event_bus:
                await self.event_bus.emit("performance.profiling_toggled", {
                    'active': self._profiling_active,
                    'timestamp': datetime.now().isoformat()
                })

        except Exception as e:
            logger.error(f"Failed to handle profiling request: {e}")

    async def _handle_snapshot_requested(self, event_data) -> None:
        """Handle manual snapshot requests."""
        try:
            snapshot = await self.collect_performance_snapshot()

            if snapshot and self.event_bus:
                await self.event_bus.emit("performance.manual_snapshot", {
                    'snapshot': self._snapshot_to_dict(snapshot),
                    'timestamp': snapshot.timestamp.isoformat()
                })

        except Exception as e:
            logger.error(f"Failed to handle snapshot request: {e}")

    async def shutdown(self) -> None:
        """Shutdown the performance monitor."""
        try:
            logger.info("Shutting down PerformanceMonitor")

            # Cancel monitoring tasks
            if self._collection_task and not self._collection_task.done():
                self._collection_task.cancel()
                try:
                    await self._collection_task
                except asyncio.CancelledError:
                    pass

            if self._cleanup_task and not self._cleanup_task.done():
                self._cleanup_task.cancel()
                try:
                    await self._cleanup_task
                except asyncio.CancelledError:
                    pass

            logger.info("PerformanceMonitor shutdown complete")

        except Exception as e:
            logger.error(f"Error during PerformanceMonitor shutdown: {e}")
