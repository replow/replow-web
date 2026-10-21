<script setup lang="ts">
defineOptions({ inheritAttrs: false });

defineProps<{
  id: string;
  label: string;
  modelValue: string;
}>();

const emit = defineEmits<{
  "update:modelValue": [value: string];
}>();
</script>

<template>
  <div
    class="floating-login-field"
    :class="{ 'has-value': modelValue.length > 0 }"
  >
    <el-input
      v-bind="$attrs"
      :id="id"
      :model-value="modelValue"
      placeholder=" "
      @update:model-value="emit('update:modelValue', $event)"
    />
    <label :for="id">{{ label }}</label>
  </div>
</template>
