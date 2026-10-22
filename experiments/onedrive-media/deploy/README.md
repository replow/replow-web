# Preview 独立部署

仅部署 preview 中的 OneDrive 实验服务；不合并 main，不构建主站。

- 服务仅监听 127.0.0.1:8812，单 worker。
- 私有环境文件 /etc/replow/od-preview.env：设置 OD_DRIVE_ID、OD_ROOT_ITEM_ID、OD_TOKEN_FILE、OD_LINK_TTL；不得提交令牌。
- 令牌目录须已存在且归 agentdock。服务需要写入轮换后的令牌。
- systemd 单元安装到 /etc/systemd/system/replow-od-preview.service。
- Nginx 配置安装到 /www/server/panel/vhost/nginx/drive.4z.ink.conf；使用现有通配证书。
- 安装后执行 systemd-analyze verify、daemon-reload、enable --now；Nginx 必须先 nginx -t，再 reload。
- 域名必须加入 Cloudflare SaaS，再经 CF 优选 DNS 接入。禁止直连源站。
- 302 禁止缓存，文件流量由客户端直接从 OneDrive 下载。
- 宝塔全局 header.lua 会重查 301/302 并可能替换为 444。本 vhost 仅对本服务返回、带 X-OD-Cache 且 Cache-Control 为 no-store 的上游 302 跳过该响应检查，其余响应仍执行原 header.lua，请求/正文/日志 WAF 保留。模板依赖本机宝塔 Lua 模块与 /www/server/btwaf/header.lua。
- 当前公网验证：CF hostname/SSL active，DNS 恢复 api.4z.ink 优选；正常 DNS 和指定优选边缘均返回 302，下载内容匹配，缺失 404、POST 403。
- 公网只暴露 website-media 中的文件，不提供目录列表或上传。
- 停用回滚：先停用域名解析，再移走本独立 vhost 并 nginx -t/reload，最后 systemctl disable --now replow-od-preview。保留私有令牌及源码以便恢复。

验证须分别检查 origin、CF 边缘和正常 DNS 公网访问；不能只用进程状态判断成功。
