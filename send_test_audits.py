import sys
import asyncio
from datetime import datetime

from src.services.integration.platform_api_client import PlatformAPIClient


async def run_all(agent_task_id: str) -> None:
    client = PlatformAPIClient()
    results = []

    results.append((
        'workflow_started_simple',
        await client.send_simple_log(
            agent_task_id=agent_task_id,
            log_text='Workflow started successfully and waiting for active meeting event and transcripts.',
            activity_type='task',
            log_for_status='success',
            action='Read',
            action_issue_event='Request payload processed.',
            action_required='None',
            outcome='Workflow scheduled.',
            step_str='Received the request and scheduled the workflow based on user preferences.',
            tool_str='N/A',
            log_data={'trigger': 'manual_test'}
        )
    ))

    results.append((
        'no_events_found',
        await client.send_audit_log({
            'agent_task_id': agent_task_id,
            'action': 'no_events_found',
            'timestamp': datetime.utcnow().isoformat(),
            'details': {
                'headline': 'No new meetings within the scan window; agent will retry on schedule.',
                'message': 'No active calendar events were found in the selected window. The agent will check again as scheduled.'
            }
        })
    ))

    results.append((
        'agent_workflow_completed',
        await client.send_audit_log({
            'agent_task_id': agent_task_id,
            'action': 'agent_workflow_completed',
            'timestamp': datetime.utcnow().isoformat(),
            'details': {'events_scanned': 2, 'summaries_generated': 1, 'tasks_extracted': 5}
        })
    ))

    results.append((
        'drive_folder_created',
        await client.send_audit_log({
            'agent_task_id': agent_task_id,
            'action': 'drive_folder_created',
            'timestamp': datetime.utcnow().isoformat(),
            'details': {'drive_folder_id': 'test_folder_123'}
        })
    ))

    results.append((
        'sheets_created',
        await client.send_audit_log({
            'agent_task_id': agent_task_id,
            'action': 'sheets_created',
            'timestamp': datetime.utcnow().isoformat(),
            'details': {'sheets_id': 'test_sheet_123'}
        })
    ))

    results.append((
        'email_sent',
        await client.send_audit_log({
            'agent_task_id': agent_task_id,
            'action': 'email_sent',
            'timestamp': datetime.utcnow().isoformat(),
            'details': {'message': 'Email sent with meeting summary and tasks.'}
        })
    ))

    results.append((
        'tasks_sent_simple',
        await client.send_simple_log(
            agent_task_id=agent_task_id,
            log_text='Successfully sent 5 tasks to platform.',
            activity_type='task',
            log_for_status='success',
            action='Complete',
            action_issue_event='Tasks distributed to platform.',
            action_required='None',
            outcome='Tasks added to task management.',
            step_str='Meeting tasks synchronized with platform.',
            tool_str='Meeting Agent',
            log_data={'tasks_sent': 5}
        )
    ))

    results.append((
        'agent_completed',
        await client.send_audit_log({
            'agent_task_id': agent_task_id,
            'action': 'agent_completed',
            'timestamp': datetime.utcnow().isoformat(),
            'details': {}
        })
    ))

    for name, ok in results:
        print(f"{name}: {'OK' if ok else 'FAIL'}")


def main() -> int:
    agent_task_id = sys.argv[1] if len(sys.argv) > 1 else 'atePlgz0lv'
    asyncio.run(run_all(agent_task_id))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())


