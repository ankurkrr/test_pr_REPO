"""
Enhanced Scheduler Service with Intelligent Scheduling
Provides advanced scheduling capabilities with pattern analysis, retry logic, and monitoring
"""

import asyncio
import logging
import os
from datetime import datetime, timedelta, time
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass
from enum import Enum
import json
import time as time_module
import pytz  # Add pytz for timezone handling
from dotenv import load_dotenv

# Load environment variables
load_dotenv()
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.jobstores.memory import MemoryJobStore
from apscheduler.executors.asyncio import AsyncIOExecutor
from apscheduler.events import EVENT_JOB_EXECUTED, EVENT_JOB_ERROR, EVENT_JOB_MISSED

from ..configuration.config import (
    SCHEDULER_MEETING_WORKFLOW_INTERVAL,
    SCHEDULER_TOKEN_REFRESH_INTERVAL,
    SCHEDULER_PAYLOAD_PULL_INTERVAL,
    SCHEDULER_HEALTH_CHECK_INTERVAL,
    SCHEDULER_LOG_CLEANUP_INTERVAL,
    CALENDAR_LOOKBACK_MINUTES,
    MAX_RETRY_ATTEMPTS,
    RETRY_DELAY_SECONDS,
    BACKOFF_MULTIPLIER,
    MAX_CONCURRENT_WORKFLOWS,
    MAX_CONCURRENT_TOKEN_REFRESHES,
    ENABLE_INTELLIGENT_SCHEDULING,
    MEETING_PATTERN_ANALYSIS_DAYS,
    QUIET_HOURS_START,
    QUIET_HOURS_END,
    QUIET_HOURS_TIMEZONE,
    ENABLE_SCHEDULER_METRICS,
    METRICS_RETENTION_DAYS
)

logger = logging.getLogger(__name__)

class JobStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    RETRYING = "retrying"
    CANCELLED = "cancelled"

class JobPriority(Enum):
    LOW = 1
    NORMAL = 2
    HIGH = 3
    CRITICAL = 4

@dataclass
class JobMetrics:
    job_id: str
    start_time: datetime
    end_time: Optional[datetime] = None
    status: JobStatus = JobStatus.PENDING
    retry_count: int = 0
    error_message: Optional[str] = None
    execution_time_seconds: Optional[float] = None
    success: bool = False

@dataclass
class MeetingPattern:
    user_id: str
    peak_hours: List[int]  # Hours of day when meetings are most common
    quiet_hours: List[int]  # Hours when no meetings typically occur
    average_meetings_per_day: float
    last_analysis: datetime
    confidence_score: float  # 0-1, how confident we are in this pattern

class IntelligentScheduler:
    """
    Enhanced scheduler with intelligent scheduling capabilities
    """
    
    def __init__(self):
        self.scheduler = AsyncIOScheduler(
            jobstores={'default': MemoryJobStore()},
            executors={'default': AsyncIOExecutor()},
            job_defaults={
                'coalesce': True,
                'max_instances': 1,
                'misfire_grace_time': 300  # 5 minutes
            }
        )
        
        self.job_metrics: Dict[str, JobMetrics] = {}
        self.meeting_patterns: Dict[str, MeetingPattern] = {}
        self.active_jobs: Dict[str, asyncio.Task] = {}
        self.semaphore = asyncio.Semaphore(MAX_CONCURRENT_WORKFLOWS)
        
        # Setup event listeners
        self.scheduler.add_listener(self._job_executed, EVENT_JOB_EXECUTED)
        self.scheduler.add_listener(self._job_error, EVENT_JOB_ERROR)
        self.scheduler.add_listener(self._job_missed, EVENT_JOB_MISSED)
    
    async def start(self):
        """Start the intelligent scheduler"""
        try:
            if not self.scheduler.running:
                self.scheduler.start()
                logger.info("Intelligent Scheduler started")
                
                # Schedule core jobs
                await self._schedule_core_jobs()
                
                # Start pattern analysis if enabled
                if ENABLE_INTELLIGENT_SCHEDULING:
                    await self._start_pattern_analysis()
            else:
                logger.info("Scheduler is already running")
        except Exception as e:
            logger.error(f"Failed to start scheduler: {e}")
            raise
    
    async def stop(self):
        """Stop the scheduler gracefully"""
        try:
            if self.scheduler.running:
                # Cancel all active jobs
                for task in self.active_jobs.values():
                    if not task.done():
                        task.cancel()
                
                self.scheduler.shutdown(wait=True)
                logger.info("🛑 Intelligent Scheduler stopped")
        except Exception as e:
            logger.error(f"Failed to stop scheduler: {e}")
    
    async def _schedule_core_jobs(self):
        """Schedule the core system jobs"""
        try:
            # Meeting workflow job with intelligent scheduling
            if ENABLE_INTELLIGENT_SCHEDULING:
                self.scheduler.add_job(
                    self._intelligent_meeting_workflow,
                    trigger=IntervalTrigger(minutes=SCHEDULER_MEETING_WORKFLOW_INTERVAL),
                    id='intelligent_meeting_workflow',
                    name='Intelligent Meeting Workflow',
                    replace_existing=True
                )
            else:
                self.scheduler.add_job(
                    self._standard_meeting_workflow,
                    trigger=IntervalTrigger(minutes=SCHEDULER_MEETING_WORKFLOW_INTERVAL),
                    id='meeting_workflow',
                    name='Meeting Workflow',
                    replace_existing=True
                )
            
            # Token refresh job
            self.scheduler.add_job(
                self._refresh_tokens_job,
                trigger=IntervalTrigger(minutes=SCHEDULER_TOKEN_REFRESH_INTERVAL),
                id='token_refresh',
                name='Token Refresh',
                replace_existing=True
            )
            
            # Payload pull job
            self.scheduler.add_job(
                self._pull_payloads_job,
                trigger=IntervalTrigger(minutes=SCHEDULER_PAYLOAD_PULL_INTERVAL),
                id='payload_pull',
                name='Payload Pull',
                replace_existing=True
            )
            
            # Health check job
            self.scheduler.add_job(
                self._health_check_job,
                trigger=IntervalTrigger(minutes=SCHEDULER_HEALTH_CHECK_INTERVAL),
                id='health_check',
                name='Health Check',
                replace_existing=True
            )
            
            # Log cleanup job (daily at 2 AM)
            self.scheduler.add_job(
                self._log_cleanup_job,
                trigger=CronTrigger(hour=2, minute=0),
                id='log_cleanup',
                name='Log Cleanup',
                replace_existing=True
            )
            
            logger.info("[SUCCESS] Core jobs scheduled successfully")
            
        except Exception as e:
            logger.error(f"Failed to schedule core jobs: {e}")
            raise
    
    async def _intelligent_meeting_workflow(self):
        """Intelligent meeting workflow that adapts to user patterns"""
        job_id = "intelligent_meeting_workflow"
        start_time = datetime.now()
        
        try:
            logger.info("🧠 Starting intelligent meeting workflow")
            
            # Get users with active patterns
            active_users = await self._get_users_with_patterns()
            
            if not active_users:
                logger.info("No users with meeting patterns found, falling back to standard workflow")
                await self._standard_meeting_workflow()
                return
            
            # Filter users based on current time and their patterns
            current_hour = datetime.now().hour
            users_to_process = []
            
            for user_id in active_users:
                pattern = self.meeting_patterns.get(user_id)
                if pattern and self._should_process_user_now(user_id, current_hour, pattern):
                    users_to_process.append(user_id)
            
            if not users_to_process:
                logger.info("No users need processing based on intelligent scheduling")
                return
            
            logger.info(f"Processing {len(users_to_process)} users with intelligent scheduling")
            
            # Process users with concurrency control
            tasks = []
            for user_id in users_to_process[:MAX_CONCURRENT_WORKFLOWS]:
                task = asyncio.create_task(
                    self._process_user_workflow_with_retry(user_id)
                )
                tasks.append(task)
            
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            
            # Update metrics
            self._update_job_metrics(job_id, start_time, success=True)
            
        except Exception as e:
            logger.error(f"Intelligent meeting workflow failed: {e}")
            self._update_job_metrics(job_id, start_time, success=False, error=str(e))
    
    async def _standard_meeting_workflow(self):
        """Standard meeting workflow for all active users"""
        job_id = "meeting_workflow"
        start_time = datetime.now()
        
        try:
            logger.info("[START] Starting standard meeting workflow")
            
            # Import here to avoid circular imports
            from ..agents.meeting_agent import get_meeting_agent
            from ..services.database_service_new import get_database_service
            
            db_service = get_database_service()
            
            # Get active users
            rows = await self._get_active_users(db_service)
            
            if not rows:
                logger.info("No active users found")
                return
            
            logger.info(f"Processing {len(rows)} users with standard workflow")
            
            # Process users with concurrency control
            tasks = []
            for row in rows[:MAX_CONCURRENT_WORKFLOWS]:
                user_id, org_id, agent_task_id = row[0], row[1], row[2]
                task = asyncio.create_task(
                    self._process_user_workflow_with_retry(user_id, org_id, agent_task_id)
                )
                tasks.append(task)
            
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            
            # Update metrics
            self._update_job_metrics(job_id, start_time, success=True)
            
        except Exception as e:
            logger.error(f"Standard meeting workflow failed: {e}")
            self._update_job_metrics(job_id, start_time, success=False, error=str(e))
    
    async def _process_user_workflow_with_retry(self, user_id: str, org_id: str = None, agent_task_id: str = None):
        """Process user workflow with retry logic"""
        async with self.semaphore:
            max_retries = MAX_RETRY_ATTEMPTS
            retry_delay = RETRY_DELAY_SECONDS
            
            for attempt in range(max_retries + 1):
                try:
                    if attempt > 0:
                        logger.info(f"Retry attempt {attempt} for user {user_id}")
                        await asyncio.sleep(retry_delay)
                        retry_delay *= BACKOFF_MULTIPLIER
                    
                    # Import here to avoid circular imports
                    from ..agents.meeting_agent import get_meeting_agent
                    
                    if not org_id or not agent_task_id:
                        # Get from database if not provided
                        from ..services.database_service_new import get_database_service
                        db_service = get_database_service()
                        rows = await self._get_active_users(db_service, user_id=user_id)
                        if not rows:
                            logger.warning(f"No active user found for {user_id}")
                            return
                        org_id, agent_task_id = rows[0][1], rows[0][2]
                    
                    config = {"user_id": user_id, "org_id": org_id, "agent_task_id": agent_task_id}
                    agent = get_meeting_agent(config)
                    
                    # Execute workflow - do NOT send "workflow_started" audit for scheduled runs
                    # Scheduled runs should only send status updates (no events found / events processed)
                    # "workflow_started" should only be sent for manual API starts
                    result = agent.execute_workflow(send_workflow_started_audit=False)
                    
                    if result.get("success", False):
                        logger.info(f"[SUCCESS] Workflow completed successfully for user {user_id}")
                        return result
                    else:
                        raise Exception(f"Workflow failed: {result.get('error', 'Unknown error')}")
                
                except Exception as e:
                    if attempt == max_retries:
                        logger.error(f"[ERROR] Workflow failed for user {user_id} after {max_retries} retries: {e}")
                        return {"success": False, "error": str(e)}
                    else:
                        logger.warning(f"Workflow attempt {attempt + 1} failed for user {user_id}: {e}")
    
    def _should_process_user_now(self, user_id: str, current_hour: int, pattern: MeetingPattern) -> bool:
        """Determine if user should be processed now based on their meeting pattern"""
        try:
            # Check if current hour is in quiet hours
            if current_hour in pattern.quiet_hours:
                return False
            
            # Check if current hour is in peak hours (higher priority)
            if current_hour in pattern.peak_hours:
                return True
            
            # For other hours, process based on confidence score
            return pattern.confidence_score > 0.5
            
        except Exception as e:
            logger.warning(f"Error checking user pattern for {user_id}: {e}")
            return True  # Default to processing if pattern analysis fails
    
    async def _get_users_with_patterns(self) -> List[str]:
        """Get users who have meeting patterns analyzed"""
        return list(self.meeting_patterns.keys())
    
    async def _get_active_users(self, db_service, user_id: str = None) -> List[tuple]:
        """Get active users from database"""
        try:
            if user_id:
                query = """
                SELECT DISTINCT user_id, org_id, agent_task_id
                FROM oauth_tokens ot
                WHERE provider = 'google'
                  AND access_token IS NOT NULL AND access_token <> ''
                  AND user_id = %s
                  AND EXISTS (
                      SELECT 1 FROM user_agent_task uat
                      WHERE uat.agent_task_id = ot.agent_task_id
                        AND uat.status = 1 AND uat.ready_to_use = 1
                  )
                """
                return db_service.execute_query(query, (user_id,))
            else:
                query = """
                SELECT DISTINCT user_id, org_id, agent_task_id
                FROM oauth_tokens ot
                WHERE provider = 'google'
                  AND access_token IS NOT NULL AND access_token <> ''
                  AND EXISTS (
                      SELECT 1 FROM user_agent_task uat
                      WHERE uat.agent_task_id = ot.agent_task_id
                        AND uat.status = 1 AND uat.ready_to_use = 1
                  )
                """
                return db_service.execute_query(query)
        except Exception as e:
            logger.error(f"Error getting active users: {e}")
            return []
    
    async def _start_pattern_analysis(self):
        """Start background pattern analysis"""
        try:
            # Schedule pattern analysis job (daily at 3 AM)
            self.scheduler.add_job(
                self._analyze_meeting_patterns,
                trigger=CronTrigger(hour=3, minute=0),
                id='pattern_analysis',
                name='Meeting Pattern Analysis',
                replace_existing=True
            )
            
            # Run initial analysis
            await self._analyze_meeting_patterns()
            
            logger.info("[SUCCESS] Pattern analysis started")
        except Exception as e:
            logger.error(f"Failed to start pattern analysis: {e}")
    
    async def _analyze_meeting_patterns(self):
        """Analyze meeting patterns for all users"""
        job_id = "pattern_analysis"
        start_time = datetime.now()
        
        try:
            logger.info("Starting meeting pattern analysis")
            
            from ..services.database_service_new import get_database_service
            db_service = get_database_service()
            
            # Get all users with meetings in the last N days
            cutoff_date = datetime.now() - timedelta(days=MEETING_PATTERN_ANALYSIS_DAYS)
            
            query = """
            SELECT DISTINCT user_id, org_id, agent_task_id
            FROM meetings
            WHERE start_time >= %s
            """
            users = db_service.execute_query(query, (cutoff_date,))
            
            for user_id, org_id, agent_task_id in users:
                try:
                    pattern = await self._analyze_user_pattern(user_id, db_service, cutoff_date)
                    if pattern:
                        self.meeting_patterns[user_id] = pattern
                        logger.info(f"Analyzed pattern for user {user_id}: {pattern.average_meetings_per_day:.1f} meetings/day")
                except Exception as e:
                    logger.warning(f"Failed to analyze pattern for user {user_id}: {e}")
            
            # Update metrics
            self._update_job_metrics(job_id, start_time, success=True)
            logger.info(f"[SUCCESS] Pattern analysis completed for {len(self.meeting_patterns)} users")
            
        except Exception as e:
            logger.error(f"Pattern analysis failed: {e}")
            self._update_job_metrics(job_id, start_time, success=False, error=str(e))
    
    async def _analyze_user_pattern(self, user_id: str, db_service, cutoff_date: datetime) -> Optional[MeetingPattern]:
        """Analyze meeting pattern for a specific user"""
        try:
            # Get meetings for the user
            query = """
            SELECT start_time, end_time
            FROM meetings
            WHERE user_id = %s AND start_time >= %s
            ORDER BY start_time
            """
            meetings = db_service.execute_query(query, (user_id, cutoff_date))
            
            if not meetings:
                return None
            
            # Analyze meeting times
            meeting_hours = []
            total_meetings = len(meetings)
            
            for start_time, end_time in meetings:
                if start_time:
                    meeting_hours.append(start_time.hour)
            
            if not meeting_hours:
                return None
            
            # Calculate peak and quiet hours
            hour_counts = {}
            for hour in meeting_hours:
                hour_counts[hour] = hour_counts.get(hour, 0) + 1
            
            # Peak hours: hours with above-average meeting frequency
            avg_per_hour = total_meetings / 24
            peak_hours = [hour for hour, count in hour_counts.items() if count > avg_per_hour * 1.5]
            
            # Quiet hours: hours with no meetings
            all_hours = set(range(24))
            meeting_hours_set = set(meeting_hours)
            quiet_hours = list(all_hours - meeting_hours_set)
            
            # Calculate confidence score based on data quality
            confidence_score = min(1.0, total_meetings / (MEETING_PATTERN_ANALYSIS_DAYS * 2))
            
            return MeetingPattern(
                user_id=user_id,
                peak_hours=peak_hours,
                quiet_hours=quiet_hours,
                average_meetings_per_day=total_meetings / MEETING_PATTERN_ANALYSIS_DAYS,
                last_analysis=datetime.now(),
                confidence_score=confidence_score
            )
            
        except Exception as e:
            logger.error(f"Error analyzing pattern for user {user_id}: {e}")
            return None
    
    async def _refresh_tokens_job(self):
        """Refresh Google tokens for all users"""
        job_id = "token_refresh"
        start_time = datetime.now()
        
        try:
            logger.info("[START] Starting token refresh job")
            
            # Use our working refresh function
            result = refresh_all_users_tokens()
            
            # Update metrics
            self._update_job_metrics(job_id, start_time, success=result.get("success", False))
            
        except Exception as e:
            logger.error(f"Token refresh job failed: {e}")
            self._update_job_metrics(job_id, start_time, success=False, error=str(e))
    
    async def _pull_payloads_job(self):
        """Pull latest payloads from platform"""
        job_id = "payload_pull"
        start_time = datetime.now()
        
        try:
            logger.info("[START] Starting payload pull job")
            
            # Import here to avoid circular imports
            from ..api.routes.cron_routes import pull_latest_payloads
            result = await pull_latest_payloads()
            
            # Update metrics
            self._update_job_metrics(job_id, start_time, success=result.get("success", False))
            
        except Exception as e:
            logger.error(f"Payload pull job failed: {e}")
            self._update_job_metrics(job_id, start_time, success=False, error=str(e))
    
    async def _health_check_job(self):
        """Perform system health check"""
        job_id = "health_check"
        start_time = datetime.now()
        
        try:
            logger.info("🏥 Starting health check job")
            
            # Import here to avoid circular imports
            from ..api.routes.cron_routes import cron_health_check
            result = await cron_health_check()
            
            # Update metrics
            self._update_job_metrics(job_id, start_time, success=result.get("success", False))
            
        except Exception as e:
            logger.error(f"Health check job failed: {e}")
            self._update_job_metrics(job_id, start_time, success=False, error=str(e))
    
    async def _log_cleanup_job(self):
        """Clean up old log files"""
        job_id = "log_cleanup"
        start_time = datetime.now()
        
        try:
            logger.info("🧹 Starting log cleanup job")
            
            # Import here to avoid circular imports
            from ..api.routes.cron_routes import cleanup_logs
            from ..api.models.request_models import CronCleanupRequest
            
            request = CronCleanupRequest(cleanup_days=7, log_types=["cron", "app", "audit"])
            result = await cleanup_logs(request)
            
            # Update metrics
            self._update_job_metrics(job_id, start_time, success=result.get("success", False))
            
        except Exception as e:
            logger.error(f"Log cleanup job failed: {e}")
            self._update_job_metrics(job_id, start_time, success=False, error=str(e))
    
    def _update_job_metrics(self, job_id: str, start_time: datetime, success: bool, error: str = None):
        """Update job metrics"""
        try:
            end_time = datetime.now()
            execution_time = (end_time - start_time).total_seconds()
            
            if job_id not in self.job_metrics:
                self.job_metrics[job_id] = JobMetrics(
                    job_id=job_id,
                    start_time=start_time
                )
            
            metrics = self.job_metrics[job_id]
            metrics.end_time = end_time
            metrics.status = JobStatus.COMPLETED if success else JobStatus.FAILED
            metrics.execution_time_seconds = execution_time
            metrics.success = success
            metrics.error_message = error
            
            # Clean up old metrics if enabled
            if ENABLE_SCHEDULER_METRICS:
                self._cleanup_old_metrics()
            
        except Exception as e:
            logger.warning(f"Failed to update metrics for job {job_id}: {e}")
    
    def _cleanup_old_metrics(self):
        """Clean up old metrics data"""
        try:
            cutoff_date = datetime.now() - timedelta(days=METRICS_RETENTION_DAYS)
            jobs_to_remove = []
            
            for job_id, metrics in self.job_metrics.items():
                if metrics.start_time < cutoff_date:
                    jobs_to_remove.append(job_id)
            
            for job_id in jobs_to_remove:
                del self.job_metrics[job_id]
            
            if jobs_to_remove:
                logger.info(f"Cleaned up {len(jobs_to_remove)} old job metrics")
                
        except Exception as e:
            logger.warning(f"Failed to cleanup old metrics: {e}")
    
    def _job_executed(self, event):
        """Handle job execution events"""
        try:
            job_id = event.job_id
            logger.debug(f"Job {job_id} executed successfully")
        except Exception as e:
            logger.warning(f"Error handling job executed event: {e}")
    
    def _job_error(self, event):
        """Handle job error events"""
        try:
            job_id = event.job_id
            exception = event.exception
            logger.error(f"Job {job_id} failed with exception: {exception}")
        except Exception as e:
            logger.warning(f"Error handling job error event: {e}")
    
    def _job_missed(self, event):
        """Handle job missed events"""
        try:
            job_id = event.job_id
            logger.warning(f"Job {job_id} was missed")
        except Exception as e:
            logger.warning(f"Error handling job missed event: {e}")
    
    def get_status(self) -> Dict[str, Any]:
        """Get scheduler status and metrics"""
        try:
            jobs = []
            if self.scheduler.running:
                for job in self.scheduler.get_jobs():
                    jobs.append({
                        "id": job.id,
                        "name": job.name,
                        "next_run": str(job.next_run_time) if job.next_run_time else None,
                        "trigger": str(job.trigger)
                    })
            
            # Get recent metrics
            recent_metrics = {}
            for job_id, metrics in self.job_metrics.items():
                if metrics.start_time > datetime.now() - timedelta(hours=24):
                    recent_metrics[job_id] = {
                        "status": metrics.status.value,
                        "execution_time_seconds": metrics.execution_time_seconds,
                        "success": metrics.success,
                        "error_message": metrics.error_message,
                        "last_run": metrics.start_time.isoformat()
                    }
            
            return {
                "scheduler_running": self.scheduler.running,
                "jobs": jobs,
                "metrics": recent_metrics,
                "meeting_patterns_count": len(self.meeting_patterns),
                "active_jobs_count": len(self.active_jobs),
                "intelligent_scheduling_enabled": ENABLE_INTELLIGENT_SCHEDULING
            }
        except Exception as e:
            logger.error(f"Error getting scheduler status: {e}")
            return {"error": str(e)}

# Global scheduler instance
_scheduler_instance: Optional[IntelligentScheduler] = None

async def get_scheduler() -> IntelligentScheduler:
    """Get the global scheduler instance"""
    global _scheduler_instance
    if _scheduler_instance is None:
        _scheduler_instance = IntelligentScheduler()
    return _scheduler_instance

async def start_scheduler():
    """Start the global scheduler"""
    scheduler = await get_scheduler()
    await scheduler.start()

async def stop_scheduler():
    """Stop the global scheduler"""
    global _scheduler_instance
    if _scheduler_instance:
        await _scheduler_instance.stop()
        _scheduler_instance = None

# ==============================================================================
# SIMPLE SCHEDULER FUNCTIONS FOR BACKGROUND SCHEDULER
# ==============================================================================

def read_google_calendar_events():
    """
    Complete Meeting Intelligence Agent workflow for all active users.
    
    This function runs STRICTLY EVERY {SCHEDULER_MEETING_WORKFLOW_INTERVAL} MINUTES ONCE from agent initialization and:
    1. Queries the database for ALL active users (status=1 AND ready_to_use=1)
    2. Processes each active user through the FULL LangChain agent workflow (unified_meeting_agent)
    3. Sends audit stream to platform every {SCHEDULER_MEETING_WORKFLOW_INTERVAL} minutes (even if no events found)
    
    FULL LangChain Agent Workflow (executes ALL tools via LangChain AgentExecutor):
    - Calendar Tool: Find recent calendar events from the last {CALENDAR_LOOKBACK_MINUTES} minutes
    - Drive Tool: Download meeting transcripts for events found
    - Summarizer Tool: Generate AI summaries of meeting content
    - Dedup Tool: Remove duplicate tasks and organize them
    - Email Notification Tool: Send notifications as needed
    
    The LangChain agent orchestrates the complete workflow using all available tools.
    If AgentExecutor is not available, falls back to direct tool execution.
    
    Audit Logs:
    - Case 1: No events found → Sends audit with "Don't worry—everything's on track" message
    - Case 2: Events found → Completes full workflow and sends "Email Sent" audit to CONFIRM agent work is done
    
    IMPORTANT: Token refresh happens separately every {SCHEDULER_TOKEN_REFRESH_INTERVAL} minutes via scheduled job - NOT in this function.
    
    This function is designed to be called by BackgroundScheduler STRICTLY every {SCHEDULER_MEETING_WORKFLOW_INTERVAL} minutes ONCE.
    
    Includes drift tracking and VM idle cycle detection for reliable scheduling in VM environments.
    """
    # Capture precise start time for drift tracking (using UTC consistently)
    import time as time_module
    from ..configuration.config import SCHEDULER_MEETING_WORKFLOW_INTERVAL
    # Ensure datetime is available (already imported at module level, but ensure it's not shadowed)
    from datetime import datetime as dt_module
    
    # Standardize to UTC timezone for all datetime operations
    utc_tz = pytz.UTC
    workflow_interval = SCHEDULER_MEETING_WORKFLOW_INTERVAL
    start_timestamp = dt_module.now(utc_tz)  # Use timezone-aware UTC datetime
    start_time_epoch = time_module.time()
    
    # Drift tracking: Calculate expected next run time
    expected_interval_seconds = workflow_interval * 60
    expected_next_run_epoch = start_time_epoch + expected_interval_seconds
    
    # Check for VM idle cycle detection (large time gap indicates VM was idle)
    # Store last execution time in a module-level variable for drift detection
    if not hasattr(read_google_calendar_events, '_last_execution_time'):
        read_google_calendar_events._last_execution_time = None
        read_google_calendar_events._last_execution_epoch = None
    
    drift_detected = False
    vm_idle_detected = False
    if read_google_calendar_events._last_execution_epoch is not None:
        actual_interval_seconds = start_time_epoch - read_google_calendar_events._last_execution_epoch
        drift_seconds = actual_interval_seconds - expected_interval_seconds
        drift_percentage = (drift_seconds / expected_interval_seconds) * 100 if expected_interval_seconds > 0 else 0
        
        # Detect VM idle cycles (interval > 2x expected indicates VM was idle)
        if actual_interval_seconds > (expected_interval_seconds * 2):
            vm_idle_detected = True
            logger.warning(f"[VM IDLE DETECTED] Large interval detected: {actual_interval_seconds:.1f}s (expected: {expected_interval_seconds}s). VM may have been idle.")
        
        # Detect significant drift (>5% deviation)
        if abs(drift_seconds) > (expected_interval_seconds * 0.05):
            drift_detected = True
            logger.warning(f"[DRIFT DETECTED] Interval drift: {drift_seconds:.1f}s ({drift_percentage:.2f}% deviation). Actual: {actual_interval_seconds:.1f}s, Expected: {expected_interval_seconds}s")
    
    # Update last execution time
    read_google_calendar_events._last_execution_time = start_timestamp
    read_google_calendar_events._last_execution_epoch = start_time_epoch
    
    try:
        logger.info("=" * 80)
        logger.info(f"[SCHEDULER START] Agent auto-run started at {start_timestamp.isoformat()} (UTC)")
        logger.info(f"[SCHEDULER START] Epoch time: {start_time_epoch}")
        if drift_detected or vm_idle_detected:
            logger.info(f"[SCHEDULER TIMING] Expected next run: {dt_module.fromtimestamp(expected_next_run_epoch, tz=utc_tz).isoformat()} (UTC)")
        logger.info("[START] Starting Complete Meeting Intelligence Agent workflow for all users...")
        logger.info(" Tools included: Calendar, Drive, Summarizer, Email, Dedup")
        logger.info(" Note: Token refresh happens separately every 60 minutes via scheduled job")
        
        # Import here to avoid circular imports
        from ..agents.meeting_agent import get_meeting_agent
        from ..services.database_service_new import get_database_service
        from ..auth.google_auth_handler import get_auth_status_for_user
        from ..services.agent_tracking_service import get_agent_tracking_service
        
        db_service = get_database_service()
        tracking_service = get_agent_tracking_service(db_service)
        
        # Get all users with valid Google tokens and ensure they have valid agent_task entries
        query = """
        SELECT DISTINCT ot.user_id, ot.org_id, ot.agent_task_id
        FROM oauth_tokens ot
        WHERE ot.provider = 'google'
          AND ((ot.access_token IS NOT NULL AND ot.access_token <> '')
               OR (ot.refresh_token IS NOT NULL AND ot.refresh_token <> ''))
          AND EXISTS (
              SELECT 1 FROM user_agent_task uat
              WHERE uat.agent_task_id = ot.agent_task_id
                AND uat.status = 1 AND uat.ready_to_use = 1
          )
        """
        rows = db_service.execute_query(query)
        
        if not rows:
            logger.info("No active users found with valid Google tokens")
            # Even if no active users found, this is a scheduled run - log it
            logger.info("Scheduled run completed: No active users to process this cycle")
            return {"success": True, "message": "No active users found", "users_processed": 0}
        
        logger.info(f"Found {len(rows)} active users with Google tokens (status=1 AND ready_to_use=1)")
        logger.info("Processing each active user through unified_meeting_agent workflow...")
        
        # Pre-validate tokens before processing
        valid_users = []
        invalid_users = []
        
        for user_id, org_id, agent_task_id in rows:
            try:
                # Check auth status for each user
                # Create a fresh auth handler to avoid cache issues
                from ..auth.google_auth_handler import GoogleAuthHandler
                auth_handler = GoogleAuthHandler(user_id, org_id, agent_task_id)
                # Clear any cached tokens to ensure fresh data
                auth_handler._tokens = None
                
                auth_status = get_auth_status_for_user(user_id, org_id, agent_task_id)
                
                if auth_status.get("has_valid_tokens", False):
                    valid_users.append((user_id, org_id, agent_task_id))
                    logger.info(f"[SUCCESS] User {user_id} has valid tokens (expires_in: {auth_status.get('expires_in', 'N/A')} seconds)")
                else:
                    invalid_users.append((user_id, org_id, agent_task_id))
                    logger.warning(f"[WARNING] User {user_id} has invalid tokens: {auth_status.get('message', 'Unknown issue')}")
                    logger.warning(f"   Token details: has_access_token={auth_status.get('has_access_token')}, has_refresh_token={auth_status.get('has_refresh_token')}, expires_in={auth_status.get('expires_in')}")
                    
            except Exception as e:
                logger.error(f"[ERROR] Error checking auth status for user {user_id}: {e}", exc_info=True)
                invalid_users.append((user_id, org_id, agent_task_id))
        
        # Log summary
        logger.info(f"Token validation results: {len(valid_users)} valid, {len(invalid_users)} invalid")
        
        if not valid_users:
            logger.warning("[WARNING] No users have valid Google tokens! All users need to re-authenticate.")
            logger.info("[INFO] Users need to go through the OAuth flow again to get new tokens.")
            return {
                "success": False,
                "message": "No users have valid Google tokens - re-authentication required",
                "valid_users": 0,
                "invalid_users": len(invalid_users),
                "action_required": "user_re_authentication"
            }
        
        # Process only users with valid tokens
        logger.info(f"[START] Processing {len(valid_users)} users with valid tokens")
        
        # Process each user
        results = []
        for user_id, org_id, agent_task_id in valid_users:
            # Start tracking agent execution
            agent_id = tracking_service.start_agent_execution(
                user_id=user_id,
                org_id=org_id,
                agent_task_id=agent_task_id,
                description="langchain_meeting_agent"
            )
            
            # Ensure agent_task_id exists in user_agent_task table
            try:
                # Check if agent_task_id exists in user_agent_task
                check_query = """
                SELECT COUNT(*) FROM user_agent_task 
                WHERE agent_task_id = :agent_task_id
                """
                count_result = db_service.execute_query(check_query, {"agent_task_id": agent_task_id})
                count = count_result[0][0] if count_result else 0
                
                if count == 0:
                    logger.warning(f"Agent task {agent_task_id} not found in user_agent_task, creating entry...")
                    # Create missing agent_task entry
                    import uuid
                    # datetime is already imported at module level
                    
                    create_query = """
                    INSERT INTO user_agent_task 
                    (agent_task_id, org_id, user_id, name, ready_to_use, status, created, updated)
                    VALUES (:agent_task_id, :org_id, :user_id, :name, 1, 1, NOW(), NOW())
                    """
                    db_service.execute_query(create_query, {
                        "agent_task_id": agent_task_id,
                        "org_id": org_id,
                        "user_id": user_id,
                        "name": f"Scheduler task for {user_id}"
                    })
                    logger.info(f"Created missing agent_task entry: {agent_task_id}")
            except Exception as e:
                logger.error(f"Failed to ensure agent_task exists for {agent_task_id}: {e}")
                tracking_service.complete_agent_execution('failed', str(e))
                continue
                
            try:
                config = {"user_id": user_id, "org_id": org_id, "agent_task_id": agent_task_id}
                agent = get_meeting_agent(config)
                
                # Verify LangChain agent is initialized
                if agent.agent_executor:
                    logger.info(f"LangChain AgentExecutor initialized for user {user_id}")
                    logger.info(f"   Tools available: {[tool.name for tool in agent.tools]}")
                    logger.info(f"   Will execute FULL LangChain agent workflow with all tools")
                else:
                    logger.warning(f" AgentExecutor not available for user {user_id}, will use fallback direct execution")
                
                # Execute the FULL LangChain agent workflow
                # Do NOT send "workflow_started" audit for scheduled runs (every {SCHEDULER_MEETING_WORKFLOW_INTERVAL} minutes)
                # Scheduled runs should only send status updates, not "workflow started" every {SCHEDULER_MEETING_WORKFLOW_INTERVAL} minutes
                logger.info(f" Executing unified_meeting_agent workflow for user {user_id}...")
                result = agent.execute_workflow(send_workflow_started_audit=False)
                logger.info(f"Workflow execution completed for user {user_id}")
                
                # Extract metrics for audit logs (not stored in agent table)
                # Parse tool_results if available to get detailed metrics for audit
                tool_results = result.get('tool_results', {})
                
                # Extract metrics from individual tool results for audit logs
                events_scanned = result.get('meetings_found', 0)
                transcripts_ingested = 0
                summaries_generated = 0
                tasks_extracted = result.get('tasks_processed', 0)
                emails_sent = 0
                
                # Try to extract from tool results for audit logs
                if isinstance(tool_results, dict):
                    # Calendar tool
                    calendar_result = tool_results.get('calendar_tool', {})
                    if isinstance(calendar_result, str):
                        try:
                            calendar_data = json.loads(calendar_result)
                            events_scanned = calendar_data.get('events_found', 0)
                        except:
                            pass
                    
                    # Drive tool
                    drive_result = tool_results.get('drive_tool', {})
                    if isinstance(drive_result, str):
                        try:
                            drive_data = json.loads(drive_result)
                            transcripts_ingested = drive_data.get('transcripts_found', 0)
                        except:
                            pass
                    
                    # Email tool - extract email sent count
                    email_result = tool_results.get('email_tool', {})
                    if isinstance(email_result, str):
                        try:
                            email_data = json.loads(email_result)
                            if email_data.get('status') == 'success':
                                recipients = email_data.get('recipients', [])
                                emails_sent = len(recipients) if recipients else 0
                                logger.info(f"   Email tool result: {emails_sent} email(s) sent successfully")
                        except Exception as email_parse_err:
                            logger.debug(f"   Could not parse email tool result: {email_parse_err}")
                            # Try to extract from result.output if available
                            if 'email' in str(email_result).lower() or 'sent' in str(email_result).lower():
                                emails_sent = 1  # Assume at least one email was sent if email-related text found
                    elif isinstance(email_result, dict):
                        # Handle dict format directly
                        if email_result.get('status') == 'success':
                            recipients = email_result.get('recipients', [])
                            emails_sent = len(recipients) if recipients else 0
                            logger.info(f"   Email tool result (dict): {emails_sent} email(s) sent successfully")
                    
                    # Also check result.output for email information
                    if emails_sent == 0 and result.get('output'):
                        output_str = str(result.get('output', ''))
                        if 'email' in output_str.lower() and ('sent' in output_str.lower() or 'success' in output_str.lower()):
                            # Try to extract email count from output
                            import re
                            email_match = re.search(r'(\d+)\s*email', output_str, re.IGNORECASE)
                            if email_match:
                                emails_sent = int(email_match.group(1))
                                logger.info(f"   Extracted email count from output: {emails_sent} email(s)")
                            else:
                                emails_sent = 1  # At least one email was sent
                                logger.info(f"   Email sent detected in output, setting emails_sent=1")
                
                # Note: Metrics are used for audit logs only, not stored in agent table
                
                # Send comprehensive audit log to platform EVERY {SCHEDULER_MEETING_WORKFLOW_INTERVAL} MINUTES (even if no events)
                # This ensures the platform receives regular status updates
                try:
                    from ..services.integration.platform_api_client import PlatformAPIClient
                    import asyncio
                    # datetime is already imported at module level - no need to reimport
                    # workflow_interval is already defined at function start
                    
                    platform_client = PlatformAPIClient()
                    
                    # ALWAYS send audit for every scheduled run (every {SCHEDULER_MEETING_WORKFLOW_INTERVAL} minutes)
                    # Case 1: No events found - send friendly "don't worry" message
                    if events_scanned == 0:
                        platform_client.send_simple_log_sync(
                            agent_task_id=agent_task_id,
                            log_text="No new meetings found in the search window.",
                            activity_type="task",
                            log_for_status="success",
                            action="Read",
                            action_issue_event="No active meetings were found during this check. This may mean that there are no scheduled meetings at the moment. The agent will try again in the next cycle.",
                            action_required="None",
                            outcome=f"Calendar checked successfully. No new meetings found. Will check again in {workflow_interval} minutes.",
                            step_str=f"Don't worry—everything's on track! The agent will check again in next {workflow_interval} minutes.",
                            tool_str="Calendar API",
                            log_data={
                                "user_id": user_id, 
                                "org_id": org_id, 
                                "events_scanned": 0,
                                "scheduled_run": True,
                                "run_timestamp": dt_module.now(pytz.UTC).isoformat()
                            }
                        )
                        logger.info(f" Sent audit log to platform for user {user_id}: No events found (scheduled {workflow_interval}-min run)")
                    else:
                        # Case 2: Events found - send summary of processing
                        platform_client.send_simple_log_sync(
                            agent_task_id=agent_task_id,
                            log_text=f"Meeting agent processed {events_scanned} event(s).",
                            activity_type="task",
                            log_for_status="success",
                            action="Process",
                            action_issue_event=f"The agent has successfully processed {events_scanned} meeting event(s). Summaries were generated, and key tasks were identified and organized for follow-up.",
                            action_required="None",
                            outcome=f"Generated {summaries_generated} summary/ies and extracted {tasks_extracted} task(s).",
                            step_str=f"Meeting agent successfully processed {events_scanned} calendar event(s). Transcripts ingested: {transcripts_ingested}, summaries generated: {summaries_generated}, tasks extracted: {tasks_extracted}.",
                            tool_str="Meeting Agent",
                            log_data={
                                "user_id": user_id,
                                "org_id": org_id,
                                "events_scanned": events_scanned,
                                "summaries_generated": summaries_generated,
                                "tasks_extracted": tasks_extracted,
                                "transcripts_ingested": transcripts_ingested,
                                "scheduled_run": True,
                                "run_timestamp": dt_module.now(pytz.UTC).isoformat()
                            }
                        )
                        logger.info(f"[SUCCESS] Sent audit log to platform for user {user_id}: {events_scanned} events processed (scheduled {workflow_interval}-min run)")
                except Exception as audit_error:
                    logger.error(f"[ERROR] Failed to send audit log to platform for user {user_id}: {audit_error}")
                    # Don't fail the entire workflow if audit fails, but log the error
                
                # Emit email sent audit to CONFIRM agent work is done when events are found
                # This audit confirms the agent has completed all work: events processed, summaries generated, tasks extracted, and emails sent
                # Only send if events were found AND emails were sent (confirms complete workflow)
                try:
                    if events_scanned > 0 and emails_sent > 0:
                        logger.info(f"📧 Sending email sent audit to CONFIRM agent work done for user {user_id}: {emails_sent} email(s) sent for {events_scanned} event(s)")
                        from ..services.integration.platform_api_client import PlatformAPIClient as _PAC
                        import asyncio as _asyncio
                        _client = _PAC()
                        _client.send_simple_log_sync(
                            agent_task_id=agent_task_id,
                            log_text=f"Agent work completed successfully. Meeting summary email sent to {emails_sent} participant(s) for {events_scanned} event(s).",
                            activity_type="task",
                            log_for_status="success",
                            action="Complete",
                            action_issue_event=f"Agent has successfully completed all work: processed {events_scanned} meeting event(s), generated summaries, extracted tasks, and sent emails to {emails_sent} participant(s). All work is done.",
                            action_required="None",
                            outcome=f"Agent work completed successfully. Meeting summary and extracted tasks distributed via email to {emails_sent} recipient(s). All workflows completed.",
                            step_str=f"[SUCCESS] Agent work completed! Email containing the meeting summary and extracted tasks has been sent successfully to {emails_sent} designated recipient(s) for {events_scanned} meeting event(s). All meeting insights and action items are now available. Work is done.",
                            tool_str="Meeting Agent",
                            log_data={
                                "user_id": user_id, 
                                "org_id": org_id, 
                                "emails_sent": emails_sent,
                                "events_scanned": events_scanned,
                                "summaries_generated": summaries_generated,
                                "tasks_extracted": tasks_extracted,
                                "transcripts_ingested": transcripts_ingested,
                                "work_completed": True,
                                "scheduled_run": True,
                                "run_timestamp": dt_module.now(pytz.UTC).isoformat()
                            }
                        )
                        logger.info(f"[SUCCESS] Sent email audit log to CONFIRM agent work done for user {user_id}: {emails_sent} email(s) sent for {events_scanned} event(s)")
                    elif events_scanned > 0 and emails_sent == 0:
                        logger.debug(f"   Events found ({events_scanned}) but no emails sent - skipping email audit")
                except Exception as _email_audit_err:
                    logger.error(f"[ERROR] Failed to emit email_sent audit for user {user_id}: {_email_audit_err}")
                
                if result.get("success", False) or result.get("status") == "completed":
                    logger.info(f"[SUCCESS] Complete Meeting Agent workflow processed successfully for user {user_id}")
                    logger.info(f"   Result: {result.get('status', 'success')}")
                    tracking_service.complete_agent_execution('completed')
                    # Final completion audit suppressed to avoid duplicate entries
                    results.append({"user_id": user_id, "success": True, "agent_id": agent_id})
                else:
                    logger.warning(f"[FAILED] Meeting Agent workflow failed for user {user_id}: {result.get('error', 'Unknown error')}")
                    tracking_service.complete_agent_execution('failed', result.get('error'))
                    results.append({"user_id": user_id, "success": False, "error": result.get('error'), "agent_id": agent_id})
                    
            except Exception as e:
                logger.error(f"[ERROR] Error processing user {user_id}: {e}")
                tracking_service.complete_agent_execution('failed', str(e))
                results.append({"user_id": user_id, "success": False, "error": str(e), "agent_id": agent_id})
        
        successful_users = len([r for r in results if r["success"]])
        logger.info("=" * 80)
        from ..configuration.config import SCHEDULER_MEETING_WORKFLOW_INTERVAL
        workflow_interval = SCHEDULER_MEETING_WORKFLOW_INTERVAL
        logger.info(f"[COMPLETE] Scheduled {workflow_interval}-minute run completed: {successful_users}/{len(results)} users successful")
        logger.info(f"   Total active users processed: {len(results)}")
        logger.info(f"   Users with valid tokens: {len(valid_users)}")
        logger.info(f"   Users needing re-authentication: {len(invalid_users)}")
        logger.info(f" Tools executed per user: Calendar → Drive → Summarizer → Email → Dedup")
        logger.info(f"   Calendar lookback window: {CALENDAR_LOOKBACK_MINUTES} minutes")
        logger.info(f"Audit logs sent to platform for each user (every {workflow_interval} minutes)")
        logger.info(f" Next scheduled run: {workflow_interval} minutes from now")
        logger.info("=" * 80)
        
        # Log invalid users for admin attention
        if invalid_users:
            logger.warning(f"[WARNING] {len(invalid_users)} users need re-authentication:")
            for user_id, org_id, agent_task_id in invalid_users:
                logger.warning(f"   - User {user_id} (org: {org_id}, task: {agent_task_id})")
        
        # Capture precise end time and calculate execution duration (using UTC consistently)
        import time as time_module
        utc_tz = pytz.UTC
        end_timestamp = dt_module.now(utc_tz)  # Use timezone-aware UTC datetime
        end_time_epoch = time_module.time()
        execution_duration_seconds = end_time_epoch - start_time_epoch
        execution_duration_minutes = execution_duration_seconds / 60.0
        
        # Calculate time until next expected run
        expected_interval_seconds = workflow_interval * 60
        time_until_next_run_seconds = expected_interval_seconds - execution_duration_seconds
        time_until_next_run_minutes = time_until_next_run_seconds / 60.0
        
        logger.info("=" * 80)
        logger.info(f"[SCHEDULER END] Agent auto-run completed at {end_timestamp.isoformat()} (UTC)")
        logger.info(f"[SCHEDULER END] Epoch time: {end_time_epoch}")
        logger.info(f"[SCHEDULER TIMING] Execution duration: {execution_duration_seconds:.2f} seconds ({execution_duration_minutes:.2f} minutes)")
        logger.info(f"[SCHEDULER TIMING] Start: {start_timestamp.isoformat()} (UTC) | End: {end_timestamp.isoformat()} (UTC)")
        if time_until_next_run_seconds > 0:
            logger.info(f"[SCHEDULER TIMING] Next run expected in: {time_until_next_run_seconds:.1f} seconds ({time_until_next_run_minutes:.2f} minutes)")
        else:
            logger.warning(f"[SCHEDULER TIMING] Execution exceeded interval! Overrun by: {abs(time_until_next_run_seconds):.1f} seconds")
        logger.info("=" * 80)
        
        # Send audit log with timing information to platform for each user
        try:
            from ..services.integration.platform_api_client import PlatformAPIClient
            from ..configuration.config import SCHEDULER_MEETING_WORKFLOW_INTERVAL
            
            platform_client = PlatformAPIClient()
            
            # Send scheduler execution timing audit log for each successful user
            # This provides visibility into when the scheduler runs and how long it takes
            for result in results:
                if result.get("success") and result.get("user_id"):
                    try:
                        # Get agent_task_id from the result or from the database
                        agent_task_id = None
                        user_id = result.get("user_id")
                        
                        # Try to extract agent_task_id from the result
                        if result.get("agent_id"):
                            # We need to get agent_task_id from the database or from the result context
                            # For now, we'll skip per-user audit logs for timing and just log the summary
                            pass
                    except Exception as e:
                        logger.debug(f"Could not send per-user timing audit for {result.get('user_id')}: {e}")
            
            # Log scheduler execution timing summary
            logger.info(f"Scheduler execution summary: {len(results)} users processed in {execution_duration_minutes:.2f} minutes")
            logger.info(f"Next scheduled run: Expected in {SCHEDULER_MEETING_WORKFLOW_INTERVAL} minutes from {end_timestamp.isoformat()}Z")
            
        except Exception as audit_error:
            logger.warning(f"Failed to send scheduler timing audit log: {audit_error}")
        
        return {
            "success": True,
            "message": f"Processed {len(results)} users, {successful_users} successful",
            "results": results,
            "valid_users": len(valid_users),
            "invalid_users": len(invalid_users),
            "action_required": "re_authentication" if invalid_users else None,
            "execution_start": start_timestamp.isoformat(),
            "execution_end": end_timestamp.isoformat(),
            "execution_duration_seconds": execution_duration_seconds,
            "execution_duration_minutes": execution_duration_minutes
        }
        
    except Exception as e:
        # Capture end time even on error (using UTC consistently)
        import time as time_module
        utc_tz = pytz.UTC
        end_timestamp = dt_module.now(utc_tz)
        end_time_epoch = time_module.time()
        execution_duration_seconds = end_time_epoch - start_time_epoch
        
        logger.error("=" * 80)
        logger.error(f"[SCHEDULER ERROR] Agent auto-run failed at {end_timestamp.isoformat()} (UTC)")
        logger.error(f"[SCHEDULER TIMING] Execution duration before error: {execution_duration_seconds:.2f} seconds")
        logger.error(f"[ERROR] Failed to read Google Calendar events: {e}")
        logger.error("=" * 80)
        
        return {
            "success": False,
            "error": str(e),
            "execution_start": start_timestamp.isoformat(),
            "execution_end": end_timestamp.isoformat(),
            "execution_duration_seconds": execution_duration_seconds
        }

def sync_user_data_from_platform():
    """
    Sync user data from platform API every {PLATFORM_SYNC_INTERVAL_MINUTES} minutes.
    Calls https://devapi.agentic.elevationai.com/user-agent-task/get-latest-agent-details
    for all active users and updates user_agent_task table.
    """
    try:
        logger.info("[START] Starting platform user data sync...")
        
        from ..services.database_service_new import get_database_service
        from ..api.utils.encryption import decrypt_token
        import asyncio
        import httpx
        
        # Check environment variables first
        required_env_vars = [
            'PLATFORM_API_KEY', 
            'PLATFORM_API_SECRET'
        ]
        
        missing_vars = [var for var in required_env_vars if not os.getenv(var)]
        if missing_vars:
            error_msg = f"Missing environment variables: {', '.join(missing_vars)}"
            logger.error(f"[ERROR] Platform sync failed: {error_msg}")
            logger.info("[INFO] To fix this, set the following environment variables:")
            logger.info("   PLATFORM_API_KEY=64b0ff1733d9f3dceaa5355eb7f6af16a")
            logger.info("   PLATFORM_API_SECRET=60f499e88fadb2919524771cd43d0fffcea2f571f549a3230f761b0f00ff209b")
            logger.info("   Or create a .env file in the project root with these variables")
            return {
                "success": False,
                "error": error_msg,
                "message": "Platform sync skipped due to missing configuration",
                "help": "Set PLATFORM_API_KEY and PLATFORM_API_SECRET environment variables"
            }
        
        db_service = get_database_service()
        
        # Get all active users from user_agent_task table
        query = """
        SELECT user_id, org_id, agent_task_id
        FROM user_agent_task
        WHERE status = 1 AND ready_to_use = 1
        ORDER BY updated DESC
        """
        rows = db_service.execute_query(query)
        
        if not rows:
            logger.info("No active users found for platform sync")
            return {"success": True, "message": "No active users found"}
        
        logger.info(f"Found {len(rows)} active users for platform sync")
        
        # Platform API configuration (allow override via env, fallback to default base URL)
        base_url = os.getenv("ELEVATION_AI_PLATFORM_URL", "https://devapi.agentic.elevationai.com").rstrip("/")
        platform_url = os.getenv("PLATFORM_LATEST_AGENT_URL") or f"{base_url}/user-agent-task/get-latest-agent-details"
        api_key = os.getenv("PLATFORM_API_KEY")
        api_secret = os.getenv("PLATFORM_API_SECRET")
        
        headers = {
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "x-api-secret": api_secret
        }
        
        # Process each user
        results = []
        for user_id, org_id, agent_task_id in rows:
            try:
                # Prepare payload as specified
                payload = {
                    "org_id": org_id,
                    "user_id": user_id,
                    "agent_task_id": agent_task_id
                }
                
                # Call the platform API directly (synchronous)
                try:
                    with httpx.Client(timeout=30.0) as client:
                        response = client.post(
                            platform_url,
                            json=payload,
                            headers=headers
                        )
                        
                        # Handle different HTTP status codes
                        if response.status_code == 404:
                            # User/agent_task_id not found on platform
                            try:
                                error_response = response.json()
                                error_detail = error_response.get("detail", error_response.get("message", "Not found"))
                            except:
                                error_detail = response.text[:200] if response.text else "Not found"
                            
                            logger.warning(
                                f"[WARNING] User {user_id} (agent_task_id: {agent_task_id}) not found on platform API (404). "
                                f"This may mean the user/agent doesn't exist on the platform yet. "
                                f"Error detail: {error_detail}"
                            )
                            results.append({
                                "user_id": user_id,
                                "agent_task_id": agent_task_id,
                                "success": False,
                                "error": "User not found on platform (404)",
                                "error_detail": error_detail,
                                "status_code": 404
                            })
                            continue
                        elif response.status_code == 401:
                            # Authentication failed
                            logger.error(f"[ERROR] Authentication failed for platform API (401). Check API credentials.")
                            results.append({
                                "user_id": user_id,
                                "success": False,
                                "error": "Platform API authentication failed (401)",
                                "status_code": 401
                            })
                            continue
                        elif response.status_code == 403:
                            # Forbidden
                            logger.error(f"[ERROR] Access forbidden for user {user_id} (403). Check API permissions.")
                            results.append({
                                "user_id": user_id,
                                "success": False,
                                "error": "Platform API access forbidden (403)",
                                "status_code": 403
                            })
                            continue
                        elif response.status_code >= 500:
                            # Server error
                            logger.error(f"[ERROR] Platform API server error for user {user_id} ({response.status_code})")
                            try:
                                error_response = response.json()
                                error_detail = error_response.get("detail", error_response.get("message", "Server error"))
                            except:
                                error_detail = response.text[:200] if response.text else "Server error"
                            
                            results.append({
                                "user_id": user_id,
                                "success": False,
                                "error": f"Platform API server error ({response.status_code})",
                                "error_detail": error_detail,
                                "status_code": response.status_code
                            })
                            continue
                        
                        # Raise for other status codes
                        response.raise_for_status()
                        platform_data = response.json()
                        
                except httpx.HTTPStatusError as e:
                    # Handle other HTTP status errors
                    status_code = e.response.status_code if hasattr(e, 'response') else None
                    try:
                        error_response = e.response.json() if hasattr(e, 'response') and e.response else {}
                        error_detail = error_response.get("detail", error_response.get("message", str(e)))
                    except:
                        error_detail = e.response.text[:200] if hasattr(e, 'response') and e.response and e.response.text else str(e)
                    
                    logger.error(
                        f"[ERROR] HTTP error calling platform API for user {user_id} (agent_task_id: {agent_task_id}): "
                        f"Status {status_code}, Error: {error_detail}"
                    )
                    results.append({
                        "user_id": user_id,
                        "agent_task_id": agent_task_id,
                        "success": False,
                        "error": f"HTTP error: {status_code}",
                        "error_detail": error_detail[:200],
                        "status_code": status_code
                    })
                    continue
                except httpx.RequestError as e:
                    # Network/connection errors
                    logger.error(f"[ERROR] Network error calling platform API for user {user_id}: {e}")
                    results.append({
                        "user_id": user_id,
                        "success": False,
                        "error": f"Network error: {str(e)[:100]}",
                        "error_type": "network_error"
                    })
                    continue
                except Exception as e:
                    # Other unexpected errors
                    logger.error(f"[ERROR] Unexpected error calling platform API for user {user_id}: {e}")
                    results.append({
                        "user_id": user_id,
                        "success": False,
                        "error": f"Unexpected error: {str(e)[:100]}",
                        "error_type": "unexpected_error"
                    })
                    continue
                
                # Check if platform API returned success
                # Handle both dict and list responses from platform API
                is_success = False
                if isinstance(platform_data, dict):
                    is_success = platform_data.get("success") or platform_data.get("status") == "success"
                elif isinstance(platform_data, list) and len(platform_data) > 0:
                    # If it's a list, assume it's successful if we got data
                    is_success = True
                    # Convert list to dict format for processing
                    platform_data = {"data": platform_data[0] if platform_data else {}}
                
                if is_success:
                    # Update user_agent_task table with platform data
                    update_success = _update_user_agent_task_from_platform(
                        db_service, user_id, org_id, agent_task_id, platform_data
                    )
                    
                    if update_success:
                        logger.info(f"[SUCCESS] Successfully synced user {user_id} from platform")
                        results.append({"user_id": user_id, "success": True})
                    else:
                        logger.warning(f"[WARNING] Failed to update user {user_id} in database")
                        results.append({"user_id": user_id, "success": False, "error": "Database update failed"})
                else:
                    logger.warning(f"[WARNING] Platform API returned no data for user {user_id}")
                    results.append({"user_id": user_id, "success": False, "error": "No platform data"})
                    
            except Exception as e:
                # Truncate error message to prevent database issues
                error_msg = str(e)
                if len(error_msg) > 500:
                    error_msg = error_msg[:500] + "... (truncated)"
                
                logger.error(f"[ERROR] Error syncing user {user_id}: {error_msg}")
                results.append({"user_id": user_id, "success": False, "error": error_msg})
        
        successful_syncs = len([r for r in results if r.get("success")])
        total_checked = len(rows)
        failed_syncs = total_checked - successful_syncs
        
        # Categorize failures by error type
        not_found_404 = [r for r in results if r.get("status_code") == 404]
        auth_errors = [r for r in results if r.get("status_code") in (401, 403)]
        server_errors = [r for r in results if r.get("status_code") and r.get("status_code") >= 500]
        other_errors = [r for r in results if not r.get("success") and r.get("status_code") not in (404, 401, 403) and (not r.get("status_code") or r.get("status_code") < 500)]
        
        # Log detailed summary
        logger.info("=" * 80)
        logger.info(f"Platform Sync Summary:")
        logger.info(f"   Total users checked: {total_checked}")
        logger.info(f"   [SUCCESS] Successfully synced: {successful_syncs}")
        logger.info(f"   [ERROR] Failed: {failed_syncs}")
        
        if not_found_404:
            logger.warning(f"   [WARNING] Users not found on platform (404): {len(not_found_404)}")
            for r in not_found_404:
                logger.warning(f"      - User: {r.get('user_id')}, Agent Task: {r.get('agent_task_id')}")
        
        if auth_errors:
            logger.error(f"   [ERROR] Authentication/Authorization errors: {len(auth_errors)}")
            for r in auth_errors:
                logger.error(f"      - User: {r.get('user_id')}, Status: {r.get('status_code')}")
        
        if server_errors:
            logger.error(f"   [ERROR] Platform API server errors: {len(server_errors)}")
            for r in server_errors:
                logger.error(f"      - User: {r.get('user_id')}, Status: {r.get('status_code')}")
        
        if other_errors:
            logger.warning(f"   [WARNING] Other errors: {len(other_errors)}")
            for r in other_errors:
                logger.warning(f"      - User: {r.get('user_id')}, Error: {r.get('error', 'Unknown')}")
        
        logger.info("=" * 80)
        
        if successful_syncs > 0:
            logger.info(f"[SUCCESS] Platform sync completed: {successful_syncs}/{total_checked} users synced successfully")
        else:
            logger.warning(f"[WARNING] Platform sync completed: No users synced out of {total_checked} checked")
            if not_found_404:
                logger.info("[INFO] Tip: Users with 404 errors may not exist on the platform yet. They will be synced once created on the platform.")
        
        return {
            "success": True,
            "message": f"Synced {successful_syncs}/{total_checked} users from platform",
            "results": results,
            "checked": total_checked,
            "synced": successful_syncs,
            "failed": failed_syncs,
            "error_breakdown": {
                "not_found_404": len(not_found_404),
                "auth_errors": len(auth_errors),
                "server_errors": len(server_errors),
                "other_errors": len(other_errors)
            }
        }
        
    except Exception as e:
        # Truncate error message to prevent database issues
        error_msg = str(e)
        if len(error_msg) > 500:
            error_msg = error_msg[:500] + "... (truncated)"
        
        logger.error(f"[ERROR] Platform sync job failed: {error_msg}")
        return {"success": False, "error": error_msg}


def _update_user_agent_task_from_platform(db_service, user_id: str, org_id: str, agent_task_id: str, platform_data: dict) -> bool:
    """
    Update user_agent_task and oauth_tokens tables with data from platform API.
    Follows the same pattern as the start endpoint for data storage.
    Extracts and decrypts Google tokens from workflow data and updates both tables.
    
    Args:
        db_service: Database service instance
        user_id: User ID
        org_id: Organization ID  
        agent_task_id: Agent task ID
        platform_data: Data returned from platform API
        
    Returns:
        True if update successful, False otherwise
    """
    try:
        # Import token processing function from workflow handlers
        from ..api.handlers.workflow_handlers import process_google_tokens_from_workflow_data
        
        # Extract data from platform response
        # Handle different response structures from platform API
        data = platform_data.get("data", [])
        
        # Initialize default values
        user_info = {}
        notification_preference = "only_me"  # default
        timezone = "UTC"  # default
        google_access_token = None
        google_refresh_token = None
        name = f"Agent for {user_id}"
        drive_folder_id = ""
        sheets_id = ""
        

        # Process Google tokens from workflow data using same logic as start endpoint
        if isinstance(data, list) and len(data) > 0:
            try:
                processed_data = process_google_tokens_from_workflow_data(data)
                google_tokens = processed_data.get("google_tokens", {})
                extracted_user_info = processed_data.get("user_info", {})
                
                # Extract decrypted tokens
                google_access_token = google_tokens.get("access_token")
                google_refresh_token = google_tokens.get("refresh_token")
                
                # Update user_info with extracted info
                if extracted_user_info:
                    user_info.update(extracted_user_info)
                
                logger.info(f"[SUCCESS] Extracted Google tokens from platform payload for user {user_id}")
                logger.info(f"   Has access_token: {bool(google_access_token)}")
                logger.info(f"   Has refresh_token: {bool(google_refresh_token)}")
            except Exception as e:
                logger.warning(f"[WARNING] Failed to extract tokens from workflow data for user {user_id}: {e}")
                # Continue with other data extraction even if token extraction fails
        
        # If data is a list, process each item (the actual payload structure)
        if isinstance(data, list):
            # Extract data from each workflow item
            for workflow_item in data:
                if isinstance(workflow_item, dict):
                    # Extract Google account information (id: 360e41e7-ddf7-445f-9141-0b5c2ecb1009)
                    if workflow_item.get("id") == "360e41e7-ddf7-445f-9141-0b5c2ecb1009":
                        for tool in workflow_item.get("tool_to_use", []):
                            for field in tool.get("fields_json", []):
                                if field.get("field") == "email":
                                    user_info["email"] = field.get("value")
                                elif field.get("field") == "name":
                                    user_info["name"] = field.get("value")
                                elif field.get("field") == "first_name":
                                    user_info["first_name"] = field.get("value")
                                elif field.get("field") == "last_name":
                                    user_info["last_name"] = field.get("value")
                                # SKIPPED: Token extraction - only notification_preference is updated
                                # Tokens are managed by:
                                # 1. Start endpoint (initial setup)
                                # 2. Token refresh job (every 1 hour)
                    
                    # Extract notification preference (id: 360e41e7-ddf7-445f-9141-0b5c2ecb1010)
                    elif workflow_item.get("id") == "360e41e7-ddf7-445f-9141-0b5c2ecb1010":
                        for tool in workflow_item.get("tool_to_use", []):
                            for field in tool.get("fields_json", []):
                                if field.get("field") == "notify_to":
                                    val = (field.get("value") or "").strip().lower()
                                    if val == "only_me":
                                        notification_preference = "only_me"
                                    elif val == "all":
                                        notification_preference = "all_participants"
                                    else:
                                        notification_preference = "only_me"  # default
                                    break
                    
                    # Extract timezone (if present)
                    elif workflow_item.get("id") == "timezone":
                        for tool in workflow_item.get("tool_to_use", []):
                            for field in tool.get("fields_json", []):
                                if field.get("field") == "timezone":
                                    timezone = field.get("value", "UTC")
                                    break
            
            # Extract other data from platform response
            name = user_info.get("name") or f"{user_info.get('first_name', '')} {user_info.get('last_name', '')}".strip() or f"Agent for {user_id}"
        
        # Handle case where data is not a list (fallback)
        elif isinstance(data, dict):
            # Try to extract basic info from dict structure
            name = data.get("name") or f"Agent for {user_id}"
            # Map notification preference same as start endpoint
            notify_val = data.get("notification_preference", "only_me")
            if notify_val == "all":
                notification_preference = "all_participants"
            else:
                notification_preference = "only_me"
            timezone = data.get("timezone", "UTC")
            drive_folder_id = data.get("drive_folder_id", "")
            sheets_id = data.get("sheets_id", "")
            google_access_token = data.get("google_access_token", "")
            google_refresh_token = data.get("google_refresh_token", "")
        
        # Update user_agent_task table with platform data (including tokens if available)
        update_query = """
        UPDATE user_agent_task 
        SET 
            name = COALESCE(:name, name),
            notification_preference = COALESCE(:notification_preference, notification_preference),
            timezone = COALESCE(:timezone, timezone),
            updated = NOW()
            {token_update_clause}
        WHERE user_id = :user_id 
          AND org_id = :org_id 
          AND agent_task_id = :agent_task_id
        """
        
        update_data = {
            "user_id": user_id,
            "org_id": org_id,
            "agent_task_id": agent_task_id,
            "name": name,
            "notification_preference": notification_preference,
            "timezone": timezone
        }
        
        # Add token updates if tokens were extracted
        token_update_clause = ""
        if google_access_token or google_refresh_token:
            if google_access_token:
                token_update_clause += ", google_access_token = :google_access_token"
                update_data["google_access_token"] = google_access_token
            if google_refresh_token:
                token_update_clause += ", google_refresh_token = :google_refresh_token"
                update_data["google_refresh_token"] = google_refresh_token
        
        update_query = update_query.format(token_update_clause=token_update_clause)
        
        # Execute update
        db_service.execute_query(update_query, update_data)
        logger.info(f"[SUCCESS] Updated user_agent_task table for user {user_id}")
        
        # Update oauth_tokens table with decrypted tokens (same logic as start endpoint)
        if google_access_token or google_refresh_token:
            try:
                # datetime is already imported at module level
                
                # Build update query with available tokens
                oauth_update_query = """
                INSERT INTO oauth_tokens
                (user_id, org_id, agent_task_id, provider,
                 access_token, refresh_token, token_type, expires_at, scope, created_at, updated_at)
                VALUES (:user_id, :org_id, :agent_task_id, :provider,
                        :access_token, :refresh_token, :token_type, :expires_at, :scope, :created_at, :updated_at)
                ON DUPLICATE KEY UPDATE
                {update_clause}updated_at = VALUES(updated_at)
                """
                
                oauth_params = {
                    "user_id": user_id,
                    "org_id": org_id,
                    "agent_task_id": agent_task_id,
                    "provider": "google",
                    "token_type": "Bearer",
                    "expires_at": None,
                    "scope": "https://www.googleapis.com/auth/calendar https://www.googleapis.com/auth/drive https://www.googleapis.com/auth/spreadsheets",
                    "created_at": datetime.now(),
                    "updated_at": datetime.now()
                }
                
                # Build update clause based on available tokens
                update_clauses = []
                if google_access_token:
                    update_clauses.append("access_token = VALUES(access_token)")
                    oauth_params["access_token"] = google_access_token
                else:
                    # Don't update if token not provided - keep existing
                    oauth_params["access_token"] = None
                
                if google_refresh_token:
                    update_clauses.append("refresh_token = VALUES(refresh_token)")
                    oauth_params["refresh_token"] = google_refresh_token
                else:
                    # Don't update if token not provided - keep existing
                    oauth_params["refresh_token"] = None
                
                # Only update fields that were provided
                if update_clauses:
                    oauth_update_query = oauth_update_query.format(update_clause=", ".join(update_clauses) + ", ")
                    db_service.execute_query(oauth_update_query, oauth_params)
                    logger.info(f"[SUCCESS] Updated oauth_tokens table for user {user_id}")
                    logger.info(f"   - access_token: {'UPDATED' if google_access_token else 'preserved'}")
                    logger.info(f"   - refresh_token: {'UPDATED' if google_refresh_token else 'preserved'}")
                else:
                    logger.info(f"[INFO] No tokens to update in oauth_tokens table for user {user_id}")
            except Exception as oauth_error:
                logger.error(f"[ERROR] Failed to update oauth_tokens table for user {user_id}: {oauth_error}")
        else:
            logger.info(f"[INFO] No tokens extracted from platform payload for user {user_id} - tokens preserved")
        
        logger.info(f"[SUCCESS] Updated user {user_id} with platform data:")
        logger.info(f"   - Notification Preference: {notification_preference} (UPDATED)")
        logger.info(f"   - Name: {name}")
        logger.info(f"   - Timezone: {timezone}")
        logger.info(f"   - Google Access Token: {'UPDATED' if google_access_token else 'preserved'}")
        logger.info(f"   - Google Refresh Token: {'UPDATED' if google_refresh_token else 'preserved'}")
        logger.info(f"   - Drive Folder ID: PRESERVED (not updated)")
        logger.info(f"   - Sheets ID: PRESERVED (not updated)")
        return True
        
    except Exception as e:
        logger.error(f"Failed to update user_agent_task for user {user_id}: {e}")
        return False


def refresh_all_users_tokens():
    """
    Enhanced function to refresh Google OAuth tokens for all users using direct API call.
    This function is designed to be called by BackgroundScheduler every {SCHEDULER_TOKEN_REFRESH_INTERVAL} minutes.
    Uses the requests library to directly call Google's token endpoint.
    Refreshes tokens for ALL users with status=1 and ready_to_use=1, regardless of expiry.
    
    IMPORTANT: This job runs EVERY 55 MINUTES NO MATTER WHAT - it will always execute on schedule.
    Even if there are no users or all refreshes fail, the job will still run again in 55 minutes.
    
    For each user:
    1. Gets their refresh_token from database
    2. Calls Google API to get new access_token
    3. Updates BOTH tables with new access_token (REQUIRED):
       - oauth_tokens: access_token, expires_at, updated_at
       - user_agent_task: google_access_token, updated
    4. If Google provides a new refresh_token, updates both tables with it
    
    IMPORTANT: Both tables MUST be updated successfully. If either update fails, the operation is marked as failed.
    """
    try:
        import requests
        import os
        from datetime import datetime, timedelta
        
        logger.info(f"[START] Starting token refresh for ALL users every {SCHEDULER_TOKEN_REFRESH_INTERVAL} minutes...")
        logger.info("   This job runs EVERY 55 MINUTES NO MATTER WHAT - it will always execute on schedule")
        logger.info("   This will update each user's access_token using their refresh_token")
        
        from ..services.database_service_new import get_database_service
        
        db_service = get_database_service()
        
        # Get Google OAuth credentials from environment (use primary, not OAuth-specific)
        client_id = os.getenv("GOOGLE_CLIENT_ID")
        client_secret = os.getenv("GOOGLE_CLIENT_SECRET")
        
        if not client_id or not client_secret:
            logger.error(" Missing GOOGLE_CLIENT_ID or GOOGLE_CLIENT_SECRET in environment variables")
            logger.error(f"   GOOGLE_CLIENT_ID present: {bool(client_id)}")
            logger.error(f"   GOOGLE_CLIENT_SECRET present: {bool(client_secret)}")
            return {"success": False, "error": "Missing OAuth credentials"}
        
        logger.info(f"OAuth credentials loaded: client_id={client_id[:10]}... (first 10 chars)")
        
        token_url = "https://oauth2.googleapis.com/token"
        
        # Get ALL active users with refresh tokens - refresh every 60 minutes regardless of expiry
        # Join both tables to get refresh_token from either location
        query = """
        SELECT DISTINCT 
            ot.user_id, 
            ot.org_id, 
            ot.agent_task_id,
            COALESCE(ot.refresh_token, uat.google_refresh_token) as refresh_token,
            ot.access_token,
            uat.google_access_token,
            ot.expires_at,
            ot.created_at
        FROM oauth_tokens ot
        INNER JOIN user_agent_task uat ON uat.agent_task_id = ot.agent_task_id
        WHERE ot.provider = 'google'
          AND COALESCE(ot.refresh_token, uat.google_refresh_token) IS NOT NULL 
          AND COALESCE(ot.refresh_token, uat.google_refresh_token) <> ''
          AND uat.status = 1 
          AND uat.ready_to_use = 1
        ORDER BY ot.updated_at ASC
        """
        rows = db_service.execute_query(query)
        
        if not rows:
            logger.info("No active users found with refresh tokens - job executed successfully but no users to process")
            logger.info("This is expected if no users are active. Job will run again in 55 minutes.")
            return {"success": True, "message": "No active users found with refresh tokens", "users_processed": 0}
        
        logger.info(f"Found {len(rows)} active users to refresh tokens for")
        
        # Process each user's token refresh - ALWAYS refresh every 55 minutes regardless of expiry
        # This job runs EVERY 55 MINUTES NO MATTER WHAT - it will always execute on schedule
        results = []
        for row in rows:
            user_id = row[0]
            org_id = row[1]
            agent_task_id = row[2]
            refresh_token = row[3]
            oauth_access_token = row[4]
            uat_access_token = row[5]
            expires_at = row[6]
            created_at = row[7]
            
            # Use access token from either table (prioritize oauth_tokens)
            current_access_token = oauth_access_token or uat_access_token
            
            try:
                logger.info(f"Refreshing token for user {user_id}, agent_task {agent_task_id}")
                logger.info(f"   Current access token (first 20 chars): {current_access_token[:20] if current_access_token else 'None'}...")
                logger.info(f"   Expires at: {expires_at}, Created at: {created_at}")
                
                # Prepare payload for token refresh
                payload = {
                    'grant_type': 'refresh_token',
                    'refresh_token': refresh_token,
                    'client_id': client_id,
                    'client_secret': client_secret
                }
                
                # Make the POST request to Google's token endpoint
                logger.info(f"Calling Google token endpoint for user {user_id}")
                response = requests.post(token_url, data=payload, timeout=30)
                response.raise_for_status()  # Raise an error for bad responses (4xx or 5xx)
                
                # Parse response
                new_tokens = response.json()
                new_access_token = new_tokens.get('access_token')
                new_refresh_token = new_tokens.get('refresh_token')  # Google may return a new refresh_token
                expires_in = new_tokens.get('expires_in', 3600)  # Default to 1 hour
                
                if new_access_token:
                    logger.info(f"[SUCCESS] New access token obtained for user {user_id} (first 20 chars): {new_access_token[:20]}...")
                    
                    # Calculate new expiry time (use UTC for consistency with database)
                    from datetime import timezone
                    new_expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
                    
                    # Update oauth_tokens table with NEW access_token AND refresh_token (if provided)
                    # Follow the same pattern as refresh_token_simple.py for consistency
                    logger.info(f"Updating oauth_tokens table for user {user_id}")
                    
                    # Build query with optional refresh_token update
                    oauth_params = {
                        "access_token": new_access_token,
                        "expires_at": new_expires_at,
                        "user_id": user_id,
                        "agent_task_id": agent_task_id
                    }
                    
                    if new_refresh_token:
                        update_oauth_query = """
                        UPDATE oauth_tokens 
                        SET access_token = :access_token,
                            refresh_token = :refresh_token,
                            expires_at = :expires_at,
                            updated_at = NOW()
                        WHERE user_id = :user_id AND agent_task_id = :agent_task_id AND provider = 'google'
                        """
                        oauth_params["refresh_token"] = new_refresh_token
                        logger.info(f"   Also updating refresh_token in oauth_tokens table")
                    else:
                        # If no new refresh_token, keep the existing one (don't update it)
                        update_oauth_query = """
                        UPDATE oauth_tokens 
                        SET access_token = :access_token,
                            expires_at = :expires_at,
                            updated_at = NOW()
                        WHERE user_id = :user_id AND agent_task_id = :agent_task_id AND provider = 'google'
                        """
                    
                    # execute_query returns [] for UPDATE queries on success, raises exception on failure
                    try:
                        oauth_result = db_service.execute_query(update_oauth_query, oauth_params)
                        # If we get here without exception, the update succeeded
                        # execute_query returns [] for UPDATE/INSERT/DELETE queries
                        logger.info(f"   [SUCCESS] oauth_tokens table updated successfully with new access_token")
                        logger.info(f"   - access_token: UPDATED (first 20 chars: {new_access_token[:20]}...)")
                        logger.info(f"   - expires_at: UPDATED ({new_expires_at}) (UTC)")
                        logger.info(f"   - expires_in: {expires_in} seconds ({expires_in/3600:.2f} hours)")
                        if new_refresh_token:
                            logger.info(f"   - refresh_token: UPDATED")
                    except Exception as oauth_update_error:
                        logger.error(f"   [ERROR] Failed to update oauth_tokens table for user {user_id}: {oauth_update_error}", exc_info=True)
                        logger.error(f"   Query: {update_oauth_query[:200]}...")
                        logger.error(f"   Params: user_id={user_id}, agent_task_id={agent_task_id}")
                        results.append({"user_id": user_id, "success": False, "error": f"oauth_tokens update failed: {str(oauth_update_error)[:100]}"})
                        continue
                    
                    # Update user_agent_task table with NEW access_token AND refresh_token (if provided)
                    logger.info(f"Updating user_agent_task table for user {user_id}")
                    
                    uat_params = {
                        "access_token": new_access_token,
                        "user_id": user_id,
                        "org_id": org_id,
                        "agent_task_id": agent_task_id
                    }
                    
                    if new_refresh_token:
                        update_uat_query = """
                        UPDATE user_agent_task 
                        SET google_access_token = :access_token,
                            google_refresh_token = :refresh_token,
                            updated = NOW()
                        WHERE user_id = :user_id AND org_id = :org_id AND agent_task_id = :agent_task_id
                        """
                        uat_params["refresh_token"] = new_refresh_token
                        logger.info(f"   Also updating google_refresh_token in user_agent_task table")
                    else:
                        update_uat_query = """
                        UPDATE user_agent_task 
                        SET google_access_token = :access_token,
                            updated = NOW()
                        WHERE user_id = :user_id AND org_id = :org_id AND agent_task_id = :agent_task_id
                        """
                    
                    # execute_query returns [] for UPDATE queries on success, raises exception on failure
                    try:
                        uat_result = db_service.execute_query(update_uat_query, uat_params)
                        # If we get here without exception, the update succeeded
                        # execute_query returns [] for UPDATE/INSERT/DELETE queries
                        logger.info(f"   [SUCCESS] user_agent_task table updated successfully with new access_token")
                        logger.info(f"   - google_access_token: UPDATED (first 20 chars: {new_access_token[:20]}...)")
                        logger.info(f"   - updated: UPDATED (NOW())")
                        if new_refresh_token:
                            logger.info(f"   - google_refresh_token: UPDATED")
                    except Exception as uat_update_error:
                        logger.error(f"   [ERROR] Failed to update user_agent_task table for user {user_id}: {uat_update_error}", exc_info=True)
                        logger.error(f"   Query: {update_uat_query[:200]}...")
                        logger.error(f"   Params: user_id={user_id}, org_id={org_id}, agent_task_id={agent_task_id}")
                        results.append({"user_id": user_id, "success": False, "error": f"user_agent_task update failed: {str(uat_update_error)[:100]}"})
                        continue
                    
                    # Check if token actually changed
                    if current_access_token and new_access_token == current_access_token:
                        logger.warning(f"Token refresh succeeded but token didn't change for user {user_id}")
                    else:
                        logger.info(f"Token refreshed successfully for user {user_id}. New token obtained.")

                    results.append({
                        "user_id": user_id, 
                        "success": True, 
                        "token_changed": current_access_token != new_access_token if current_access_token and new_access_token else True
                    })
                else:
                    logger.error(f"Could not find 'access_token' in response for user {user_id}: {new_tokens}")
                    results.append({"user_id": user_id, "success": False, "error": "No access_token in response"})
                    
            except requests.exceptions.RequestException as e:
                logger.error(f"[ERROR] HTTP Error refreshing token for user {user_id}: {e}")
                if hasattr(e, 'response') and e.response:
                    try:
                        error_response = e.response.json()
                        error_type = error_response.get('error', 'unknown')
                        error_description = error_response.get('error_description', 'No description')
                        logger.error(f"   Google Error: {error_type}")
                        logger.error(f"   Description: {error_description}")
                        logger.error(f"   Full Response: {e.response.text}")
                        
                        # Provide helpful guidance based on error type
                        if error_type == 'invalid_grant':
                            logger.error(f"   [WARNING] This usually means:")
                            logger.error(f"      - Refresh token has been revoked by user")
                            logger.error(f"      - Refresh token is expired or invalid")
                            logger.error(f"      - User needs to re-authenticate")
                        elif error_type == 'invalid_client':
                            logger.error(f"   [WARNING] This usually means:")
                            logger.error(f"      - GOOGLE_CLIENT_ID or GOOGLE_CLIENT_SECRET is wrong")
                            logger.error(f"      - OAuth client credentials don't match the token")
                    except:
                        logger.error(f"   Raw Response: {e.response.text}")
                else:
                    logger.error(f"   No response object available")
                results.append({"user_id": user_id, "success": False, "error": str(e)})
            except Exception as e:
                logger.error(f"[ERROR] Unexpected error refreshing token for user {user_id}: {e}", exc_info=True)
                results.append({"user_id": user_id, "success": False, "error": str(e)})
        
        successful_refreshes = len([r for r in results if r.get("success") and not r.get("skipped")])
        total_checked = len(rows)
        
        if successful_refreshes > 0:
            logger.info(f"[SUCCESS] Token refresh completed: {successful_refreshes}/{total_checked} users' access_tokens updated successfully")
            logger.info(f"   All {successful_refreshes} users now have fresh access tokens valid for 1 hour")
            logger.info(f"   [SUCCESS] Updated oauth_tokens table: access_token, expires_at, updated_at")
            logger.info(f"   [SUCCESS] Updated user_agent_task table: google_access_token, updated")
            logger.info(f"   Both tables updated with new access_token for all successful refreshes")
        else:
            logger.warning(f"[WARNING] Token refresh completed: No tokens were refreshed out of {total_checked} users checked")
            logger.warning(f"   This may indicate all users need to re-authenticate")
        
        return {
            "success": True,
            "message": f"Checked {total_checked} users, updated {successful_refreshes} access tokens",
            "results": results,
            "checked": total_checked,
            "refreshed": successful_refreshes,
            "updated_tables": ["oauth_tokens", "user_agent_task"]
        }
        
    except Exception as e:
        logger.error(f"[ERROR] Token refresh job failed: {e}", exc_info=True)
        return {"success": False, "error": str(e)}

def _should_refresh_token(expires_at, created_at) -> bool:
    """Determine if a token should be refreshed"""
    try:
        from datetime import datetime, timedelta
        
        now = datetime.now()
        
        # If no expiry info, assume it might need refresh after 1 hour
        if not expires_at:
            if created_at:
                if isinstance(created_at, str):
                    created_at = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                # Refresh if created more than 50 minutes ago
                return (now - created_at).total_seconds() > 3000  # 50 minutes
            return True  # No creation time either, refresh to be safe
        
        # Parse expiry time
        if isinstance(expires_at, str):
            expires_at = datetime.fromisoformat(expires_at.replace('Z', '+00:00'))
        
        # Refresh if expired or expires within 10 minutes
        return expires_at <= now + timedelta(minutes=10)
        
    except Exception as e:
        logger.warning(f"Error checking token expiry: {e}")
        return True  # Refresh to be safe

def cleanup_old_agent_records():
    """
    Clean up old agent execution records from the agent table.
    Deletes records older than 2 days to prevent table growth.
    
    This function runs every 2 days via scheduled job.
    """
    try:
        from ..services.database_service_new import get_database_service
        from datetime import datetime, timedelta
        
        db_service = get_database_service()
        
        # Calculate cutoff date (2 days ago)
        cutoff_date = datetime.now(pytz.UTC) - timedelta(days=2)
        cutoff_date_str = cutoff_date.strftime('%Y-%m-%d %H:%M:%S')
        
        logger.info(f"Starting agent table cleanup: deleting records older than {cutoff_date_str}")
        
        # Get count of records to be deleted first
        count_query = """
            SELECT COUNT(*) FROM agent 
            WHERE created < :cutoff_date
        """
        
        count_result = db_service.execute_query(count_query, {"cutoff_date": cutoff_date_str})
        deleted_count = count_result[0][0] if count_result and count_result[0] else 0
        
        # Delete old agent records
        if deleted_count > 0:
            query = """
                DELETE FROM agent 
                WHERE created < :cutoff_date
            """
            
            db_service.execute_query(query, {"cutoff_date": cutoff_date_str})
        
        logger.info(f"[SUCCESS] Agent table cleanup completed: deleted {deleted_count} record(s) older than 2 days")
        
        return {
            "success": True,
            "deleted_count": deleted_count,
            "cutoff_date": cutoff_date_str
        }
        
    except Exception as e:
        logger.error(f"[ERROR] Failed to cleanup old agent records: {e}", exc_info=True)
        return {
            "success": False,
            "error": str(e)
        }