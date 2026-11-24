/** 恢复范围看板的纯前端领域逻辑：看板数据形状与可恢复范围的对比口径。 */

export interface RecoveryPiece {
  id: number
  看板编号: string
  来源批次: string
  归档卷: string
  归档版本: string
  分片编号: string
  成员范围: string
  校验凭据: string
  血缘链路: string
  卷校验状态: string
  status: string
  登记时间?: string
}

export interface CoverageRow {
  volume: string
  version: string
  verify_state: string
  lineage: string
  total: number
  recoverable: number
  missing: number
  pieces: string[]
}

export interface LineageInfo {
  chains: Record<string, unknown>[]
  files: Record<string, unknown>[]
  active_code: string
}

export interface LastReplay {
  replay_code: string
  at: number
  volumes: string[]
  pieces: number
  all_verified: boolean
}

export interface RecoveryDashboard {
  batch_code: string
  coverage: CoverageRow[]
  recoverable: RecoveryPiece[]
  missing: RecoveryPiece[]
  superseded: RecoveryPiece[]
  lineage: LineageInfo
  last_replay: LastReplay | null
}

export interface ReplayFetch {
  replay_code: string
  batch_code: string
  piece_code: string
  member_range: string
  volume: string
  version: string
  credential: string
  records: number
  verified: boolean
  at: number
}

export interface ReplayResult {
  replay_code: string
  batch_code: string
  pieces: ReplayFetch[]
  volumes_used: string[]
  total_records: number
  all_verified: boolean
  artifact_path: string
  error?: string
}

/** 看板顶部统计卡：可恢复片、缺片、覆盖卷数、上次重放引用的卷数。 */
export function summarizeBoard(board: RecoveryDashboard): { label: string; value: number }[] {
  return [
    { label: '可恢复分片', value: board.recoverable.length },
    { label: '缺片待补', value: board.missing.length },
    { label: '覆盖归档卷', value: board.coverage.length },
    { label: '上次重放引用卷', value: board.last_replay ? board.last_replay.volumes.length : 0 },
  ]
}

/**
 * 比较当前可取回范围与上一次重放引用的卷：
 * 补回缺片或更换版本后再查询，用这段说明告诉值班同学哪些片是上次重放之后新可恢复的。
 */
export function diffAgainstLastReplay(board: RecoveryDashboard): string {
  if (!board.last_replay) {
    return board.recoverable.length > 0
      ? `当前可恢复 ${board.recoverable.length} 片，尚未发起过重放。`
      : '当前没有可恢复分片，也尚未发起过重放。'
  }
  const replay = board.last_replay
  const replayVolumes = new Set(replay.volumes)
  const newPieces = board.recoverable.filter((piece) => !replayVolumes.has(piece.归档卷))
  const parts = [
    `上一次重放 ${replay.replay_code} 取回 ${replay.pieces} 片，引用卷：${replay.volumes.join('、') || '无'}。`,
    `当前可取回 ${board.recoverable.length} 片。`,
  ]
  if (newPieces.length > 0) {
    parts.push(
      `其中 ${newPieces.length} 片来自上次重放未引用的卷：${newPieces.map((p) => `${p.分片编号}(${p.归档卷})`).join('、')}。`,
    )
  } else {
    parts.push('可取回分片的来源卷与上次重放一致。')
  }
  if (board.missing.length > 0) {
    parts.push(`仍有 ${board.missing.length} 片缺片待补。`)
  }
  return parts.join('')
}
