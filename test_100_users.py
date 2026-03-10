"""
Test Script for Simulating 100+ Users
Tests agent performance with concurrent user processing
"""

import asyncio
import time
import logging
from datetime import datetime
from typing import List, Dict, Any
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.performance_monitor import get_performance_monitor, PerformanceMonitor

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def simulate_user_workflow(user_id: str, workflow_id: str, monitor: PerformanceMonitor) -> Dict[str, Any]:
    """
    Simulate a single user workflow execution.
    This is a mock implementation - replace with actual agent execution.
    """
    # Start workflow tracking
    monitor.start_workflow(user_id, workflow_id)

    try:
        # Step 1: Calendar Tool (simulated)
        monitor.start_tool(workflow_id, "calendar_tool", user_id)
        await asyncio.sleep(3.5)  # Simulate 3.5s execution
        monitor.finish_tool(workflow_id, "calendar_tool", "success")

        # Step 2: Drive Tool (simulated)
        monitor.start_tool(workflow_id, "drive_tool", user_id)
        await asyncio.sleep(10.0)  # Simulate 10s execution
        monitor.finish_tool(workflow_id, "drive_tool", "success")

        # Step 3: Summarizer Tool (simulated)
        monitor.start_tool(workflow_id, "summarizer_tool", user_id)
        await asyncio.sleep(20.0)  # Simulate 20s execution
        monitor.finish_tool(workflow_id, "summarizer_tool", "success")

        # Step 4: Dedup Tool (simulated)
        monitor.start_tool(workflow_id, "dedup_tool", user_id)
        await asyncio.sleep(5.5)  # Simulate 5.5s execution
        monitor.finish_tool(workflow_id, "dedup_tool", "success")

        # Step 5: Email Tool (simulated)
        monitor.start_tool(workflow_id, "email_notification_tool", user_id)
        email_start = time.time()
        await asyncio.sleep(3.5)  # Simulate 3.5s execution
        email_duration = time.time() - email_start
        monitor.track_email_send(email_duration, recipients_count=1)
        monitor.finish_tool(workflow_id, "email_notification_tool", "success")

        # Finish workflow
        monitor.finish_workflow(workflow_id, "success")

        return {
            "user_id": user_id,
            "workflow_id": workflow_id,
            "status": "success"
        }

    except Exception as e:
        logger.error(f"Error processing user {user_id}: {e}")
        monitor.finish_workflow(workflow_id, "error", str(e))
        return {
            "user_id": user_id,
            "workflow_id": workflow_id,
            "status": "error",
            "error": str(e)
        }


async def process_users_concurrent(user_ids: List[str], max_concurrent: int = 10) -> Dict[str, Any]:
    """
    Process multiple users concurrently with a concurrency limit.
    
    Args:
        user_ids: List of user IDs to process
        max_concurrent: Maximum number of concurrent workflows
    
    Returns:
        Dictionary with processing results
    """
    monitor = get_performance_monitor()
    start_time = time.time()

    # Create semaphore to limit concurrency
    semaphore = asyncio.Semaphore(max_concurrent)

    async def process_with_limit(user_id: str):
        """Process a single user with concurrency limit."""
        async with semaphore:
            workflow_id = f"wf_{user_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            return await simulate_user_workflow(user_id, workflow_id, monitor)

    # Process all users concurrently (with limit)
    logger.info(f"Starting to process {len(user_ids)} users with max_concurrent={max_concurrent}")
    tasks = [process_with_limit(user_id) for user_id in user_ids]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Calculate total time
    total_time = time.time() - start_time

    # Process results
    successful = sum(1 for r in results if isinstance(r, dict) and r.get("status") == "success")
    failed = len(results) - successful

    return {
        "total_users": len(user_ids),
        "successful": successful,
        "failed": failed,
        "total_time": total_time,
        "avg_time_per_user": total_time / len(user_ids) if user_ids else 0,
        "results": results
    }


async def main():
    """Main test function."""
    print("="*80)
    print("MEETING AGENT PERFORMANCE TEST - 100+ USERS")
    print("="*80)
    print()

    # Test configurations
    test_configs = [
        {"users": 10, "concurrent": 5, "name": "Small Test (10 users, 5 concurrent)"},
        {"users": 50, "concurrent": 10, "name": "Medium Test (50 users, 10 concurrent)"},
        {"users": 100, "concurrent": 10, "name": "Large Test (100 users, 10 concurrent)"},
        {"users": 100, "concurrent": 50, "name": "Large Test (100 users, 50 concurrent)"},
        {"users": 200, "concurrent": 50, "name": "XLarge Test (200 users, 50 concurrent)"},
    ]

    for config in test_configs:
        print(f"\n{'='*80}")
        print(f"Running: {config['name']}")
        print(f"{'='*80}\n")

        # Generate user IDs
        user_ids = [f"user_{i:04d}" for i in range(1, config["users"] + 1)]

        # Reset monitor for clean stats
        from scripts.performance_monitor import reset_performance_monitor
        reset_performance_monitor()

        # Process users
        start_time = time.time()
        result = await process_users_concurrent(user_ids, max_concurrent=config["concurrent"])
        end_time = time.time()

        # Print results
        print(f"\nResults for {config['name']}:")
        print(f"  Total Users: {result['total_users']}")
        print(f"  Successful: {result['successful']}")
        print(f"  Failed: {result['failed']}")
        print(f"  Total Time: {result['total_time']:.2f}s ({result['total_time']/60:.2f} minutes)")
        print(f"  Avg Time per User: {result['avg_time_per_user']:.2f}s")
        print(f"  Throughput: {result['total_users']/result['total_time']:.2f} users/second")

        # Print performance summary
        monitor = get_performance_monitor()
        monitor.print_summary()

        # Export stats
        stats_file = f"performance_stats_{config['users']}users_{config['concurrent']}concurrent.json"
        monitor.export_stats(stats_file)
        print(f"\nStatistics exported to: {stats_file}")

        print(f"\n{'='*80}\n")


if __name__ == "__main__":
    # Run the test
    asyncio.run(main())

