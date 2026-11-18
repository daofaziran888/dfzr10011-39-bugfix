<template>
  <section class="page" data-module="logparse">
    <header class="page-head">
      <div>
        <h2>采集日志解析管理</h2>
        <p class="page-desc">维护采集日志的解析规则、字段提取与异常匹配；模板状态与解析规则同版本，关闭后不再产生新的结构化输出。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记日志模板</button>
        <button class="btn" type="button" @click="exportRows">导出采集日志解析清单</button>
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
          <th>当前版本</th>
          <th>可执行动作</th>
          <th>详情</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
          <td>{{ row.version ?? '—' }}</td>
          <td class="row-actions">
            <button
              v-for="action in actions"
              :key="action"
              class="link"
              type="button"
              :disabled="row.status === '已关闭'"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
          </td>
          <td><button class="link" type="button" @click="loadDetail(row)">查看</button></td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 3" class="empty-state">暂无采集日志解析数据，可先登记日志模板</td>
        </tr>
      </tbody>
    </table>

    <section v-if="detail" class="panel">
      <header class="panel-head">
        <h3>模板详情：{{ detail['模板编号'] }}（{{ detail['模板状态'] }} · {{ detail['当前版本'] }}）</h3>
        <button class="link" type="button" @click="detail = null">收起</button>
      </header>
      <p class="panel-note">
        解析规则：{{ detail['解析规则'] }} · 字段提取：{{ detail['字段提取'] }} · 异常匹配：{{ detail['异常匹配'] }}
      </p>
      <form class="filter-bar" @submit.prevent="submitCallback">
        <label class="filter-item" style="flex: 1">
          <span>原始日志</span>
          <input v-model="callbackRaw" placeholder="粘贴一条原始日志，按当前版本解析" />
        </label>
        <button class="btn primary" type="submit" :disabled="!canCallback">提交解析回调</button>
      </form>
      <p v-if="callbackMessage" class="panel-note">{{ callbackMessage }}</p>

      <h4>版本快照（状态与解析规则同版本）</h4>
      <table class="data-table">
        <thead>
          <tr><th>版本</th><th>当前状态</th><th>状态流转</th><th>解析规则</th><th>记录时间</th></tr>
        </thead>
        <tbody>
          <tr v-for="item in detail['版本快照'] ?? []" :key="`v-${item.id}`">
            <td>{{ item.version }}</td>
            <td>{{ item.status }}</td>
            <td>{{ (item.statuses ?? []).map((step: any) => step.status).join(' → ') || item.status }}</td>
            <td>{{ item.rule }}</td>
            <td>{{ item.recorded_at }}</td>
          </tr>
          <tr v-if="!(detail['版本快照'] ?? []).length">
            <td colspan="5" class="empty-state">暂无版本快照</td>
          </tr>
        </tbody>
      </table>

      <h4>最近回调</h4>
      <table class="data-table">
        <thead>
          <tr><th>回调编号</th><th>结果</th><th>模板版本</th><th>解析字段</th><th>记录时间</th></tr>
        </thead>
        <tbody>
          <tr v-for="item in detail['最近回调'] ?? []" :key="`cb-${item.id}`">
            <td>{{ item.callback_id }}</td>
            <td>{{ item.result }}</td>
            <td>{{ item.template_version }}</td>
            <td>{{ formatFields(item.fields, item.raw) }}</td>
            <td>{{ item.received_at }}</td>
          </tr>
          <tr v-if="!(detail['最近回调'] ?? []).length">
            <td colspan="5" class="empty-state">暂无解析回调</td>
          </tr>
        </tbody>
      </table>
    </section>

    <footer class="page-foot">
      <span>共 {{ total }} 条采集日志解析记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, any>

const ENDPOINT = '/api/logparse'
const columns = ["模板编号", "日志类型", "解析规则", "字段提取", "格式化输出", "异常匹配", "应用范围", "模板状态"]
const actions = ["启用模板", "暂停模板", "关闭模板"]
const statuses = ["草稿", "已启用", "已暂停", "已关闭"]

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = columns.slice(0, 3)
const detail = ref<Row | null>(null)
const callbackRaw = ref('')
const callbackMessage = ref('')

const stats = computed(() => [
  { label: '日志模板总数', value: total.value },
  { label: '已启用模板', value: rows.value.filter((row) => row.status === '已启用').length },
  { label: '已暂停模板', value: rows.value.filter((row) => row.status === '已暂停').length },
])
const canCallback = computed(() => !!detail.value && detail.value['模板状态'] !== '已关闭')

function resetFilters() {
  filters.value = {}
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  errorMessage.value = '日志模板登记入口尚未接入审批流'
}

function formatFields(fields: Record<string, string> | undefined, raw: string) {
  if (fields && Object.keys(fields).length) {
    return Object.entries(fields)
      .map(([key, value]) => `${key}=${value}`)
      .join(' · ')
  }
  // 解析失败时保留原始字段，供人工回查。
  return raw ? `原始字段：${raw}` : '—'
}

async function loadDetail(row: Row) {
  errorMessage.value = ''
  callbackMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}`)
    if (!response.ok) {
      throw new Error('日志模板详情读取失败')
    }
    detail.value = await response.json()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '日志模板详情读取失败'
  }
}

async function submitCallback() {
  if (!detail.value) {
    return
  }
  callbackMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${detail.value.id}/callbacks`, {
      method: 'POST',
      body: JSON.stringify({ values: { callback_id: `UI-${Date.now()}`, raw: callbackRaw.value } }),
    })
    const payload = await response.json()
    callbackMessage.value = payload.message ?? (payload.ok ? '回调已处理' : '回调失败')
    await reload()
    await loadDetail(detail.value)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '解析回调提交失败'
  }
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action } }),
    })
    const payload = await response.json()
    if (!payload.ok) {
      throw new Error(payload.message ?? '采集日志解析动作未生效，请稍后重试')
    }
    await reload()
    if (detail.value && detail.value.id === row.id) {
      await loadDetail(row)
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '采集日志解析操作失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams(filters.value as Record<string, string>).toString()
  try {
    const response = await request(`${ENDPOINT}?${query}`)
    if (!response.ok) {
      throw new Error('日志模板列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '采集日志解析列表读取失败'
  }
}

onMounted(reload)
</script>
