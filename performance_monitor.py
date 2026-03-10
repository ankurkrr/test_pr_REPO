"""
Performance Monitoring Script for Meeting Agent
Tracks execution times, email sending times, and overall workflow performance
"""

import time
import logging
from datetime import datetime
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from collections import defaultdict
import json

logger = logging.getLogger(__name__)


@dataclass
class ToolTiming:
    """Track timing for a single tool execution."""
    tool_name: str
    user_id: str
    start_time: float
    end_time: Optional[float] = None
    duration: Optional[float] = None
    status: str = "running"
    error: Optional[str] = None

    def finish(self, status: str = "success", error: Optional[str] = None):
        """Mark tool execution as finished."""
        self.end_time = time.time()
        self.duration = self.end_time - self.start_time
        self.status = status
        self.error = error


@dataclass
class WorkflowTiming:
    """Track timing for a complete workflow execution."""
    user_id: str
    workflow_id: str
    start_time: float
    end_time: Optional[float] = None
    total_duration: Optional[float] = None
    tool_timings: List[ToolTiming] = field(default_factory=list)
    status: str = "running"
    error: Optional[str] = None

    def finish(self, status: str = "success", error: Optional[str] = None):
        """Mark workflow execution as finished."""
        self.end_time = time.time()
        self.total_duration = self.end_time - self.start_time
        self.status = status
        self.error = error

    def get_tool_timing(self, tool_name: str) -> Optional[ToolTiming]:
        """Get timing for a specific tool."""
        for timing in self.tool_timings:
            if timing.tool_name == tool_name:
                return timing
        return None


class PerformanceMonitor:
    """Monitor and track performance metrics for the meeting agent."""

    def __init__(self):
        self.active_workflows: Dict[str, WorkflowTiming] = {}
        self.completed_workflows: List[WorkflowTiming] = []
        self.tool_stats: Dict[str, List[float]] = defaultdict(list)
        self.email_stats: List[float] = []
        self.total_users_processed = 0
        self.total_errors = 0

    def start_workflow(self, user_id: str, workflow_id: str) -> WorkflowTiming:
        """Start tracking a workflow execution."""
        timing = WorkflowTiming(
            user_id=user_id,
            workflow_id=workflow_id,
            start_time=time.time()
        )
        self.active_workflows[workflow_id] = timing
        logger.info(f"[PERF] Started workflow tracking: {workflow_id} for user {user_id}")
        return timing

    def finish_workflow(self, workflow_id: str, status: str = "success", error: Optional[str] = None):
        """Finish tracking a workflow execution."""
        if workflow_id in self.active_workflows:
            timing = self.active_workflows[workflow_id]
            timing.finish(status, error)
            self.completed_workflows.append(timing)
            del self.active_workflows[workflow_id]

            # Update stats
            if status == "success":
                self.total_users_processed += 1
                # Track tool durations
                for tool_timing in timing.tool_timings:
                    if tool_timing.duration:
                        self.tool_stats[tool_timing.tool_name].append(tool_timing.duration)
            else:
                self.total_errors += 1

            logger.info(
                f"[PERF] Finished workflow: {workflow_id} - "
                f"Duration: {timing.total_duration:.2f}s, Status: {status}"
            )

    def start_tool(self, workflow_id: str, tool_name: str, user_id: str) -> ToolTiming:
        """Start tracking a tool execution."""
        if workflow_id not in self.active_workflows:
            logger.warning(f"[PERF] Workflow {workflow_id} not found, creating new one")
            self.start_workflow(user_id, workflow_id)

        timing = ToolTiming(
            tool_name=tool_name,
            user_id=user_id,
            start_time=time.time()
        )
        self.active_workflows[workflow_id].tool_timings.append(timing)
        logger.info(f"[PERF] Started tool: {tool_name} for workflow {workflow_id}")
        return timing

    def finish_tool(self, workflow_id: str, tool_name: str, status: str = "success", error: Optional[str] = None):
        """Finish tracking a tool execution."""
        if workflow_id in self.active_workflows:
            timing = self.active_workflows[workflow_id]
            tool_timing = timing.get_tool_timing(tool_name)
            if tool_timing:
                tool_timing.finish(status, error)
                logger.info(
                    f"[PERF] Finished tool: {tool_name} - "
                    f"Duration: {tool_timing.duration:.2f}s, Status: {status}"
                )

    def track_email_send(self, duration: float, recipients_count: int = 1):
        """Track email sending time."""
        self.email_stats.append(duration)
        logger.info(f"[PERF] Email sent in {duration:.2f}s to {recipients_count} recipients")

    def get_stats(self) -> Dict[str, Any]:
        """Get aggregated performance statistics."""
        stats = {
            "total_workflows": len(self.completed_workflows),
            "active_workflows": len(self.active_workflows),
            "total_users_processed": self.total_users_processed,
            "total_errors": self.total_errors,
            "tool_stats": {},
            "email_stats": {},
            "workflow_stats": {}
        }

        # Calculate tool statistics
        for tool_name, durations in self.tool_stats.items():
            if durations:
                stats["tool_stats"][tool_name] = {
                    "count": len(durations),
                    "avg": sum(durations) / len(durations),
                    "min": min(durations),
                    "max": max(durations),
                    "p95": self._percentile(durations, 95),
                    "p99": self._percentile(durations, 99)
                }

        # Calculate email statistics
        if self.email_stats:
            stats["email_stats"] = {
                "count": len(self.email_stats),
                "avg": sum(self.email_stats) / len(self.email_stats),
                "min": min(self.email_stats),
                "max": max(self.email_stats),
                "p95": self._percentile(self.email_stats, 95),
                "p99": self._percentile(self.email_stats, 99)
            }

        # Calculate workflow statistics
        workflow_durations = [w.total_duration for w in self.completed_workflows if w.total_duration]
        if workflow_durations:
            stats["workflow_stats"] = {
                "count": len(workflow_durations),
                "avg": sum(workflow_durations) / len(workflow_durations),
                "min": min(workflow_durations),
                "max": max(workflow_durations),
                "p95": self._percentile(workflow_durations, 95),
                "p99": self._percentile(workflow_durations, 99)
            }

        return stats

    def _percentile(self, data: List[float], percentile: int) -> float:
        """Calculate percentile value."""
        sorted_data = sorted(data)
        index = int(len(sorted_data) * percentile / 100)
        return sorted_data[min(index, len(sorted_data) - 1)]

    def print_summary(self):
        """Print a summary of performance statistics."""
        stats = self.get_stats()
        print("\n" + "="*80)
        print("PERFORMANCE SUMMARY")
        print("="*80)
        print(f"Total Workflows: {stats['total_workflows']}")
        print(f"Active Workflows: {stats['active_workflows']}")
        print(f"Users Processed: {stats['total_users_processed']}")
        print(f"Errors: {stats['total_errors']}")
        print()

        # Tool statistics
        if stats["tool_stats"]:
            print("TOOL STATISTICS:")
            print("-" * 80)
            for tool_name, tool_stat in stats["tool_stats"].items():
                print(f"  {tool_name}:")
                print(f"    Count: {tool_stat['count']}")
                print(f"    Avg: {tool_stat['avg']:.2f}s")
                print(f"    Min: {tool_stat['min']:.2f}s")
                print(f"    Max: {tool_stat['max']:.2f}s")
                print(f"    P95: {tool_stat['p95']:.2f}s")
                print(f"    P99: {tool_stat['p99']:.2f}s")
                print()

        # Email statistics
        if stats["email_stats"]:
            print("EMAIL STATISTICS:")
            print("-" * 80)
            email_stat = stats["email_stats"]
            print(f"  Count: {email_stat['count']}")
            print(f"  Avg: {email_stat['avg']:.2f}s")
            print(f"  Min: {email_stat['min']:.2f}s")
            print(f"  Max: {email_stat['max']:.2f}s")
            print(f"  P95: {email_stat['p95']:.2f}s")
            print(f"  P99: {email_stat['p99']:.2f}s")
            print()

        # Workflow statistics
        if stats["workflow_stats"]:
            print("WORKFLOW STATISTICS:")
            print("-" * 80)
            workflow_stat = stats["workflow_stats"]
            print(f"  Count: {workflow_stat['count']}")
            print(f"  Avg: {workflow_stat['avg']:.2f}s")
            print(f"  Min: {workflow_stat['min']:.2f}s")
            print(f"  Max: {workflow_stat['max']:.2f}s")
            print(f"  P95: {workflow_stat['p95']:.2f}s")
            print(f"  P99: {workflow_stat['p99']:.2f}s")
            print()

        print("="*80)

    def export_stats(self, filepath: str):
        """Export statistics to JSON file."""
        stats = self.get_stats()
        with open(filepath, 'w') as f:
            json.dump(stats, f, indent=2, default=str)
        logger.info(f"[PERF] Statistics exported to {filepath}")


# Global instance
_performance_monitor = None


def get_performance_monitor() -> PerformanceMonitor:
    """Get the global performance monitor instance."""
    global _performance_monitor
    if _performance_monitor is None:
        _performance_monitor = PerformanceMonitor()
    return _performance_monitor


def reset_performance_monitor():
    """Reset the global performance monitor (for testing)."""
    global _performance_monitor
    _performance_monitor = None

