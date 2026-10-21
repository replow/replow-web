<script setup lang="ts">
import { computed, nextTick, onMounted, reactive, ref } from "vue";
import { ElMessageBox, type FormInstance, type FormRules } from "element-plus";
import {
  deleteAccessKey,
  getAccessKeys,
  getApiModules,
  registerAccessKey,
  regenerateAccessKeyChallenge,
  rotateAccessKey,
  verifyAccessKey,
  type AccessKeyItem,
  type AccessKeyRegistration,
  type AccessKeyVerifyResult,
  type ChallengeInstructions,
  type ModuleItem
} from "@/api/replow";
import { message } from "@/utils/message";

defineOptions({ name: "ReplowAccessKeys" });

const loading = ref(false);
const verifying = ref<number | null>(null);
const rows = ref<AccessKeyItem[]>([]);
const modules = ref<ModuleItem[]>([]);

const registerVisible = ref(false);
const registering = ref(false);
const formRef = ref<FormInstance>();
const form = reactive({
  site_url: "",
  module_slug: "oauth",
  email: ""
});
const rules: FormRules = {
  site_url: [
    { required: true, message: "请输入要注册的域名", trigger: "blur" },
    {
      validator: (_rule, value: string, callback) => {
        const raw = (value || "").trim();
        if (!raw) return callback();
        const candidate = raw.includes("://") ? raw : `https://${raw}`;
        try {
          const url = new URL(candidate);
          if (url.protocol !== "http:" && url.protocol !== "https:") {
            return callback(new Error("仅支持 http 或 https"));
          }
        } catch {
          return callback(new Error("请输入有效的域名，例如 account.example.com"));
        }
        callback();
      },
      trigger: "blur"
    }
  ],
  module_slug: [{ required: true, message: "请选择所属模块", trigger: "change" }]
};

/** One-time credential payload shown in the reveal drawer. */
const reveal = ref<{
  title: string;
  key: string;
  site_url: string;
  verification?: ChallengeInstructions;
  warning: string;
} | null>(null);
const revealVisible = ref(false);

const verifyDialogVisible = ref(false);
const verifyRecord = ref<AccessKeyItem | null>(null);
const verifyMethod = ref<"auto" | "dns" | "http">("auto");
const verifyResult = ref<AccessKeyVerifyResult | null>(null);
const verifyRunning = ref(false);

const pendingCount = computed(() => rows.value.filter(row => row.status === "pending").length);
const activeCount = computed(() => rows.value.filter(row => row.status === "active").length);

const statusMeta: Record<string, { label: string; type: "success" | "warning" | "danger" | "info" }> = {
  active: { label: "已激活", type: "success" },
  pending: { label: "待验证", type: "warning" },
  revoked: { label: "已吊销", type: "danger" }
};

const methodLabel: Record<string, string> = {
  dns: "DNS TXT",
  http: "文件校验"
};

const errorLabels: Record<string, string> = {
  site_url_required: "域名不能为空",
  site_url_not_allowed: "该域名不允许注册（回环地址 / 内网地址会被拒绝）",
  invalid_scheme: "仅支持 http 或 https",
  invalid_site_url: "域名格式不正确",
  email_required: "请填写联系邮箱",
  unknown_module: "所选模块不存在",
  access_key_not_found: "记录不存在或已被删除",
  verification_expired: "验证令牌已过期，请重新生成",
  verification_not_initialized: "验证令牌缺失，请重新生成",
  access_key_revoked: "该密钥已被吊销",
  access_key_already_active: "该域名已激活，无需重复操作",
  invalid_verification_method: "验证方式不合法",
  not_your_access_key: "无权操作该记录",
  invalid_status: "状态值不合法"
};

function errorText(error: any, fallback: string) {
  const detail = String(error?.response?.data?.detail ?? "");
  if (detail.startsWith("already_registered")) {
    const site = detail.split(":")[1] || "";
    return `该模块下已有激活中的域名${site ? `（${site}）` : ""}，请先轮换密钥或删除后再注册`;
  }
  return errorLabels[detail] || fallback;
}

function formatTime(value: string | null | undefined) {
  if (!value) return "—";
  const parsed = new Date(String(value).replace(" ", "T"));
  if (Number.isNaN(parsed.getTime())) return String(value);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${parsed.getFullYear()}-${pad(parsed.getMonth() + 1)}-${pad(parsed.getDate())} ${pad(parsed.getHours())}:${pad(parsed.getMinutes())}`;
}

function expiryHint(row: AccessKeyItem) {
  if (row.status !== "pending" || !row.verification_expires_at) return "";
  const parsed = new Date(String(row.verification_expires_at).replace(" ", "T"));
  if (Number.isNaN(parsed.getTime())) return "";
  const hours = Math.round((parsed.getTime() - Date.now()) / 3600000);
  if (hours < 0) return "验证令牌已过期";
  return `剩余 ${hours} 小时`;
}

async function load() {
  loading.value = true;
  try {
    const result = await getAccessKeys();
    rows.value = result.data || [];
  } catch (error) {
    message(errorText(error, "读取域名列表失败"), { type: "error" });
  } finally {
    loading.value = false;
  }
}

async function loadModules() {
  try {
    const result = await getApiModules();
    modules.value = (result.data || []).filter(item => item.enabled !== false);
    if (modules.value.length && !modules.value.some(item => item.slug === form.module_slug)) {
      form.module_slug = modules.value[0].slug;
    }
  } catch {
    // Non-fatal: the selector falls back to the default slug.
  }
}

function resetForm() {
  Object.assign(form, { site_url: "", module_slug: form.module_slug || "oauth", email: "" });
  nextTick(() => formRef.value?.clearValidate());
}

function openRegister() {
  resetForm();
  registerVisible.value = true;
}

async function submitRegister() {
  const valid = await formRef.value?.validate().catch(() => false);
  if (!valid) return;
  registering.value = true;
  try {
    const result = await registerAccessKey({
      site_url: form.site_url.trim(),
      module_slug: form.module_slug,
      email: form.email.trim() || undefined
    });
    registerVisible.value = false;
    const data: AccessKeyRegistration = result.data;
    openReveal({
      title: `「${data.host}」注册成功`,
      key: data.key,
      site_url: data.site_url,
      verification: data.verification,
      warning: "访问密钥仅显示这一次。请立即复制保存，关闭后无法再次查看（丢失只能轮换）。"
    });
    await load();
  } catch (error) {
    message(errorText(error, "域名注册失败"), { type: "error" });
  } finally {
    registering.value = false;
  }
}

function openReveal(payload: {
  title: string;
  key: string;
  site_url: string;
  verification?: ChallengeInstructions;
  warning: string;
}) {
  reveal.value = payload;
  revealVisible.value = true;
}

async function copy(text: string, label = "已复制") {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text);
    } else {
      const area = document.createElement("textarea");
      area.value = text;
      area.style.position = "fixed";
      area.style.opacity = "0";
      document.body.appendChild(area);
      area.select();
      document.execCommand("copy");
      document.body.removeChild(area);
    }
    message(label, { type: "success" });
  } catch {
    message("复制失败，请手动选择文本", { type: "error" });
  }
}

function openVerify(row: AccessKeyItem) {
  verifyRecord.value = row;
  verifyMethod.value = "auto";
  verifyResult.value = null;
  verifyDialogVisible.value = true;
}

async function runVerify() {
  if (!verifyRecord.value) return;
  verifyRunning.value = true;
  verifying.value = verifyRecord.value.id;
  try {
    const result = await verifyAccessKey(verifyRecord.value.id, verifyMethod.value);
    verifyResult.value = result.data;
    if (result.data.verified) {
      message(result.data.detail || "验证通过", { type: "success" });
      await load();
    } else {
      message(result.data.detail || "未检测到验证记录", { type: "warning" });
    }
  } catch (error) {
    message(errorText(error, "验证请求失败"), { type: "error" });
  } finally {
    verifyRunning.value = false;
    verifying.value = null;
  }
}

async function reissue(row: AccessKeyItem) {
  try {
    await ElMessageBox.confirm(
      `将为「${row.host}」重新生成验证令牌与访问密钥，旧密钥立即失效。`,
      "重新生成验证信息",
      { type: "warning", confirmButtonText: "重新生成", cancelButtonText: "取消" }
    );
    const result = await regenerateAccessKeyChallenge(row.id);
    const data: AccessKeyRegistration = result.data;
    openReveal({
      title: `「${data.site_url}」验证信息已重置`,
      key: data.key,
      site_url: data.site_url,
      verification: data.verification,
      warning: "这是新的访问密钥，仅显示这一次。请更新站点配置，旧的密钥已失效。"
    });
    await load();
  } catch (error: any) {
    if (error !== "cancel" && error !== "close") {
      message(errorText(error, "重新生成失败"), { type: "error" });
    }
  }
}

async function rotate(row: AccessKeyItem) {
  try {
    await ElMessageBox.confirm(
      `轮换后「${row.host}」的旧密钥立刻失效，使用旧密钥的调用会返回 401。`,
      "轮换访问密钥",
      { type: "warning", confirmButtonText: "确认轮换", cancelButtonText: "取消" }
    );
    const result = await rotateAccessKey(row.id);
    openReveal({
      title: `「${row.host}」密钥已轮换`,
      key: result.data.key,
      site_url: row.site_url,
      warning: "新密钥仅显示这一次。旧的密钥已立即失效，请尽快更新站点配置。"
    });
    await load();
  } catch (error: any) {
    if (error !== "cancel" && error !== "close") {
      message(errorText(error, "密钥轮换失败"), { type: "error" });
    }
  }
}

async function remove(row: AccessKeyItem) {
  try {
    await ElMessageBox.confirm(
      `确定删除「${row.site_url}」的注册记录吗？删除后该域名的调用将立即被拒绝。`,
      "删除注册记录",
      { type: "warning", confirmButtonText: "删除", cancelButtonText: "取消" }
    );
    await deleteAccessKey(row.id);
    message("注册记录已删除", { type: "success" });
    await load();
  } catch (error: any) {
    if (error !== "cancel" && error !== "close") {
      message(errorText(error, "删除失败"), { type: "error" });
    }
  }
}

async function copyVerifyFile(row: AccessKeyItem) {
  const url = `${row.site_url}/.well-known/replow-verify.txt`;
  await copy(url, "文件地址已复制");
}

onMounted(async () => {
  await Promise.all([loadModules(), load()]);
});
</script>

<template>
  <div class="page-wrap">
    <el-card shadow="never" class="intro-card">
      <div class="intro">
        <div class="intro-main">
          <h2>域名注册与访问密钥</h2>
          <p>
            注册你想要接入 Replow 的域名，系统会生成一把一次性访问密钥和一份所有权验证令牌。
            证明你控制该域名（DNS 或文件任选其一）后，密钥才会激活，之后才能用它调用对应模块的接口。
          </p>
        </div>
        <div class="intro-stats">
          <div class="stat">
            <span class="stat-num">{{ activeCount }}</span>
            <span class="stat-label">已激活</span>
          </div>
          <div class="stat">
            <span class="stat-num warn">{{ pendingCount }}</span>
            <span class="stat-label">待验证</span>
          </div>
          <div class="stat">
            <span class="stat-num">{{ rows.length }}</span>
            <span class="stat-label">全部</span>
          </div>
        </div>
      </div>
    </el-card>

    <el-card shadow="never">
      <template #header>
        <div class="toolbar">
          <div>
            <strong>我的域名</strong>
            <span class="muted">共 {{ rows.length }} 条</span>
          </div>
          <div class="toolbar-actions">
            <el-button :loading="loading" @click="load">刷新</el-button>
            <el-button type="primary" @click="openRegister">注册新域名</el-button>
          </div>
        </div>
      </template>

      <el-table v-loading="loading" :data="rows" stripe>
        <el-table-column prop="site_url" label="域名" min-width="220" show-overflow-tooltip>
          <template #default="scope">
            <div class="cell-domain">
              <span class="domain">{{ scope.row.site_url }}</span>
              <span class="module-tag">{{ scope.row.module_slug }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="170">
          <template #default="scope">
            <el-tag :type="(statusMeta[scope.row.status] || statusMeta.pending).type" effect="light">
              {{ (statusMeta[scope.row.status] || statusMeta.pending).label }}
            </el-tag>
            <div v-if="expiryHint(scope.row)" class="hint warn-text">{{ expiryHint(scope.row) }}</div>
          </template>
        </el-table-column>
        <el-table-column prop="key_prefix" label="密钥前缀" min-width="180" show-overflow-tooltip>
          <template #default="scope">
            <code class="key-prefix">{{ scope.row.key_prefix }}…</code>
          </template>
        </el-table-column>
        <el-table-column prop="email" label="联系邮箱" min-width="180" show-overflow-tooltip />
        <el-table-column label="验证时间" width="150">
          <template #default="scope">{{ formatTime(scope.row.verified_at) }}</template>
        </el-table-column>
        <el-table-column label="最近使用" width="150">
          <template #default="scope">{{ formatTime(scope.row.last_used_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="260" fixed="right">
          <template #default="scope">
            <el-button
              v-if="scope.row.status !== 'active'"
              link
              type="primary"
              :loading="verifying === scope.row.id"
              @click="openVerify(scope.row)"
            >
              验证
            </el-button>
            <el-button v-else link type="primary" @click="openVerify(scope.row)">查看</el-button>
            <el-button v-if="scope.row.status !== 'active'" link type="info" @click="reissue(scope.row)">
              重置令牌
            </el-button>
            <el-button v-else link type="warning" @click="rotate(scope.row)">轮换密钥</el-button>
            <el-button link type="danger" @click="remove(scope.row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>

      <el-empty v-if="!loading && rows.length === 0" description="还没有注册任何域名">
        <el-button type="primary" @click="openRegister">注册第一个域名</el-button>
      </el-empty>
    </el-card>

    <!-- register -->
    <el-dialog
      v-model="registerVisible"
      title="注册新域名"
      width="min(94vw, 620px)"
      destroy-on-close
    >
      <el-alert
        type="info"
        :closable="false"
        show-icon
        title="注册后需要验证域名所有权，通过后密钥才会生效。"
        description="每个模块下同一时间只允许一个激活域名，注册前请确认没有冲突的记录。"
        class="mb"
      />
      <el-form ref="formRef" :model="form" :rules="rules" label-position="top">
        <el-form-item label="域名 / 站点地址" prop="site_url">
          <el-input v-model="form.site_url" placeholder="例如 account.example.com 或 https://account.example.com" clearable />
        </el-form-item>
        <el-form-item label="所属模块" prop="module_slug">
          <el-select v-model="form.module_slug" class="full" placeholder="请选择模块">
            <el-option
              v-for="item in modules"
              :key="item.slug"
              :label="item.name ? `${item.name}（${item.slug}）` : item.slug"
              :value="item.slug"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="联系邮箱">
          <el-input v-model="form.email" placeholder="留空默认使用当前账号邮箱" clearable />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="registerVisible = false">取消</el-button>
        <el-button type="primary" :loading="registering" @click="submitRegister">
          注册并生成密钥
        </el-button>
      </template>
    </el-dialog>

    <!-- one-time key + challenge -->
    <el-drawer v-model="revealVisible" :title="reveal?.title || '访问密钥'" size="min(94vw, 640px)">
      <div v-if="reveal" class="reveal">
        <el-alert type="warning" :closable="false" show-icon :title="reveal.warning" class="mb" />

        <div class="block">
          <div class="block-title">访问密钥（Access Key）</div>
          <div class="copy-row">
            <code class="secret">{{ reveal.key }}</code>
            <el-button link type="primary" @click="copy(reveal.key, '访问密钥已复制')">复制</el-button>
          </div>
          <p class="tip">调用模块接口时，通过请求头 <code>X-Access-Key</code> 或 <code>Authorization: Bearer</code> 携带该密钥。</p>
        </div>

        <template v-if="reveal.verification">
          <div class="block">
            <div class="block-title">验证令牌</div>
            <div class="copy-row">
              <code class="token">{{ reveal.verification.token }}</code>
              <el-button link type="primary" @click="copy(reveal.verification!.token, '验证令牌已复制')">复制</el-button>
            </div>
          </div>

          <el-divider content-position="left">任选一种验证方式</el-divider>

          <div class="block">
            <div class="block-title">方式一 · DNS TXT 记录</div>
            <el-descriptions :column="1" border size="small">
              <el-descriptions-item label="记录类型">TXT</el-descriptions-item>
              <el-descriptions-item label="主机记录">
                <span class="mono">{{ reveal.verification.dns.name }}</span>
              </el-descriptions-item>
              <el-descriptions-item label="记录值">
                <span class="mono">{{ reveal.verification.dns.value }}</span>
              </el-descriptions-item>
            </el-descriptions>
            <el-button
              class="mt"
              link
              type="primary"
              @click="copy(reveal.verification!.dns.value, 'TXT 记录值已复制')"
            >
              复制记录值
            </el-button>
          </div>

          <div class="block">
            <div class="block-title">方式二 · 站点文件</div>
            <p class="tip">在站点根目录放置以下文件，内容为上面的验证令牌：</p>
            <div class="copy-row">
              <code class="mono">{{ reveal.site_url }}/.well-known/replow-verify.txt</code>
              <el-button
                link
                type="primary"
                @click="copy(`${reveal.site_url}/.well-known/replow-verify.txt`, '文件地址已复制')"
              >
                复制地址
              </el-button>
            </div>
          </div>
        </template>
      </div>
      <template #footer>
        <el-button @click="revealVisible = false">我已保存，关闭</el-button>
      </template>
    </el-drawer>

    <!-- verify -->
    <el-dialog
      v-model="verifyDialogVisible"
      title="域名所有权验证"
      width="min(94vw, 680px)"
      destroy-on-close
    >
      <div v-if="verifyRecord" class="verify-head">
        <div>
          <div class="verify-host">{{ verifyRecord.site_url }}</div>
          <div class="muted small">模块 {{ verifyRecord.module_slug }}</div>
        </div>
        <el-tag :type="(statusMeta[verifyRecord.status] || statusMeta.pending).type">
          {{ (statusMeta[verifyRecord.status] || statusMeta.pending).label }}
        </el-tag>
      </div>

      <template v-if="verifyRecord.status !== 'active'">
        <el-alert
          type="info"
          :closable="false"
          show-icon
          class="mb"
          title="验证会实时请求你的 DNS 与站点文件，请确保验证令牌已经发布。"
        />
        <div class="method-picker">
          <el-radio-group v-model="verifyMethod" size="large">
            <el-radio-button label="auto">自动（先 DNS 后文件）</el-radio-button>
            <el-radio-button label="dns">仅 DNS TXT</el-radio-button>
            <el-radio-button label="http">仅站点文件</el-radio-button>
          </el-radio-group>
          <el-button type="primary" :loading="verifyRunning" @click="runVerify">开始验证</el-button>
        </div>
        <el-button link type="primary" class="mt" @click="copyVerifyFile(verifyRecord)">
          复制文件校验地址
        </el-button>
      </template>

      <el-empty v-else description="该域名已验证通过，无需重复验证" />

      <div v-if="verifyResult" class="verify-result">
        <el-alert
          :type="verifyResult.verified ? 'success' : 'warning'"
          :closable="false"
          show-icon
          :title="verifyResult.detail"
        />
        <div v-if="verifyResult.checks?.length" class="checks">
          <div v-for="check in verifyResult.checks" :key="check.method" class="check">
            <div class="check-head">
              <span class="check-method">{{ methodLabel[check.method] || check.method }}</span>
              <el-tag :type="check.matched ? 'success' : 'info'" size="small">
                {{ check.matched ? "匹配" : "未匹配" }}
              </el-tag>
            </div>
            <div class="check-target mono">{{ check.target }}</div>
            <div class="check-detail">{{ check.detail }}</div>
          </div>
        </div>
      </div>
    </el-dialog>
  </div>
</template>

<style scoped>
.page-wrap { display: flex; flex-direction: column; gap: 14px; padding: 2px; }
.intro-card :deep(.el-card__body) { padding: 18px 20px; }
.intro { display: flex; align-items: center; justify-content: space-between; gap: 24px; }
.intro-main h2 { margin: 0 0 6px; font-size: 17px; font-weight: 600; }
.intro-main p { margin: 0; max-width: 640px; line-height: 1.7; color: var(--el-text-color-regular); font-size: 13px; }
.intro-stats { display: flex; gap: 22px; flex-shrink: 0; }
.stat { display: flex; flex-direction: column; align-items: center; min-width: 60px; }
.stat-num { font-size: 22px; font-weight: 600; line-height: 1.2; }
.stat-num.warn { color: var(--el-color-warning); }
.stat-label { font-size: 12px; color: var(--el-text-color-secondary); }
.toolbar { display: flex; align-items: center; justify-content: space-between; gap: 18px; }
.toolbar > div:first-child { display: flex; gap: 12px; align-items: baseline; }
.toolbar-actions { display: flex; gap: 10px; }
.muted { color: var(--el-text-color-secondary); font-size: 12px; }
.small { font-size: 12px; }
.full { width: 100%; }
.mb { margin-bottom: 14px; }
.mt { margin-top: 8px; }
.hint { margin-top: 4px; font-size: 12px; }
.warn-text { color: var(--el-color-warning); }
.cell-domain { display: flex; align-items: center; gap: 8px; }
.domain { font-weight: 500; }
.module-tag { padding: 1px 8px; border-radius: 10px; background: var(--el-fill-color); color: var(--el-text-color-secondary); font-size: 12px; }
.key-prefix, .mono { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px; }
.key-prefix { color: var(--el-text-color-regular); }
.reveal { display: flex; flex-direction: column; gap: 4px; }
.block { padding: 12px 0; }
.block-title { margin-bottom: 8px; font-weight: 600; font-size: 13px; }
.copy-row { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.secret, .token { flex: 1; min-width: 200px; padding: 8px 10px; border-radius: 6px; background: var(--el-fill-color-light); font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px; word-break: break-all; }
.token { color: var(--el-color-primary); }
.tip { margin: 8px 0 0; font-size: 12px; color: var(--el-text-color-secondary); line-height: 1.7; }
.verify-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 14px; }
.verify-host { font-weight: 600; }
.method-picker { display: flex; align-items: center; justify-content: space-between; gap: 14px; flex-wrap: wrap; }
.verify-result { margin-top: 16px; }
.checks { margin-top: 12px; display: flex; flex-direction: column; gap: 10px; }
.check { padding: 10px 12px; border: 1px solid var(--el-border-color-lighter); border-radius: 8px; }
.check-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 4px; }
.check-method { font-weight: 600; font-size: 13px; }
.check-target { color: var(--el-text-color-secondary); word-break: break-all; }
.check-detail { margin-top: 4px; font-size: 12px; color: var(--el-text-color-regular); }
@media (max-width: 700px) {
  .intro { flex-direction: column; align-items: flex-start; }
  .toolbar { align-items: stretch; flex-direction: column; }
  .toolbar-actions { justify-content: flex-end; }
}
</style>
