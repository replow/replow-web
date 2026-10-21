<script setup lang="ts">
import { onMounted, ref } from "vue";
import { ElMessageBox } from "element-plus";
import {
  getDeviceSessions,
  revokeDeviceSession,
  revokeOtherSessions,
  type DeviceSession
} from "@/api/replow";
import { hydrateReplowSession, setToken } from "@/utils/auth";
import { useUserStoreHook } from "@/store/modules/user";
import { localTime } from "@/utils/replow-time";
import { message } from "@/utils/message";
const rows = ref<DeviceSession[]>([]),
  loading = ref(false),
  busy = ref("");
function device(ua: string) {
  const os = /Android/.test(ua)
    ? "Android"
    : /iPhone|iPad/.test(ua)
      ? "iOS"
      : /Windows/.test(ua)
        ? "Windows"
        : /Macintosh/.test(ua)
          ? "macOS"
          : /Linux/.test(ua)
            ? "Linux"
            : "设备";
  const browser = /Edg\//.test(ua)
    ? "Edge"
    : /Firefox\//.test(ua)
      ? "Firefox"
      : /Chrome\//.test(ua)
        ? "Chrome"
        : /Safari\//.test(ua)
          ? "Safari"
          : "浏览器";
  return os + " · " + browser;
}
async function load() {
  loading.value = true;
  try {
    rows.value = (await getDeviceSessions()).items;
  } catch {
    message("登录设备读取失败", { type: "error" });
  } finally {
    loading.value = false;
  }
}
async function revoke(row: DeviceSession) {
  try {
    await ElMessageBox.confirm(
      row.is_current
        ? "此操作会退出当前设备。"
        : "此设备将立即退出，访问令牌与共享登录会话同时失效。",
      "退出设备",
      {
        type: "warning",
        confirmButtonText: "确认退出",
        cancelButtonText: "取消"
      }
    );
    busy.value = row.id;
    const result = await revokeDeviceSession(row.id);
    if (result.current_revoked) useUserStoreHook().logOut();
    else {
      await load();
      message("设备已退出", { type: "success" });
    }
  } catch (e: any) {
    if (e !== "cancel" && e !== "close")
      message("退出设备失败", { type: "error" });
  } finally {
    busy.value = "";
  }
}
async function others() {
  try {
    await ElMessageBox.confirm(
      "保留当前设备，退出此账号的所有其他设备；以前未登记的旧登录也会失效。",
      "退出其他设备",
      {
        type: "warning",
        confirmButtonText: "确认退出其他设备",
        cancelButtonText: "取消"
      }
    );
    busy.value = "others";
    const result = await revokeOtherSessions();
    setToken(result.data);
    await load();
    message("其他设备已退出", { type: "success" });
  } catch (e: any) {
    if (e !== "cancel" && e !== "close")
      message("操作失败，请刷新后重试", { type: "error" });
  } finally {
    busy.value = "";
  }
}
onMounted(async () => {
  await hydrateReplowSession();
  await load();
});
</script>
<template>
  <el-card shadow="never" class="device-card">
    <template #header
      ><div class="session-toolbar">
        <strong>登录设备</strong>
        <div>
          <el-button :loading="loading" :disabled="!!busy" @click="load"
            >刷新设备</el-button
          ><el-button
            type="danger"
            plain
            :loading="busy === 'others'"
            :disabled="!!busy && busy !== 'others'"
            @click="others"
            >退出其他设备</el-button
          >
        </div>
      </div></template
    >
    <p class="muted">
      同一浏览器在主站、后台和账号中心共享一个登录会话。时间为北京时间。
    </p>
    <div v-loading="loading" class="device-list">
      <article v-for="row in rows" :key="row.id" class="device-row">
        <div>
          <strong>{{ device(row.user_agent) }}</strong
          ><el-tag v-if="row.is_current" size="small">当前设备</el-tag>
          <p>{{ row.ip_address || "未知 IP" }}</p>
          <small
            >最近活动 {{ localTime(row.last_seen_at) }} · 首次登录
            {{ localTime(row.created_at) }}</small
          >
          <details>
            <summary>设备信息</summary>
            <p class="agent">{{ row.user_agent || "未提供浏览器信息" }}</p>
          </details>
        </div>
        <el-button
          :loading="busy === row.id"
          :disabled="!!busy && busy !== row.id"
          @click="revoke(row)"
          >{{ row.is_current ? "退出当前设备" : "退出设备" }}</el-button
        >
      </article>
      <el-empty
        v-if="!loading && !rows.length"
        description="暂无设备记录，重新登录后将登记当前设备"
      />
    </div>
  </el-card>
</template>
<style scoped>
.device-card {
  margin-top: 18px;
}
.session-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}
.session-toolbar > div {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
.session-toolbar .el-button + .el-button {
  margin-left: 0;
}
.device-list {
  display: grid;
  gap: 12px;
}
.device-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 16px;
  border: 1px solid var(--el-border-color-light);
  border-radius: 12px;
}
.device-row > div {
  min-width: 0;
}
.device-row .el-tag {
  margin-left: 10px;
}
.device-row p {
  font-size: 13px;
  margin: 7px 0;
}
.muted,
.device-row small,
.device-row summary {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.agent {
  overflow-wrap: anywhere;
}
details {
  margin-top: 8px;
}
@media (max-width: 600px) {
  .device-row {
    align-items: flex-start;
    flex-direction: column;
  }
  .device-row > .el-button {
    align-self: flex-end;
  }
  .session-toolbar > div {
    width: 100%;
  }
}
</style>
