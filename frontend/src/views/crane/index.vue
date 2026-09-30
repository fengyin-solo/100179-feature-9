<template>
  <section class="page" data-module="crane">
    <header class="page-head">
      <div>
        <h2>起重机械管理</h2>
        <p class="page-desc">维护起重机械，围绕机械编号、机械名称、额定起重量、跨度规格做登记、筛选与状态流转；到期提醒按检验口径自动标记。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记起重机械</button>
        <button class="btn" type="button" @click="exportRows">导出起重机械清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label v-for="field in filterFields" :key="field" class="filter-item">
        <span>{{ field }}</span>
        <input v-model="filters[field]" :placeholder="`按${field}检索`" />
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">
            <span v-if="column === '到期提醒'" class="tag" :class="tagClass(row[column])">
              {{ row[column] ?? '—' }}
            </span>
            <span v-else-if="column === '剩余天数'">{{ formatRemaining(row[column]) }}</span>
            <template v-else>{{ row[column] ?? '—' }}</template>
          </td>
          <td class="row-actions">
            <button
              v-for="action in actions"
              :key="action"
              class="link"
              type="button"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无起重机械数据，可先登记起重机械</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条起重机械记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { fetchJson, request } from '@/api/client'

type Row = Record<string, string | number | null>
type LedgerSummary = { summary: Record<string, number> }

const ENDPOINT = '/api/crane'
const columns = ["机械编号", "机械名称", "额定起重量", "跨度规格", "使用场所", "投用日期", "下次检验日", "机械状态", "检验口径", "剩余天数", "到期提醒"]
const actions = ["办理投用", "安排检修", "报废机械"]
const statuses = ["待投用", "在用运行", "停机检修", "已报废"]

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = columns.slice(0, 3)
// 统计卡与起重机械台账共用同一份判定汇总，刷新后口径一致
const stats = ref([
  { label: '待处理（临近+超期）', value: 0 },
  { label: '临近检验', value: 0 },
  { label: '已超期', value: 0 },
  { label: '检验日缺失', value: 0 },
])

function tagClass(label: Row[string]) {
  switch (label) {
    case '超期':
      return 'tag-overdue'
    case '临近':
      return 'tag-near'
    case '缺失':
      return 'tag-missing'
    default:
      return 'tag-normal'
  }
}

function formatRemaining(days: Row[string]) {
  if (days === null || days === undefined || days === '') return '—'
  const value = Number(days)
  if (Number.isNaN(value)) return '—'
  return value < 0 ? `已超期 ${-value} 天` : `剩 ${value} 天`
}

function resetFilters() {
  filters.value = {}
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  errorMessage.value = '起重机械登记入口尚未接入审批流'
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ action }),
    })
    if (!response.ok) {
      throw new Error('起重机械动作未生效，请稍后重试')
    }
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '起重机械操作失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams(filters.value as Record<string, string>).toString()
  try {
    const [response, ledger] = await Promise.all([
      request(`${ENDPOINT}?${query}`),
      fetchJson<LedgerSummary>(`${ENDPOINT}/ledger`),
    ])
    if (!response.ok) {
      throw new Error('起重机械列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
    const summary = ledger.summary ?? {}
    stats.value = [
      { label: '待处理（临近+超期）', value: summary['待处理'] ?? 0 },
      { label: '临近检验', value: summary['临近'] ?? 0 },
      { label: '已超期', value: summary['超期'] ?? 0 },
      { label: '检验日缺失', value: summary['缺失'] ?? 0 },
    ]
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '起重机械列表读取失败'
  }
}

onMounted(reload)
</script>
