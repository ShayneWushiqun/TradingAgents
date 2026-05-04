# Analysis Queue Design

## Goal

Hot Radar should let a user start analysis without leaving the page, while still choosing the same core parameters available on the Analyze page. Analysis tasks must enter a real backend queue so the UI can show waiting/running/completed work, adjust waiting priority, stop running work, and delete tasks that have not started.

The Analyze page remains the power-user path for starting a single analysis in a dedicated workspace. Tasks started from Analyze have higher priority than tasks started from Hot Radar.

## Scope

This design covers:

- Hot Radar row-level analysis parameter modal.
- Analyze page report-model selector.
- Backend analysis queue with model-specific concurrency.
- Queue status UI and task controls.
- API changes needed by the frontend.

This design does not include bulk-select batch creation, configurable concurrency, account-level rate-limit tuning, or a durable distributed job system.

## Model Lanes

Tasks are assigned to an execution lane based on the selected report model:

- `deepseek-v4-pro`: Pro lane, maximum 1 running task.
- `deepseek-v4-flash`: Flash lane, maximum 3 running tasks.

Priority is resolved within each lane. A Pro task never blocks Flash capacity, and Flash tasks never consume the Pro slot.

## Task Priority

Each task has an origin and priority:

- Analyze page manual task: high priority.
- Hot Radar modal task: normal priority.

Within a lane:

1. Running tasks continue unless stopped.
2. Waiting tasks are ordered by priority first.
3. For equal priority, user-controlled queue order wins.
4. For equal queue order, older tasks run first.

When a user starts an analysis from the Analyze page, it is inserted near the front of the matching lane, behind already-running tasks.

## Hot Radar Modal

Clicking a Hot Radar row's `分析` or `再次分析` opens a modal instead of navigating away or directly posting a hard-coded task.

The modal shows:

- Stock name, code, and trade date.
- Analyst team chips: market, fundamentals, news, social.
- Research depth: standard or deep.
- Report model: DeepSeek V4 Pro or DeepSeek V4 Flash.
- Primary action: `加入分析队列`.

Defaults should match the Analyze page defaults:

- Analysts: market and fundamentals selected.
- Research depth: standard.
- Report model: value from `TRADINGAGENTS_REPORT_MODEL`, defaulting to `deepseek-v4-pro`.

Submitting the modal creates a queued task and refreshes the queue panel. The Hot Radar row should show a running/waiting chip when a matching current-day task exists and should show `报告` when completed.

## Analyze Page Model Selector

The Analyze page adds `报告分析模型` between `研究深度` and the action buttons.

It uses the same local storage key as Settings:

- `TRADINGAGENTS_REPORT_MODEL`

Changing this selector affects only future tasks. Running tasks keep the model captured in their request. The payload sent to `/api/analysis` uses the selected model for both `quick_model` and `deep_model`.

## Queue Panel

Hot Radar shows a queue panel near the candidate list or right-side context area. It should be visible enough that users understand analyses are queued, but it should not dominate the radar scanning workflow.

Each queue row shows:

- Stock name and code.
- Trade date.
- Model lane: Pro or Flash.
- Selected analysts.
- Research depth.
- Origin: Analyze or Hot Radar.
- Status: queued, running, stopping, stopped, completed, failed.
- Position within its lane for queued tasks.

Controls:

- Queued tasks: move up, move down, delete.
- Running tasks: stop.
- Completed tasks: open report.
- Failed or stopped tasks: optionally retry later through the same modal or Analyze page.

## Backend Queue Semantics

`POST /api/analysis` creates a task and places it in the queue. It should not start an ad-hoc thread immediately. A scheduler owns task dispatch and starts work only when the task's lane has capacity.

Task lifecycle:

```text
queued -> running -> completed
queued -> deleted
queued -> stopped
running -> stopping -> stopped
running -> failed
running -> completed
```

Stopping a running task is cooperative. If the underlying LLM call cannot be interrupted immediately, the task enters `stopping` and the UI explains that the stop request has been sent.

Deleting is only allowed for queued tasks. Historical deletion for completed/failed tasks keeps the existing reports-page behavior.

## API Shape

Existing:

- `POST /api/analysis`: create queued task.
- `GET /api/analysis/{task_id}`: task detail.
- `GET /api/analysis/history`: recent task history.
- `DELETE /api/analysis/{task_id}`: delete queued tasks, and keep existing completed/failed historical deletion behavior.

New:

- `GET /api/analysis/queue`: returns lanes, running tasks, queued tasks, and capacity.
- `POST /api/analysis/{task_id}/priority`: move a queued task up/down or set absolute position within its lane.
- `POST /api/analysis/{task_id}/stop`: request stop for queued/running task.

Queue payloads should include enough display data for the UI. If a task was created from Hot Radar, include the stock name supplied by the row so the queue does not fall back to code-only display.

## Error Handling

- If task creation fails, keep the modal open and show the error.
- If queue refresh fails, show the last known queue plus a small stale-data warning.
- If deleting a task fails because it already started, refresh the queue and show that it is now running.
- If stopping is requested for a completed task, treat it as a no-op and refresh state.
- If cache hit completes immediately, the task may move from queued to completed without entering running.

## Persistence

The existing MySQL analysis store keeps task history. Queue-specific fields should be persisted when the store is available:

- origin.
- lane.
- priority.
- queue position.
- stop requested flag.

When the store is unavailable, in-memory queue behavior is acceptable for the current local workstation mode.

## Testing

Backend tests:

- Pro lane starts only one task at a time.
- Flash lane starts at most three tasks.
- Analyze-origin tasks outrank Hot Radar tasks in the same lane.
- Moving queued tasks changes dispatch order.
- Deleting queued tasks removes them.
- Deleting running tasks is blocked or converted to stop according to API.
- Stop request moves running tasks to stopping/stopped when cooperative cancellation is observed.
- No-store history still returns all recent tasks.

Frontend/design tests:

- Hot Radar no longer direct-posts hard-coded analysis on row click.
- Hot Radar modal includes analysts, depth, and model controls.
- Modal submission posts selected parameters.
- Analyze page includes model selector and uses `TRADINGAGENTS_REPORT_MODEL`.
- Queue panel renders Pro capacity 1 and Flash capacity 3.
- Queued rows expose move/delete controls; running rows expose stop.

## Rollout

Implement in stages:

1. Add Analyze page model selector.
2. Add backend queue primitives and lane scheduler.
3. Add queue API endpoints.
4. Replace Hot Radar row click with modal task creation.
5. Add queue panel and controls.
6. Browser-verify Hot Radar and Analyze flows.
