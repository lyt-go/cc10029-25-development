import { request } from './client'
import { moduleMeta } from '@/data/modules'
import type { ActionResult, EntryRow, OverviewResult, PageResult } from '@/data/types'
import type { RecoveryDashboard, ReplayResult } from '@/domain/recovery_scope'

export { moduleMeta }

export async function listEntries(
  key: string,
  filters: Record<string, string> = {},
): Promise<PageResult> {
  const query = new URLSearchParams(filters).toString()
  const response = await request(`/api/${key}?${query}`)
  if (!response.ok) throw new Error('业务数据读取失败')
  return await response.json()
}

export async function createEntry(
  key: string,
  values: Record<string, string>,
): Promise<ActionResult> {
  const response = await request(`/api/${key}`, {
    method: 'POST',
    body: JSON.stringify({ values }),
  })
  return await response.json()
}

export async function runAction(
  key: string,
  id: number,
  action: string,
): Promise<ActionResult> {
  const response = await request(`/api/${key}/${id}/actions`, {
    method: 'POST',
    body: JSON.stringify({ action }),
  })
  return await response.json()
}

export async function downloadEntries(
  key: string,
  filters: Record<string, string> = {},
): Promise<void> {
  const query = new URLSearchParams(filters).toString()
  const response = await request(`/api/${key}/export?${query}`)
  if (!response.ok) throw new Error('业务数据导出失败')
  const url = URL.createObjectURL(await response.blob())
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `${key}.csv`
  document.body.appendChild(anchor)
  anchor.click()
  document.body.removeChild(anchor)
  URL.revokeObjectURL(url)
}

export async function loadOverview(): Promise<OverviewResult> {
  const response = await request('/api/overview')
  if (!response.ok) throw new Error('运营概览读取失败')
  return await response.json()
}

/* ---- 恢复范围看板 ---- */

async function postJson<T>(path: string, body: unknown): Promise<T> {
  const response = await request(path, { method: 'POST', body: JSON.stringify(body) })
  const payload = await response.json()
  if (!response.ok) throw new Error(payload?.detail ?? '看板操作失败')
  return payload as T
}

export async function fetchRecoveryDashboard(batchCode: string): Promise<RecoveryDashboard> {
  const response = await request(`/api/recovery_scope/dashboard?batch_code=${encodeURIComponent(batchCode)}`)
  if (!response.ok) throw new Error('恢复范围看板读取失败')
  return await response.json()
}

export async function replayRecoveryBatch(batchCode: string): Promise<ReplayResult> {
  return await postJson<ReplayResult>('/api/recovery_scope/replay', { batch_code: batchCode })
}

export async function restoreRecoveryPiece(entryId: number): Promise<{ message?: string }> {
  return await postJson('/api/recovery_scope/restore', { entry_id: entryId })
}

export async function syncRecoveryLineage(
  batchCode: string,
): Promise<{ linked: number; lineage_code: string }> {
  return await postJson('/api/recovery_scope/sync_lineage', { batch_code: batchCode })
}

export interface VersionRow {
  id: number
  归档卷: string
  归档版本: string
  来源批次: string
  分片编号: string
  成员范围: string
  校验凭据: string
  卷校验状态: string
  status: string
  登记时间: string
}

export async function fetchRecoveryVersions(
  volumeCode: string,
): Promise<{ items: VersionRow[]; total: number }> {
  const response = await request(`/api/recovery_scope/versions?volume_code=${encodeURIComponent(volumeCode)}`)
  if (!response.ok) throw new Error('卷版本回查失败')
  return await response.json()
}

export async function fetchRecoveryReplays(
  batchCode: string,
): Promise<{ items: import('@/domain/recovery_scope').ReplayFetch[]; total: number }> {
  const response = await request(`/api/recovery_scope/replays?batch_code=${encodeURIComponent(batchCode)}`)
  if (!response.ok) throw new Error('重放记录读取失败')
  return await response.json()
}
