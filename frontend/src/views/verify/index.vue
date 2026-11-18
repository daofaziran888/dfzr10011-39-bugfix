<template>
  <section class="page" data-module="verify">
    <header class="page-head">
      <div>
        <h2>采集结果校验管理</h2>
        <p class="page-desc">维护采集结果的校验类型与不通过处理；读取异常日志清单，核对解析字段所属模板版本。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记校验规则</button>
        <button class="btn" type="button" @click="exportRows">导出采集结果校验清单</button>
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
          <th>绑定日志模板</th>
          <th>可执行动作</th>
          <th>核对</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
          <td>{{ row['绑定模板编号'] ?? '—' }}</td>
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
          <td><button class="link" type="button" @click="loadDetail(row)">查看</button></td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 3" class="empty-state">暂无采集结果校验数据，可先登记校验规则</td>
        </tr>
      </tbody>
    </table>

    <section v-if="detail" class="panel">
      <header class="panel-head">
        <h3>校验详情：{{ detail['规则编号'] }}（{{ detail['规则状态'] }}）</h3>
        <button class="link" type="button" @click="detail = null">收起</button>
      </header>

      <h4>结构化结果批次（核对解析字段与模板版本）</h4>
      <table class="data-table">
        <thead>
          <tr><th>模板版本</th><th>模板编号</th><th>模板状态</th><th>解析字段</th><th>记录时间</th></tr>
        </thead>
        <tbody>
          <tr v-for="batch in detail['结构化结果批次'] ?? []" :key="batch.template_version">
            <template v-for="item in batch.items" :key="item.callback_id">
              <tr>
                <td>{{ batch.template_version }}</td>
                <td>{{ batch.template_code }}</td>
                <td>{{ batch.closed ? '已关闭（仅回放最后一批完整结果）' : '已启用' }}</td>
                <td>{{ formatFields(item.fields) }}</td>
                <td>{{ item.received_at }}</td>
              </tr>
            </template>
          </tr>
          <tr v-if="!(detail['结构化结果批次'] ?? []).length">
            <td colspan="5" class="empty-state">暂无结构化结果</td>
          </tr>
        </tbody>
      </table>

      <h4>异常日志清单</h4>
      <table class="data-table">
        <thead>
          <tr><th>回调编号</th><th>异常原因</th><th>模板版本</th><th>解析字段</th><th>原始字段</th><th>记录时间</th></tr>
        </thead>
        <tbody>
          <tr v-for="item in detail['异常日志清单'] ?? []" :key="`ex-${item.id}`">
            <td>{{ item.callback_id }}</td>
            <td>{{ item['异常原因'] }}</td>
            <td>{{ item['模板版本'] }}</td>
            <td>{{ formatFields(item['解析字段']) }}</td>
            <td>{{ item['原始字段'] || '—' }}</td>
            <td>{{ item['记录时间'] }}</td>
          </tr>
          <tr v-if="!(detail['异常日志清单'] ?? []).length">
            <td colspan="6" class="empty-state">暂无异常日志</td>
          </tr>
        </tbody>
      </table>

      <h4>修复日志模板动作核对清单</h4>
      <table class="data-table">
        <thead>
          <tr><th>依据</th><th>类型</th><th>模板编号</th><th>模板版本</th><th>当前版本</th><th>版本一致</th><th>状态</th></tr>
        </thead>
        <tbody>
          <tr v-for="item in detail['核对清单'] ?? []" :key="`ck-${item.kind}-${item.source_id}`">
            <td>{{ item['依据'] }}</td>
            <td>{{ item.kind }}</td>
            <td>{{ item['模板编号'] }}</td>
            <td>{{ item['模板版本'] }}</td>
            <td>{{ item['当前模板版本'] }}</td>
            <td>{{ item['版本一致'] ? '一致' : '不一致' }}</td>
            <td>{{ item.status }}</td>
          </tr>
          <tr v-if="!(detail['核对清单'] ?? []).length">
            <td colspan="7" class="empty-state">暂无核对依据</td>
          </tr>
        </tbody>
      </table>
    </section>

    <footer class="page-foot">
      <span>共 {{ total }} 条采集结果校验记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, any>

const ENDPOINT = '/api/verify'
const columns = ["规则编号", "采集计划", "校验类型", "校验字段", "阈值配置", "不通过动作", "最近校验", "规则状态"]
const actions = ["启用校验", "暂停校验", "关闭校验"]
const statuses = ["草稿", "已启用", "已暂停", "已关闭"]

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = columns.slice(0, 3)
const detail = ref<Row | null>(null)

const stats = computed(() => [
  { label: '校验规则总数', value: total.value },
  { label: '已启用校验', value: rows.value.filter((row) => row.status === '已启用').length },
  { label: '已暂停校验', value: rows.value.filter((row) => row.status === '已暂停').length },
])

function resetFilters() {
  filters.value = {}
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  errorMessage.value = '校验规则登记入口尚未接入审批流'
}

function formatFields(fields: Record<string, string> | undefined) {
  if (!fields || !Object.keys(fields).length) {
    return '—'
  }
  return Object.entries(fields)
    .map(([key, value]) => `${key}=${value}`)
    .join(' · ')
}

async function loadDetail(row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}`)
    if (!response.ok) {
      throw new Error('校验规则详情读取失败')
    }
    detail.value = await response.json()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '校验规则详情读取失败'
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
      throw new Error(payload.message ?? '采集结果校验动作未生效，请稍后重试')
    }
    await reload()
    if (detail.value && detail.value.id === row.id) {
      await loadDetail(row)
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '采集结果校验操作失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams(filters.value as Record<string, string>).toString()
  try {
    const response = await request(`${ENDPOINT}?${query}`)
    if (!response.ok) {
      throw new Error('校验规则列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '采集结果校验列表读取失败'
  }
}

onMounted(reload)
</script>
