import { reactive } from "vue";
import type { FormRules } from "element-plus";
import { validLoginPassword } from "@/utils/password-policy";

/** 登录校验 */
const loginRules = reactive<FormRules>({
  password: [
    {
      validator: (rule, value, callback) => {
        if (value === "") {
          callback(new Error("请输入密码"));
        } else if (!validLoginPassword(value)) {
          callback(new Error("密码长度应为 6-128 位"));
        } else {
          callback();
        }
      },
      trigger: "blur"
    }
  ]
});

export { loginRules };
