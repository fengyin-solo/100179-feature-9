<template>
  <section class="page" data-module="crane">
    <header class="page-head">
      <div>
        <h2>起重机械管理</h2>
        <p class="page-desc">维护起重机械，围绕机械编号、机械名称、额定起重量、跨度规格做登记、筛选与状态流转。</p>
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
      <label class="filter-item">
        <span>到期提醒阈值（天）</span>
        <input v-model="thresholdInput" type="number" min="0" max="365" step="1" />
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn" type="button" @click="applyThreshold">更新阈值并重算</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table v-if="groups.length" class="data-table">
      <thead>
        <tr>
          <th>额定起重量</th><th>跨度规格</th><th>机械数</th>
          <th>临近</th><th>超期</th><th>检验日缺失</th><th>待处理</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="group in groups" :key="`${group.额定起重量}-${group.跨度规格}`">
          <td>{{ group.额定起重量 || '—' }}</td>
          <td>{{ group.跨度规格 || '—' }}</td>
          <td>{{ group.总数 }}</td>
          <td>{{ group.临近 }}</td>
          <td>{{ group.超期 }}</td>
          <td>{{ group.缺失 }}</td>
          <td>{{ group.待处理 }}</td>
        </tr>
      </tbody>
    </table>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>检验提醒</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
          <td>
            <span class="tag" :class="tagClass(row.reminder_status)">{{ row.检验提醒 ?? '—' }}</span>
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
          <td :colspan="columns.length + 2" class="empty-state">暂无起重机械数据，可先登记起重机械</td>
        </tr>
      </tbody>
    </table>

    <table v-if="history.length" class="data-table">
      <thead>
        <tr><th>评估时间</th><th>当时阈值（天）</th><th>临近</th><th>超期</th><th>待处理</th></tr>
      </thead>
      <tbody>
        <tr v-for="(record, index) in history" :key="index">
          <td>{{ record.evaluated_at }}</td>
          <td>{{ record.threshold_days }}</td>
          <td>{{ record.summary.临近 }}</td>
          <td>{{ record.summary.超期 }}</td>
          <td>{{ record.summary.待处理 }}</td>
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
import { computed, onMounted, ref } from 'vue'

import { fetchJson, request } from '@/api/client'

type Row = Record<string, string | number | null> & {
  reminder_status?: string
  reminder_days?: number | null
}

type ReminderSummary = {
  临近: number
  超期: number
  缺失: number
  正常: number
  待处理: number
  状态统计: Record<string, number>
}

type ReminderGroup = {
  额定起重量: string
  跨度规格: string
  总数: number
  临近: number
  超期: number
  缺失: number
  正常: number
  待处理: number
}

type ReminderSnapshot = {
  threshold_days: number
  evaluated_on: string
  evaluated_at: string
  summary: ReminderSummary
  groups: ReminderGroup[]
}

type ReminderHistory = {
  evaluated_at: string
  threshold_days: number
  summary: ReminderSummary
}

const ENDPOINT = '/api/crane'
const columns = ["机械编号", "机械名称", "额定起重量", "跨度规格", "使用场所", "投用日期", "下次检验日", "机械状态"]
const actions = ["办理投用", "安排检修", "报废机械"]
const statuses = ["待投用", "在用运行", "停机检修", "已报废"]

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = columns.slice(0, 3)
const snapshot = ref<ReminderSnapshot | null>(null)
const groups = ref<ReminderGroup[]>([])
const history = ref<ReminderHistory[]>([])
const thresholdInput = ref('30')

const stats = computed(() => {
  const summary = snapshot.value?.summary
  return [
    { label: '在用起重机械', value: summary?.状态统计?.['在用运行'] ?? 0 },
    { label: '停机检修', value: summary?.状态统计?.['停机检修'] ?? 0 },
    { label: '临近检验', value: summary?.临近 ?? 0 },
    { label: '已超期', value: summary?.超期 ?? 0 },
  ]
})

function tagClass(status?: string) {
  switch (status) {
    case '超期':
      return 'tag-danger'
    case '临近':
      return 'tag-warn'
    case '缺失':
      return 'tag-muted'
    default:
      return 'tag-ok'
  }
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

async function applyThreshold() {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/reminders/threshold`, {
      method: 'PUT',
      body: JSON.stringify({ values: { threshold_days: thresholdInput.value } }),
    })
    const payload = await response.json()
    if (!payload.ok) {
      throw new Error(payload.message || '提醒阈值未生效，请检查输入')
    }
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '提醒阈值更新失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams(filters.value as Record<string, string>).toString()
  try {
    const [listPayload, reminderPayload, historyPayload] = await Promise.all([
      fetchJson<{ items: Row[]; total: number }>(`${ENDPOINT}?${query}`),
      fetchJson<ReminderSnapshot>(`${ENDPOINT}/reminders`),
      fetchJson<{ items: ReminderHistory[] }>(`${ENDPOINT}/reminders/history`),
    ])
    rows.value = listPayload.items ?? []
    total.value = listPayload.total ?? rows.value.length
    snapshot.value = reminderPayload
    groups.value = reminderPayload.groups ?? []
    thresholdInput.value = String(reminderPayload.threshold_days ?? 30)
    history.value = (historyPayload.items ?? []).slice(-5).reverse()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '起重机械列表读取失败'
  }
}

onMounted(reload)
</script>
