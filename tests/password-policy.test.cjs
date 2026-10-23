const fs = require("node:fs");
const ts = require("typescript");
const vm = require("node:vm");
const assert = require("node:assert/strict");
const { test } = require("node:test");
const ctx = { exports: {} };
vm.createContext(ctx);
vm.runInContext(ts.transpileModule(
  fs.readFileSync("src/utils/password-policy.ts", "utf8"),
  { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }
).outputText, ctx);
const valid = ctx.exports.validNewPassword;
for (const password of ["Ab1234", "AB12!@", "ab12!@", "ABcd!@", "Ab" + "1".repeat(126)])
  test("accepts valid policy fixture length " + password.length + " " + password.slice(0, 2), () => assert.equal(valid(password), true));
for (const password of ["Ab12!", "abcdef", "ABCDEF", "123456", "Abcdef", "abc123", "Ab" + "1".repeat(127), "ab12 中"])
  test("rejects invalid policy fixture length " + password.length + " " + password.slice(0, 2), () => assert.equal(valid(password), false));
