<template>
  <section class="page" data-module="recovery_scope">
    <header class="page-head">
      <div>
        <h2>恢复范围看板</h2>
        <p class="page-desc">
          按批次汇总归档卷分片的可恢复范围：每片标注归档版本、来源批次与重放采用的校验凭据，缺片单独记录。
        </p>
      </div>
    </header>

    <form class="filter-bar" @submit.prevent="reload">
      <label class="filter-item">
        <span>批次编号</span>
        <input v-model="batchCode" data-testid="batch-input" placeholder="按批次查询可恢复范围" />
      </label>
      <button class="btn primary" data-testid="query" type="submit">查询</button>
      <button class="btn" data-testid="sync-lineage" type="button" @click="syncLineage">关联传输血缘</button>
      <button class="btn" data-testid="replay" type="button" :disabled="replaying" @click="replay">{{ replaying ? '重放中…' : '发起重放' }}</button>
    </form>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <p v-if="board" class="diff-banner" data-testid="diff-banner">{{ diffText }}</p>

    <template v-if="board">
      <h3 class="section-title">覆盖概览</h3>
      <table class="data-table" data-testid="coverage-table">
        <thead>
          <tr>
            <th>归档卷</th><th>归档版本</th><th>卷校验状态</th><th>血缘链路</th>
            <th>分片总数</th><th>可恢复</th><th>缺片</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in board.coverage" :key="row.volume" :data-testid="`coverage-${row.volume}`">
            <td>{{ row.volume }}</td>
            <td>{{ row.version }}</td>
            <td>{{ row.verify_state }}</td>
            <td>{{ row.lineage || '—' }}</td>
            <td>{{ row.total }}</td>
            <td>{{ row.recoverable }}</td>
            <td>{{ row.missing }}</td>
          </tr>
          <tr v-if="!board.coverage.length">
            <td colspan="7" class="empty-state">该批次暂无归档卷覆盖记录</td>
          </tr>
        </tbody>
      </table>

      <h3 class="section-title">可恢复范围清单</h3>
      <table class="data-table" data-testid="recoverable-table">
        <thead>
          <tr>
            <th>分片编号</th><th>来源批次</th><th>归档卷</th><th>归档版本</th>
            <th>成员范围</th><th>校验凭据</th><th>血缘链路</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="piece in board.recoverable" :key="piece.id" :data-testid="`recoverable-${piece.id}`">
            <td>{{ piece.分片编号 }}</td>
            <td>{{ piece.来源批次 }}</td>
            <td>{{ piece.归档卷 }}</td>
            <td>{{ piece.归档版本 }}</td>
            <td>{{ piece.成员范围 }}</td>
            <td>{{ piece.校验凭据 }}</td>
            <td>{{ piece.血缘链路 || '—' }}</td>
          </tr>
          <tr v-if="!board.recoverable.length">
            <td colspan="7" class="empty-state">暂无可恢复分片</td>
          </tr>
        </tbody>
      </table>

      <h3 class="section-title">缺片记录</h3>
      <table class="data-table" data-testid="missing-table">
        <thead>
          <tr>
            <th>分片编号</th><th>来源批次</th><th>归档卷</th><th>归档版本</th>
            <th>成员范围</th><th>卷校验状态</th><th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="piece in board.missing" :key="piece.id" :data-testid="`missing-${piece.id}`">
            <td>{{ piece.分片编号 }}</td>
            <td>{{ piece.来源批次 }}</td>
            <td>{{ piece.归档卷 }}</td>
            <td>{{ piece.归档版本 }}</td>
            <td>{{ piece.成员范围 }}</td>
            <td>{{ piece.卷校验状态 }}</td>
            <td class="row-actions">
              <button class="link" type="button" :data-testid="`restore-${piece.id}`" @click="restore(piece.id)">
                补回缺片
              </button>
            </td>
          </tr>
          <tr v-if="!board.missing.length">
            <td colspan="7" class="empty-state">没有缺片，范围完整</td>
          </tr>
        </tbody>
      </table>

      <template v-if="board.superseded.length">
        <h3 class="section-title">已替换的旧版本分片（更换版本后仍可回查）</h3>
        <table class="data-table" data-testid="superseded-table">
          <thead>
            <tr>
              <th>分片编号</th><th>归档卷</th><th>归档版本</th><th>成员范围</th><th>校验凭据</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="piece in board.superseded" :key="piece.id">
              <td>{{ piece.分片编号 }}</td>
              <td>{{ piece.归档卷 }}</td>
              <td>{{ piece.归档版本 }}</td>
              <td>{{ piece.成员范围 }}</td>
              <td>{{ piece.校验凭据 || '—' }}</td>
            </tr>
          </tbody>
        </table>
      </template>

      <h3 class="section-title">卷版本回查</h3>
      <form class="filter-bar" @submit.prevent="loadVersions">
        <label class="filter-item">
          <span>归档卷</span>
          <input v-model="versionVolume" data-testid="version-volume-input" placeholder="回查先前用过的卷版本" />
        </label>
        <button class="btn" data-testid="version-query" type="submit">回查版本</button>
      </form>
      <table v-if="versions.length" class="data-table" data-testid="versions-table">
        <thead>
          <tr>
            <th>归档版本</th><th>来源批次</th><th>分片编号</th><th>成员范围</th>
            <th>校验凭据</th><th>当前状态</th><th>登记时间</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in versions" :key="row.id">
            <td>{{ row.归档版本 }}</td>
            <td>{{ row.来源批次 }}</td>
            <td>{{ row.分片编号 }}</td>
            <td>{{ row.成员范围 }}</td>
            <td>{{ row.校验凭据 || '—' }}</td>
            <td>{{ row.status }}</td>
            <td>{{ row.登记时间 || '—' }}</td>
          </tr>
        </tbody>
      </table>

      <template v-if="replayResult">
        <h3 class="section-title">本次重放核对结果</h3>
        <table class="data-table" data-testid="replay-result-table">
          <thead>
            <tr>
              <th>分片编号</th><th>成员范围</th><th>来源卷</th><th>归档版本</th>
              <th>校验凭据</th><th>取回条数</th><th>核对</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="piece in replayResult.pieces" :key="piece.piece_code">
              <td>{{ piece.piece_code }}</td>
              <td>{{ piece.member_range }}</td>
              <td>{{ piece.volume }}</td>
              <td>{{ piece.version }}</td>
              <td>{{ piece.credential }}</td>
              <td>{{ piece.records }}</td>
              <td>{{ piece.verified ? '通过' : '不符' }}</td>
            </tr>
          </tbody>
        </table>
      </template>

      <h3 class="section-title">重放取片记录</h3>
      <table class="data-table" data-testid="replay-history-table">
        <thead>
          <tr>
            <th>重放编号</th><th>分片编号</th><th>来源卷</th><th>归档版本</th>
            <th>校验凭据</th><th>取回条数</th><th>核对</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(rec, idx) in replayHistory" :key="`${rec.replay_code}-${idx}`">
            <td>{{ rec.replay_code }}</td>
            <td>{{ rec.piece_code }}</td>
            <td>{{ rec.volume }}</td>
            <td>{{ rec.version }}</td>
            <td>{{ rec.credential }}</td>
            <td>{{ rec.records }}</td>
            <td>{{ rec.verified ? '通过' : '不符' }}</td>
          </tr>
          <tr v-if="!replayHistory.length">
            <td colspan="7" class="empty-state">尚未发起过重放</td>
          </tr>
        </tbody>
      </table>
    </template>

    <footer class="page-foot">
      <span v-if="board">批次 {{ board.batch_code }}：可恢复 {{ board.recoverable.length }} 片，缺片 {{ board.missing.length }} 片</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
      <span v-if="notice" class="notice-text">{{ notice }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import {
  fetchRecoveryDashboard,
  fetchRecoveryReplays,
  fetchRecoveryVersions,
  replayRecoveryBatch,
  restoreRecoveryPiece,
  syncRecoveryLineage,
  type VersionRow,
} from '@/api/backend-service'
import {
  diffAgainstLastReplay,
  summarizeBoard,
  type RecoveryDashboard,
  type ReplayFetch,
  type ReplayResult,
} from '@/domain/recovery_scope'

const DEFAULT_BATCH = 'BATC-2024-11'

const batchCode = ref(DEFAULT_BATCH)
const board = ref<RecoveryDashboard | null>(null)
const replayResult = ref<ReplayResult | null>(null)
const replayHistory = ref<ReplayFetch[]>([])
const versions = ref<VersionRow[]>([])
const versionVolume = ref('')
const replaying = ref(false)
const errorMessage = ref('')
const notice = ref('')

const stats = computed(() => (board.value ? summarizeBoard(board.value) : []))
const diffText = computed(() => (board.value ? diffAgainstLastReplay(board.value) : ''))

async function reload() {
  errorMessage.value = ''
  const code = batchCode.value.trim()
  if (!code) {
    errorMessage.value = '请先填写批次编号'
    return
  }
  try {
    board.value = await fetchRecoveryDashboard(code)
    const replays = await fetchRecoveryReplays(code)
    replayHistory.value = replays.items
    if (board.value.coverage.length && !versionVolume.value) {
      versionVolume.value = board.value.coverage[0].volume
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '看板读取失败'
  }
}

async function syncLineage() {
  errorMessage.value = ''
  notice.value = ''
  try {
    const result = await syncRecoveryLineage(batchCode.value.trim())
    notice.value = result.linked > 0
      ? `已把血缘链路 ${result.lineage_code} 关联到 ${result.linked} 片`
      : '没有需要补登血缘的分片'
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '血缘关联失败'
  }
}

async function replay() {
  replaying.value = true
  errorMessage.value = ''
  notice.value = ''
  try {
    replayResult.value = await replayRecoveryBatch(batchCode.value.trim())
    notice.value = `重放完成：取回 ${replayResult.value.pieces.length} 片共 ${replayResult.value.total_records} 条，来源卷 ${replayResult.value.volumes_used.join('、')}`
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '重放失败'
  } finally {
    replaying.value = false
  }
}

async function restore(entryId: number) {
  errorMessage.value = ''
  notice.value = ''
  try {
    await restoreRecoveryPiece(entryId)
    notice.value = '缺片已补回，可重新查询可恢复范围'
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '补回缺片失败'
  }
}

async function loadVersions() {
  errorMessage.value = ''
  const volume = versionVolume.value.trim()
  if (!volume) {
    errorMessage.value = '请先填写归档卷'
    return
  }
  try {
    const result = await fetchRecoveryVersions(volume)
    versions.value = result.items
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '版本回查失败'
  }
}

onMounted(reload)
</script>

<style scoped>
.section-title {
  font-size: 14px;
  margin: 16px 0 8px;
}
.diff-banner {
  background: #eef4ff;
  border: 1px solid #c7dbff;
  border-radius: 6px;
  padding: 8px 12px;
  font-size: 13px;
  color: #1f3b73;
}
.notice-text {
  color: #15803d;
}
</style>
