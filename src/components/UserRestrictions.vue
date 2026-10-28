<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { ElMessageBox } from "element-plus";
import {
  updateRestrictions,
  type UserItem,
  type Restriction
} from "@/api/replow";
import { localTime } from "@/utils/replow-time";
import { message } from "@/utils/message";

const props = defineProps<{ user: UserItem | null }>();
const emit = defineEmits<{ changed: [] }>();
const visible = defineModel<boolean>({ default: false });
const kind = ref("ban"),
  enabled = ref(true),
  reason = ref("");
const duration = ref("86400"),
  customUntil = ref<Date | null>(null);
const saving = ref(false),
  current = ref<Restriction[]>([]);
const labels: Record<string, string> = {
  ban: "封号",
  mute: "禁言",
  publish: "禁止发布文章"
};
const selected = computed(() =>
  current.value.find(item => item.kind === kind.value)
);
watch(
  () => props.user,
  user => {
    current.value = user?.restrictions || [];
    reason.value = "";
    kind.value = "ban";
    enabled.value = true;
    duration.value = "86400";
  }
);

async function save() {
  if (!props.user || !reason.value.trim())
    return message("请填写操作理由", { type: "warning" });
  let until: string | null = null;
  if (enabled.value && duration.value !== "forever") {
    const date =
      duration.value === "custom"
        ? customUntil.value
        : new Date(Date.now() + Number(duration.value) * 1000);
    if (!date || date.getTime() <= Date.now())
      return message("请选择未来的解除日期", { type: "warning" });
    until = date.toISOString();
  }
  try {
    await ElMessageBox.confirm(
      `${props.user.display_name || props.user.username}（@${props.user.username}，UID ${props.user.uid}）\n${enabled.value ? labels[kind.value] : "解除" + labels[kind.value]}\n${enabled.value ? "解除日期：" + (until ? localTime(until) : "永久，需管理员解除") + "\n" : ""}理由：${reason.value.trim()}\n系统将向用户发送邮件通知。`,
      "确认用户限制",
      {
        type: "warning",
        confirmButtonText: "确认执行",
        cancelButtonText: "取消",
        closeOnClickModal: false
      }
    );
  } catch {
    return;
  }
  saving.value = true;
  try {
    const result = await updateRestrictions(props.user.uid, {
      kind: kind.value,
      enabled: enabled.value,
      reason: reason.value.trim(),
      until,
      confirmed: true
    });
    current.value = result.restrictions;
    reason.value = "";
    message("操作已生效，邮件通知已加入发送队列", { type: "success" });
    emit("changed");
  } catch (error: unknown) {
    const detail = (error as { response?: { data?: { detail?: string } } })
      ?.response?.data?.detail;
    message(detail || "操作失败，请重试", { type: "error" });
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <el-dialog
    v-model="visible"
    title="封号、禁言与发文限制"
    width="min(94vw,680px)"
    :close-on-click-modal="false"
    :close-on-press-escape="!saving"
    :show-close="!saving"
  >
    <p>
      <strong>{{ user?.display_name || user?.username }}</strong> · @{{
        user?.username
      }}
      · UID {{ user?.uid }}
    </p>
    <el-alert
      v-for="item in current"
      :key="item.kind"
      type="warning"
      :closable="false"
      style="margin-bottom: 12px"
    >
      <template #title>{{ item.label }}：{{ item.reason }}</template>
      开始：{{ localTime(item.started_at) }}；解除：{{
        item.until ? localTime(item.until) : "永久（需管理员解除）"
      }}
    </el-alert>
    <el-form label-position="top">
      <el-form-item label="限制类型"
        ><el-select v-model="kind"
          ><el-option
            v-for="(label, key) in labels"
            :key="key"
            :label="label"
            :value="key" /></el-select
      ></el-form-item>
      <el-form-item label="操作"
        ><el-radio-group v-model="enabled"
          ><el-radio-button :value="true">施加 / 更新限制</el-radio-button
          ><el-radio-button :value="false" :disabled="!selected"
            >解除限制</el-radio-button
          ></el-radio-group
        ></el-form-item
      >
      <p>
        {{
          kind === "ban"
            ? "封号后立即撤销所有登录会话，用户不能登录。"
            : kind === "mute"
              ? "禁言期间不能发布或修改评论，保持登录。"
              : "限制期间不能创建、发布或修改文章，保持登录。"
        }}
      </p>
      <el-form-item v-if="enabled" label="限制时长"
        ><el-select v-model="duration"
          ><el-option label="1 小时" value="3600" /><el-option
            label="1 天"
            value="86400" /><el-option label="3 天" value="259200" /><el-option
            label="7 天"
            value="604800" /><el-option
            label="30 天"
            value="2592000" /><el-option
            label="永久"
            value="forever" /><el-option
            label="指定解除日期"
            value="custom" /></el-select
      ></el-form-item>
      <el-form-item
        v-if="enabled && duration === 'custom'"
        label="解除日期（当前设备时区）"
        ><el-date-picker
          v-model="customUntil"
          type="datetime"
          placeholder="选择解除日期和时间"
      /></el-form-item>
      <el-form-item label="理由（必填）"
        ><el-input
          v-model="reason"
          type="textarea"
          :rows="4"
          maxlength="1000"
          show-word-limit
          placeholder="向用户说明原因，邮件和账号提示中会展示"
      /></el-form-item>
    </el-form>
    <template #footer
      ><el-button :disabled="saving" @click="visible = false">关闭</el-button
      ><el-button type="danger" :loading="saving" @click="save">{{
        enabled ? "确认限制" : "确认解除"
      }}</el-button></template
    >
  </el-dialog>
</template>
